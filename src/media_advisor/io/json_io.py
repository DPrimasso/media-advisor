"""Atomic JSON read/write helpers.

Write is atomic: write to a temp file then os.replace() to avoid partial writes.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    """Read and return parsed JSON from path."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any, indent: int = 2) -> None:
    """Write data as JSON atomically (temp file + replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json_or_default(path: Path, default: Any = None) -> Any:
    """Return parsed JSON or default if file doesn't exist."""
    if not path.exists():
        return default
    return read_json(path)


def read_video_list(path: Path) -> list[str]:
    """Read a channel video list JSON file (array of URL strings)."""
    if not path.exists():
        return []
    data = read_json(path)
    if not isinstance(data, list):
        return []
    return [str(x) for x in data]


def write_video_list(path: Path, urls: list[str]) -> None:
    write_json(path, urls)
