from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes.files import router as files_router
from app.api.routes.health import router as health_router
from app.db.database import Base, engine
from app.models import FeatureMeasurement, UploadedFile  # noqa: F401


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Local SQLite convenience only. Container deployments apply versioned Alembic migrations
    # before starting the server; production schemas must not be mutated at app startup.
    from app.core.config import get_settings

    if get_settings().app_env.lower() in {"development", "test"} and get_settings().database_url.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Aereo Geospatial File Measurement API",
    version="4.0.0",
    description="Upload KML or Shapefile ZIP files and retrieve CRS-aware feature measurements.",
    lifespan=lifespan,
)
app.include_router(health_router)
app.include_router(files_router)
