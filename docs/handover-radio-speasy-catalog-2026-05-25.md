# Handover — `feat/radio-speasy-catalog`

**Status:** feature complete, not merged. Branch is 13 commits ahead of `main` at HEAD `b9e5082`.
**Test state:** 74 passed / 1 skipped / 5 pre-existing failures (all in `test_settings.py`, present on `main` too — orthogonal to this work, do not touch).

## What this branch ships

A declarative, curated catalog of space-mission radio dynamic-spectra that surfaces under the radio plugin's tree at `radio/<Mission>/<Instrument>/<Band>[/<Unit>]`. Data is fetched at plot time via `speasy.get_data`, with skip-with-log for entries absent from the user's installed Speasy inventory.

**Catalog content (38 entries):**

| Group | Path pattern | Source | Count |
|---|---|---|---|
| PSP/FIELDS RFS | `PSP/FIELDS/RFS_{LFR,HFR}/{FLUX,SFU}` | CDA L3 | 4 |
| Wind/WAVES | `Wind/WAVES/{RAD1,RAD2,TNR}` | CDA L2 | 3 |
| STEREO-A/B SWAVES | `STEREO-{A,B}/SWAVES/{HFR,LFR}/{FLUX,SFU}` | CDA L3 | 8 |
| Solar Orbiter/RPW | `Solar Orbiter/RPW/{HFR,TNR}/{FLUX,SFU}` | CDA L3 | 4 |
| Juno/Waves | `Juno/Waves/{E-HFR-{hi,lo},E-LFR-{hi,lo},B-LFR-lo} ({orbit,cruise})` | AMDA | 10 |
| Cassini/RPWS SKR | `Cassini/RPWS/SKR/{RH,LH,V}` | AMDA | 3 |
| Galileo/PWS | `Galileo/PWS/{E,B} ({summary,high-rate})` | AMDA | 4 |
| Voyager 1/2 PWS | `Voyager-{1,2}/PWS/LR` | CDA | 2 |

Two continuous (radiospectra-Fido) VPs remain in `continuous.py`:
`radio/eovsa` and `radio/ilofar` — ground-based receivers with no calibrated Speasy equivalent. PSP/RFS used to live here too; replaced by the catalog L3 entries (calibrated flux + SFU, real frequency axis).

## Code map (what to read first if you're new)

- `sciqlop_radio/sciqlop_radio/catalog.py` — the whole feature. Three layers:
  - **schema** — `CuratedRadioProduct` pydantic model + `ProductType` Literal.
  - **loader** — `load_catalog(path)` reads YAML, fail-soft on missing file / parse error / per-entry validation.
  - **registration** — pure `_register_entries(entries, create_vp, vp_types, speasy_module)` + thin `register_catalog_products(catalog_path)` wrapper that imports SciQLop's `user_api.virtual_products` lazily (returns `None` on ImportError, matching `continuous.register_continuous_products`).
- `sciqlop_radio/sciqlop_radio/radio_catalog.yaml` — the declarative catalog. Header comment locks in the layout rules. **38 entries** today.
- `sciqlop_radio/sciqlop_radio/__init__.py` — `load()` calls `catalog.register_catalog_products(Path(__file__).parent / "radio_catalog.yaml")` next to the existing `register_continuous_products(...)` and stores both handles in the 3-tuple `_LOADED_PANELS[key] = (panel, _cont, _cat)` so neither set of VPs gets GC'd.
- `sciqlop_radio/sciqlop_radio/tests/test_catalog.py` — 24 tests covering the schema, loader, helpers, registration, and a shipped-file validation test that strictly validates every entry in `radio_catalog.yaml` and asserts catalog paths are disjoint from the continuous-VP paths.
- `docs/superpowers/specs/2026-05-22-curated-radio-products-from-speasy-design.md` — the spec.
- `docs/superpowers/plans/2026-05-22-curated-radio-products-from-speasy.md` — the 6-task implementation plan that produced this work.

## Conventions locked in by the design + tests

- **Path namespace split.** Catalog entries use nested title-case `radio/<Mission>/<Instrument>/<Band>[/<Unit>]`. `continuous.py` registers flat lowercase paths only (`radio/eovsa`, `radio/ilofar`). They cannot collide by construction; the shipped-file test enforces this.
- **Unit duplication is allowed and intentional** where Speasy carries both `PSD_FLUX` and `PSD_SFU`. Solar radio astronomers reach for SFU; fields/plasma physicists prefer W·m⁻²·Hz⁻¹. Plot styling inherits from the SpeasyVariable's ISTP metadata, so each gets the right colorbar label automatically.
- **VP callback signature is `(start: float, stop: float) -> SpeasyVariable | None`.** No `*args`, no `**kwargs`. Both are introspected by `SciQLop.core.knobs.introspection.extract_specs_from_callback` — anything var-positional or var-keyword triggers `log.warning("knobs disabled")` and suppresses the whole knobs UI. If you ever want knobs, declare them as explicit kwargs with defaults (SciQLop reads the defaults to build the UI); never `**kwargs`.
- **Resolution is in-memory.** `_resolves(speasy_id, speasy_module)` looks up `speasy.inventories.flat_inventories.<provider>.parameters` — a dict lookup, NOT a network call, because SciQLop's `speasy_provider` already built the inventory at startup before our `load()` runs.
- **`speasy_id` is `<provider>/<uid>`** where `<uid>` may itself contain `/` (CDA datasets like `WI_L2_WAV_RAD1/PSD_V2_S`). The schema validator allows this — `partition("/")` splits on the FIRST `/`. The provider name (`amda`, `cda`) MUST come first.

## How to extend (since you're continuing with metadata)

The likely meaning of "add metadata" — add optional fields to `CuratedRadioProduct` to capture per-entry attributes (frequency range, mission lifetime, instrument blurb, reference URL, axis hints, …). The loader is fail-soft on schema violations, but the **shipped-file test re-validates strictly**: any malformed entry breaks CI.

Where to plug in:

1. **Schema fields** — extend `CuratedRadioProduct` in `catalog.py`. Pure-pydantic additions are zero-risk; the existing fields stay required and only new optional fields are added.
   - Add the field with `Optional[T] = None`.
   - If the field needs validation (e.g. frequency range tuple ordering, ISO-date lifetime bounds), use `field_validator` for it.
   - If two fields interact, use `model_validator(mode="after")`.

2. **Pass metadata into SciQLop** — `_register_entries` currently calls `create_vp(path, cb, vptype)` (or with `labels=` for non-spectrogram). `create_virtual_product` also accepts:
   - `cachable=True/False` — whether SciQLop is allowed to cache the callback's result by `(path, start, stop)`. Default `False`. If your products are deterministic and the network is slow, set `True`.
   - `debug=True/False` — turns on per-call diagnostic logging via `SciQLop.user_api.virtual_products.validation.validate_and_call`.
   - `knobs_model` — a pydantic model whose fields become UI knobs; the callback then takes a `knobs=<model_instance>` kwarg (NOT `**kwargs`).
   - `knobs_kwarg_name` — alternate name for the knobs kwarg (default `"knobs"`).

3. **Per-callback knobs** — if a catalog entry needs runtime tunables (e.g. a band filter, a smoothing window), give the callback closure explicit kwargs with defaults. `_build_callback` would need a per-entry override path; the simplest extension is an optional `knobs` field in the YAML that names a knobs model the entry should be bound to.

4. **ISTP/plot-hint enrichment** — if Speasy's metadata is missing a label or scale you'd like to set, you can post-process the `SpeasyVariable` inside `_build_callback` before returning it. Resist this unless you've confirmed the metadata is genuinely missing — overriding ISTP attributes that Speasy carries correctly creates drift.

5. **Catalog growth** — keep the file declarative. Use the discovery script pattern from the plan (Task 6) to find new candidates:
   ```python
   import speasy as spz
   flat = spz.inventories.flat_inventories
   for prov in ("amda", "cda"):
       f = getattr(flat, prov, None)
       if f is None: continue
       params = getattr(f, "parameters", {}) or {}
       for uid, node in params.items():
           bag = " ".join(str(v) for k, v in vars(node).items() if isinstance(v, str))
           if "spectrogram" in bag.lower() and "<your-hint>" in (uid + bag).lower():
               print(f"{prov}/{uid}")
   ```
   **Always verify each candidate returns a 2-D `SpeasyVariable` with a frequency axis via a quick `spz.get_data(pid, t0, t1)` before adding it** — products labelled "spectrogram" sometimes turn out to be 1-D summaries (the L2 PSP `_averages` were a trap; they're `(N, 1)`).

## Open follow-ups (non-blocking)

From the final whole-branch review and earlier per-task reviews:

1. **`load_catalog` YAML-parse-error test** — the `yaml.YAMLError` branch is reachable via a `tmp_path` file containing malformed YAML (e.g. `":\t:"`); current tests only exercise the path indirectly. One-test addition.
2. **Optional injectable `create_virtual_product`** — the spec listed it as a parameter on `register_catalog_products` for testability; the implementation went with monkeypatching at the module boundary. Tests pass; the parameter is a YAGNI-vs-spec call.
3. **Continuous VPs path harmonisation** — `radio/eovsa` and `radio/ilofar` are still flat lowercase. Optionally migrate to `radio/Ground/eCALLISTO/...` and `radio/Ground/ILOFAR/...` for a uniform tree shape. Out of scope for this branch.
4. **The `radiospectra @ git+main` pin in `pyproject.toml`** — direct-URL deps can't be uploaded to PyPI. Before cutting `sciqlop_radio/v*`, radiospectra needs a real release with the sunpy-7 Scraper fix so the dep can become a normal version pin (see project memory `sunpy_radiospectra_version_pin`).

## Pitfalls re-learned the hard way (don't repeat)

- **Read `~/.claude/memory/sciqlop-user-api.md` BEFORE the project-local `feedback_*` files.** The project memory drifts; the user_api memory is the versioned contract. The 6-day-old `feedback_continuous_virtual_products.md` had `**kwargs` advice that was wrong against current SciQLop — caused a "knobs disabled" warning storm before I read the canonical reference (commit `9d95ded` is the fix; project memory has been corrected). See `feedback_read_user_api_memory_before_plugin_design.md`.
- **Don't bundle uncommitted side-fixes onto a feature branch.** The earlier (now-reverted) sunpy-7 + filter changes were unrelated to the catalog feature and got tangled into the conversation. If you start a new piece of work, branch separately.
- **The implementer subagents in this session committed task 4-6 on a detached HEAD** before the branch ref was advanced; recovery was `git reset --hard <tip>`. Watch the branch ref between subagent dispatches if you reuse the subagent-driven workflow.

## Unrelated open threads

- **NenuFAR local-FITS reader** (`DYNSPEC_24_2023-01-15_1225.fits`): radiospectra has no NenuFAR reader; the file is fully self-describing via standard WCS (`CTYPE1=TIME`, `CTYPE2=FREQ`). A fallback generic-WCS reader in `reader.py` was scoped during this session but not built — interrupted by the catalog-design work. Re-engage if needed; the diagnostic is captured in the conversation log of 2026-05-22.
- **`test_settings.py` × 5 failures** — ~~pre-existing on `main`. Pydantic-bound-clamp regressions in `settings.py`'s `RadioSettings`. Not introduced by this branch; do NOT include in any catalog-feature fix.~~ **CORRECTED 2026-05-26 (commit `3c3b8be`):** these were NOT pydantic regressions. They were test-isolation failures specific to running tests on a dev machine with real SciQLop installed. Real `ConfigEntry.__init__` (entry.py:158-180) reads `~/.config/sciqlop/<class>.yaml` and uses the loaded dict IN PLACE OF constructor kwargs — and auto-saves the file on first construction. So the existing user yaml hijacked `RadioSettings(download_timeout_s=…)`, and the FIRST settings test wrote a fresh yaml that hijacked the next four. The fix is in `tests/conftest.py`: set `XDG_CONFIG_HOME` to a session tempdir BEFORE any SciQLop import, plus an autouse function-scoped fixture that wipes the yaml between tests. One test was also asserting the wrong contract (`ConfigEntry.__init__` catches `ValidationError` and falls back to defaults — entry.py:172-177 — so invalid input never raises); the test was updated to pin the actual fallback behaviour. Net: 0 failures. **Earlier directives in this doc to "leave the 5 failures alone" were wrong** — they were a real isolation bug.

## How to land this

The finishing-skill prompt was paused on your choice — merge / PR / keep / discard. Tests pass; the whole branch has been spec-compliance-reviewed and code-quality-reviewed per task, plus a holistic final review approved it. Pick a verb and the existing skill flow will handle it.

## Update 2026-05-25 — metadata + plot-hints parity

Branch advanced from `b9e5082` to 53c74c4 with parity work:

- New `sciqlop_radio/sciqlop_radio/hints.py` (~185 LOC): `extract_speasy_index_meta` (Speasy ParameterIndex -> flat metadata dict), four `RichEasy*` subclasses overriding `plot_hints` + `plot_hints_from_variable` exactly as `SciQLop.plugins.speasy_provider.SpeasyPlugin` does, `make_rich_vp` factory.
- `catalog.py`: `_resolves` -> `_resolve_index` (returns the index); `_register_entries` extracts ISTP metadata and passes through `vp_factory` (kw-only signature: `(path, cb, vptype, *, metadata, labels=None)`); `register_catalog_products` defaults `vp_factory=hints.make_rich_vp`.
- `continuous.py`: `ContinuousSource.static_meta` field + minimal hand-written meta per source; `register_continuous_products` uses the same factory.

Net behaviour: every radio VP node carries the same ISTP-flavoured metadata its `speasy/...` sibling would (when one exists); on plot, the z (colour) axis label/unit/log-scale appear immediately from the node metadata; the y2 (frequency) axis appears on first fetch from the SpeasyVariable's axes meta. Identical UX to native Speasy products.

Test count moved from 74 passed baseline to **92 passed**; 4 dispatch tests skip under headless conftest (the conftest pre-stubs `easy_provider` as MagicMock to dodge a QCoreApplication SIGABRT, so `RichEasy*` subclasses fall back to `object` parents in tests via an `isinstance(x, type)` guard in `hints.py`; the factory dispatch needs real EasyProvider parents to construct). **The 5 `test_settings.py` failures previously called "pre-existing" turned out to be a test-isolation bug — fixed in `3c3b8be`. See "Unrelated open threads" above.**

Spec: `docs/superpowers/specs/2026-05-25-radio-vp-metadata-and-plot-hints-design.md` (d3f343f).
Plan: `docs/superpowers/plans/2026-05-25-radio-vp-metadata-and-plot-hints.md` (27c6d78).

### Known limitations (carry-over from upstream)

- **`EasyProvider.__init__` overwrites `description` and `stable_id`** on the metadata dict before forwarding to `ProductsModelNode`. The auto-generated `description = "Virtual {parameter_type} product built from Python function: {name}"` always wins over anything we put in `static_meta` or extract from the Speasy inventory. `stable_id` is replaced with the VP path (e.g. `radio/eovsa`) instead of the speasy_id we set. This is pre-existing upstream behaviour and equally affects every plugin using `EasyProvider`/`create_virtual_product`. Net user impact is small (the VP path is itself a fine stable identifier, and the auto-description is informative), but if richer descriptions are desired, the fix is either upstream (`{**metadata, "description": ..., "stable_id": ...}` instead of `metadata.update(...)`) or pre-applying our values inside the RichEasy* subclass's own `__init__` overrides.
