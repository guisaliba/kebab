# Ingestion Rules

- Every source must have a `manifest.yaml`.
- Every source must be registered in `raw/registry.yaml`.
- Raw source content is immutable after ingestion.
- Long transcripts should be chunked into stable file units.
- Every ingest must create a review package in `staging/reviews/`.
- No source may promote directly into `wiki/`.
