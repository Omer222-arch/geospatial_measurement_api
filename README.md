# Aereo Geospatial File Measurement API

Hiring assignment implementation for Aereo. The brief requires a FastAPI or Django backend that accepts a Shapefile ZIP or KML, extracts features, identifies geometry/CRS/properties, calculates polygon area and LineString length, and correctly handles geographic CRS before measurement.

## What is implemented

- FastAPI REST API
- `.kml` uploads
- `.zip` uploads containing Shapefile components
- Feature metadata: index, geometry type, geometry, CRS and properties
- Polygon area in square metres
- LineString length in metres
- Point handling without measurement
- Graceful unsupported-geometry handling
- Geographic CRS transformation using a centroid-selected UTM zone
- PostgreSQL in Docker; SQLite default for local testing
- Persistent file + feature measurement records
- Automated tests
- OpenAPI/Swagger documentation

## Endpoints

### Upload
`POST /api/files/`

Multipart form field: `file`

Accepts:
- `survey.kml`
- `survey.zip` containing `.shp`, `.shx`, `.dbf` and preferably `.prj`

### File information
`GET /api/files/{id}/`

Returns file metadata, feature count, source CRS and processing status. The assignment specifies this information as a required API.

### Measurements
`GET /api/files/{id}/measurements/?limit=100&offset=0`

Returns every extracted feature and its measurement status/results.

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

Open Swagger at `http://localhost:8000/docs`.

## Run with Docker Compose (API + PostgreSQL)

Requirements: Docker Desktop (Windows/macOS) or Docker Engine + the Compose plugin (Linux).

1. Copy `.env.example` to `.env`.
2. Replace `POSTGRES_PASSWORD` with a long random password before sharing or deploying.
3. Start the stack:

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f api
```

On Windows PowerShell, use `Copy-Item .env.example .env` for step 1.

- API: `http://localhost:8000`
- Swagger: `http://localhost:8000/docs`
- Liveness: `http://localhost:8000/health`

The API waits for PostgreSQL to become healthy, runs `alembic upgrade head`, and then starts Uvicorn. PostgreSQL data and uploaded files use named Docker volumes and survive container recreation. Do not run `docker compose down -v` unless you intentionally want to delete the persisted database and uploaded files.

Useful commands:

```bash
docker compose exec api alembic current
docker compose exec api pytest -q
docker compose logs --tail=200 api
docker compose down
```

PostgreSQL is published on `127.0.0.1` only by default. Change the default password in `.env`; never commit `.env` or expose the database port publicly. For production, use a managed secret and TLS/reverse proxy appropriate to your deployment environment.

## Test

```bash
pytest -q
ruff check .
```

## Design decisions

### FastAPI
Chosen because the brief explicitly allows FastAPI and the project benefits from typed API contracts and automatic OpenAPI documentation.

### Shapefile parser
The ZIP is validated for the required Shapefile components and read with PyShp, avoiding a heavyweight GIS stack when only feature extraction is needed.

### KML parser
KML is parsed with `fastkml`, and KML coordinates are treated as EPSG:4326 unless the format provides otherwise.

### CRS
The brief specifically says not to calculate area/distance directly in latitude/longitude degrees and requires transformation into an appropriate projected CRS.

### Persistence
The API persists upload metadata and per-feature measurement results so the required GET endpoints remain deterministic after upload.

## Learning

This implementation reinforces production backend patterns: API/service separation, multipart file handling, geometry parsing, CRS transformation, SQL persistence, automated tests and containerized execution.

## Future scope

- Async processing for very large files
- S3-compatible object storage
- PostGIS spatial queries
- Redis-backed job status
- Authentication and per-user file ownership
- Rate limiting and malware scanning
- More GIS formats such as GeoJSON, GeoPackage and DXF


## V2 Security and Data-Quality Decisions

- Uploads are streamed to disk and capped by configuration; empty uploads are rejected and temporary failed uploads are removed.
- ZIP uploads must contain exactly one Shapefile and matching `.shp`, `.shx`, and `.dbf` files. Unsafe paths, symbolic links, excessive member counts, oversized uncompressed contents, and suspicious compression ratios are rejected.
- KML XML is parsed with `defusedxml` to reduce XML entity-expansion risks.
- Invalid geometries are reported rather than silently repaired, because repair can change the geometry and its measured area/length.
- Files without a known CRS are not assigned guessed units; polygon/line measurements return `CRS_MISSING`.
- Geographic coordinates are transformed to a suitable metric CRS. Polar geometries use UPS; projected CRSs with non-metre axes are transformed before measurements.
- Client error messages avoid exposing internal exception details.

### V2 validation

Run `pytest` to execute the API and geospatial regression tests. V2 adds regression coverage for missing CRS, invalid polygons, points, line measurements, multi-Shapefile archives, and ZIP path traversal.


## V3 reliability improvements

- Measurement results are paginated with `limit` (1–500) and `offset`; responses include `count`, `total`, `limit`, `offset`, and `next_offset`.
- SQLAlchemy indexes support file creation-time lookups and ordered feature pagination.
- Alembic is configured for versioned schema management. For a fresh or existing database, run `alembic upgrade head` before deployment; application startup retains `create_all` for convenient local development.
- Missing-file measurement errors use a structured `FILE_NOT_FOUND` code.

Example: `GET /api/files/<file-id>/measurements/?limit=50&offset=0`. Continue with the returned `next_offset` until it is `null`.


## V3.1 geospatial edge-case coverage

- Malformed KML coordinates and longitude/latitude values outside valid bounds are rejected with clear validation errors.
- Empty geometries receive an explicit `EMPTY_GEOMETRY` status; placemarks with no supported geometry are skipped, and an upload with no readable features is rejected.
- Mixed KML `MultiGeometry` is retained as a `GeometryCollection` and reported as `UNSUPPORTED` rather than silently losing a valid placemark.
- Non-finite and out-of-range geographic coordinates are not measured.
- Projected source CRSs with non-metre units (for example EPSG:2263, US survey feet) are transformed before returning square metres/metres.
- Missing `.prj` files preserve the feature but return `CRS_MISSING`; no units are guessed.

## V3.2 database integration coverage

- SQLite integration tests verify stored file/feature records survive closing and reopening the database engine.
- The measurements endpoint is exercised with a temporary database and verifies page boundaries, total counts, and `next_offset`.
- A rollback test verifies that uncommitted file metadata is not persisted.
- Alembic upgrade and downgrade have been exercised against a fresh temporary SQLite database.

Run the full suite with `pytest -q`. Ruff is configured in the development extras (`pip install -e ".[dev]"`) and can be run with `ruff check app tests migrations`.
