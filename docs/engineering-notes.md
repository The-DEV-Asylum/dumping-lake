# Engineering notes and validation plan

## Architecture decisions

- **SHA-256 content addressing:** stores one raw object for byte-identical files while preserving distinct source-path records. Hash equality is useful for deduplication; it is not a provenance guarantee or authenticity check.
- **PostgreSQL catalogue:** separates object identity, source location, ingestion state, and extraction state. This allows stages to resume without treating a filesystem walk as the whole database.
- **Separate extraction stage:** parser failures should not block initial cataloguing. Extracted output is derived and should be reproducible from retained originals.
- **Chunked extracted text:** bounds the size of individual indexed documents and supports large logs, SQL dumps, and text exports.
- **OpenSearch as a derivative:** useful for search, but not the system of record. Rebuild it from the catalogue and extracted text when necessary.
- **Local-only defaults:** database/search ports bind to loopback in Compose. The supplied OpenSearch setup disables its security plugin, so changing network bindings is unsafe without adding and validating authentication and TLS.

## Manual validation checklist

Run these tests on a disposable corpus before using the system for sensitive research. Record versions, commands, exit codes, and outcomes.

### Ingestion and identity

- [ ] Ingest a small directory containing a text file, a binary file, and a nested directory.
- [ ] Ingest two differently named files with identical bytes; confirm raw storage is deduplicated and both source relationships remain discoverable.
- [ ] Modify one byte and re-ingest; confirm it is treated as a distinct object.
- [ ] Run ingestion twice; verify the second run does not create duplicate object records or corrupt existing metadata.
- [ ] Test an unreadable file and a path that disappears during traversal; confirm errors are recorded and the run reports failure/partial completion clearly.
- [ ] Test filenames with spaces, Unicode, and shell metacharacters.

### Extraction

- [ ] Extract a small supported text file and compare extracted content with the source.
- [ ] Test empty files, invalid encodings, very long lines, and a file larger than the configured chunk size.
- [ ] Confirm chunk metadata and compressed files agree on chunk count and byte counts.
- [ ] Force a parser failure; verify raw objects remain intact and the extraction error is recorded.
- [ ] Re-run extraction and verify its intended idempotency/recovery behaviour.

### Indexing and search

- [ ] Build the metadata index and search for a known filename and source path.
- [ ] Build the content index and search for a phrase present only inside a text file.
- [ ] Delete/recreate the disposable OpenSearch indexes and verify they can be rebuilt from the catalogue and extracted text.
- [ ] Simulate a missing extracted chunk and verify the indexer logs it clearly.
- [ ] Test an empty corpus and a corpus with enough chunks to exercise bulk indexing.

### Operations and safety

- [ ] Validate configuration with `docker compose config` before startup.
- [ ] Confirm PostgreSQL and OpenSearch are reachable only through loopback on the host.
- [ ] Confirm no real corpus data, `.env`, credentials, or sensitive logs are tracked by Git.
- [ ] Measure disk and memory use on representative data; test low-disk and restart scenarios where practical.
- [ ] Verify backup and restore procedures for the catalogue, raw object store, and derived data.
- [ ] Record the exact versions of Docker, Python dependencies, PostgreSQL, and OpenSearch used for the test.

## Known limitations and open questions

- Extraction is limited to supported file types and may not preserve every semantic detail of complex formats.
- OCR and archive-aware extraction are not currently part of the default pipeline.
- Hash-based identity does not establish source authenticity, legal provenance, or whether content is safe to open.
- Indexing is a separate stage and can be incomplete even when ingestion succeeded. Operators must check exit status, logs, and index counts.
- The supplied Compose configuration disables OpenSearch security. Loopback binding reduces exposure on a single host, but it is not a substitute for authentication and TLS if the topology changes.
- Resource limits and retention policy should be set for the actual corpus. Search indexes, raw bytes, and extracted text can each contain sensitive material.

## Release discipline

Do not label a release "tested" unless the relevant checks have been run and the environment and results are recorded. If something fails, document the failure and the recovery path. Logs are evidence; confidence is not.
