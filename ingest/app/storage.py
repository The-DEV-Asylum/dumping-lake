from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import os
import tempfile
import time

CHUNK_SIZE = 1024 * 1024
PARTIAL_SUFFIX = ".partial"
PARTIAL_MAX_AGE_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class FileSnapshot:
    size_bytes: int
    modified_ns: int
    inode: int


class FileChangedError(Exception):
    pass


def snapshot_file(path: Path) -> FileSnapshot:
    stat = path.stat()
    return FileSnapshot(stat.st_size, stat.st_mtime_ns, stat.st_ino)


def object_path(raw_root: Path, sha256_hash: str) -> Path:
    return raw_root / sha256_hash[:2] / sha256_hash[2:4] / sha256_hash


def fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def cleanup_partial_objects(raw_root: Path) -> int:
    now = time.time()
    removed = 0
    for path in raw_root.glob(f"*{PARTIAL_SUFFIX}"):
        try:
            if path.is_file() and now - path.stat().st_mtime >= PARTIAL_MAX_AGE_SECONDS:
                path.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def store_object(source: Path, raw_root: Path) -> tuple[str, Path, FileSnapshot]:
    raw_root.mkdir(parents=True, exist_ok=True)
    initial_snapshot = snapshot_file(source)
    fd, temporary_name = tempfile.mkstemp(prefix=".ingest-", suffix=PARTIAL_SUFFIX, dir=raw_root)
    temporary_path = Path(temporary_name)
    digest = sha256()
    try:
        with os.fdopen(fd, "wb") as destination_file, source.open("rb") as source_file:
            while chunk := source_file.read(CHUNK_SIZE):
                digest.update(chunk)
                destination_file.write(chunk)
            destination_file.flush()
            os.fsync(destination_file.fileno())
        final_snapshot = snapshot_file(source)
        if final_snapshot != initial_snapshot:
            raise FileChangedError(f"source file changed during ingestion: {source}")
        file_hash = digest.hexdigest()
        destination = object_path(raw_root, file_hash)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            temporary_path.unlink(missing_ok=True)
            return file_hash, destination, initial_snapshot
        os.replace(temporary_path, destination)
        fsync_directory(destination.parent)
        return file_hash, destination, initial_snapshot
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
