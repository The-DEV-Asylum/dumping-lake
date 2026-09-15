from pathlib import Path

import magic


def detect_file(path: Path) -> tuple[str, str]:
    mime = magic.from_file(str(path), mime=True)
    description = magic.from_file(str(path))
    return mime, description
