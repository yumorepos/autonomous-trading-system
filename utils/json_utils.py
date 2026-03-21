from __future__ import annotations

import json
import os
import tempfile
import warnings
from pathlib import Path
from typing import Any


def safe_read_json(path: Path | str) -> Any:
    file_path = Path(path)
    if not file_path.exists():
        return None

    try:
        with open(file_path) as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        warnings.warn(f"Malformed JSON skipped: {file_path} ({exc})")
    except OSError as exc:
        warnings.warn(f"Failed to read JSON: {file_path} ({exc})")
    return None


def safe_read_jsonl(path: Path | str) -> list[Any]:
    file_path = Path(path)
    if not file_path.exists():
        return []

    records: list[Any] = []
    try:
        with open(file_path) as handle:
            for line_number, line in enumerate(handle, start=1):
                payload = line.strip()
                if not payload:
                    continue
                try:
                    records.append(json.loads(payload))
                except json.JSONDecodeError as exc:
                    warnings.warn(
                        f"Malformed JSONL skipped: {file_path}:{line_number} ({exc})"
                    )
    except OSError as exc:
        warnings.warn(f"Failed to read JSONL: {file_path} ({exc})")
        return []

    return records


def write_json_atomic(path: Path | str, data: Any) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(prefix=f".{file_path.name}.", dir=file_path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, file_path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
