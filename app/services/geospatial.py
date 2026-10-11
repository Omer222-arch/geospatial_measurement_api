import json
import os
import math
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from defusedxml import ElementTree as ET

import shapefile
from pyproj import CRS, Transformer
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPoint, MultiPolygon, Point, Polygon, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform


@dataclass
class ParsedFeature:
    index: int
    geometry: BaseGeometry
    properties: dict[str, Any]
    source_crs: CRS | None


def _safe_properties(record: Any, fields: list[str]) -> dict[str, Any]:
    values = list(record)
    return {field: values[i] for i, field in enumerate(fields) if i < len(values)}


def parse_shapefile_zip(path: Path) -> list[ParsedFeature]:
    """Parse one Shapefile from a ZIP without trusting archive paths or sizes."""
    try:
        with zipfile.ZipFile(path) as archive:
            infos = [info for info in archive.infolist() if not info.is_dir()]
            if not infos:
                raise ValueError("ZIP archive is empty")
            if len(infos) > 5000:
                raise ValueError("ZIP contains too many files (limit: 5000)")
            if sum(info.file_size for info in infos) > 100 * 1024 * 1024:
                raise ValueError("Uncompressed ZIP contents exceed the 100 MB processing limit")
            if any(info.file_size > 100 * 1024 * 1024 for info in infos):
                raise ValueError("A ZIP member exceeds the 100 MB processing limit")
            # Reject traversal, absolute paths, symlinks, and suspicious compression ratios.
            for info in infos:
                member = Path(info.filename)
                mode = (info.external_attr >> 16) & 0o170000
                if member.is_absolute() or ".." in member.parts or mode == 0o120000:
                    raise ValueError("ZIP contains an unsafe path or symbolic link")
                if info.file_size > 0 and info.compress_size == 0:
                    raise ValueError("ZIP contains a suspicious compressed member")
                if info.compress_size and info.file_size / info.compress_size > 1000:
                    raise ValueError("ZIP contains a member with an unsafe compression ratio")

            shp_files = [n for n in (i.filename for i in infos) if n.lower().endswith(".shp")]
            if len(shp_files) != 1:
                raise ValueError("ZIP must contain exactly one .shp file")
            shp = shp_files[0]
            stem = shp[:-4].lower()
            by_lower = {i.filename.lower(): i.filename for i in infos}
            required = [stem + ext for ext in (".shx", ".dbf")]
            if any(name not in by_lower for name in required):
                raise ValueError("ZIP must contain matching .shp, .shx and .dbf components")

            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                for info in infos:
                    target = (root / info.filename).resolve()
                    if not target.is_relative_to(root):
                        raise ValueError("ZIP contains an unsafe path")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, target.open("wb") as destination:
                        while chunk := source.read(1024 * 1024):
                            destination.write(chunk)
                shp_path = root / shp
                reader = shapefile.Reader(str(shp_path), encoding="utf-8", encodingErrors="replace")
                try:
                    fields = [f[0] for f in reader.fields[1:]]
                    prj_path = next((p for p in shp_path.parent.iterdir()
                                     if p.name.lower() == shp_path.with_suffix(".prj").name.lower()), None)
                    source_crs = None
                    if prj_path and prj_path.exists():
                        try:
                            source_crs = CRS.from_wkt(prj_path.read_text(errors="replace"))
                        except Exception as exc:
                            raise ValueError("Shapefile .prj contains an invalid CRS definition") from exc
                    result: list[ParsedFeature] = []
                    records = reader.iterRecords()
                    shapes = reader.iterShapes()
                    for idx, (record, shp_geom) in enumerate(zip(records, shapes)):
                        if shp_geom.shapeType == shapefile.NULL:
                            continue
                        geom = shape(shp_geom.__geo_interface__)
                        result.append(ParsedFeature(idx, geom, _safe_properties(record, fields), source_crs))
                    return result
                finally:
                    reader.close()
    except zipfile.BadZipFile as exc:
        raise ValueError("Uploaded .zip file is not a valid ZIP archive") from exc


def _coordinates(text: str) -> list[tuple[float, float]]:
    """Parse KML lon,lat[,alt] tuples and reject malformed/non-finite coordinates."""
    values: list[tuple[float, float]] = []
    for token in text.strip().split():
        parts = token.split(",")
        if len(parts) < 2:
            raise ValueError("KML coordinate must contain longitude and latitude")
        try:
            lon, lat = float(parts[0]), float(parts[1])
        except (TypeError, ValueError) as exc:
            raise ValueError("KML contains a malformed coordinate") from exc
        if not (math.isfinite(lon) and math.isfinite(lat)):
            raise ValueError("KML coordinates must be finite numbers")
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError("KML longitude/latitude is outside valid geographic bounds")
        values.append((lon, lat))
    return values


def _kml_geometry(element: Any) -> BaseGeometry | None:
    tag = element.tag.rsplit("}", 1)[-1]
    if tag == "Point":
        node = element.find(".//{*}coordinates")
        return Point(_coordinates(node.text or "")[0]) if node is not None and _coordinates(node.text or "") else None
    if tag == "LineString":
        node = element.find(".//{*}coordinates")
        coords = _coordinates(node.text or "") if node is not None else []
        return LineString(coords) if len(coords) >= 2 else None
    if tag == "LinearRing":
        node = element.find(".//{*}coordinates")
        coords = _coordinates(node.text or "") if node is not None else []
        return LineString(coords) if len(coords) >= 2 else None
    if tag == "Polygon":
        outer = element.find("./{*}outerBoundaryIs/{*}LinearRing/{*}coordinates")
        if outer is None:
            return None
        shell = _coordinates(outer.text or "")
        holes = []
        for node in element.findall("./{*}innerBoundaryIs/{*}LinearRing/{*}coordinates"):
            ring = _coordinates(node.text or "")
            if len(ring) >= 4:
                holes.append(ring)
        return Polygon(shell, holes) if len(shell) >= 4 else None
    if tag == "MultiGeometry":
        parts = [_kml_geometry(child) for child in element if child.tag.rsplit("}", 1)[-1] != "MultiGeometry"]
        parts = [g for g in parts if g is not None]
        if not parts:
            return None
        types = {g.geom_type for g in parts}
        if types <= {"Polygon", "MultiPolygon"}:
            polygons = [poly for g in parts for poly in ([g] if g.geom_type == "Polygon" else list(g.geoms))]
            return MultiPolygon(polygons)
        if types <= {"LineString", "MultiLineString"}:
            lines = [line for g in parts for line in ([g] if g.geom_type == "LineString" else list(g.geoms))]
            return MultiLineString(lines)
        if types <= {"Point", "MultiPoint"}:
            points = [point for g in parts for point in ([g] if g.geom_type == "Point" else list(g.geoms))]
            return MultiPoint(points)
        # Preserve mixed KML MultiGeometry rather than silently dropping a valid placemark.
        return GeometryCollection(parts)
    return None


def parse_kml(path: Path) -> list[ParsedFeature]:
    try:
        root = ET.parse(path).getroot()
    except Exception as exc:
        raise ValueError("KML is malformed or contains unsafe XML") from exc
    result: list[ParsedFeature] = []
    placemarks = root.findall(".//{*}Placemark")
    for idx, placemark in enumerate(placemarks):
        geometry = None
        for child in placemark:
            if child.tag.rsplit("}", 1)[-1] in {"Point", "LineString", "Polygon", "MultiGeometry"}:
                geometry = _kml_geometry(child)
                if geometry is not None:
                    break
        if geometry is None:
            # Placemark contains no supported geometry element; skip it deliberately.
            continue
        props: dict[str, Any] = {}
        for key in ("name", "description"):
            node = placemark.find(f"./{{*}}{key}")
            if node is not None and node.text is not None:
                props[key] = node.text
        for data in placemark.findall(".//{*}ExtendedData/{*}Data"):
            key = data.attrib.get("name")
            value = data.find("./{*}value")
            if key and value is not None:
                props[key] = value.text
        if "id" in placemark.attrib:
            props["id"] = placemark.attrib["id"]
        result.append(ParsedFeature(len(result), geometry, props, CRS.from_epsg(4326)))
    return result

def parse_file(path: Path, fmt: str) -> list[ParsedFeature]:
    if fmt == "kml":
        return parse_kml(path)
    if fmt == "shapefile":
        return parse_shapefile_zip(path)
    raise ValueError(f"Unsupported format: {fmt}")


def _to_geographic(geometry: BaseGeometry, source_crs: CRS) -> BaseGeometry:
    geographic = CRS.from_epsg(4326)
    if source_crs == geographic:
        return geometry
    transformer = Transformer.from_crs(source_crs, geographic, always_xy=True)
    return transform(transformer.transform, geometry)


def choose_measurement_crs(geometry: BaseGeometry, source_crs: CRS | None) -> CRS | None:
    """Choose a metric CRS; preserve projected source CRS only when its units are metres."""
    if source_crs is None:
        return None
    if source_crs.is_projected:
        axes = source_crs.axis_info
        if axes and all(abs((axis.unit_conversion_factor or 0) - 1.0) < 1e-9 for axis in axes[:2]):
            return source_crs
    geographic_geometry = _to_geographic(geometry, source_crs)
    lon, lat = geographic_geometry.centroid.x, geographic_geometry.centroid.y
    if not (math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    # UPS is preferable to UTM at the polar extremes.
    if lat >= 84:
        return CRS.from_epsg(32661)
    if lat <= -80:
        return CRS.from_epsg(32761)
    zone = math.floor((lon + 180) / 6) + 1
    zone = max(1, min(60, zone))
    return CRS.from_epsg((32600 if lat >= 0 else 32700) + zone)


def measure_feature(feature: ParsedFeature) -> dict[str, Any]:
    geom = feature.geometry
    base = {"area_m2": None, "length_m": None, "measurement_crs": None}
    if geom.is_empty:
        return {**base, "status": "EMPTY_GEOMETRY", "message": "Geometry is empty; measurement was not calculated"}
    if not geom.is_valid:
        return {**base, "status": "INVALID_GEOMETRY", "message": "Geometry is invalid; measurement was not calculated"}
    supported_area = isinstance(geom, (Polygon, MultiPolygon))
    supported_length = isinstance(geom, (LineString, MultiLineString))
    supported_point = isinstance(geom, (Point, MultiPoint))
    if supported_point:
        return {**base, "status": "NOT_REQUIRED", "message": "No measurement required for point geometry"}
    if not (supported_area or supported_length):
        return {**base, "status": "UNSUPPORTED", "message": f"Measurement is not supported for geometry type {geom.geom_type}"}
    if feature.source_crs is None:
        return {**base, "status": "CRS_MISSING", "message": "Source CRS is missing; metric measurement cannot be calculated safely"}
    try:
        if feature.source_crs.is_geographic:
            minx, miny, maxx, maxy = geom.bounds
            if not all(math.isfinite(v) for v in (minx, miny, maxx, maxy)):
                return {**base, "status": "INVALID_COORDINATES", "message": "Geometry contains non-finite coordinates"}
            if minx < -180 or maxx > 180 or miny < -90 or maxy > 90:
                return {**base, "status": "INVALID_COORDINATES", "message": "Geographic coordinates are outside valid longitude/latitude bounds"}
        measurement_crs = choose_measurement_crs(geom, feature.source_crs)
        if measurement_crs is None:
            return {**base, "status": "CRS_UNSUPPORTED", "message": "Could not determine a suitable metric CRS"}
        transformer = Transformer.from_crs(feature.source_crs, measurement_crs, always_xy=True)
        measured = transform(transformer.transform, geom)
        if measured.is_empty or not measured.is_valid or not all(math.isfinite(v) for v in measured.bounds):
            return {**base, "status": "INVALID_GEOMETRY", "message": "Geometry became invalid during CRS transformation"}
        area = float(measured.area) if supported_area else None
        length = float(measured.length) if supported_length else None
        if area is not None and (not math.isfinite(area) or area < 0):
            raise ValueError("Calculated area is not finite")
        if length is not None and (not math.isfinite(length) or length < 0):
            raise ValueError("Calculated length is not finite")
        return {"status": "MEASURED", "message": None, "area_m2": area, "length_m": length,
                "measurement_crs": measurement_crs.to_string()}
    except Exception:
        return {**base, "status": "MEASUREMENT_ERROR", "message": "Measurement failed during CRS transformation"}
