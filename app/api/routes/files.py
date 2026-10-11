from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models import FeatureMeasurement, UploadedFile
from app.schemas.file import FileResponse, MeasurementItem, MeasurementsResponse
from app.services.file_service import save_upload
from app.services.geospatial import measure_feature, parse_file
from shapely.geometry import mapping
from shapely import wkt

router = APIRouter(prefix="/api/files", tags=["files"])


@router.post("/", response_model=FileResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(file: UploadFile = File(...), db: Session = Depends(get_db)) -> FileResponse:
    path = None
    persisted = False
    try:
        path, size, fmt = await save_upload(file)
        features = parse_file(path, fmt)
        if not features:
            raise ValueError("The uploaded file contains no readable features")

        source_crs = features[0].source_crs.to_string() if features[0].source_crs else None
        record = UploadedFile(
            filename=file.filename or path.name,
            format=fmt,
            storage_path=str(path),
            file_size=size,
            feature_count=len(features),
            source_crs=source_crs,
            status="COMPLETED",
        )
        db.add(record)
        db.flush()

        for feature in features:
            measurement = measure_feature(feature)
            db.add(FeatureMeasurement(
                file_id=record.id,
                feature_index=feature.index,
                geometry_type=feature.geometry.geom_type,
                geometry_wkt=feature.geometry.wkt,
                properties_json=__import__("json").dumps(feature.properties, default=str),
                source_crs=feature.source_crs.to_string() if feature.source_crs else None,
                measurement_crs=measurement["measurement_crs"],
                area_m2=measurement["area_m2"],
                length_m=measurement["length_m"],
                status=measurement["status"],
                message=measurement["message"],
            ))
        db.commit()
        persisted = True
        db.refresh(record)
        return FileResponse(
            id=record.id, filename=record.filename, feature_count=record.feature_count,
            crs=record.source_crs, status=record.status, format=record.format, created_at=record.created_at
        )
    except ValueError as exc:
        db.rollback()
        if path is not None and not persisted:
            path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        db.rollback()
        if path is not None and not persisted:
            path.unlink(missing_ok=True)
        # Do not expose parser, filesystem, SQL, or library internals to clients.
        raise HTTPException(status_code=422, detail="Unable to process geospatial file; verify the file format and contents") from exc


@router.get("/{file_id}/", response_model=FileResponse)
def get_file(file_id: str, db: Session = Depends(get_db)) -> FileResponse:
    record = db.get(UploadedFile, file_id)
    if not record:
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(
        id=record.id, filename=record.filename, feature_count=record.feature_count,
        crs=record.source_crs, status=record.status, format=record.format, created_at=record.created_at
    )


@router.get("/{file_id}/measurements/", response_model=MeasurementsResponse)
def get_measurements(
    file_id: str,
    limit: int = Query(default=100, ge=1, le=500, description="Maximum features returned per page"),
    offset: int = Query(default=0, ge=0, description="Number of features to skip"),
    db: Session = Depends(get_db),
) -> MeasurementsResponse:
    if not db.get(UploadedFile, file_id):
        raise HTTPException(status_code=404, detail={"code": "FILE_NOT_FOUND", "message": "File not found"})

    base_query = select(FeatureMeasurement).where(FeatureMeasurement.file_id == file_id)
    total = db.scalar(select(func.count()).select_from(base_query.subquery())) or 0
    rows = db.scalars(
        base_query.order_by(FeatureMeasurement.feature_index).offset(offset).limit(limit)
    ).all()
    items = [MeasurementItem(
        feature_index=row.feature_index,
        geometry_type=row.geometry_type,
        geometry=mapping(wkt.loads(row.geometry_wkt)),
        crs=row.source_crs,
        measurement_crs=row.measurement_crs,
        properties=__import__("json").loads(row.properties_json),
        area_m2=row.area_m2,
        length_m=row.length_m,
        status=row.status,
        message=row.message,
    ) for row in rows]
    next_offset = offset + len(items) if offset + len(items) < total else None
    return MeasurementsResponse(
        file_id=file_id,
        count=len(items),
        total=total,
        limit=limit,
        offset=offset,
        next_offset=next_offset,
        measurement_crs_strategy="UTM zone selected from geometry centroid for geographic CRS; projected source CRS is preserved when its axes use metres.",
        measurements=items,
    )
