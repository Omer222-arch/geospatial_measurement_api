# Architecture

## Flow

Client -> `POST /api/files/` -> upload validation -> temporary/local storage -> format parser -> feature extraction -> CRS-aware measurement -> PostgreSQL -> response.

## Layers

- `api/routes`: HTTP contracts and status codes.
- `services/file_service.py`: upload constraints and format detection.
- `services/geospatial.py`: KML/Shapefile parsing and measurement engine.
- `models`: persistent file and per-feature measurement records.
- `schemas`: stable API response contracts.
- `db`: SQLAlchemy engine/session management.

## CRS strategy

The assignment explicitly prohibits calculating area or distance directly from geographic latitude/longitude degrees. If the source CRS is geographic, the service chooses a UTM zone from the feature centroid and transforms the geometry before calculating area or length. If the source CRS is projected and its axis units are metres, it is preserved. If the projected CRS uses another unit, the geometry is transformed to a metric CRS before measurement. Geographic coordinates are range-checked before transformation.

## Graceful unsupported geometry

Polygon -> `area_m2`; LineString -> `length_m`; Point -> `NOT_REQUIRED`; other geometry types -> `UNSUPPORTED` with a human-readable message rather than a failed request.

## Production evolution

For larger datasets, the synchronous processing path can be moved behind a job queue (Redis/Celery or a managed queue), with object storage replacing local disk. PostGIS can be introduced if spatial querying becomes a requirement.


## Database reliability (V3.2)

Alembic versions the SQLAlchemy schema. The integration tests use isolated temporary SQLite databases to verify persistence after reconnect, deterministic paginated feature retrieval, and rollback behavior. PostgreSQL remains the deployment target; a live PostgreSQL/Docker integration run is still required before production claims.
