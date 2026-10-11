import io
import zipfile
from pathlib import Path

import pytest
from pyproj import CRS
from shapely.geometry import LineString, Point, Polygon

from app.services.geospatial import ParsedFeature, measure_feature, parse_shapefile_zip


def test_missing_crs_does_not_return_fake_metric_measurement() -> None:
    feature = ParsedFeature(
        index=0,
        geometry=Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]),
        properties={},
        source_crs=None,
    )
    result = measure_feature(feature)
    assert result["status"] == "CRS_MISSING"
    assert result["area_m2"] is None


def test_point_has_no_measurement() -> None:
    feature = ParsedFeature(0, Point(77, 17), {}, CRS.from_epsg(4326))
    result = measure_feature(feature)
    assert result["status"] == "NOT_REQUIRED"
    assert result["area_m2"] is None
    assert result["length_m"] is None


def test_invalid_polygon_is_not_silently_repaired() -> None:
    bow_tie = Polygon([(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)])
    result = measure_feature(ParsedFeature(0, bow_tie, {}, CRS.from_epsg(4326)))
    assert result["status"] == "INVALID_GEOMETRY"
    assert result["area_m2"] is None


def test_line_length_uses_metric_crs() -> None:
    line = LineString([(77.0, 17.0), (77.01, 17.0)])
    result = measure_feature(ParsedFeature(0, line, {}, CRS.from_epsg(4326)))
    assert result["status"] == "MEASURED"
    assert result["length_m"] is not None
    assert 900 < result["length_m"] < 1200
    assert result["measurement_crs"] == "EPSG:32643"


def test_zip_with_multiple_shapefiles_is_rejected(tmp_path: Path) -> None:
    archive_path = tmp_path / "multiple.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for name in ("a.shp", "a.shx", "a.dbf", "b.shp", "b.shx", "b.dbf"):
            archive.writestr(name, b"placeholder")
    with pytest.raises(ValueError, match="exactly one"):
        parse_shapefile_zip(archive_path)


def test_zip_path_traversal_is_rejected(tmp_path: Path) -> None:
    archive_path = tmp_path / "traversal.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../escape.txt", b"nope")
    with pytest.raises(ValueError, match="unsafe path"):
        parse_shapefile_zip(archive_path)
