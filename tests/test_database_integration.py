from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.db.database import Base
from app.models import FeatureMeasurement, UploadedFile


def _make_engine(path: Path):
    return create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})


def test_database_persistence_across_engine_restart_and_pagination(tmp_path: Path) -> None:
    db_path = tmp_path / "integration.sqlite3"
    engine = _make_engine(db_path)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        uploaded = UploadedFile(
            filename="sample.kml", format="kml", storage_path="/tmp/sample.kml",
            file_size=123, feature_count=3, source_crs="EPSG:4326", status="COMPLETED",
        )
        session.add(uploaded)
        session.flush()
        file_id = uploaded.id
        for idx in range(3):
            session.add(FeatureMeasurement(
                file_id=file_id, feature_index=idx, geometry_type="Point",
                geometry_wkt=f"POINT ({idx} {idx})", properties_json="{}",
                source_crs="EPSG:4326", measurement_crs=None, area_m2=None,
                length_m=None, status="NOT_REQUIRED", message=None,
            ))
        session.commit()
    engine.dispose()

    # Re-open the same on-disk database to model an application restart.
    restarted_engine = _make_engine(db_path)
    with Session(restarted_engine) as session:
        persisted = session.get(UploadedFile, file_id)
        assert persisted is not None
        assert persisted.feature_count == 3
        query = select(FeatureMeasurement).where(FeatureMeasurement.file_id == file_id)
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        first_page = session.scalars(query.order_by(FeatureMeasurement.feature_index).offset(0).limit(2)).all()
        second_page = session.scalars(query.order_by(FeatureMeasurement.feature_index).offset(2).limit(2)).all()
        assert total == 3
        assert [row.feature_index for row in first_page] == [0, 1]
        assert [row.feature_index for row in second_page] == [2]
    restarted_engine.dispose()


def test_transaction_rollback_leaves_no_persisted_file(tmp_path: Path) -> None:
    engine = _make_engine(tmp_path / "rollback.sqlite3")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(UploadedFile(
            filename="failed.kml", format="kml", storage_path="/tmp/failed.kml",
            file_size=10, feature_count=0, source_crs=None, status="PROCESSING",
        ))
        session.flush()
        session.rollback()
    with Session(engine) as session:
        count = session.scalar(select(func.count()).select_from(UploadedFile))
        assert count == 0
    engine.dispose()


def test_measurements_endpoint_paginates_against_temporary_database(tmp_path: Path, monkeypatch) -> None:
    import io

    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    from app.db.database import get_db
    from app.main import app

    db_path = tmp_path / "api-pagination.sqlite3"
    engine = _make_engine(db_path)
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    # Isolate uploaded test artifacts as well as the database.
    from app.core.config import Settings
    monkeypatch.setattr(
        "app.services.file_service.get_settings",
        lambda: Settings(database_url=f"sqlite:///{db_path}", storage_dir=str(tmp_path / "uploads")),
    )
    app.dependency_overrides[get_db] = override_get_db
    kml = b'''<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
      <Placemark><Point><coordinates>77,17</coordinates></Point></Placemark>
      <Placemark><Point><coordinates>78,18</coordinates></Point></Placemark>
      <Placemark><Point><coordinates>79,19</coordinates></Point></Placemark>
    </Document></kml>'''
    try:
        with TestClient(app) as client:
            uploaded = client.post("/api/files/", files={"file": ("three.kml", io.BytesIO(kml), "application/xml")})
            assert uploaded.status_code == 201, uploaded.text
            file_id = uploaded.json()["id"]
            first = client.get(f"/api/files/{file_id}/measurements/?limit=2&offset=0")
            second = client.get(f"/api/files/{file_id}/measurements/?limit=2&offset=2")
            assert first.status_code == second.status_code == 200
            assert first.json()["total"] == 3
            assert [item["feature_index"] for item in first.json()["measurements"]] == [0, 1]
            assert first.json()["next_offset"] == 2
            assert [item["feature_index"] for item in second.json()["measurements"]] == [2]
            assert second.json()["next_offset"] is None
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()
