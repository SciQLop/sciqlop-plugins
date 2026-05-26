# Curated radio products from Speasy, surfaced in the radio plugin tree

**Date:** 2026-05-22
**Plugin:** `sciqlop_radio`
**Status:** approved design, pre-implementation

## Goal

Give SciQLop users a single, curated place to find space-mission radio
dynamic-spectra. Many such products already exist in Speasy (AMDA / CDAWeb)
but are scattered across the `speasy/<provider>/…` provider trees and hard to
discover. We surface a hand-picked selection under the radio plugin's own
`radio/<Mission>/<Instrument>/<Product>` subtree, alongside the existing
radiospectra-sourced continuous virtual products.

This is **curated discoverability**: the data still comes from Speasy at plot
time. We create parallel tree entries — we do not move or alias the existing
Speasy nodes (SciQLop's `ProductsModel` is frozen at startup, so in-place
re-organization isn't a supported runtime operation).

## Non-goals

- Reorganizing / aliasing existing `speasy/…` nodes in place.
- Moving the existing radiospectra continuous VPs (`radio/psp_rfs_lfr`, …) into
  a `radio/<Mission>/…` layout. Left where they are in this change.
- Auto-discovering radio products from Speasy metadata heuristics (rejected:
  noisy/unpredictable).
- Per-entry plot-hint overrides (YAGNI — styling is inherited from Speasy
  metadata; revisit only if a real product needs it).

## Why Approach A (virtual products delegating to Speasy)

`create_virtual_product(path, callback, type)` is the only supported way to add
nodes to SciQLop's product tree at runtime (project memory:
`feedback_use_virtual_products_api`, `feedback_sciqlop_products_model_frozen_at_startup`).
The callback fetches via `speasy.get_data`, so:

- Spectrogram styling (log-frequency axis, labels, units) is applied by
  SciQLop's spectrogram-VP pipeline from the returned `SpeasyVariable`'s ISTP
  metadata — no `plot_hints` code, no `_impl` reach-through in the plugin.
- We reuse the exact machinery `continuous.py` already uses.
- The catalog stays pure data.

Rejected alternative — injecting `ProductsModelNode`s directly (native
drag-drop, no wrapper) — fights the frozen-model design, has unverified
`add_node` dedup behavior, and adds private-API coupling. Memory has already
steered us away from reaching into `ProductsModel`.

## Module layout

- **`sciqlop_radio/catalog.py`** *(new)*
  - `CuratedRadioProduct` — pydantic model (one catalog entry).
  - `load_catalog(path) -> list[CuratedRadioProduct]` — read YAML, validate each
    entry, skip-with-log on malformed entries, return `[]` on missing file or
    top-level parse error.
  - `register_catalog_products(catalog_path, *, speasy_module=None,
    create_virtual_product=None) -> CatalogRegistration` — mirrors
    `continuous.register_continuous_products`. Resolves each entry against the
    Speasy inventory, registers a VP per resolvable entry, keeps refs alive.
    Injectable `speasy_module` / `create_virtual_product` for testing.
- **`sciqlop_radio/radio_catalog.yaml`** *(new, package-data)* — the curated data.
- **`sciqlop_radio/__init__.py`** — `load()` calls `register_catalog_products(...)`
  next to the existing `register_continuous_products(...)`; both handles stored
  in `_LOADED_PANELS[key]` so the VPs aren't GC'd (SciQLop's tree holds the
  callback weakly).
- **Packaging** — add `pyyaml` to `dependencies` in `pyproject.toml` and to
  `python_dependencies` in `plugin.json`; add `radio_catalog.yaml` to
  `[tool.setuptools.package-data]`.

## Catalog YAML schema

```yaml
# radio_catalog.yaml — curated space-mission radio dynamic spectra.
# Data is fetched from Speasy at plot time. Entries that don't resolve in the
# installed Speasy inventory are skipped-with-log, so this file can list more
# than any single user has providers enabled for.
# Curation rule: do NOT duplicate products already covered by the radiospectra
# continuous VPs (radio/psp_rfs_lfr, radio/psp_rfs_hfr, radio/eovsa,
# radio/ilofar).
- path: Wind/WAVES/RAD1            # → tree node radio/Wind/WAVES/RAD1
  speasy_id: amda/wnd_swaves_rad1  # "<provider>/<uid>" passed to speasy.get_data
  type: spectrogram                # default; vector | scalar | multicomponent allowed
  label: Wind/WAVES RAD1           # optional; defaults to `path`
```

`CuratedRadioProduct` fields:

| field      | type                                                  | rules |
|------------|-------------------------------------------------------|-------|
| `path`     | `str`                                                 | non-blank; no leading/trailing `/`; nested via `/` |
| `speasy_id`| `str`                                                 | shape `<provider>/<uid>` (must contain one `/`, both sides non-blank) |
| `type`     | enum `spectrogram \| vector \| scalar \| multicomponent` | default `spectrogram` |
| `label`    | `str \| None`                                         | defaults to `path` |
| `labels`   | `list[str] \| None`                                   | **required** when `type != spectrogram` (create_virtual_product needs component labels for Scalar/Vector/MultiComponent); ignored for spectrogram |

## Load → resolve → register flow

For each validated entry:

1. **Map type → `VirtualProductType`**: `spectrogram → Spectrogram`,
   `vector → Vector`, `scalar → Scalar`, `multicomponent → MultiComponent`.
2. **Resolve** `speasy_id`: split into `provider, uid`; look up
   `getattr(speasy.inventories.flat_inventories, provider, None)` then
   `uid in getattr(flat, "parameters", {})`. In-memory dict lookup — no network,
   because SciQLop's `speasy_provider` builds the inventories at startup, before
   our `load()` runs. Unresolved → `log.info(...)` + skip (don't register).
3. **Register**: `create_virtual_product(f"radio/{entry.path}", callback,
   vptype)` (plus `labels=` when non-spectrogram). Store the returned VP in the
   `CatalogRegistration.vps` dict to keep it alive.

Callback (built per entry):

```python
def _build_callback(entry, speasy_module):
    def _cb(start, stop, **kwargs):  # **kwargs: SciQLop may pass knobs
        t0 = datetime.fromtimestamp(float(start), tz=timezone.utc)
        t1 = datetime.fromtimestamp(float(stop), tz=timezone.utc)
        try:
            return speasy_module.get_data(entry.speasy_id, t0, t1)
        except Exception as exc:  # noqa: BLE001 — never break SciQLop's data thread
            log.warning("catalog(%s): get_data failed: %s", entry.path, exc)
            return None
    return _cb
```

`speasy.get_data` returns a `SpeasyVariable` (already carries time axis,
frequency depend-axis, ISTP metadata) or `None`. SciQLop renders it as a
colormap and applies styling from the metadata.

## Tree organization & overlap

- Curated set: `radio/<Mission>/<Instrument>/<Product>`
  (e.g. `radio/Wind/WAVES/RAD1`, `radio/STEREO-A/SWAVES/HFR`).
- Existing radiospectra continuous VPs unchanged: `radio/psp_rfs_lfr`,
  `radio/psp_rfs_hfr`, `radio/eovsa`, `radio/ilofar`.
- Curation avoids duplicating those (see YAML header rule).

## Initial catalog content

Broad best-effort set. Seeded by researching Speasy's AMDA/CDAWeb inventory for
radio dynamic-spectra across missions: Wind/WAVES (RAD1, RAD2, TNR), STEREO-A/B
SWAVES (LFR/HFR), Solar Orbiter/RPW (HFR/TNR), PSP/FIELDS (where not already a
continuous VP), Cassini/RPWS, Juno/Waves, Ulysses/URAP, and others present in
the inventory. Each entry is best-effort; unresolved entries skip-with-log, so
the shipped file can exceed any single install's enabled providers.

## Error handling

Fail-soft; never crash `load()`:

| failure                          | handling |
|----------------------------------|----------|
| `radio_catalog.yaml` missing     | `load_catalog` returns `[]` |
| top-level YAML parse error       | log error, return `[]`, register nothing |
| per-entry validation error       | log + skip that entry, continue |
| `speasy_id` unresolved in inventory | log.info + skip (no VP) |
| `create_virtual_product` raises  | log.exception + continue to next entry |
| callback `get_data` raises / None| catch in callback, warn, return `None` |

## Testing

`sciqlop_radio/tests/test_catalog.py`:

- `load_catalog` parses a valid temp YAML → expected entries.
- malformed entry in YAML → that entry skipped, others kept.
- missing file → `[]`.
- `speasy_id` validation: `"amda/x"` ok; `"noslash"` / `"amda/"` rejected.
- `labels` required when `type != spectrogram` (validation error otherwise).
- resolution helper: monkeypatched `flat_inventories` → resolvable vs not.
- `register_catalog_products` with injected fake `speasy_module` +
  `create_virtual_product`: resolvable entries registered at `radio/<path>`,
  unresolvable skipped, returned `CatalogRegistration.vps` retains refs.
- callback returns the fake `get_data` result; callback swallows a raised
  exception and returns `None`.
- **shipped-file test**: the real `radio_catalog.yaml` loads and every entry
  passes schema validation.
- optional `RADIO_LIVE_TESTS=1`: fetch one curated entry end-to-end via real
  Speasy.

## Out-of-scope follow-ups (noted, not built here)

- Harmonizing the radiospectra continuous VPs into the `radio/<Mission>/…`
  layout for a uniform tree.
- A dock UI to browse/toggle catalog entries (the VPs are usable from the
  product tree directly; no UI needed for v1).
- The NenuFAR local-FITS reader (separate thread; unrelated to this catalog).
