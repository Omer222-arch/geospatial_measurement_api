from uuid import uuid4

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class FeatureMeasurement(Base):
    __tablename__ = "feature_measurements"
    __table_args__ = (
        UniqueConstraint("file_id", "feature_index", name="uq_feature_file_index"),
        Index("ix_feature_file_index", "file_id", "feature_index"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    file_id: Mapped[str] = mapped_column(ForeignKey("uploaded_files.id", ondelete="CASCADE"), index=True)
    feature_index: Mapped[int] = mapped_column(Integer)
    geometry_type: Mapped[str] = mapped_column(String(50))
    geometry_wkt: Mapped[str] = mapped_column(Text())
    properties_json: Mapped[str] = mapped_column(Text(), default="{}")
    source_crs: Mapped[str | None] = mapped_column(String(100), nullable=True)
    measurement_crs: Mapped[str | None] = mapped_column(String(100), nullable=True)
    area_m2: Mapped[float | None] = mapped_column(Float, nullable=True)
    length_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(30))
    message: Mapped[str | None] = mapped_column(Text(), nullable=True)
