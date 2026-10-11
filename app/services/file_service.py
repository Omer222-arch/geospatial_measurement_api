import uuid
from pathlib import Path

from fastapi import UploadFile

from app.core.config import get_settings


ALLOWED_EXTENSIONS = {".kml", ".zip"}


def detect_format(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".kml":
        return "kml"
    if suffix == ".zip":
        return "shapefile"
    raise ValueError("Only .kml and .zip (Shapefile) uploads are supported")


async def save_upload(upload: UploadFile) -> tuple[Path, int, str]:
    if not upload.filename:
        raise ValueError("Filename is required")
    fmt = detect_format(upload.filename)
    settings = get_settings()
    root = Path(settings.storage_dir)
    root.mkdir(parents=True, exist_ok=True)
    original_name = Path(upload.filename).name
    if original_name in {"", ".", ".."} or "\x00" in original_name:
        raise ValueError("Invalid filename")
    path = root / f"{uuid.uuid4()}{Path(original_name).suffix.lower()}"
    total = 0
    try:
        with path.open("xb") as output:
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > settings.max_upload_size_bytes:
                    raise ValueError(f"File exceeds {settings.max_upload_size_mb} MB upload limit")
                output.write(chunk)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    if total == 0:
        path.unlink(missing_ok=True)
        raise ValueError("Uploaded file is empty")
    return path, total, fmt
