from hashlib import sha256
from pathlib import Path


CHUNK_SIZE = 1024 * 1024


def hash_file(path: Path) -> str:
    digest = sha256()

    with path.open("rb") as file:
        while chunk := file.read(CHUNK_SIZE):
            digest.update(chunk)

    return digest.hexdigest()
