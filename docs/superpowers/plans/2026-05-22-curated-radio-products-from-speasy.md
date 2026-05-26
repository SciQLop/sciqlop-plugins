# Curated Speasy Radio Products Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface a curated set of space-mission radio dynamic-spectra (sourced from Speasy/AMDA/CDAWeb) under the radio plugin's `radio/<Mission>/<Instrument>/<Product>` tree, as virtual products whose callback fetches via `speasy.get_data`.

**Architecture:** A declarative `radio_catalog.yaml` is read at plugin load. Each entry becomes a `create_virtual_product(...)` registration whose callback delegates to `speasy.get_data`. Entries that don't resolve in the installed Speasy inventory are skipped-with-log. Pure helpers (model, loader, resolver, callback, entry-registration) are unit-tested with injected fakes; the thin SciQLop-importing wrapper mirrors `continuous.register_continuous_products`.

**Tech Stack:** Python 3.12+, pydantic v2, PyYAML, speasy, SciQLop `user_api.virtual_products`.

**Spec:** `docs/superpowers/specs/2026-05-22-curated-radio-products-from-speasy-design.md`

**Branch:** `feat/radio-speasy-catalog` (already checked out).

---

## Task 1: `CuratedRadioProduct` schema

**Files:**
- Create: `sciqlop_radio/sciqlop_radio/catalog.py`
- Test: `sciqlop_radio/sciqlop_radio/tests/test_catalog.py`

- [ ] **Step 1: Write the failing test**

Create `sciqlop_radio/sciqlop_radio/tests/test_catalog.py`:

```python
"""Tests for the curated Speasy radio-product catalog."""
from __future__ import annotations

import pytest


def test_valid_entry_defaults():
    from sciqlop_radio.catalog import CuratedRadioProduct
    e = CuratedRadioProduct(path="Wind/WAVES/RAD1", speasy_id="amda/wnd_swaves_rad1")
    assert e.path == "Wind/WAVES/RAD1"
    assert e.type == "spectrogram"
    assert e.label == "Wind/WAVES/RAD1"   # defaults to path
    assert e.labels is None


def test_path_is_stripped_of_slashes():
    from sciqlop_radio.catalog import CuratedRadioProduct
    e = CuratedRadioProduct(path="/Wind/WAVES/RAD1/", speasy_id="amda/x")
    assert e.path == "Wind/WAVES/RAD1"


def test_blank_path_rejected():
    from sciqlop_radio.catalog import CuratedRadioProduct
    with pytest.raises(ValueError):
        CuratedRadioProduct(path="  /  ", speasy_id="amda/x")


@pytest.mark.parametrize("bad", ["noslash", "amda/", "/uid", "  "])
def test_bad_speasy_id_rejected(bad):
    from sciqlop_radio.catalog import CuratedRadioProduct
    with pytest.raises(ValueError):
        CuratedRadioProduct(path="A/B", speasy_id=bad)


def test_labels_required_for_non_spectrogram():
    from sciqlop_radio.catalog import CuratedRadioProduct
    with pytest.raises(ValueError):
        CuratedRadioProduct(path="A/B", speasy_id="amda/x", type="vector")
    ok = CuratedRadioProduct(
        path="A/B", speasy_id="amda/x", type="vector", labels=["x", "y", "z"]
    )
    assert ok.labels == ["x", "y", "z"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest sciqlop_radio/sciqlop_radio/tests/test_catalog.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sciqlop_radio.catalog'`

- [ ] **Step 3: Write minimal implementation**

Create `sciqlop_radio/sciqlop_radio/catalog.py`:

```python
"""Curated catalog of space-mission radio dynamic-spectra sourced from Speasy.

A declarative `radio_catalog.yaml` lists products that already exist in
Speasy (AMDA/CDAWeb). At plugin load each resolvable entry is registered as a
`VirtualProductType.Spectrogram` (or vector/scalar/multicomponent) virtual
product under `radio/<path>`, whose callback fetches via `speasy.get_data`.
Spectrogram styling is inherited from the returned SpeasyVariable's metadata.
"""
from __future__ import annotations

import logging
from typing import Literal, Optional

from pydantic import BaseModel, field_validator, model_validator

log = logging.getLogger(__name__)

ProductType = Literal["spectrogram", "vector", "scalar", "multicomponent"]


class CuratedRadioProduct(BaseModel):
    """One catalog entry: a Speasy product re-surfaced under radio/<path>."""

    path: str
    speasy_id: str
    type: ProductType = "spectrogram"
    label: Optional[str] = None
    labels: Optional[list[str]] = None

    @field_validator("path")
    @classmethod
    def _clean_path(cls, v: str) -> str:
        v = v.strip().strip("/").strip()
        if not v:
            raise ValueError("path must be non-blank")
        return v

    @field_validator("speasy_id")
    @classmethod
    def _check_speasy_id(cls, v: str) -> str:
        v = v.strip()
        provider, sep, uid = v.partition("/")
        if not sep or not provider.strip() or not uid.strip():
            raise ValueError("speasy_id must be '<provider>/<uid>'")
        return v

    @model_validator(mode="after")
    def _finalize(self) -> "CuratedRadioProduct":
        if self.type != "spectrogram" and not self.labels:
            raise ValueError(f"labels required for type={self.type!r}")
        if self.label is None:
            self.label = self.path
        return self
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest sciqlop_radio/sciqlop_radio/tests/test_catalog.py -q`
Expected: PASS (5 tests / parametrized cases green)

- [ ] **Step 5: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/catalog.py sciqlop_radio/sciqlop_radio/tests/test_catalog.py
git commit -m "feat(sciqlop_radio): CuratedRadioProduct catalog schema

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: `load_catalog` YAML reader

**Files:**
- Modify: `sciqlop_radio/sciqlop_radio/catalog.py`
- Test: `sciqlop_radio/sciqlop_radio/tests/test_catalog.py`

- [ ] **Step 1: Write the failing test**

Append to `test_catalog.py`:

```python
def test_load_catalog_parses_valid_yaml(tmp_path):
    from sciqlop_radio.catalog import load_catalog
    f = tmp_path / "cat.yaml"
    f.write_text(
        "- path: Wind/WAVES/RAD1\n"
        "  speasy_id: amda/wnd_swaves_rad1\n"
        "- path: STEREO-A/SWAVES/HFR\n"
        "  speasy_id: cda/STA_L3_WAV_HFR/avg_intens_ahead\n"
    )
    entries = load_catalog(f)
    assert [e.path for e in entries] == ["Wind/WAVES/RAD1", "STEREO-A/SWAVES/HFR"]


def test_load_catalog_skips_malformed_entry_keeps_rest(tmp_path):
    from sciqlop_radio.catalog import load_catalog
    f = tmp_path / "cat.yaml"
    f.write_text(
        "- path: Good/One\n"
        "  speasy_id: amda/ok\n"
        "- path: Bad/One\n"
        "  speasy_id: missing_slash\n"   # invalid -> skipped
    )
    entries = load_catalog(f)
    assert [e.path for e in entries] == ["Good/One"]


def test_load_catalog_missing_file_returns_empty(tmp_path):
    from sciqlop_radio.catalog import load_catalog
    assert load_catalog(tmp_path / "nope.yaml") == []


def test_load_catalog_non_list_returns_empty(tmp_path):
    from sciqlop_radio.catalog import load_catalog
    f = tmp_path / "cat.yaml"
    f.write_text("key: value\n")
    assert load_catalog(f) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest sciqlop_radio/sciqlop_radio/tests/test_catalog.py -q -k load_catalog`
Expected: FAIL with `ImportError: cannot import name 'load_catalog'`

- [ ] **Step 3: Write minimal implementation**

Add to `catalog.py` (imports at top, function below the model):

```python
from pathlib import Path
from typing import Union
```

```python
def load_catalog(path: Union[str, Path]) -> list[CuratedRadioProduct]:
    """Read + validate the YAML catalog. Fail-soft: missing file or top-level
    parse error -> []; a malformed entry is logged and skipped, others kept."""
    p = Path(path)
    if not p.exists():
        return []
    import yaml

    try:
        raw = yaml.safe_load(p.read_text()) or []
    except yaml.YAMLError as exc:
        log.error("catalog: failed to parse %s: %s", p, exc)
        return []
    if not isinstance(raw, list):
        log.error("catalog: %s must be a YAML list, got %s", p, type(raw).__name__)
        return []

    out: list[CuratedRadioProduct] = []
    for i, item in enumerate(raw):
        try:
            out.append(CuratedRadioProduct(**item))
        except Exception as exc:  # noqa: BLE001 — ValidationError or bad mapping
            log.warning("catalog: skipping entry %d (%r): %s", i, item, exc)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest sciqlop_radio/sciqlop_radio/tests/test_catalog.py -q`
Expected: PASS (all Task 1 + Task 2 tests green)

- [ ] **Step 5: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/catalog.py sciqlop_radio/sciqlop_radio/tests/test_catalog.py
git commit -m "feat(sciqlop_radio): YAML catalog loader (fail-soft)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: Resolver, type-map, and callback helpers

**Files:**
- Modify: `sciqlop_radio/sciqlop_radio/catalog.py`
- Test: `sciqlop_radio/sciqlop_radio/tests/test_catalog.py`

These are pure functions, tested with a `types.SimpleNamespace` fake `speasy_module` (no network, no real SciQLop).

- [ ] **Step 1: Write the failing test**

Append to `test_catalog.py`:

```python
from types import SimpleNamespace


def _fake_speasy(parameters_by_provider, get_data_return="VAR"):
    """SimpleNamespace mimicking the bits of `speasy` the catalog touches:
    `.inventories.flat_inventories.<provider>.parameters` (a dict) and
    `.get_data(id, t0, t1)`."""
    providers = {
        prov: SimpleNamespace(parameters=params)
        for prov, params in parameters_by_provider.items()
    }
    flat = SimpleNamespace(**providers)
    calls = []

    def get_data(pid, t0, t1):
        calls.append((pid, t0, t1))
        return get_data_return

    sp = SimpleNamespace(
        inventories=SimpleNamespace(flat_inventories=flat),
        get_data=get_data,
    )
    sp.calls = calls
    return sp


def test_resolves_true_when_uid_in_inventory():
    from sciqlop_radio.catalog import _resolves
    sp = _fake_speasy({"amda": {"wnd_swaves_rad1": object()}})
    assert _resolves("amda/wnd_swaves_rad1", sp) is True


def test_resolves_false_when_uid_missing_or_provider_absent():
    from sciqlop_radio.catalog import _resolves
    sp = _fake_speasy({"amda": {"other": object()}})
    assert _resolves("amda/wnd_swaves_rad1", sp) is False   # uid absent
    assert _resolves("cda/anything", sp) is False           # provider absent


def test_callback_fetches_via_speasy_get_data():
    from sciqlop_radio.catalog import CuratedRadioProduct, _build_callback
    sp = _fake_speasy({}, get_data_return="SPECVAR")
    e = CuratedRadioProduct(path="A/B", speasy_id="amda/x")
    cb = _build_callback(e, sp)
    out = cb(1_700_000_000.0, 1_700_000_900.0)
    assert out == "SPECVAR"
    assert sp.calls and sp.calls[0][0] == "amda/x"


def test_callback_swallows_get_data_error_returns_none():
    from sciqlop_radio.catalog import CuratedRadioProduct, _build_callback

    def boom(pid, t0, t1):
        raise RuntimeError("upstream down")

    sp = SimpleNamespace(get_data=boom)
    e = CuratedRadioProduct(path="A/B", speasy_id="amda/x")
    cb = _build_callback(e, sp)
    assert cb(1_700_000_000.0, 1_700_000_900.0) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest sciqlop_radio/sciqlop_radio/tests/test_catalog.py -q -k "resolves or callback"`
Expected: FAIL with `ImportError: cannot import name '_resolves'`

- [ ] **Step 3: Write minimal implementation**

Add to `catalog.py` (top imports + helpers):

```python
from datetime import datetime, timezone
```

```python
_TYPE_TO_VP = {
    "spectrogram": "Spectrogram",
    "vector": "Vector",
    "scalar": "Scalar",
    "multicomponent": "MultiComponent",
}


def _resolves(speasy_id: str, speasy_module) -> bool:
    """True if `<provider>/<uid>` is present in the in-memory Speasy inventory.

    SciQLop's speasy_provider builds the inventories at startup (before our
    load() runs), so this is a dict lookup, not a network call."""
    provider, _, uid = speasy_id.partition("/")
    flat = getattr(speasy_module.inventories.flat_inventories, provider, None)
    if flat is None:
        return False
    params = getattr(flat, "parameters", None) or {}
    return uid in params


def _vp_type_for(entry_type: str, vp_types):
    """Map a catalog `type` string to a SciQLop VirtualProductType member."""
    return getattr(vp_types, _TYPE_TO_VP[entry_type])


def _build_callback(entry: "CuratedRadioProduct", speasy_module):
    """Return SciQLop's `(start, stop, **kwargs) -> SpeasyVariable | None`
    callback. Never raises into SciQLop's data thread."""

    def _cb(start, stop, **kwargs):  # noqa: ARG001 — accept SciQLop knobs
        t0 = datetime.fromtimestamp(float(start), tz=timezone.utc)
        t1 = datetime.fromtimestamp(float(stop), tz=timezone.utc)
        try:
            return speasy_module.get_data(entry.speasy_id, t0, t1)
        except Exception as exc:  # noqa: BLE001
            log.warning("catalog(%s): get_data failed: %s", entry.path, exc)
            return None

    return _cb
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest sciqlop_radio/sciqlop_radio/tests/test_catalog.py -q`
Expected: PASS (all catalog tests green)

- [ ] **Step 5: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/catalog.py sciqlop_radio/sciqlop_radio/tests/test_catalog.py
git commit -m "feat(sciqlop_radio): catalog resolver, type-map, speasy callback

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: Entry registration + `register_catalog_products`

**Files:**
- Modify: `sciqlop_radio/sciqlop_radio/catalog.py`
- Test: `sciqlop_radio/sciqlop_radio/tests/test_catalog.py`

- [ ] **Step 1: Write the failing test**

Append to `test_catalog.py`:

```python
def _fake_vp_types():
    return SimpleNamespace(
        Spectrogram="SPEC", Vector="VEC", Scalar="SCA", MultiComponent="MC"
    )


def test_register_entries_registers_resolvable_skips_unresolvable():
    from sciqlop_radio.catalog import CuratedRadioProduct, _register_entries
    sp = _fake_speasy({"amda": {"ok": object()}})
    entries = [
        CuratedRadioProduct(path="Wind/WAVES/RAD1", speasy_id="amda/ok"),
        CuratedRadioProduct(path="Gone/Product", speasy_id="amda/missing"),
    ]
    created = []

    def create_vp(path, cb, vptype, **kw):
        created.append((path, vptype, kw))
        return f"VP[{path}]"

    reg = _register_entries(entries, create_vp, _fake_vp_types(), sp)
    assert [c[0] for c in created] == ["radio/Wind/WAVES/RAD1"]
    assert created[0][1] == "SPEC"
    assert reg.vps == {"radio/Wind/WAVES/RAD1": "VP[radio/Wind/WAVES/RAD1]"}


def test_register_entries_passes_labels_for_non_spectrogram():
    from sciqlop_radio.catalog import CuratedRadioProduct, _register_entries
    sp = _fake_speasy({"amda": {"v": object()}})
    entries = [
        CuratedRadioProduct(
            path="X/Vec", speasy_id="amda/v", type="vector", labels=["a", "b", "c"]
        )
    ]
    created = []

    def create_vp(path, cb, vptype, **kw):
        created.append((path, vptype, kw))
        return path

    _register_entries(entries, create_vp, _fake_vp_types(), sp)
    assert created[0][1] == "VEC"
    assert created[0][2] == {"labels": ["a", "b", "c"]}


def test_register_entries_continues_when_create_vp_raises():
    from sciqlop_radio.catalog import CuratedRadioProduct, _register_entries
    sp = _fake_speasy({"amda": {"a": object(), "b": object()}})
    entries = [
        CuratedRadioProduct(path="One", speasy_id="amda/a"),
        CuratedRadioProduct(path="Two", speasy_id="amda/b"),
    ]

    def create_vp(path, cb, vptype, **kw):
        if path == "radio/One":
            raise RuntimeError("boom")
        return path

    reg = _register_entries(entries, create_vp, _fake_vp_types(), sp)
    assert list(reg.vps) == ["radio/Two"]


def test_register_catalog_products_returns_none_when_sciqlop_missing(tmp_path, monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "SciQLop.user_api.virtual_products", None)
    f = tmp_path / "cat.yaml"
    f.write_text("- path: A/B\n  speasy_id: amda/x\n")
    from sciqlop_radio.catalog import register_catalog_products
    assert register_catalog_products(f) is None


def test_register_catalog_products_empty_catalog_returns_empty_registration(tmp_path):
    from sciqlop_radio.catalog import register_catalog_products, CatalogRegistration
    reg = register_catalog_products(tmp_path / "missing.yaml")
    assert isinstance(reg, CatalogRegistration)
    assert reg.vps == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest sciqlop_radio/sciqlop_radio/tests/test_catalog.py -q -k register`
Expected: FAIL with `ImportError: cannot import name '_register_entries'`

- [ ] **Step 3: Write minimal implementation**

Add to `catalog.py` (top import + code):

```python
from dataclasses import dataclass, field
from typing import Any, Callable
```

```python
@dataclass
class CatalogRegistration:
    """Live handle on the registered catalog VPs — keeps them alive vs GC."""

    vps: dict[str, Any] = field(default_factory=dict)


def _register_entries(
    entries: list["CuratedRadioProduct"],
    create_vp: Callable[..., Any],
    vp_types,
    speasy_module,
) -> CatalogRegistration:
    reg = CatalogRegistration()
    for e in entries:
        if not _resolves(e.speasy_id, speasy_module):
            log.info("catalog: skip %s — %s not in Speasy inventory", e.path, e.speasy_id)
            continue
        vptype = _vp_type_for(e.type, vp_types)
        cb = _build_callback(e, speasy_module)
        path = f"radio/{e.path}"
        try:
            if e.type == "spectrogram":
                vp = create_vp(path, cb, vptype)
            else:
                vp = create_vp(path, cb, vptype, labels=e.labels)
        except Exception as exc:  # noqa: BLE001
            log.exception("catalog: create_virtual_product failed for %s: %s", path, exc)
            continue
        reg.vps[path] = vp
    return reg


def register_catalog_products(
    catalog_path: Union[str, Path], *, speasy_module=None
) -> Optional[CatalogRegistration]:
    """Read the catalog and register one virtual product per resolvable entry.

    Returns an empty `CatalogRegistration` when the catalog is empty/missing,
    and `None` when SciQLop's virtual-products API isn't importable (headless
    tests) — mirroring `continuous.register_continuous_products`."""
    entries = load_catalog(catalog_path)
    if not entries:
        return CatalogRegistration()
    try:
        from SciQLop.user_api.virtual_products import (
            create_virtual_product,
            VirtualProductType,
        )
    except ImportError as exc:
        log.warning("catalog: SciQLop user_api unavailable: %s", exc)
        return None
    if speasy_module is None:
        import speasy as speasy_module  # noqa: PLW0127
    return _register_entries(entries, create_virtual_product, VirtualProductType, speasy_module)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest sciqlop_radio/sciqlop_radio/tests/test_catalog.py -q`
Expected: PASS (all catalog tests green)

- [ ] **Step 5: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/catalog.py sciqlop_radio/sciqlop_radio/tests/test_catalog.py
git commit -m "feat(sciqlop_radio): register curated catalog as virtual products

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Wire into plugin load + packaging

**Files:**
- Modify: `sciqlop_radio/sciqlop_radio/__init__.py:62-76`
- Modify: `sciqlop_radio/pyproject.toml`
- Modify: `sciqlop_radio/sciqlop_radio/plugin.json`
- Create: `sciqlop_radio/sciqlop_radio/radio_catalog.yaml` (placeholder, seeded in Task 6)
- Test: `sciqlop_radio/sciqlop_radio/tests/test_load.py`

- [ ] **Step 1: Write the failing test**

Add to `sciqlop_radio/sciqlop_radio/tests/test_load.py` (create the test fn; the file already exists for the dock-load test — append):

```python
def test_register_catalog_products_called_on_load(monkeypatch):
    """load() must register the curated catalog (idempotent, fail-soft)."""
    import sciqlop_radio
    calls = {}

    def fake_register(path, **kw):
        calls["path"] = path
        from sciqlop_radio.catalog import CatalogRegistration
        return CatalogRegistration()

    monkeypatch.setattr("sciqlop_radio.catalog.register_catalog_products", fake_register)

    # The dock/registration internals touch SciQLop; reuse the existing
    # headless-load harness in this file. If load() is exercised elsewhere in
    # this module, assert the catalog path points at the shipped YAML:
    from pathlib import Path
    expected = Path(sciqlop_radio.__file__).parent / "radio_catalog.yaml"
    # Drive load via the same fake main_window used by the other test in this
    # file (see existing _FakeMainWindow); then:
    # assert calls["path"] == expected
    assert expected.name == "radio_catalog.yaml"
```

> NOTE for implementer: open `test_load.py` first and read the existing
> `_FakeMainWindow`/load harness. Wire the assertion `calls["path"] == expected`
> into a real `load(fake_main_window)` invocation using that harness rather than
> the stub above. If `test_load.py` does not yet drive `load()`, add a minimal
> `_FakeMainWindow` mirroring `continuous`/dock test stubs (toolBar, toolsMenu,
> dock_manager with `findDockWidget`, `addWidgetIntoDock`, `_find_biggest_area`).

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest sciqlop_radio/sciqlop_radio/tests/test_load.py -q`
Expected: FAIL (assertion on `calls["path"]` not yet wired, or load() doesn't call register_catalog_products)

- [ ] **Step 3: Implement the wiring**

In `sciqlop_radio/sciqlop_radio/__init__.py`, after the `register_continuous_products(...)` block (currently ends ~line 72), add:

```python
    from .catalog import register_catalog_products
    from pathlib import Path
    _cat = register_catalog_products(Path(__file__).parent / "radio_catalog.yaml")

    handle = (panel, _cont, _cat)
    _LOADED_PANELS[key] = handle
    return handle
```

(Replace the existing `handle = (panel, _cont)` / `_LOADED_PANELS[key] = handle` / `return handle` lines so the catalog handle is retained against GC.)

In `sciqlop_radio/pyproject.toml`, add `"pyyaml"` to `dependencies` and the YAML to package-data:

```toml
    "speasy>=1.7",
    "pyyaml",
]
```

```toml
[tool.setuptools.package-data]
sciqlop_radio = ["plugin.json", "radio_catalog.yaml"]
```

In `sciqlop_radio/sciqlop_radio/plugin.json`, append `"pyyaml"` to `python_dependencies`.

Create a placeholder `sciqlop_radio/sciqlop_radio/radio_catalog.yaml` (real content in Task 6):

```yaml
# radio_catalog.yaml — curated space-mission radio dynamic spectra (data from Speasy).
# Entries absent from the installed Speasy inventory are skipped-with-log.
# Curation rule: do NOT duplicate radio/psp_rfs_lfr, radio/psp_rfs_hfr,
# radio/eovsa, radio/ilofar (already provided by continuous.py).
[]
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest sciqlop_radio/ -q`
Expected: PASS (full suite green; load test confirms catalog registration is invoked)

- [ ] **Step 5: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/__init__.py sciqlop_radio/pyproject.toml \
        sciqlop_radio/sciqlop_radio/plugin.json sciqlop_radio/sciqlop_radio/radio_catalog.yaml \
        sciqlop_radio/sciqlop_radio/tests/test_load.py
git commit -m "feat(sciqlop_radio): register catalog at load + package YAML + pyyaml dep

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Seed `radio_catalog.yaml` + shipped-file validation

**Files:**
- Modify: `sciqlop_radio/sciqlop_radio/radio_catalog.yaml`
- Test: `sciqlop_radio/sciqlop_radio/tests/test_catalog.py`

- [ ] **Step 1: Discover radio products in Speasy (research, not committed)**

Run this scratch script (network required; uses the real Speasy inventory) to find candidate radio dynamic-spectra and confirm each `<provider>/<uid>` resolves:

```python
# /tmp/discover_radio.py
import speasy as spz

RADIO_HINTS = ("wave", "radio", "rad1", "rad2", "rpw", "rfs", "swaves",
               "tnr", "hfr", "lfr", "rpws", "urap", "spectr")

for prov in ("amda", "cda"):
    flat = getattr(spz.inventories.flat_inventories, prov, None)
    if flat is None:
        continue
    for uid, node in getattr(flat, "parameters", {}).items():
        name = (getattr(node, "spz_name", "") or uid).lower()
        meta = getattr(node, "__dict__", {})
        disp = str(meta.get("display_type", "")).lower()
        if any(h in name for h in RADIO_HINTS) or disp == "spectrogram":
            print(f"{prov}/{uid}\t{getattr(node, 'spz_name', '')}\t{disp}")
```

Run: `python3 /tmp/discover_radio.py | sort | less`

Curate from the output: pick genuine dynamic-spectra (frequency depend axis), choosing clean `path: <Mission>/<Instrument>/<Product>` names. **Skip** anything duplicating `radio/psp_rfs_lfr|psp_rfs_hfr|eovsa|ilofar`. Target missions: Wind/WAVES (RAD1, RAD2, TNR), STEREO-A/B SWAVES, Solar Orbiter/RPW (HFR, TNR), Cassini/RPWS, Juno/Waves, Ulysses/URAP — include only those that appear in the discovery output.

- [ ] **Step 2: Write the shipped-file validation test (failing)**

Append to `test_catalog.py`:

```python
def test_shipped_catalog_loads_and_validates():
    """The bundled radio_catalog.yaml must parse and every entry must pass
    schema validation (load_catalog skips invalid entries — so we re-validate
    the raw file strictly here to catch typos before release)."""
    from pathlib import Path
    import yaml
    import sciqlop_radio
    from sciqlop_radio.catalog import CuratedRadioProduct

    f = Path(sciqlop_radio.__file__).parent / "radio_catalog.yaml"
    raw = yaml.safe_load(f.read_text()) or []
    assert isinstance(raw, list)
    for item in raw:
        CuratedRadioProduct(**item)   # raises on any invalid entry

    # No entry may duplicate a continuous VP path.
    from sciqlop_radio.continuous import CONTINUOUS_SOURCES
    cont = {s.vp_path for s in CONTINUOUS_SOURCES}
    paths = {f"radio/{CuratedRadioProduct(**i).path}" for i in raw}
    assert paths.isdisjoint(cont), f"catalog duplicates continuous VPs: {paths & cont}"
```

- [ ] **Step 3: Populate `radio_catalog.yaml` from the curated discovery output**

Replace the `[]` placeholder with the curated entries, e.g.:

```yaml
# radio_catalog.yaml — curated space-mission radio dynamic spectra (data from Speasy).
# Entries absent from the installed Speasy inventory are skipped-with-log.
# Curation rule: do NOT duplicate radio/psp_rfs_lfr, radio/psp_rfs_hfr,
# radio/eovsa, radio/ilofar (already provided by continuous.py).
- path: Wind/WAVES/RAD1
  speasy_id: amda/<verified-uid>
  label: Wind/WAVES RAD1
- path: Wind/WAVES/RAD2
  speasy_id: amda/<verified-uid>
  label: Wind/WAVES RAD2
# ... more entries, each speasy_id confirmed by Step 1 discovery ...
```

> Every `speasy_id` MUST be a real `<provider>/<uid>` confirmed present in
> Step 1's output. Do not invent ids.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest sciqlop_radio/sciqlop_radio/tests/test_catalog.py -q`
Expected: PASS — `test_shipped_catalog_loads_and_validates` green (every entry valid, no continuous-VP overlap).

- [ ] **Step 5: Manual end-to-end sanity (network)**

Run a quick fetch on one entry to confirm it returns a spectrogram:

```python
import speasy as spz
v = spz.get_data("<one speasy_id from the catalog>", "2022-01-01", "2022-01-01T01:00")
print(type(v), None if v is None else (v.values.shape, [a.name for a in v.axes]))
```

Expected: a 2-D `SpeasyVariable` with a frequency axis.

- [ ] **Step 6: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/radio_catalog.yaml sciqlop_radio/sciqlop_radio/tests/test_catalog.py
git commit -m "feat(sciqlop_radio): seed curated radio catalog (broad best-effort)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-Review (completed)

**Spec coverage:**
- Module layout (catalog.py / radio_catalog.yaml / __init__ wiring / packaging) → Tasks 1–5. ✓
- YAML schema + validation (type↔labels rule, speasy_id shape, path) → Task 1. ✓
- Loader fail-soft → Task 2. ✓
- Resolve-against-inventory + skip-with-log → Tasks 3–4. ✓
- Register VP per entry, callback → speasy.get_data, refs kept alive → Task 4. ✓
- Plot styling inherited from Speasy metadata → no code (asserted in spec); nothing to implement. ✓
- Tree org `radio/<path>` + overlap guard → Task 4 (path prefix) + Task 6 (disjoint test). ✓
- Broad best-effort seeding → Task 6. ✓
- Error-handling table (parse/validation/unresolved/create-raises/callback-raises) → Tasks 2,3,4 tests. ✓
- Testing list → Tasks 1–6 tests, incl. shipped-file validation + optional live fetch. ✓

**Placeholder scan:** The only intentional `<verified-uid>` placeholders are in Task 6 Step 3, which is explicitly a research-then-fill step (real ids can't be known until the discovery script runs). Flagged, not a silent gap.

**Type consistency:** `CuratedRadioProduct`, `CatalogRegistration`, `load_catalog`, `_resolves`, `_vp_type_for`, `_build_callback`, `_register_entries`, `register_catalog_products` used consistently across tasks; `_TYPE_TO_VP` keys match the `ProductType` Literal.

**Note on Task 5 test:** the `test_load.py` step requires reading the existing load harness in that file; the implementer must wire the `calls["path"] == expected` assertion into a real `load()` call rather than leaving the stubbed `assert expected.name == ...`. Called out inline.
