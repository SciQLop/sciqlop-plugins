# CDF Workbench backlog

Goal: a full CDF IDE inside SciQLop — read, edit, compare, convert.
Several items port features from the CDFpp Explorer (WASM demo, `CDFpp/docs/explorer.rst`).

Size: S = under a day, M = a few days, L = a week or more.
Order inside each section is the suggested build order.

## Read

- [x] **R1 — Plot variables of rank > 2** (M) — `reduce.py`, `axis_bar.py`
  Today `_is_plottable` rejects ndim > 2, so particle distributions can't be plotted.
  One menu per dimension, named after its `DEPEND_k`: *plot* (becomes y axis, only one), *sum*, *mean*, *= value* (slice).
  Default: energy plotted, other dims summed → omnidirectional energy spectrogram.
  FILLVAL / out-of-range values skipped in sums and means.
  The result is a 2D array, so preview, "Plot in New Panel" and "Send to Console" work unchanged.
  Port of CDFpp `d640f2b`.
  Done. Per-axis sum / mean (sums run before means). "Send to Console" still sends the full variable.
  Not checked on screen: the offscreen test run has no QRhi, so only the preview's plot type and data were verified.
- [x] **R2 — Y axis log/linear override** (S) — "log y" checkbox, `PlotBundle.with_y_scale`
  Toggle above the preview; overrides `SCALETYP`.
  On log, values ≤ 0 are hidden. A spectrogram whose bins include ≤ 0 (e.g. azimuth) stays linear.
  Port of CDFpp `ba289d9`.
- [x] **R3 — Open URL** (S) — URL field on the "+" page, downloads off the GUI thread
  Menu entry / input for an http(s) CDF. `loader._load_url` already exists; only drag-and-drop text reaches it today.
- [x] **R4 — Example files** (S) — `open_page.EXAMPLES`, CDFpp's six + an FPI distribution
  A few public SPDF files (ACE MFI, MMS FPI, THEMIS) on the "+" tab to start from.
  Port of CDFpp `4178582`.
- [x] **R5 — Clear error on very large files** (S) — `memory.py`, per variable read
  Estimate memory before loading; refuse with a message saying how much is needed.
  Port of CDFpp `faaf795`.
  Done per variable, not per file: files load lazily, the memory goes when values are read
  (preview, plot, console, quality analysis). The message shows under the preview.

## Bugs

- [x] **B1 — No preview when DEPEND_1 is a text variable** (S)
  ACE `BGSEc` has `DEPEND_1 = cartesian`, a CDF_CHAR variable. `_read_depend_1` calls `.astype(float64)` on it and raises.
  Treat a text DEPEND_1 as labels, not as a y axis.
- [x] **B3 — Component labels not reversed with a descending DEPEND_1** (S)
  `_make_ascending` flipped the columns but not the labels.
- [x] **B4 — Is pycdfpp lazy loading thread-safe?**
  Yes, per CDFpp's author: the worker and the GUI may load values from the same CDF concurrently.
- [x] **B2 — No quality report for CDF_EPOCH16 files** (S)
  `AnalysisWorker` cast epochs with `astype("datetime64[ns]")`: wrong dates for TT2000/EPOCH, a swallowed error for EPOCH16.

## Edit

A `pycdfpp.CDF` is mostly immutable (no rename, no attribute delete, no overwrite).
So we don't edit it. We load it into our own model, edit the model, and build a fresh CDF on save.

- [x] **E1 — Document model** (M) — `document.py`
  Frozen `Document` / `Variable` / `Attribute`; values stay lazy; `to_cdf` rebuilds a CDF.
  Every CDFpp test file round-trips (types, shapes, NRV, per-variable compression, attributes, values).
  Views read the document; `DocumentSession` tracks modified state; tab title gets `•`.
  Known limits, all pycdfpp 0.15 gaps:
  - file-level compression is lost on save (`CDF.compression` is read-only);
  - CDF_BYTE and empty attributes can't be written from values, so they are copied from the source while unedited;
  - an empty global attribute can't be created at all (`add_attribute(name, [])` breaks on `zip(*[])`);
  - column-major files are saved row-major (`add_variable` takes no majority). Values are identical.
- [ ] **E2 — Save / Save As** (S) — depends on E1
  `pycdfpp.save(to_cdf(doc), path)`, then `session.mark_saved()`. Ctrl+S / Ctrl+Shift+S. URL-opened files only get Save As.
  Closing a modified tab asks Save / Discard / Cancel.
  Cancel / join the `AnalysisWorker` first: it lazily loads values from the same `pycdfpp.CDF` on another thread.
  `to_cdf` holds a second copy of all values; try `add_variable(..., copy=False)` for numeric variables.
- [ ] **E3 — Undo / redo** (S) — depends on E1
  Documents are immutable, so undo is a list of past documents and an index. No per-edit undo commands.
- [ ] **E4 — Edit attributes** (M) — depends on E3
  Edit, add, delete global and variable attributes in the inspector.
  Typed entries (CDF_CHAR, numeric, epoch) — keep the type unless the user changes it.
- [ ] **E5 — Rename / delete variables** (S) — depends on E3
  Rename also updates `DEPEND_*`, `LABL_PTR_*`, `DELTA_*_VAR` references in other variables (ask first).
  Delete warns when other variables reference it.
- [ ] **E6 — Create variables** (M) — depends on E3
  From the console (`workbench.add_variable(name, array, attrs)`) and from a dialog (type, shape, NRV).
- [ ] **E7 — Live lint** (S) — depends on E2
  Re-run AstraLint on `to_cdf(doc)` after each edit (debounced), update inspector badges.
  Also stops URL-opened files being downloaded a second time: lint gets the path/URL today.
- [ ] **E8 — Edit values** (L) — depends on E3
  Table editor for small / NRV variables (labels, support data). Large record variables stay read-only.

## Compare

- [ ] **C1 — Compare two files** (L)
  Variables added / removed / renamed, attributes changed, word-level highlight of changed text.
  Inline and side-by-side views; "hide identical" filter on by default.
  Entry: "Compare with…" in the tab context menu, picking another open tab or a file.
  Port of CDFpp `411e53b`…`9955bf4`, `f3f9a4d`, `d7bf3b3`. Use stdlib `difflib`.
- [ ] **C2 — Copy across** (M) — depends on C1, E4
  From the diff, copy an attribute / attribute set from the reference file into the edited one.

## Convert & export

- [ ] **X1 — Codec comparison** (M) — depends on E2
  Re-encode with each pycdfpp `CompressionType`, show resulting sizes, save the chosen one.
  Run in a worker thread; big files take a while.
  Port of CDFpp `bcd6b00`, `4a7b232`.
- [ ] **X2 — Export structure as YAML** (S)
  Variables + attributes, no data. Start from `pycdfpp.to_dict_skeleton`.
  Port of CDFpp `6f17d37`.
- [ ] **X3 — Export variable data** (S)
  CSV / `.npy` of the plotted (masked, reduced) data, next to "Send to Console".
- [ ] **X4 — Save subset** (S) — depends on E2
  Pick variables (auto-include their `DEPEND_*` / label vars), save a copy via `pycdfpp.filter_cdf`.

## Not planned

- Explorer's spectrogram/line-plot performance work: SciQLopPlots already does it natively.
- Shareable `?url=` links: no equivalent in a desktop app.
