from pathlib import Path
import shutil
import uuid

from app.config import get_settings


def save_upload(filename: str, data: bytes) -> Path:
    settings = get_settings()
    safe = f"{uuid.uuid4().hex}_{filename}"
    dest = settings.uploads_dir / safe
    dest.write_bytes(data)
    return dest
