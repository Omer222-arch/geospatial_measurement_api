from datetime import datetime

from pydantic import BaseModel, ConfigDict


class FileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    feature_count: int
    crs: str | None = None
    status: str
    format: str
    created_at: datetime


class MeasurementItem(BaseModel):
    feature_index: int
    geometry_type: str
    geometry: dict
    crs: str | None
    measurement_crs: str | None
    properties: dict
    area_m2: float | None
    length_m: float | None
    status: str
    message: str | None


class MeasurementsResponse(BaseModel):
    file_id: str
    count: int
    total: int
    limit: int
    offset: int
    next_offset: int | None
    measurement_crs_strategy: str
    measurements: list[MeasurementItem]
