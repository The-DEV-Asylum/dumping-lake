import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .detector import detect_file
from .metadata import get_connection
from .storage import FileChangedError, cleanup_partial_objects, object_path, store_object
from .walker import WalkError, walk_source

DATA_ROOT = Path(os.getenv("DATA_ROOT", "/data"))
RAW_ROOT = DATA_ROOT / "raw"
SOURCE_NAME = os.getenv("INGEST_SOURCE", "local").strip()
INGEST_ROOT = Path(os.getenv("INGEST_ROOT", "/data/staging"))


@dataclass(frozen=True)
class FileResult:
    kind: str
    bytes_processed: int


def utc_datetime_from_ns(timestamp_ns: int) -> datetime:
    microseconds = timestamp_ns // 1_000
    seconds, remainder = divmod(microseconds, 1_000_000)
    return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(microsecond=remainder)


def acquire_run_lock(connection) -> None:
    lock_name = f"dumping-lake:ingest:{SOURCE_NAME}"
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", (lock_name,))
        if not cursor.fetchone()[0]:
            raise RuntimeError(f"an ingestion run for source '{SOURCE_NAME}' is already running")


def release_run_lock(connection) -> None:
    lock_name = f"dumping-lake:ingest:{SOURCE_NAME}"
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (lock_name,))
        connection.commit()
    except Exception:
        connection.rollback()


def start_run(connection) -> int:
    with connection.cursor() as cursor:
        cursor.execute("INSERT INTO ingestion_runs (source) VALUES (%s) RETURNING id", (SOURCE_NAME,))
        run_id = cursor.fetchone()[0]
    connection.commit()
    return run_id


def update_run_counters(connection, run_id: int, counters: dict[str, int]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE ingestion_runs
            SET files_seen = %s,
                files_new = %s,
                files_duplicate = %s,
                files_unchanged = %s,
                files_failed = %s,
                filesystem_errors = %s,
                bytes_processed = %s
            WHERE id = %s
            """,
            (
                counters["files_seen"],
                counters["files_new"],
                counters["files_duplicate"],
                counters["files_unchanged"],
                counters["files_failed"],
                counters["filesystem_errors"],
                counters["bytes_processed"],
                run_id,
            ),
        )


def finish_run(connection, run_id: int, counters: dict[str, int]) -> None:
    update_run_counters(connection, run_id, counters)
    with connection.cursor() as cursor:
        cursor.execute("UPDATE ingestion_runs SET completed_at = NOW() WHERE id = %s", (run_id,))
    connection.commit()


def record_error(connection, run_id: int, source_path: str, error_type: str, error_message: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO ingestion_errors (
                ingestion_run_id,
                source,
                source_path,
                error_type,
                error_message
            )
            VALUES (%s, %s, %s, %s, %s)
            """,
            (run_id, SOURCE_NAME, source_path, error_type, error_message),
        )


def get_existing_source(connection, source_path: str):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT sf.object_id, sf.size_bytes, sf.modified_at, sf.modified_ns, o.sha256 FROM source_files sf LEFT JOIN objects o ON o.id = sf.object_id WHERE sf.source = %s AND sf.source_path = %s",
            (SOURCE_NAME, source_path),
        )
        return cursor.fetchone()


def find_object(connection, file_hash: str):
    with connection.cursor() as cursor:
        cursor.execute("SELECT id FROM objects WHERE sha256 = %s", (file_hash,))
        row = cursor.fetchone()
        return row[0] if row else None


def insert_object(connection, file_hash: str, size_bytes: int, original_name: str, source_path: str, modified_at: datetime) -> tuple[int, bool]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO objects (
                sha256,
                size_bytes,
                original_name,
                source,
                source_path,
                modified_at
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (sha256) DO NOTHING
            RETURNING id
            """,
            (file_hash, size_bytes, original_name, SOURCE_NAME, source_path, modified_at),
        )
        row = cursor.fetchone()
        if row:
            return row[0], True
        cursor.execute("SELECT id FROM objects WHERE sha256 = %s", (file_hash,))
        row = cursor.fetchone()
        if not row:
            raise RuntimeError(f"object disappeared after SHA-256 conflict: {file_hash}")
        return row[0], False


def set_object_detection(connection, object_id: int, mime_type: str, detected_type: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE objects SET mime_type = %s, detected_type = %s WHERE id = %s",
            (mime_type, detected_type, object_id),
        )


def upsert_source_file(connection, object_id: int, source_path: str, size_bytes: int, modified_at: datetime, modified_ns: int, first_seen: bool) -> None:
    if first_seen:
        query = """
            INSERT INTO source_files (object_id, source, source_path, size_bytes, modified_at, modified_ns)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (source, source_path)
            DO UPDATE SET
                object_id = EXCLUDED.object_id,
                size_bytes = EXCLUDED.size_bytes,
                modified_at = EXCLUDED.modified_at,
                modified_ns = EXCLUDED.modified_ns,
                last_seen_at = NOW()
        """
    else:
        query = "UPDATE source_files SET last_seen_at = NOW() WHERE source = %s AND source_path = %s"
        object_id = source_path = size_bytes = modified_at = modified_ns = None
    with connection.cursor() as cursor:
        if first_seen:
            cursor.execute(query, (object_id, SOURCE_NAME, source_path, size_bytes, modified_at, modified_ns))
        else:
            cursor.execute(query, (SOURCE_NAME, source_path))


def ingest_file(path: Path, connection) -> FileResult:
    relative_path = path.relative_to(INGEST_ROOT).as_posix()
    initial = path.stat()
    initial_modified = utc_datetime_from_ns(initial.st_mtime_ns)
    existing_source = get_existing_source(connection, relative_path)

    raw_object_exists = False
    if existing_source and existing_source[0] is not None and existing_source[4]:
        raw_object_exists = object_path(RAW_ROOT, existing_source[4]).is_file()
    if (
        existing_source
        and existing_source[0] is not None
        and existing_source[1] == initial.st_size
        and existing_source[3] == initial.st_mtime_ns
        and raw_object_exists
    ):
        upsert_source_file(connection, existing_source[0], relative_path, initial.st_size, initial_modified, initial.st_mtime_ns, False)
        return FileResult("unchanged", 0)

    file_hash, _, snapshot = store_object(path, RAW_ROOT)
    modified_at = utc_datetime_from_ns(snapshot.modified_ns)
    existing_object_id = find_object(connection, file_hash)

    if existing_object_id is not None:
        object_id = existing_object_id
        kind = "duplicate"
    else:
        object_id, inserted = insert_object(
            connection,
            file_hash,
            snapshot.size_bytes,
            path.name,
            relative_path,
            modified_at,
        )
        if inserted:
            mime_type, detected_type = detect_file(path)
            set_object_detection(connection, object_id, mime_type, detected_type)
            kind = "new-object"
        else:
            kind = "duplicate"

    upsert_source_file(connection, object_id, relative_path, snapshot.size_bytes, modified_at, snapshot.modified_ns, True)
    return FileResult(kind, snapshot.size_bytes)


def normalize_walk_error_path(path: Path) -> str:
    try:
        return path.relative_to(INGEST_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def main() -> None:
    if not SOURCE_NAME:
        raise RuntimeError("INGEST_SOURCE must not be empty")
    if not INGEST_ROOT.exists():
        raise RuntimeError(f"ingestion source does not exist: {INGEST_ROOT}")
    if not INGEST_ROOT.is_dir():
        raise RuntimeError(f"ingestion source is not a directory: {INGEST_ROOT}")

    RAW_ROOT.mkdir(parents=True, exist_ok=True)
    cleanup_partial_objects(RAW_ROOT)

    connection = get_connection()
    run_id = None
    lock_acquired = False
    counters = {
        "files_seen": 0,
        "files_new": 0,
        "files_duplicate": 0,
        "files_unchanged": 0,
        "files_failed": 0,
        "filesystem_errors": 0,
        "bytes_processed": 0,
    }

    try:
        acquire_run_lock(connection)
        lock_acquired = True
        run_id = start_run(connection)
        print(f"Starting ingestion run #{run_id}")
        print(f"Source: {SOURCE_NAME}")
        print(f"Root:   {INGEST_ROOT}")
        print()

        try:
            for item in walk_source(INGEST_ROOT):
                if isinstance(item, WalkError):
                    counters["filesystem_errors"] += 1
                    counters["files_failed"] += 1
                    connection.rollback()
                    record_error(
                        connection,
                        run_id,
                        normalize_walk_error_path(item.path),
                        type(item.error).__name__,
                        str(item.error),
                    )
                    update_run_counters(connection, run_id, counters)
                    connection.commit()
                    print(f"[FILESYSTEM ERROR] {item.path}: {item.error}")
                    continue

                counters["files_seen"] += 1
                try:
                    result = ingest_file(item, connection)
                    counters["bytes_processed"] += result.bytes_processed
                    if result.kind == "new-object":
                        counters["files_new"] += 1
                    elif result.kind == "duplicate":
                        counters["files_duplicate"] += 1
                    elif result.kind == "unchanged":
                        counters["files_unchanged"] += 1
                    update_run_counters(connection, run_id, counters)
                    connection.commit()
                    print(f"[{result.kind.upper():16}] {item}")
                except FileChangedError as exc:
                    counters["files_failed"] += 1
                    connection.rollback()
                    record_error(connection, run_id, normalize_walk_error_path(item), "file_changed", str(exc))
                    update_run_counters(connection, run_id, counters)
                    connection.commit()
                    print(f"[CHANGED         ] {item}: {exc}")
                except Exception as exc:
                    counters["files_failed"] += 1
                    connection.rollback()
                    record_error(connection, run_id, normalize_walk_error_path(item), type(exc).__name__, str(exc))
                    update_run_counters(connection, run_id, counters)
                    connection.commit()
                    print(f"[FAILED          ] {item}: {exc}")
        finally:
            finish_run(connection, run_id, counters)
    finally:
        if lock_acquired:
            release_run_lock(connection)
        connection.close()

    print()
    print(f"Ingestion run #{run_id} complete")
    for key, label in (
        ("files_seen", "Files seen"),
        ("files_new", "New objects"),
        ("files_duplicate", "Duplicates"),
        ("files_unchanged", "Unchanged"),
        ("files_failed", "Failed"),
        ("filesystem_errors", "Filesystem errors"),
        ("bytes_processed", "Bytes processed"),
    ):
        print(f"{label + ':':20}{counters[key]}")


if __name__ == "__main__":
    main()
