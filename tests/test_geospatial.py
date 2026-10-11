import io
import zipfile

import shapefile
from fastapi.testclient import TestClient

from app.main import app


def make_shapefile_zip() -> bytes:
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "survey"
        writer = shapefile.Writer(str(base), shapeType=shapefile.POLYGON)
        writer.field("name", "C")
        writer.poly([[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]])
        writer.record("test-area")
        writer.close()
        base.with_suffix(".prj").write_text(
            'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
            'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]]'
        )
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            for ext in (".shp", ".shx", ".dbf", ".prj"):
                z.write(base.with_suffix(ext), f"survey{ext}")
        return out.getvalue()


def test_upload_shapefile_zip() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/files/",
            files={"file": ("survey.zip", io.BytesIO(make_shapefile_zip()), "application/zip")},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["format"] == "shapefile"
        assert body["feature_count"] == 1

        detail = client.get(f"/api/files/{body['id']}/")
        assert detail.status_code == 200
        assert detail.json()["crs"] == "EPSG:4326"

        measurements = client.get(f"/api/files/{body['id']}/measurements/?limit=1&offset=0")
        assert measurements.status_code == 200
        page = measurements.json()
        assert page["count"] == 1
        assert page["total"] == 1
        assert page["limit"] == 1
        assert page["offset"] == 0
        assert page["next_offset"] is None
        item = page["measurements"][0]
        assert item["geometry_type"] == "Polygon"
        assert item["area_m2"] is not None
        assert item["area_m2"] > 1_000_000
        assert item["measurement_crs" if "measurement_crs" in item else "status"]


def test_upload_kml() -> None:
    kml = b'''<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2">
      <Document>
        <Placemark id="parcel-1">
          <name>Parcel 1</name>
          <Polygon><outerBoundaryIs><LinearRing>
            <coordinates>77.0,17.0 77.01,17.0 77.01,17.01 77.0,17.01 77.0,17.0</coordinates>
          </LinearRing></outerBoundaryIs></Polygon>
        </Placemark>
      </Document>
    </kml>'''
    with TestClient(app) as client:
        response = client.post(
            "/api/files/",
            files={"file": ("parcel.kml", io.BytesIO(kml), "application/vnd.google-earth.kml+xml")},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["format"] == "kml"
        measurements = client.get(f"/api/files/{body['id']}/measurements/")
        item = measurements.json()["measurements"][0]
        assert item["geometry_type"] == "Polygon"
        assert item["area_m2"] > 900_000


def test_measurement_pagination_rejects_invalid_limit() -> None:
    with TestClient(app) as client:
        response = client.get("/api/files/not-a-real-file/measurements/?limit=0")
        assert response.status_code == 422


def test_measurements_for_missing_file_returns_structured_error() -> None:
    with TestClient(app) as client:
        response = client.get("/api/files/missing-file/measurements/")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "FILE_NOT_FOUND"
