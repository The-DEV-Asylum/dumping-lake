# dumping-lake

Local research data lake for heterogeneous security-research datasets.

## Architecture

- Raw bytes: local SHA-256 content-addressed objects under `data/raw`.
- PostgreSQL: catalogue, source mappings, ingestion runs, extraction metadata and errors.
- OpenSearch 3.8.0: metadata index plus a separate chunked full-text index.
- Extractor: derives text from supported objects into bounded, gzip-compressed chunks under `data/extracted`.

## Pipeline

```text
External source
    ↓
ingest
    ↓
SHA-256 raw objects
    ↓
PostgreSQL catalogue
    ↓
extractor
    ↓
bounded compressed text chunks
    ↓
OpenSearch metadata index + content index
    ↓
metadata/full-text search
```

## Full-text extraction

Run the database migrations once for an existing PostgreSQL volume:

```bash
./scripts/db-migrate.sh
```

Build and run extraction:

```bash
./scripts/extract.sh
```

Watch extraction progress:

```bash
./scripts/extraction-status.sh
```

Extraction is versioned and restartable. The chunked extractor is version `2`. It supersedes the earlier version-1 single-file extraction and will reprocess objects whose recorded extractor version is older.

Supported first-pass formats:

- plain text and common source/config/data formats;
- PDF;
- DOCX;
- XLSX;
- HTML/XHTML.

Unsupported formats are recorded as `unsupported` rather than treated as failures. Extraction failures are recorded separately and do not stop the whole pass.

Extracted text is gzip-compressed and split into chunks. `EXTRACT_CHUNK_BYTES` defaults to 16 MiB of uncompressed UTF-8 text per chunk. There is no whole-object text cap, so a large SQL dump produces many chunks instead of being truncated.

Each chunk is represented in PostgreSQL by `object_extraction_chunks` and can be independently indexed into OpenSearch. Raw source objects are never modified.

## Full-text indexing

Initialize the content index:

```bash
./scripts/search-index.sh content-init
```

Index all extracted chunks. This rebuilds the content index so removed or replaced extraction output cannot leave stale chunks behind:

```bash
./scripts/search-index.sh content-index
```

Search inside extracted file contents:

```bash
./scripts/search-index.sh content-search credential
./scripts/search-index.sh content-search "passport number"
```

Results collapse multiple chunks back to one result per object and print the matching chunk number plus highlighted fragments where OpenSearch can provide them.

The existing metadata index remains separate:

```bash
./scripts/search-index.sh search credential
```

## Local security

The Compose configuration disables the OpenSearch Security plugin and binds PostgreSQL/OpenSearch ports to localhost. This is for local development only.
