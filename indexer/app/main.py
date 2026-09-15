import gzip
import os
import sys
from datetime import datetime
from pathlib import Path

import psycopg
from opensearchpy import OpenSearch, helpers

DATABASE_URL = os.environ["DATABASE_URL"]
OPENSEARCH_URL = os.getenv("OPENSEARCH_URL", "http://opensearch:9200")
INDEX_NAME = os.getenv("OPENSEARCH_INDEX", "objects")
CONTENT_INDEX_NAME = os.getenv("OPENSEARCH_CONTENT_INDEX", "object-content")
DATA_ROOT = Path(os.getenv("DATA_ROOT", "/data"))
CONTENT_CHARS = int(os.getenv("CONTENT_CHARS", "12000"))


def client() -> OpenSearch:
    return OpenSearch(OPENSEARCH_URL, request_timeout=60, max_retries=3, retry_on_timeout=True)


def metadata_mapping() -> dict:
    return {"settings": {"index": {"number_of_shards": 1, "number_of_replicas": 0}}, "mappings": {"properties": {
        "id": {"type": "long"}, "sha256": {"type": "keyword"}, "size_bytes": {"type": "long"},
        "original_name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
        "mime_type": {"type": "keyword"}, "detected_type": {"type": "text"}, "source": {"type": "keyword"},
        "source_path": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
        "first_seen_at": {"type": "date"}, "modified_at": {"type": "date"}, "created_at": {"type": "date"},
    }}}


def content_mapping() -> dict:
    return {"settings": {"index": {"number_of_shards": 1, "number_of_replicas": 0}}, "mappings": {"properties": {
        "object_id": {"type": "long"}, "chunk_id": {"type": "long"}, "sha256": {"type": "keyword"},
        "original_name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
        "source": {"type": "keyword"}, "source_path": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
        "mime_type": {"type": "keyword"}, "content": {"type": "text"},
    }}}


def ensure_index(search_client: OpenSearch) -> None:
    if not search_client.indices.exists(index=INDEX_NAME):
        search_client.indices.create(index=INDEX_NAME, body=metadata_mapping())


def ensure_content_index(search_client: OpenSearch) -> None:
    if not search_client.indices.exists(index=CONTENT_INDEX_NAME):
        search_client.indices.create(index=CONTENT_INDEX_NAME, body=content_mapping())


def metadata_rows():
    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor(name="objects-index") as cursor:
            cursor.execute("SELECT id, sha256, size_bytes, original_name, mime_type, detected_type, source, source_path, first_seen_at, modified_at, created_at FROM objects ORDER BY id")
            columns = [column.name for column in cursor.description]
            for row in cursor:
                yield dict(zip(columns, row, strict=True))


def content_rows():
    with psycopg.connect(DATABASE_URL) as connection:
        with connection.cursor(name="content-index") as cursor:
            cursor.execute(
                """
                SELECT o.id, o.sha256, o.original_name, o.mime_type, o.source, o.source_path,
                       c.chunk_id, c.extracted_path
                FROM object_extraction_chunks c
                JOIN object_extractions e ON e.object_id = c.object_id
                JOIN objects o ON o.id = c.object_id
                WHERE e.status = 'extracted'
                ORDER BY o.id, c.chunk_id
                """
            )
            for row in cursor:
                yield row


def document(row: dict) -> dict:
    result = dict(row)
    for key in ("first_seen_at", "modified_at", "created_at"):
        if isinstance(result[key], datetime):
            result[key] = result[key].isoformat()
    return result


def index_all() -> None:
    search_client = client()
    ensure_index(search_client)
    actions = ({"_index": INDEX_NAME, "_id": row["id"], "_source": document(row)} for row in metadata_rows())
    success, failed = helpers.bulk(search_client, actions, chunk_size=500, raise_on_error=False)
    print(f"Indexed: {success}")
    print(f"Failed:  {len(failed)}")
    if failed:
        for failure in failed[:10]:
            print(f"INDEX ERROR: {failure}", file=sys.stderr)
        raise SystemExit(1)


def chunk_text(path: Path):
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
        buffer = ""
        for line in handle:
            while line:
                remaining = CONTENT_CHARS - len(buffer)
                if len(line) <= remaining:
                    buffer += line
                    break
                buffer += line[:remaining]
                yield buffer
                buffer = ""
                line = line[remaining:]
        if buffer:
            yield buffer


def content_actions():
    for object_id, sha256, original_name, mime_type, source, source_path, chunk_id, extracted_path in content_rows():
        path = DATA_ROOT / extracted_path
        if not path.is_file():
            print(f"[MISSING TEXT] object={object_id} chunk={chunk_id} path={path}", file=sys.stderr)
            continue
        for part, text in enumerate(chunk_text(path)):
            doc_id = f"{object_id}:{chunk_id}:{part}"
            yield {"_index": CONTENT_INDEX_NAME, "_id": doc_id, "_source": {
                "object_id": object_id, "chunk_id": chunk_id, "sha256": sha256,
                "original_name": original_name, "source": source, "source_path": source_path,
                "mime_type": mime_type, "content": text,
            }}


def index_content() -> None:
    search_client = client()
    ensure_content_index(search_client)
    search_client.delete_by_query(index=CONTENT_INDEX_NAME, body={"query": {"match_all": {}}}, conflicts="proceed", refresh=True, wait_for_completion=True)
    success, failed = helpers.bulk(search_client, content_actions(), chunk_size=10, max_chunk_bytes=5 * 1024 * 1024, raise_on_error=False)
    print(f"Content documents indexed: {success}")
    print(f"Content documents failed:  {len(failed)}")
    if failed:
        for failure in failed[:10]:
            print(f"CONTENT INDEX ERROR: {failure}", file=sys.stderr)
        raise SystemExit(1)


def search_metadata(query: str) -> None:
    search_client = client()
    result = search_client.search(index=INDEX_NAME, body={"query": {"multi_match": {"query": query, "fields": ["original_name^3", "source_path^2", "detected_type", "mime_type", "source"]}}, "size": 20})
    hits = result["hits"]["hits"]
    if not hits:
        print("No results.")
        return
    for hit in hits:
        source = hit["_source"]
        print(f"{hit.get('_score', 0.0):.2f}  {source['id']}  {source['source_path']}  {source.get('mime_type')}")


def search_content(query: str) -> None:
    search_client = client()
    result = search_client.search(index=CONTENT_INDEX_NAME, body={
        "query": {"multi_match": {"query": query, "fields": ["content", "original_name^2", "source_path"]}},
        "size": 20,
        "collapse": {"field": "object_id"},
        "highlight": {"fields": {"content": {"fragment_size": 240, "number_of_fragments": 2}}},
    })
    hits = result["hits"]["hits"]
    if not hits:
        print("No results.")
        return
    for hit in hits:
        source = hit["_source"]
        print(f"{hit.get('_score', 0.0):.2f}  object={source['object_id']} chunk={source['chunk_id']}  {source['source_path']}")
        for fragment in hit.get("highlight", {}).get("content", []):
            print(f"  {fragment}")


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "index"
    if command == "init":
        search_client = client()
        ensure_index(search_client)
        print(f"Index ready: {INDEX_NAME}")
        return
    if command == "index":
        index_all()
        return
    if command == "content-init":
        search_client = client()
        ensure_content_index(search_client)
        print(f"Content index ready: {CONTENT_INDEX_NAME}")
        return
    if command == "content-index":
        index_content()
        return
    if command == "search":
        if len(sys.argv) < 3:
            raise SystemExit("usage: search <query>")
        search_metadata(" ".join(sys.argv[2:]))
        return
    if command == "content-search":
        if len(sys.argv) < 3:
            raise SystemExit("usage: content-search <query>")
        search_content(" ".join(sys.argv[2:]))
        return
    raise SystemExit(f"unknown command: {command}")


if __name__ == "__main__":
    main()
