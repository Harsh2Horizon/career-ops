"""Minimal structured operational logs with a deliberately closed, non-PII field set."""

from __future__ import annotations

import json
import os
from pathlib import Path

from career_ops.common.io import now


def log_event(
    directory: Path, event: str, *, job_id: str | None = None, code: str | None = None
) -> None:
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    record = {"timestamp": now().isoformat(), "event": event, "job_id": job_id, "code": code}
    descriptor = os.open(directory / "events.jsonl", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(descriptor, (json.dumps(record) + "\n").encode())
    finally:
        os.close(descriptor)
