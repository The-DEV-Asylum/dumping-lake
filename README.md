# dumping-lake

`dumping-lake` is a local, content-addressed research corpus built for heterogeneous security datasets: 
SQL dumps, leaked databases, documents, images, archives, source code, logs, reports, and whatever 
other evidence humanity decided was a good idea to leave lying around.

The basic philosophy is simple:

> Keep the original data.
> Know exactly what it is.
> Don't lose track of where it came from.
> Make it searchable without destroying it.

Because apparently that's difficult. Especially if you have Terabytes of stuff on an old USB hard drive behind a Pi.

## What it does

`dumping-lake` takes a pile of files and turns it into a searchable research corpus.

```text
Source filesystem
       │
       V
    Ingest
       │
       ├── SHA-256
       ├── deduplication
       ├── metadata
       └── immutable raw storage
                  │
                  V
             PostgreSQL
                  │
                  ├── object catalogue
                  ├── source relationships
                  └── extraction metadata
                  │
                  V
              Extractor
                  │
                  └── derived text chunks
                  │
                  V
              OpenSearch
                  │
                  ├── metadata search
                  └── full-text search
```

The important word there is **original**.

The raw bytes are stored separately using their SHA-256 as the object identity.

We don't rewrite evidence because some parser got ambitious.

## Why content addressing?

Because filenames lie. These two:

```text
customers-final.csv
customers-final-final.csv
```

might be identical.

Or:

```text
report.pdf
report2.pdf
copy_of_report.pdf
```

might all contain the same bytes.

`dumping-lake` hashes the file and stores one object per unique SHA-256.

So:

```text
17,000 files
     |
     V
16,700 unique objects
```

The duplicates still exist in the catalogue as source relationships.
Nothing gets forgotten just because the bytes are identical.

## Storage model

Raw objects live under:

```text
data/raw/
```

They are content-addressed and never indexed directly into OpenSearch.
PostgreSQL stores the catalogue:

```text
objects
source_files
ingestion_runs
ingestion_errors
object_extractions
object_extraction_chunks
extraction_runs
```

Derived text is stored separately from the raw corpus.

Because **your evidence is the evidence**.

## Search

Metadata search:

```bash
./scripts/search-index.sh search credential
```

Full-text search:

```bash
./scripts/search-index.sh content-search "phone number"
```

The second command searches extracted content rather than filenames.

That distinction becomes fairly important when the file is called:

```text
1614851577835_19090_5e8155cce111a991bf45c2830c7c81be_2.jpg
```

and the interesting thing inside it is your ex phone number you like to drunk call.

## Extraction

Extraction is deliberately separate from ingestion.
That means a broken PDF parser doesn't get to break your corpus.

Text-capable files are extracted into compressed chunks.
Large files are split into bounded pieces instead of becoming one gigantic OpenSearch document.

This is especially useful for:

* SQL dumps
* CSV exports
* logs
* source trees
* large text files
* documents containing enormous tables

Images are currently catalogued but not automatically OCR'd.
That's coming later.
Recognizing text in pictures without killing resource quite a challenge nowdays.

## Design principles

### Raw data is immutable

The raw object is the source of truth.
Derived data can be deleted and rebuilt.

### Metadata is separate from content

PostgreSQL is the catalogue.
OpenSearch is the search layer.
Neither one is the raw-data store.

### Everything is restartable

Ingestion, extraction, and indexing are separate stages.
A failure in one should not require starting over from the beginning.

### Deduplication is by bytes

Not by filename.
Not by extension.
Not by "looks similar."

By SHA-256.

### Local first

This project is intended to run on your own hardware.

No SaaS account required.
No subscription.
No mysterious API bill appearing because somebody searched for "password."

## Current stack

* Python
* PostgreSQL
* OpenSearch
* Docker Compose
* SHA-256 content addressing
* compressed derived text
* `opensearch-py`
* `psycopg`

## Current status

The pipeline currently supports:

* recursive ingestion
* SHA-256 deduplication
* source-to-object relationships
* filesystem error tracking
* restart-safe ingestion
* metadata indexing
* text extraction
* chunked derived text
* full-text indexing
* metadata search
* content search

Planned work includes:

* OCR
* archive-aware extraction
* richer file-type support
* Parquet/DuckDB analytics
* entity extraction
* relationships between datasets
* local LLM/RAG
* better search ranking

## Important warning

This project is designed for research data.

That means the data may be sensitive, illegal to redistribute, dangerous to handle, or just generally the sort of thing 
you don't want uploaded to GitHub.

Do not expose the raw corpus through Docker ports.
Do not commit `data/`.
Do not put your `.env` in Git.
Do not assume that because you can access a dataset, you are legally allowed to publish it.
The computer is not your lawyer.

Neither am I.

## License

See `LICENSE`.

Use responsibly.
Preferably with backups.
Preferably with a working filesystem.

I've seen what happens when researchers skip the backups.
