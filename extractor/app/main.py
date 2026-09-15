import gzip
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import psycopg

from .extractors import (
    extract_docx,
    extract_html,
    extract_pdf,
    extract_plain,
    extract_xlsx,
)

DATABASE_URL = os.environ["DATABASE_URL"]
DATA_ROOT = Path(os.getenv("DATA_ROOT", "/data"))
RAW_ROOT = DATA_ROOT / "raw"
EXTRACTED_ROOT = Path(os.getenv("EXTRACTED_ROOT", str(DATA_ROOT / "extracted")))
EXTRACTOR_NAME = "builtin"
EXTRACTOR_VERSION = os.getenv("EXTRACTOR_VERSION", "2")
CHUNK_BYTES = int(os.getenv("EXTRACT_CHUNK_BYTES", str(16 * 1024 * 1024)))

TEXT_EXTENSIONS = {
    ".asm", ".bash", ".c", ".cc", ".cfg", ".conf", ".cpp", ".cs", ".css",
    ".csv", ".env", ".go", ".h", ".hpp", ".html", ".htm", ".ini", ".java",
    ".js", ".json", ".jsx", ".log", ".md", ".php", ".pl", ".properties",
    ".py", ".rb", ".rs", ".sh", ".sql", ".svg", ".swift", ".tex", ".toml",
    ".ts", ".tsx", ".txt", ".xml", ".yaml", ".yml", ".zsh",
}

SUPPORTED_APPLICATION_MIMES = {
    "application/ecmascript",
    "application/javascript",
    "application/json",
    "application/ld+json",
    "application/rss+xml",
    "application/sql",
    "application/x-javascript",
    "application/x-sh",
    "application/x-yaml",
    "application/xml",
    "application/xhtml+xml",
    "text/csv",
    "text/html",
    "text/javascript",
    "text/markdown",
    "text/plain",
    "text/xml",
}


class UnsupportedFormatError(Exception):
    pass


@dataclass(frozen=True)
class ChunkInfo:
    chunk_id: int
    path: Path
    text_bytes: int


@dataclass(frozen=True)
class ExtractionResult:
    status: str
    chunks: tuple[ChunkInfo, ...] = ()
    text_bytes: int = 0
    error_type: str | None = None
    error_message: str | None = None


def raw_path(sha256: str) -> Path:
    return RAW_ROOT / sha256[:2] / sha256[2:4] / sha256


def chunk_directory(sha256: str) -> Path:
    return EXTRACTED_ROOT / sha256[:2] / sha256[2:4] / sha256


def is_supported_plain(mime_type: str | None, original_name: str | None) -> bool:
    mime = (mime_type or "").lower()
    ext = Path(original_name or "").suffix.lower()
    return mime.startswith("text/") or mime in SUPPORTED_APPLICATION_MIMES or ext in TEXT_EXTENSIONS


def extract_chunks(
    source: Path,
    destination_dir: Path,
    mime_type: str | None,
    original_name: str | None,
) -> ExtractionResult:
    destination_dir.mkdir(parents=True, exist_ok=True)
    chunks: list[ChunkInfo] = []
    total_text_bytes = 0
    chunk_id = 0
    raw_out = None
    gzip_out = None
    temporary_path: Path | None = None
    written_in_chunk = 0

    def close_chunk() -> None:
        nonlocal raw_out, gzip_out, temporary_path, written_in_chunk, chunk_id
        if gzip_out is None or raw_out is None or temporary_path is None:
            return
        gzip_out.flush()
        raw_out.flush()
        os.fsync(raw_out.fileno())
        gzip_out.close()
        raw_out.close()
        final_path = destination_dir / f"{chunk_id:08d}.txt.gz"
        os.replace(temporary_path, final_path)
        chunks.append(ChunkInfo(chunk_id, final_path, written_in_chunk))
        chunk_id += 1
        raw_out = None
        gzip_out = None
        temporary_path = None
        written_in_chunk = 0

    def open_chunk() -> None:
        nonlocal raw_out, gzip_out, temporary_path
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{chunk_id:08d}-",
            suffix=".partial",
            dir=destination_dir,
        )
        temporary_path = Path(temp_name)
        raw_out = os.fdopen(fd, "wb")
        gzip_out = gzip.GzipFile(fileobj=raw_out, mode="wb")

    def write_text(text: str) -> None:
        nonlocal total_text_bytes, written_in_chunk
        if not text:
            return
        encoded = text.encode("utf-8", errors="replace")
        offset = 0
        while offset < len(encoded):
            if gzip_out is None:
                open_chunk()
            remaining = CHUNK_BYTES - written_in_chunk
            take = min(remaining, len(encoded) - offset)
            gzip_out.write(encoded[offset:offset + take])
            written_in_chunk += take
            total_text_bytes += take
            offset += take
            if written_in_chunk >= CHUNK_BYTES:
                close_chunk()

    try:
        mime = (mime_type or "").lower()
        name = original_name or source.name
        ext = Path(name).suffix.lower()

        if mime == "application/pdf" or ext == ".pdf":
            text_iter: Iterable[str] = extract_pdf(source)
        elif mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" or ext == ".docx":
            text_iter = extract_docx(source)
        elif mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" or ext == ".xlsx":
            text_iter = extract_xlsx(source)
        elif mime in {"text/html", "application/xhtml+xml"} or ext in {".html", ".htm"}:
            text_iter = extract_html(source)
        elif is_supported_plain(mime, name):
            text_iter = extract_plain(source)
        else:
            raise UnsupportedFormatError()

        for text in text_iter:
            write_text(text)

        close_chunk()

        if not chunks:
            try:
                destination_dir.rmdir()
            except OSError:
                pass
            return ExtractionResult(status="empty")

        return ExtractionResult(
            status="extracted",
            chunks=tuple(chunks),
            text_bytes=total_text_bytes,
        )

    except UnsupportedFormatError:
        if gzip_out is not None:
            gzip_out.close()
        if raw_out is not None:
            raw_out.close()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        for chunk in chunks:
            chunk.path.unlink(missing_ok=True)
        try:
            destination_dir.rmdir()
        except OSError:
            pass
        return ExtractionResult(status="unsupported")

    except Exception:
        if gzip_out is not None:
            try:
                gzip_out.close()
            except Exception:
                pass
        if raw_out is not None:
            try:
                raw_out.close()
            except Exception:
                pass
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        for chunk in chunks:
            chunk.path.unlink(missing_ok=True)
        try:
            destination_dir.rmdir()
        except OSError:
            pass
        raise


def should_skip(connection, object_id: int) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT extractor, extractor_version, status FROM object_extractions WHERE object_id = %s",
            (object_id,),
        )
        row = cursor.fetchone()
    return bool(
        row
        and row[0] == EXTRACTOR_NAME
        and row[1] == EXTRACTOR_VERSION
        and row[2] in {"extracted", "empty", "unsupported"}
    )


def acquire_run_lock(connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
            ("dumping-lake:extract",),
        )
        if not cursor.fetchone()[0]:
            raise RuntimeError("an extraction run is already running")


def release_run_lock(connection) -> None:
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
                ("dumping-lake:extract",),
            )
        connection.commit()
    except Exception:
        connection.rollback()


def start_run(connection) -> int:
    with connection.cursor() as cursor:
        cursor.execute("INSERT INTO extraction_runs DEFAULT VALUES RETURNING id")
        run_id = cursor.fetchone()[0]
    connection.commit()
    return run_id


def update_run(connection, run_id: int, counters: dict[str, int]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE extraction_runs
            SET objects_seen = %s,
                objects_extracted = %s,
                objects_unsupported = %s,
                objects_empty = %s,
                objects_skipped = %s,
                objects_failed = %s,
                bytes_processed = %s,
                text_bytes_written = %s,
                chunks_written = %s
            WHERE id = %s
            """,
            (
                counters["objects_seen"],
                counters["objects_extracted"],
                counters["objects_unsupported"],
                counters["objects_empty"],
                counters["objects_skipped"],
                counters["objects_failed"],
                counters["bytes_processed"],
                counters["text_bytes_written"],
                counters["chunks_written"],
                run_id,
            ),
        )


def load_objects(connection):
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT id, sha256, size_bytes, original_name, mime_type
            FROM objects
            ORDER BY id
            """
        )
        return cursor.fetchall()


def record_result(
    connection,
    object_id: int,
    result: ExtractionResult,
    old_paths: list[Path],
) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT extracted_path FROM object_extractions WHERE object_id = %s FOR UPDATE",
            (object_id,),
        )
        old_row = cursor.fetchone()
        if old_row and old_row[0]:
            old_paths.append(DATA_ROOT / old_row[0])

        cursor.execute(
            "SELECT extracted_path FROM object_extraction_chunks WHERE object_id = %s",
            (object_id,),
        )
        old_paths.extend(DATA_ROOT / row[0] for row in cursor.fetchall())

        cursor.execute(
            "DELETE FROM object_extraction_chunks WHERE object_id = %s",
            (object_id,),
        )

        cursor.execute(
            """
            INSERT INTO object_extractions (
                object_id,
                status,
                extractor,
                extractor_version,
                extracted_path,
                text_bytes,
                truncated,
                error_type,
                error_message,
                chunk_count
            )
            VALUES (%s, %s, %s, %s, NULL, %s, FALSE, %s, %s, %s)
            ON CONFLICT (object_id)
            DO UPDATE SET
                status = EXCLUDED.status,
                extractor = EXCLUDED.extractor,
                extractor_version = EXCLUDED.extractor_version,
                extracted_path = NULL,
                text_bytes = EXCLUDED.text_bytes,
                truncated = FALSE,
                error_type = EXCLUDED.error_type,
                error_message = EXCLUDED.error_message,
                chunk_count = EXCLUDED.chunk_count,
                extracted_at = NOW()
            """,
            (
                object_id,
                result.status,
                EXTRACTOR_NAME,
                EXTRACTOR_VERSION,
                result.text_bytes,
                result.error_type,
                result.error_message,
                len(result.chunks),
            ),
        )

        for chunk in result.chunks:
            cursor.execute(
                """
                INSERT INTO object_extraction_chunks (
                    object_id,
                    chunk_id,
                    extracted_path,
                    text_bytes
                )
                VALUES (%s, %s, %s, %s)
                """,
                (
                    object_id,
                    chunk.chunk_id,
                    str(chunk.path.relative_to(DATA_ROOT)),
                    chunk.text_bytes,
                ),
            )


def finish_run(connection, run_id: int, counters: dict[str, int]) -> None:
    update_run(connection, run_id, counters)
    with connection.cursor() as cursor:
        cursor.execute(
            "UPDATE extraction_runs SET completed_at = NOW() WHERE id = %s",
            (run_id,),
        )
    connection.commit()


def remove_old_paths(paths: list[Path], new_paths: set[Path]) -> None:
    for path in paths:
        if path in new_paths or not path.exists():
            continue
        try:
            path.unlink()
        except OSError:
            continue
        parent = path.parent
        try:
            parent.rmdir()
        except OSError:
            pass


def main() -> None:
    EXTRACTED_ROOT.mkdir(parents=True, exist_ok=True)
    if CHUNK_BYTES < 1024:
        raise SystemExit("EXTRACT_CHUNK_BYTES must be at least 1024")

    connection = psycopg.connect(DATABASE_URL)
    run_id = None
    lock_acquired = False
    counters = {
        "objects_seen": 0,
        "objects_extracted": 0,
        "objects_unsupported": 0,
        "objects_empty": 0,
        "objects_skipped": 0,
        "objects_failed": 0,
        "bytes_processed": 0,
        "text_bytes_written": 0,
        "chunks_written": 0,
    }

    try:
        acquire_run_lock(connection)
        lock_acquired = True
        run_id = start_run(connection)
        object_rows = load_objects(connection)

        for object_id, sha256, size_bytes, original_name, mime_type in object_rows:
            counters["objects_seen"] += 1

            try:
                if should_skip(connection, object_id):
                    counters["objects_skipped"] += 1
                    update_run(connection, run_id, counters)
                    connection.commit()
                    print(f"[SKIP           ] {object_id} {original_name}")
                    continue

                source = raw_path(sha256)
                if not source.is_file():
                    raise FileNotFoundError(f"raw object is missing: {source}")

                counters["bytes_processed"] += size_bytes
                target_dir = chunk_directory(sha256)
                result = extract_chunks(source, target_dir, mime_type, original_name)
                old_paths: list[Path] = []

                record_result(connection, object_id, result, old_paths)
                counters["text_bytes_written"] += result.text_bytes
                counters["chunks_written"] += len(result.chunks)

                if result.status == "extracted":
                    counters["objects_extracted"] += 1
                elif result.status == "unsupported":
                    counters["objects_unsupported"] += 1
                elif result.status == "empty":
                    counters["objects_empty"] += 1

                update_run(connection, run_id, counters)
                connection.commit()

                remove_old_paths(old_paths, {chunk.path for chunk in result.chunks})

                if result.status == "extracted":
                    print(
                        f"[EXTRACTED      ] {object_id} {original_name} "
                        f"CHUNKS={len(result.chunks)}"
                    )
                else:
                    print(f"[{result.status.upper():15}] {object_id} {original_name}")

            except Exception as exc:
                counters["objects_failed"] += 1
                connection.rollback()
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO extraction_errors (
                            extraction_run_id,
                            object_id,
                            error_type,
                            error_message
                        )
                        VALUES (%s, %s, %s, %s)
                        """,
                        (run_id, object_id, type(exc).__name__, str(exc)),
                    )
                update_run(connection, run_id, counters)
                connection.commit()
                print(
                    f"[FAILED         ] {object_id} {original_name}: {exc}",
                    file=sys.stderr,
                )

        finish_run(connection, run_id, counters)

    except Exception as exc:
        if run_id is not None:
            connection.rollback()
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE extraction_runs SET completed_at = NOW() WHERE id = %s",
                    (run_id,),
                )
            connection.commit()
        raise exc

    finally:
        if lock_acquired:
            release_run_lock(connection)
        connection.close()


if __name__ == "__main__":
    main()
