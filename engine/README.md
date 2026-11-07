# organize GUI engine

This package is the local, stdio-driven engine for the desktop application.
It deliberately separates **planning** from **execution**:

1. A profile is validated and scanned into an immutable plan.
2. The UI reviews and edits plan selection.
3. The executor applies only the selected plan items and journals every change.

File discovery and rule evaluation use the repository's organize v3 core:
`Walker`, `Resource`, and the v3 extension, date, size, duplicate, and hash
filters. Filesystem mutations remain owned by the desktop safety layer so
preview, recovery, quarantine, and undo share one journaled source of truth.
The optional system-trash integration is provided by `send2trash`.

The `by-date` preset files photos by the EXIF date taken (`dateSource: "taken"`,
the default) and falls back to the file's modified date when a photo has no
usable capture date; each plan item records which date was used. Metadata is
read from file headers only (`photo_meta.py`); GPS and camera details never
leave memory.

## Local AI categories (`classify/`)

Optional and off by default (`aiEnabled`). `analysis.scan` builds a read-only
inventory; `analysis.discover` embeds a scrubbed signal per file (name, folder,
metadata summary, up to 1,500 characters of text) with `nomic-embed-text`,
truncates vectors to 256 dimensions (Matryoshka), clusters them with
deterministic k-means++ (seed 42, k <= 12 by silhouette) and names each group
with one `qwen2.5:3b-instruct` call. Photos are grouped by metadata (trips from
GPS + date, screenshots, camera photos). The engine starts its own
`ollama serve` on `127.0.0.1:<free port>` and stops it afterwards; it only calls
`/api/embed`, `/api/chat` and `/api/tags` and never pulls models. Without AI it
proposes simple type/metadata categories instead.

Vector math uses Apple Accelerate (`cblas_sgemm` via `ctypes`) when available,
with a pure-Python fallback; no numpy. Only vectors, accepted centroids and
24-hour per-file assignments are stored; file text never is. Every text passes
`pii.scrub` before reaching a model and every model-returned name is sanitized
by `naming.py`. Trip names use bundled coarse country outlines
(`countries_data.py`, world-atlas 2.0.2 / Natural Earth, see `legal/README.md`).

Run the tests from the repository root:

```bash
python3 -m unittest discover -s engine/tests -v
```

Install organize v3 and its runtime dependencies from the repository root:

```bash
python3 -m pip install -e .
```

Run the NDJSON server:

```bash
PYTHONPATH=engine/src python3 -m organize_gui.rpc_server
```
