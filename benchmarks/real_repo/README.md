# Real-repository validation

This directory contains reproducible validation harnesses for testing Code Steward on pinned public open-source source trees.

These experiments are separate from Frozen Benchmark v1. They must not modify or retune the frozen benchmark.

## Requests target

`requests.json` pins `psf/requests` to an exact commit and limits the initial validation scope to `src/requests`.

The GitHub Actions workflow checks out that exact upstream commit, builds a Code Steward index, and records:

- Python source-file count
- indexed units and endpoints
- build time and SQLite size
- total Python AST `CALLS` relationships
- resolved unit targets versus unresolved symbols
- resolution percentage
- a deterministic mixed sample of resolved and unresolved relationships for manual audit

The workflow then evaluates the unchanged production `retrieve_units()` pipeline against the manually verified cases in `requests_retrieval.json`. The retrieval report records Hit@1/3/5/K, macro recall, MRR, known traps and redundancy, returned candidate count, packet bytes, and retrieval latency. `CALLS` relationships are not consumed by this baseline.

The generated JSON, Markdown summaries, and SQLite database are uploaded as a workflow artifact. The upstream source itself is not vendored into Code Steward.

## Manual run

From an installed Code Steward checkout:

```bash
python benchmarks/real_repo/validate.py \
  --project-root /path/to/requests/src/requests \
  --output-dir validation-results/requests \
  --repository psf/requests \
  --commit 8f8b212de8c2129d7954c6cd373762880375620a

python benchmarks/real_repo/retrieval_baseline.py \
  --database validation-results/requests/index.sqlite3 \
  --cases benchmarks/real_repo/requests_retrieval.json \
  --output-dir validation-results/requests
```

A successful build implies zero Python parse failures for the indexed scope because Code Steward now fails atomically on malformed Python instead of silently producing a partial index.
