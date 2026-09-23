from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path, content: str, *, overwrite: bool) -> None:
    """Write UTF-8 text through a same-directory temporary file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite and path.exists():
        raise FileExistsError(path)

    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if not overwrite and path.exists():
            raise FileExistsError(path)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def atomic_write_json(path: Path, value: Any, *, overwrite: bool) -> None:
    content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(path, content, overwrite=overwrite)
