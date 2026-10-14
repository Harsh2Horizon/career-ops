from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class CareerOpsError(Exception):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def now() -> datetime:
    return datetime.now(UTC)


def digest(value: Any) -> str:
    raw = (
        value
        if isinstance(value, bytes)
        else json.dumps(value, sort_keys=True, default=str).encode()
    )
    return hashlib.sha256(raw).hexdigest()


def atomic_write(path: Path, content: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".careerops-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content.encode() if isinstance(content, str) else content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def write_json(path: Path, value: Any) -> Path:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")[:100] or "unknown"


def within(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise CareerOpsError(
            "unsafe_path", "File must remain inside the application artifact directory"
        )
    return resolved


@contextmanager
def artifact_lock(path: Path):
    """Serialize expensive generation for the same artifact across processes."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("a+b") as stream:
        if os.name == "nt":
            import msvcrt

            if path.stat().st_size == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
