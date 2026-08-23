# Byte figures against real tokens

Every cost number this project publishes is measured in **bytes** —
packet bytes, wasted bytes per query, bytes returned per similarity
arm. Bytes are a proxy for the thing that actually costs money and
context, which is tokens, and nothing had ever checked how good a
proxy they are.

They are a decent one, and the error is not uniform. It is largest on
exactly the population the README quotes most.

## Measurement

`tiktoken`, encoding `o200k_base`, over four populations: the
normalised unit bodies of the three pinned similarity corpora, and the
per-case packets of Frozen Benchmark v1. The pooled figure is
size-weighted across all four; each row's error is what a reader
introduces by applying that single pooled ratio to that population.

| Population | Samples | Bytes | Tokens | Bytes/token | Error of the pooled assumption |
| --- | --- | --- | --- | --- | --- |
| home-assistant | 1,695 | 756,555 | 180,847 | 4.183 | +3.6% |
| airflow | 1,195 | 833,974 | 198,905 | 4.193 | +3.4% |
| django | 3,957 | 2,097,639 | 470,910 | 4.454 | −2.7% |
| **frozen-benchmark-packets** | 12 | 6,940 | 1,775 | **3.910** | **+10.9%** |

Pooled: **4.335 bytes per token.**

Committed at [`benchmarks/token_calibration.json`](../benchmarks/token_calibration.json).
Regenerate with `make bench-tokens CHECKOUTS=<dir>`.

## What it means for the published numbers

**Between corpora of ordinary Python, bytes are a fair proxy.** The
three source corpora sit within ±3.6% of the pooled ratio. A byte
comparison between two arms measured on the same corpus — which is
every comparison in [`docs/similarity.md`](similarity.md) — carries
essentially no tokenizer error, because both arms are drawn from the
same population.

**Packets are denser than source and the proxy is worst there.** At
3.910 bytes per token, the packet population is 9.8% below the pooled
ratio, so applying the pooled figure overstates its token count by
10.9%. Packets are JSON: braces, quotes, and short keys tokenize
harder than prose or identifiers do.

**The direction matters for the compression claim.** The README's
headline is 4,039 packet bytes against 21,107 source bytes, a 5.2×
compression. Converted properly, the packet side is *worse* than the
byte ratio suggests and the source side is better, so the true token
compression is **smaller than 5.2×**. This calibration covers the
frozen-benchmark packets rather than the `psf/requests` packets, so it
sizes the effect without correcting that specific figure. Sizing it
is the point: the compression claim is directionally overstated by
roughly a tenth, and the README should not be read as if 5.2× were a
token ratio.

## Why this is not enforced in CI

`tiktoken` is an optional dependency (`pip install -e '.[bench]'`).
Adding it to a five-version CI matrix costs a wheel download per job
to re-derive a number that changes only when the corpora or the packet
format change. The calibration is a periodic check whose output is
committed; the test that reads it skips when `tiktoken` is absent and
runs when it is present.
