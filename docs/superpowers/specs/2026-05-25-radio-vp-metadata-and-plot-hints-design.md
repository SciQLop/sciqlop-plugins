# Design — radio plugin: ISTP metadata on the product tree + plot hints parity with the bundled Speasy plugin

**Status:** approved, ready for plan
**Branch:** `feat/radio-speasy-catalog` (continuation; previous work shipped 38 catalog entries + 2 continuous VPs)
**Date:** 2026-05-25

## Problem

The `sciqlop_radio` plugin registers 40 virtual products (38 Speasy-sourced catalog + 2 radiospectra-Fido continuous), all of type `Spectrogram`. Two visible deficits vs. what the bundled `SciQLop.plugins.speasy_provider` produces for the same Speasy parameters under the `speasy/...` tree:

1. **Product-tree metadata is bare.** Each VP node ends up with `components` (semicolon-joined string), `provider` (the auto-generated EasyProvider name), `stable_id` (set to the VP path), `description` (auto-generated "Virtual Spectrogram product built from Python function: …"). No ISTP attributes (`UNITS`, `LABLAXIS`, `SCALETYP`, `DISPLAY_TYPE`, `FILLVAL`, `VAR_NOTES`, `DEPEND_0`, `DEPEND_1`, …). The inspector / tooltips / command-palette descriptions are correspondingly thin.

2. **No plot hints — labels and scales default to generic.** `EasyProvider` inherits `DataProvider.plot_hints(node)` → `PlotHints()` (empty) and `DataProvider.plot_hints_from_variable(node, variable)` → `PlotHints()`. SciQLop's `time_sync_panel._PostFetchHintsApplier` calls both and applies the merged result — when both are empty, the colormap renders with default y2 ticks, no frequency label, possibly linear scale on freq AND color, no colorbar unit. The bundled Speasy plugin overrides both hooks (`SciQLop/plugins/speasy_provider/speasy_provider.py:412–427`) using `SciQLop.core.istp_hints.istp_metadata_to_hints` and `SciQLop.core.speasy_hints.variable_as_istp_meta`. Result on native Speasy products: correct axis labels + units + log scaling appear on first fetch.

The fix is to make our VP-backing providers do exactly what the bundled Speasy plugin does — for both metadata storage and the two plot-hint hooks.

## Goals

- Catalog entries carry the same ISTP-flavored metadata on their product-tree nodes that the bundled Speasy plugin attaches to its `speasy/<provider>/<uid>` siblings.
- Catalog VPs and continuous VPs apply pre-fetch and post-fetch plot hints via the same translation functions the bundled Speasy plugin uses (`istp_metadata_to_hints`, `variable_as_istp_meta`).
- Behaviour parity verifiable: a fake-Speasy-inventory unit test confirms the rich metadata lands on the node; subclass-level unit tests confirm the two hooks return the expected `PlotHints` shape.
- No regression on the 74 currently-passing tests; the shipped-file catalog-validation test continues to pass.
- No new exception paths reach SciQLop's data thread or load path.

## Non-goals

- Per-entry hand-overrides of any metadata field. The catalog YAML stays minimal (path + speasy_id + type + labels). All Speasy-sourced metadata flows automatically from the inventory index at registration time.
- Knobs / templated AMDA parameters. Catalog callbacks are `(start: float, stop: float) -> SpeasyVariable | None`; knob support is unchanged.
- Touching `radio_catalog.yaml` content. The 38 entries remain.
- Touching the public `SciQLop.user_api.virtual_products.create_virtual_product` surface. We bypass it for catalog/continuous registration in favour of a thin internal factory, exactly as the bundled Speasy plugin bypasses it.
- Changing how `continuous.py` fetches/parses radiospectra files. Only the `register_continuous_products` wiring changes.

## Architecture

One new module + targeted edits to two existing modules. No new dependencies, no schema growth in `radio_catalog.yaml`.

```
sciqlop_radio/sciqlop_radio/
├── hints.py             ← NEW
├── catalog.py           ← UPDATED (_resolve_index, _register_entries)
├── continuous.py        ← UPDATED (ContinuousSource.static_meta, register_continuous_products)
├── radio_catalog.yaml   ← UNCHANGED
└── tests/
    ├── test_hints.py     ← NEW
    ├── test_catalog.py   ← UPDATED (metadata-on-node assertion)
    └── test_continuous.py ← UPDATED (static_meta pass-through assertion)
```

### `hints.py` — the whole new surface

Three public-ish items (no leading underscore on items used by `catalog.py`/`continuous.py`; underscore on internal helpers):

#### 1. `extract_speasy_index_meta(index, *, components=None) -> dict[str, Any]`

Pure function mirroring `SciQLop.plugins.speasy_provider.get_node_meta` + `make_product` minus the node construction:

- Walks `index.__dict__`; keeps entries whose value is `str | int | float | bool` or `list/tuple` of those primitives. Drops underscore-prefixed names, callables, dicts, exotic objects.
- Adds the four Speasy-plugin canonical keys:
  - `uid = index.spz_uid()`
  - `provider = index.spz_provider()`
  - `speasy_id = f"{provider}/{uid}"`
  - `stable_id = speasy_id`
- Adds `components = components or get_components_like_speasy(index)`. We re-import or vendor a minimal version of the Speasy plugin's `get_components` so AMDA/CDA quirks (LABL_PTR_1 parsing, AMDA timeseries) are handled the same way. Decision: **vendor a minimal copy**, not import from the bundled Speasy plugin — the bundled plugin is `SciQLop.plugins.speasy_provider`, not a stable user_api module; importing across plugins would be brittle. Keeps our plugin self-contained and the vendored helper is ~15 lines.
- Returns a flat `dict[str, Any]` suitable for `ProductsModelNode(... metadata, ...)`.

#### 2. `RichEasyScalar / RichEasyVector / RichEasyMultiComponent / RichEasySpectrogram`

Four thin subclasses of `EasyScalar / EasyVector / EasyMultiComponent / EasySpectrogram` from `SciQLop.components.plotting.backend.easy_provider`. Each overrides exactly the same two methods, identically:

```python
def plot_hints(self, node) -> PlotHints:
    try:
        return istp_metadata_to_hints(node.metadata())
    except Exception:
        log.debug("plot_hints failed for %s", node, exc_info=True)
        return PlotHints()

def plot_hints_from_variable(self, node, variable) -> PlotHints:
    try:
        meta = variable_as_istp_meta(variable)
        if self.graph_type(node) == GraphType.ColorMap:
            meta.setdefault("DISPLAY_TYPE", "spectrogram")
        return istp_metadata_to_hints(meta)
    except Exception:
        log.debug("plot_hints_from_variable failed for %s", node, exc_info=True)
        return PlotHints()
```

Both methods are bit-for-bit copies of the bundled Speasy plugin's overrides (cf. `speasy_provider.py:412–427`). We bundle all four variants for future-proofing even though today's catalog is 100% spectrogram — each is a 7-line copy, the cost is trivial vs. discovering later that a new vector entry doesn't get hints.

`from SciQLop.core.plot_hints import PlotHints`, `from SciQLop.core.istp_hints import istp_metadata_to_hints`, `from SciQLop.core.speasy_hints import variable_as_istp_meta`, `from SciQLop.core.enums import GraphType`.

#### 3. `make_rich_vp(path, callback, vp_type, *, metadata, labels=None) -> EasyProvider`

Internal factory that:

- Imports `SciQLop.user_api.virtual_products.VirtualProductType` lazily and matches `vp_type` against `Spectrogram | Scalar | Vector | MultiComponent`.
- For each, instantiates the matching `Rich*` subclass directly with the supplied `metadata` and `labels` (passing `components_names=labels` for Vector/MultiComponent and `component_name=labels[0]` for Scalar; ignoring labels for Spectrogram).
- Returns the constructed provider instance.

The returned object is what `_register_entries` / `register_continuous_products` store in their `*Registration.vps` dicts (keeping the providers alive against GC). They never call methods on it — it's a handle.

### `catalog.py` changes

- Rename `_resolves(speasy_id, speasy_module) -> bool` to `_resolve_index(speasy_id, speasy_module) -> ParameterIndex | None`. Same dict lookup, returns the index instead of a bool. Callers check `is None`.
- `_register_entries(entries, vp_factory, vp_types, speasy_module)` — `create_vp` parameter renamed to `vp_factory` (semantic change: the signature is now `(path, cb, vp_type, *, metadata, labels=None) -> EasyProvider`, not the user_api `create_virtual_product`). Test injection point preserved.
- Loop body:
  ```python
  index = _resolve_index(e.speasy_id, speasy_module)
  if index is None:
      log.info("catalog: skip %s — %s not in Speasy inventory", e.path, e.speasy_id)
      continue
  try:
      meta = extract_speasy_index_meta(index, components=e.labels)
  except Exception as exc:
      log.warning("catalog: metadata extraction failed for %s: %s — falling back to minimal meta", e.path, exc)
      meta = {"speasy_id": e.speasy_id, "stable_id": e.speasy_id,
              "provider": e.speasy_id.split("/", 1)[0]}
  vptype = _vp_type_for(e.type, vp_types)
  cb = _build_callback(e, speasy_module)
  path = f"radio/{e.path}"
  try:
      vp = vp_factory(path, cb, vptype, metadata=meta, labels=e.labels)
  except Exception as exc:
      log.exception("catalog: vp_factory failed for %s: %s", path, exc)
      continue
  reg.vps[path] = vp
  ```
- `register_catalog_products(catalog_path, *, speasy_module=None, vp_factory=None)` — new optional `vp_factory`, defaulting to `hints.make_rich_vp`.

### `continuous.py` changes

- `ContinuousSource` dataclass adds `static_meta: dict[str, Any] = field(default_factory=dict)`. The two existing sources get minimal hand-written meta:
  ```python
  EOVSA_META = {
      "DISPLAY_TYPE": "spectrogram",
      "SCALETYP": "log",
      "description": "EOVSA solar microwave dynamic spectrum (1–18 GHz)",
      "provider": "radiospectra",
  }
  ILOFAR_META = {
      "DISPLAY_TYPE": "spectrogram",
      "SCALETYP": "log",
      "description": "ILOFAR mode 357 BST dynamic spectrum (10–240 MHz)",
      "provider": "radiospectra",
  }
  ```
  Both rely on the post-fetch hook to populate frequency-axis (y2) and colour-axis units from whatever the radiospectra parser put on the `SpeasyVariable` (`variable.unit`, `variable.axes[1].unit`).
- `register_continuous_products(cache_dir, open_and_convert, *, vp_factory=None)` — new optional `vp_factory`, defaulting to `hints.make_rich_vp`. The call site changes from `create_virtual_product(src.vp_path, cb, VirtualProductType.Spectrogram)` to `vp_factory(src.vp_path, cb, VirtualProductType.Spectrogram, metadata=src.static_meta)`.

### Data flow at plot time

```
User drags radio/PSP/FIELDS/RFS_LFR/FLUX onto a panel
  │
  ▼
SciQLop time_sync_panel._make_product_plot
  │
  ├─ _safe_plot_hints(provider=RichEasySpectrogram, node=…)
  │     → istp_metadata_to_hints(node.metadata())
  │     → PlotHints(z=AxisHints(label="psp_fld_l3_rfs_lfr_PSD_V2_dBpHz", unit="dB/Hz",
  │                              scale="log"),
  │                 y=..., display_type="spectrogram", fill_value=-1e31)
  │     → apply_plot_hints(plot._impl, …) — colorbar label + log scale appear immediately
  │
  ▼
Callback fires → SpeasyVariable returned
  │
  ▼
_PostFetchHintsApplier.observe(variable)
  │
  ├─ RichEasySpectrogram.plot_hints_from_variable(node, variable)
  │     → variable_as_istp_meta(variable)  # includes _depend_1 from variable.axes[1].meta
  │     → istp_metadata_to_hints(…)
  │     → PlotHints(y2=AxisHints(label="Frequency", unit="Hz", scale="log"), z=…)
  │
  ▼
merge_hints(base, extra) → apply_plot_hints — y2 (frequency) axis label + log scale appear
```

The two-step is identical to native Speasy products. The frequency axis appears a few hundred milliseconds after the drop (one fetch latency) — same UX as the rest of the SciQLop product tree.

## The nested-dict constraint (why `_depend_1` is post-fetch only)

`istp_metadata_to_hints` builds y2 hints from `meta.get("_depend_1")` (a nested mapping). `ProductsModelNode` metadata is stored as a `QMap<QString, QVariant>` and only round-trips primitive QVariants — the bundled Speasy plugin's `get_node_meta` explicitly filters `isinstance(child, (list, tuple)) and all(isinstance(v, (str, int, float)))` (no dict branch). So no provider can put `_depend_1` on node metadata; it always reaches `istp_metadata_to_hints` via the post-fetch path that builds the nested dict on the fly from `variable.axes[1].meta`.

We respect this constraint. `extract_speasy_index_meta` filters identically.

## Error handling

| Failure mode | Behaviour |
|---|---|
| `extract_speasy_index_meta(index)` raises (exotic `__dict__` entry, missing `spz_uid()`) | Caught in `_register_entries`. Logged at WARNING. Falls back to `{"speasy_id": …, "stable_id": …, "provider": …}` so the VP still registers and resolves. |
| `Rich*.plot_hints(node)` raises | Caught in the override. Logged at DEBUG (same as bundled Speasy plugin). Returns `PlotHints()`. |
| `Rich*.plot_hints_from_variable(node, var)` raises | Caught in the override. Logged at DEBUG. Returns `PlotHints()`. |
| `_resolve_index(speasy_id, speasy_module)` returns `None` | Unchanged: log INFO, skip the entry. |
| `vp_factory(...)` raises | Unchanged: `log.exception`, skip the entry, registration continues. |
| Speasy module not importable in `register_catalog_products` | Unchanged: returns `None`. |
| `ContinuousSource.static_meta` is `None` or `{}` | Treated as empty dict. VP registers, only post-fetch hints flow. |

No exception escapes to the caller; the plugin loads in degraded form rather than failing.

## Tests

### New: `sciqlop_radio/sciqlop_radio/tests/test_hints.py`

1. **`extract_speasy_index_meta` accepts and filters correctly.**
   Fake `ParameterIndex` with `__dict__` containing strings, ints, floats, list-of-strings, plus a `dict` (must be filtered), an underscore-prefixed key (filtered), a callable child (filtered). `spz_uid()` + `spz_provider()` return fixed values. Assert resulting dict:
   - Contains the primitives.
   - Drops the dict, the underscore key, the callable.
   - Contains `uid`, `provider`, `speasy_id`, `stable_id`, `components`.

2. **`extract_speasy_index_meta` handles AMDA-style index without LABL_PTR_1.**
   Index with only `display_type="timeseries"` + ComponentIndex children. `components` derived from component spz_name list.

3. **`extract_speasy_index_meta` propagates exceptions; `_register_entries` catches.**
   Extractor responsibility ends at "best-effort dict from a well-formed index". Failure mode is "let it raise". Two tests pin the contract:
   - `pytest.raises(AttributeError)` when the index has no `spz_uid` method — the extractor does NOT swallow.
   - Companion test in `test_catalog.py` (#9 below) confirms `_register_entries` catches the same exception and falls back to minimal meta.

4. **`Rich*.plot_hints(node)` translates ISTP meta to `PlotHints` correctly.**
   Stub the callback with `lambda start, stop: None`. Build a fake `ProductsModelNode`-like object with `.metadata()` returning a known ISTP dict (UNITS="dB", LABLAXIS="PSD", SCALETYP="log", DISPLAY_TYPE="spectrogram"). Assert the returned `PlotHints` has `z.label="PSD"`, `z.unit="dB"`, `z.scale="log"`, `display_type="spectrogram"`. `y2` axis hints are empty (no `_depend_1` in flat meta).

5. **`Rich*.plot_hints_from_variable(node, variable)` populates `y2` from variable axes.**
   Build a fake `SpeasyVariable` with `axes=[time_axis, freq_axis]` where `freq_axis.meta = {"UNITS": "Hz", "LABLAXIS": "Frequency", "SCALETYP": "log"}`. Assert the returned `PlotHints.y2` is populated.

6. **Both hooks swallow exceptions and return `PlotHints()`.**
   Pass a node whose `.metadata()` raises; pass a variable that breaks `variable_as_istp_meta`. Assert empty `PlotHints` returned, no exception propagates.

7. **`make_rich_vp` dispatches by `VirtualProductType`.**
   Stub the user_api enum import; for each of Scalar/Vector/MultiComponent/Spectrogram, assert the returned provider is an instance of the correct `Rich*` subclass and that its node carries the supplied metadata.

### Updated: `sciqlop_radio/sciqlop_radio/tests/test_catalog.py`

8. **Metadata flows onto the registered node.**
   Inject a fake `speasy_module` whose `flat_inventories.<prov>.parameters[uid]` returns a fake index with a rich `__dict__` (UNITS, LABLAXIS, SCALETYP). Inject a fake `vp_factory` that captures its `metadata=` kwarg. Run `_register_entries`. Assert the captured metadata contains the ISTP keys plus `speasy_id`/`stable_id`.

9. **Metadata extraction failure falls back to minimal meta, entry still registers.**
   Fake index whose `spz_uid()` raises. Assert WARNING logged, entry still registers with `{"speasy_id": …, "stable_id": …, "provider": …}` metadata.

10. **Existing shipped-file validation test stays green.**
    No change — already strict.

### Updated: `sciqlop_radio/sciqlop_radio/tests/test_continuous.py`

11. **`static_meta` reaches the vp_factory.**
    Inject a fake `vp_factory`; assert it received the source's `static_meta` dict.

### Acceptance

- Existing test count (74 passed / 1 skipped / 5 pre-existing failures in `test_settings.py`) holds.
- New tests add ~10 cases (target: 84+ passed).
- The 5 pre-existing failures in `test_settings.py` are NOT touched.

## Open follow-ups (out of scope for this branch, recorded for later)

- **Catalog YAML extensions.** Eventually the catalog may want per-entry hand-overrides (e.g. "this AMDA parameter is mis-labeled in the inventory, override LABLAXIS"). The hooks needed are already in place — `extract_speasy_index_meta` could accept an `overrides: dict` kwarg, and `CuratedRadioProduct` could grow an optional `meta_overrides: dict[str, Any]` field. Add when actually needed.
- **`load_catalog` YAML-parse-error test** — still pending from the previous branch's handover.
- **Continuous path harmonisation** (`radio/Ground/eCALLISTO/...`) — still out of scope.
- **`radiospectra` PyPI release pin** — blocks any plugin release, unchanged.

## Why this approach (and what was rejected)

- **Rejected: monkey-patch `vp._impl.plot_hints` after `create_virtual_product`.** Reaches through a documented-private `_impl` attribute. Fragile across SciQLop versions. Doesn't solve the metadata-at-construction problem (the node is built in `EasyProvider.__init__` from the supplied `metadata=` arg).
- **Rejected: a new `create_rich_virtual_product` patch upstream.** Would need a SciQLop user_api change. Decoupling: a plugin shouldn't gate on an SciQLop release. The bundled Speasy plugin already imports from `SciQLop.components.*` for the same reason.
- **Rejected: hand-write `PlotHints` per catalog entry in YAML.** Manual upkeep for 38 entries; defeats the "Speasy inventory IS the metadata source" principle.
- **Chosen: thin `RichEasy*` subclasses + factory.** Mirrors the bundled plugin's design exactly. Self-contained. ~80 LOC including tests. No new public surface; the catalog YAML stays unchanged.
