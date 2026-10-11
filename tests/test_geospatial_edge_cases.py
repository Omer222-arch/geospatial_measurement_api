import zipfile
from pathlib import Path

import pytest
from pyproj import CRS
from shapely.geometry import GeometryCollection, LineString, Point, Polygon

from app.services.geospatial import ParsedFeature, measure_feature, parse_file, parse_kml


def test_empty_geometry_is_reported_without_measurement() -> None:
    result = measure_feature(ParsedFeature(0, GeometryCollection(), {}, CRS.from_epsg(4326)))
    assert result["status"] == "EMPTY_GEOMETRY"
    assert result["area_m2"] is None
    assert result["length_m"] is None


def test_non_finite_geographic_coordinates_are_rejected() -> None:
    with pytest.warns(RuntimeWarning):
        polygon = Polygon([(77, 17), (float("nan"), 17), (77, 18), (77, 17)])
    result = measure_feature(ParsedFeature(0, polygon, {}, CRS.from_epsg(4326)))
    assert result["status"] in {"INVALID_GEOMETRY", "INVALID_COORDINATES"}
    assert result["area_m2"] is None


def test_geographic_coordinates_outside_bounds_are_not_measured() -> None:
    polygon = Polygon([(190, 17), (191, 17), (191, 18), (190, 18), (190, 17)])
    result = measure_feature(ParsedFeature(0, polygon, {}, CRS.from_epsg(4326)))
    assert result["status"] == "INVALID_COORDINATES"
    assert result["area_m2"] is None


def test_projected_crs_in_feet_is_converted_to_metric_measurement() -> None:
    # EPSG:2263 uses US survey feet. A 1000 ft square is approximately 92,903 m².
    polygon = Polygon([(987000, 190000), (988000, 190000), (988000, 191000),
                       (987000, 191000), (987000, 190000)])
    result = measure_feature(ParsedFeature(0, polygon, {}, CRS.from_epsg(2263)))
    assert result["status"] == "MEASURED"
    assert result["measurement_crs"] != "EPSG:2263"
    assert result["area_m2"] == pytest.approx(92_903, rel=0.03)


def test_kml_malformed_coordinate_raises_clear_validation_error(tmp_path: Path) -> None:
    path = tmp_path / "malformed.kml"
    path.write_text('''<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><Point>
      <coordinates>abc,17</coordinates></Point></Placemark></kml>''')
    with pytest.raises(ValueError, match="malformed coordinate"):
        parse_kml(path)


def test_kml_out_of_range_coordinate_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "out-of-range.kml"
    path.write_text('''<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><Point>
      <coordinates>181,17</coordinates></Point></Placemark></kml>''')
    with pytest.raises(ValueError, match="outside valid geographic bounds"):
        parse_kml(path)


def test_kml_mixed_multigeometry_is_preserved_as_unsupported_feature(tmp_path: Path) -> None:
    path = tmp_path / "mixed.kml"
    path.write_text('''<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><MultiGeometry>
      <Point><coordinates>77,17</coordinates></Point>
      <LineString><coordinates>77,17 77.01,17</coordinates></LineString>
    </MultiGeometry></Placemark></kml>''')
    features = parse_file(path, "kml")
    assert len(features) == 1
    assert features[0].geometry.geom_type == "GeometryCollection"
    result = measure_feature(features[0])
    assert result["status"] == "UNSUPPORTED"


def test_missing_prj_is_parsed_but_never_given_fabricated_metric_measurement(tmp_path: Path) -> None:
    import io
    import shapefile

    base = tmp_path / "no_crs"
    writer = shapefile.Writer(str(base), shapeType=shapefile.POLYGON)
    writer.field("name", "C")
    writer.poly([[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]])
    writer.record("parcel")
    writer.close()
    archive_path = tmp_path / "no_crs.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for ext in (".shp", ".shx", ".dbf"):
            archive.write(base.with_suffix(ext), f"no_crs{ext}")
    features = parse_file(archive_path, "shapefile")
    assert len(features) == 1
    assert features[0].source_crs is None
    result = measure_feature(features[0])
    assert result["status"] == "CRS_MISSING"
    assert result["area_m2"] is None


def test_kml_with_no_geometry_is_empty_result_not_parser_crash(tmp_path: Path) -> None:
    path = tmp_path / "no-geometry.kml"
    path.write_text('''<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark><name>Empty</name></Placemark></kml>''')
    assert parse_kml(path) == []
