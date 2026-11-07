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
