# dumping-lake
![](.github/dev-asylum-dumping-lake.png)

**A local, content-addressed research corpus for piles of files that have outgrown human memory.**

Part evidence catalogue, part extraction pipeline, part search engine. It preserves original bytes, records where each copy came from, extracts text into rebuildable derivatives, and makes the resulting corpus searchable. Because apparently "put it in a folder and remember the filename" does not scale to several terabytes.

> **The DEV Asylum rule:** the idea can be ridiculous. The implementation cannot.

## The Asylum verdict

- **Does it work?** The repository contains a runnable multi-service pipeline. Validate it on your own data and environment using the checklist in [`docs/engineering-notes.md`](docs/engineering-notes.md) before calling a deployment tested.
- **Is it useful?** If you have a large, heterogeneous local research corpus, potentially. If you have three PDFs, a folder is still winning.
- **What does it teach?** Content-addressed storage, idempotent ingestion, provenance, database modelling, restartable pipelines, bounded text chunking, search indexing, and the art of making several containers agree on what "done" means.

## What it does

`dumping-lake` takes files from a configured local source and builds a searchable catalogue without rewriting the originals.

```text
Source filesystem (read-only mount)
          |
          v
       Ingest
          |  SHA-256, metadata, source relationships
          v
  Content-addressed raw store <----> PostgreSQL catalogue
          |
          v
       Extractor
          |  bounded text chunks, extraction status
          v
   Derived text store
          |
          v
       Indexer --------------------> OpenSearch
                                      | metadata search
                                      | full-text search
```

The important distinction is between **source files**, **unique byte-identical objects**, and **derived data**. Different paths can refer to the same SHA-256 object. Extracted text and search indexes are derivatives; the original bytes remain the source of truth.

## Why content addressing?

Filenames are not identity. `report-final.pdf`, `report-final-v2.pdf`, and `report-really-final.pdf` may be three names for one object, or three different objects with a naming problem.

The ingest stage hashes file contents with SHA-256 and deduplicates storage by bytes. Source-path relationships are retained in the catalogue, so deduplication does not erase provenance. A hash is a practical content identifier, not proof that a file is authentic or trustworthy.

## Pipeline stages

1. **Ingest** recursively walks the configured source, records metadata and source relationships, hashes files, and stores unique raw objects.
2. **PostgreSQL** tracks objects, source files, ingestion runs/errors, and extraction metadata.
3. **Extract** processes supported text-capable files separately from ingestion. Large outputs are split into bounded chunks.
4. **Index** publishes object metadata and extracted text to OpenSearch.
5. **Search** queries metadata or extracted content.

Keeping stages separate means a parser failure should not require rereading every source file. It also means each stage needs its own observability and recovery story. Containers are not a substitute for those things, despite their excellent ability to look busy.

## Stack

- Python services for ingest, extraction, and indexing
- PostgreSQL for the catalogue and pipeline state
- OpenSearch for metadata and full-text search
- Docker Compose for local orchestration
- SHA-256 content addressing and compressed extracted text

## Quick start

### 1. Prepare configuration

```bash
cp .env.example .env
```

Edit `.env` before starting anything. Set `POSTGRES_PASSWORD` to a long, unique random value and set `HOST_INGEST_ROOT` to the directory you intend to ingest. The source is mounted read-only into the ingest container. Keep `.env` out of version control.

The sample paths are examples, not magic. Replace `/home/ghost/external-hd` and `/source/Leaks` with paths that exist in your environment.

### 2. Start the services

```bash
docker compose config
docker compose up --build -d
```

Check service state and logs:

```bash
docker compose ps
docker compose logs --tail=100
```

### 3. Run the pipeline stages

Use the repository scripts as the intended entry points:

```bash
./scripts/ingest.sh
./scripts/extract.sh
./scripts/search-index.sh
```

The exact runtime and command options are defined in the scripts and service entry points. Check their output and exit status at each stage rather than assuming that a running container means the corpus is fully indexed. It means the container is running. We have not yet solved observability by wishful thinking.

### 4. Search

Search indexed metadata:

```bash
./scripts/search-index.sh search credential
```

Search extracted text:

```bash
./scripts/search-index.sh content-search "phone number"
```

Search results depend on which stages have completed and which file types the extractor supports.

## Storage layout

```text
data/
├── raw/        # original, content-addressed objects
├── staging/    # temporary pipeline work
├── extracted/  # derived, compressed text chunks
└── parquet/    # reserved for future analytical outputs
```

`data/` is deliberately excluded from source control. Treat it as potentially sensitive research material, not a sample-data directory to casually attach to an issue.

## Design principles

### Preserve originals
Raw bytes are the source of truth. Extraction and indexing must not rewrite them.

### Track provenance
A content hash identifies bytes; source records describe where those bytes were found. Keep those concepts separate.

### Make derivatives rebuildable
Search indexes and extracted text can be regenerated from source objects. Recovery should be a documented operation, not a late-night archaeological expedition.

### Bound resource use
Large text files are chunked rather than turned into a single enormous search document. Large corpora still need disk, memory, and time budgets; "local" is not another word for "free."

### Prefer repeatable stages
Ingest, extract, and index independently. Failures should be visible and recoverable without corrupting the original corpus.

## Current scope

The repository implements recursive ingestion, SHA-256 deduplication, source-to-object relationships, ingestion error tracking, text extraction, chunked derived text, metadata indexing, full-text indexing, and command-line search.

Not currently implemented as part of the standard pipeline: automatic OCR, archive-aware recursive extraction, advanced entity/relationship extraction, and local LLM/RAG. Those are future experiments, not features you should infer from a roadmap.

## Security, privacy, and legal boundaries

This tool is intended for datasets you are authorised to possess and analyse. A security-research label does not make stolen, personal, or restricted data lawful to collect or redistribute.

- **Keep it local.** The Compose file binds PostgreSQL and OpenSearch ports to loopback, but OpenSearch security is disabled in the supplied configuration. Do not change those bindings to `0.0.0.0` or expose the services to an untrusted network.
- **Protect the corpus.** Restrict filesystem permissions, encrypt disks where appropriate, and keep backups access-controlled. Hashing is not encryption.
- **Keep secrets out of Git.** Use `.env` locally; commit only `.env.example` with placeholder values.
- **Minimise sensitive data.** Ingest only what you have a lawful basis to handle. Plan retention and deletion, and remember that extracted text and search indexes can contain the same sensitive information as the originals.
- **Treat files as hostile input.** Parsers can be buggy, malformed files can consume resources, and extracted text can contain secrets. Run with least privilege and test on disposable copies first.
- **Do not publish corpus data.** Never commit `data/`, real datasets, credentials, or logs containing personal information.

This is a research pipeline, not a certified evidence-management platform or production security boundary. Threat-model your own deployment before relying on it for sensitive investigations.

## Testing and known limitations

The repository includes a manual validation checklist in [`docs/engineering-notes.md`](docs/engineering-notes.md). It covers idempotency, deduplication, failure handling, extraction chunking, indexing, search, and local-only exposure. Record actual outcomes in your release notes. A test plan is not a test result, no matter how confident the Markdown looks.

File-type support and extraction quality depend on the installed libraries and input. OpenSearch is a derived index and can be rebuilt, but index refreshes and bulk operations can still fail partway through. Large corpora need monitoring for disk consumption, memory pressure, slow parsers, and incomplete jobs.

## Contributing

Small, reviewable changes are preferred. Explain the failure mode or technical question, include reproducible steps, test the affected stage, and document limitations. Please do not include real sensitive data in issues, logs, fixtures, or screenshots. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

See [`LICENSE`](LICENSE).

---

**Does it work?** Test the pipeline. **Is it overkill?** Almost certainly. **Did we learn something?** That's the point.
