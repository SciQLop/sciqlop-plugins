# Radio Product Labels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make radio spectrograms read `I-LOFAR X pol` instead of `X` in both the product tree and the plot, and remove the duplicated product definition that made the paths drift.

**Architecture:** Two halves. In **SciQLop**, `EasyProvider` gains an optional `display_name` so a node's label can differ from its vp_path leaf (today it is hard-coded to `path.split('/')[-1]`), and it stops overwriting a plugin-supplied `description`. In **sciqlop_radio**, the path segment moves off `source_key` onto a new `RadioSource.path_name`, the pre-registered I-LOFAR products are derived from the same `StreamIdentity` machinery the dock uses instead of being spelled out a second time, and every product passes a self-contained display name at registration.

**Tech Stack:** Python 3.13, pydantic (`RadioSource` is a `BaseModel`), dataclasses (`ContinuousSource`, `StreamIdentity`, `StreamRule` are frozen dataclasses), PySide6, pytest.

**Spec:** `plugins_sciqlop/docs/superpowers/specs/2026-07-29-radio-product-labels-design.md`

## Global Constraints

- **Two repos, two branches.** SciQLop work in `/var/home/jeandet/Documents/prog/SciQLop`; plugin work in `/var/home/jeandet/Documents/prog/plugins_sciqlop`. Both are currently on `main` with unpushed commits — create a feature branch in each before editing. **Never push.**
- Plugin tests (from the plugin dir, SciQLop's venv, `xcb`):
  ```bash
  cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && \
    QT_QPA_PLATFORM=xcb /var/home/jeandet/Documents/prog/SciQLop/.venv/bin/python \
    -m pytest sciqlop_radio/tests/ -q -m "not live"
  ```
  Baseline before any change: **207 passed, 5 skipped, 2 deselected, exit 0.**
- SciQLop tests: `cd /var/home/jeandet/Documents/prog/SciQLop && QT_QPA_PLATFORM=xcb .venv/bin/python -m pytest tests/test_virtual_products -q`. **Do not** run the full SciQLop `tests/` directory — it aborts with SIGABRT in an unrelated `tscat_catalogs`/watchdog fixture teardown, on a clean baseline too.
- **Never** use `QT_QPA_PLATFORM=offscreen` — the suites hard-crash in libxkbcommon under native Wayland, and `offscreen` is separately forbidden in this project.
- Known pre-existing test noise, not yours: one `AstropyUserWarning: XDG_CONFIG_HOME is set to ...` from `astropy/config/paths.py:55`, and two `PytestUnknownMarkWarning: Unknown pytest.mark.live`. Any *additional* warning is a finding.
- Every module in `sciqlop_radio` uses `from __future__ import annotations`. Keep that.
- `source_key` values (`ilofar`, `ecallisto`, `eovsa`, `rstn`, `psp_rfs`, `custom`) **must not change** — they are also the `STREAM_RULES` keys, the day-cache search signature input, and the dock's combo-box identity.
- Renaming vp_paths is breaking and **approved** — nobody depends on them yet.
- Neither repo's plugin package has a CHANGELOG and the README documents no product paths. Do not add either.

### Target names

| vp_path (new) | Display name |
|---|---|
| `radio/I-LOFAR/X` | `I-LOFAR X pol` |
| `radio/I-LOFAR/Y` | `I-LOFAR Y pol` |
| `radio/EOVSA` | `EOVSA` |
| `radio/e-CALLISTO/<station>/<focus>` | `e-CALLISTO <station> <focus>` |
| `radio/RSTN/<station>` | `RSTN <station>` |
| `radio/LOFAR/LBA` (unchanged) | `LOFAR LBA` |
| `radio/PSP/FIELDS/RFS_LFR/FLUX` (unchanged) | `PSP/FIELDS RFS LFR (PSD flux)` |

---

### Task 1: `display_name` on EasyProvider, and stop clobbering `description`

**Files:**
- Modify: `SciQLop/components/plotting/backend/easy_provider.py:125-160`
- Modify: `SciQLop/user_api/virtual_products/__init__.py:97-100`
- Test: `SciQLop/tests/test_virtual_products/test_easy_provider_display_name.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `EasyProvider.__init__(..., display_name: Optional[str] = None)` — when a non-empty string, it becomes the `ProductsModelNode` name in place of the vp_path leaf. `create_virtual_product(..., display_name: Optional[str] = None)` forwards it. Task 4 relies on `make_rich_vp` forwarding it (added in Task 4's own repo).

**Background:** `easy_provider.py:135` currently does `product_name = self._path[-1]`, so a virtual product's node name is always its path leaf. `easy_provider.py:154-158` builds the node metadata as `{**metadata, "description": f"Virtual {parameter_type.name} product built from Python function: {self.name}", ...}`, which overwrites any `description` the caller supplied.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_virtual_products/test_easy_provider_display_name.py`:

```python
"""EasyProvider node naming and metadata passthrough.

A virtual product's node name is what SciQLop uses as the *graph* label on both
the in-process path (time_sync_panel.py's `target.plot(..., name=node.name())`)
and the remote path (plot_remote.py's `add_remote_color_map(node.name())`), and
as the label in the product tree. Until `display_name` existed it was forced to
be the last vp_path segment, so a product at `radio/ilofar/X` could only ever be
called "X".
"""
import pytest

import SciQLop.components.plotting.backend.easy_provider as ep
from SciQLop.components.plotting.backend.easy_provider import EasyProvider
from SciQLop.core.enums import ParameterType


def _spectrogram_callback(start: float, stop: float):
    return None


@pytest.fixture
def registered(monkeypatch):
    """Capture the ProductsModelNode a provider registers.

    `easy_provider` calls `products.add_node(path, node)` (module-level
    `products` imported from SciQLop.core.models). Spying on that is more
    direct than reading the node back out of the global model, and keeps each
    test from depending on registration order.
    """
    captured = {}

    def _add_node(path, node):
        captured["path"] = path
        captured["node"] = node

    monkeypatch.setattr(ep.products, "add_node", _add_node)

    def _make(path, **kwargs):
        EasyProvider(path, _spectrogram_callback, ParameterType.Spectrogram,
                     metadata=kwargs.pop("metadata", {}), **kwargs)
        return captured["node"]

    return _make


def test_node_name_defaults_to_the_path_leaf(registered):
    """Unchanged behaviour: a provider that passes no display_name still names
    its node after the last path segment."""
    assert registered("test_display/default_leaf").name() == "default_leaf"


def test_display_name_overrides_the_path_leaf(registered):
    assert registered("test_display/override_leaf",
                      display_name="I-LOFAR X pol").name() == "I-LOFAR X pol"


def test_empty_display_name_falls_back_to_the_leaf(registered):
    """An empty string is 'not supplied', not 'name this product nothing'."""
    assert registered("test_display/empty_display",
                      display_name="").name() == "empty_display"


def test_supplied_description_survives_registration(registered):
    """Regression: the metadata dict used to be built with
    `{**metadata, "description": <generated>}`, so a caller's curated
    description was silently replaced by boilerplate in every tooltip."""
    node = registered("test_display/keeps_description",
                      metadata={"description": "I-LOFAR mode 357 BST dynamic spectrum"})
    assert node.metadata()["description"] == "I-LOFAR mode 357 BST dynamic spectrum"


def test_description_is_generated_when_absent(registered):
    node = registered("test_display/generated_description")
    assert "Virtual Spectrogram product" in node.metadata()["description"]


def test_virtual_spectrogram_forwards_display_name(monkeypatch):
    """dock.py registers its live streams through VirtualSpectrogram, not
    through make_rich_vp, so the name has to survive that path too."""
    import SciQLop.user_api.virtual_products as vp
    captured = {}

    def _add_node(path, node):
        captured["node"] = node

    monkeypatch.setattr(ep.products, "add_node", _add_node)
    vp.VirtualSpectrogram("test_display/via_virtual_spectrogram",
                          _spectrogram_callback,
                          display_name="e-CALLISTO BIR 01")
    assert captured["node"].name() == "e-CALLISTO BIR 01"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /var/home/jeandet/Documents/prog/SciQLop && \
  QT_QPA_PLATFORM=xcb .venv/bin/python -m pytest \
  tests/test_virtual_products/test_easy_provider_display_name.py -q
```

Expected: the two default/leaf tests and `test_description_is_generated_when_absent` PASS (existing behaviour); `test_display_name_overrides_the_path_leaf`, `test_empty_display_name_falls_back_to_the_leaf` and `test_supplied_description_survives_registration` FAIL — the first two with `TypeError: __init__() got an unexpected keyword argument 'display_name'`, the third with the generated boilerplate instead of the supplied description.

- [ ] **Step 3: Implement in `easy_provider.py`**

Add the parameter to the signature, after `out_of_process`:

```python
                 out_of_process: bool = False,
                 display_name: Optional[str] = None):
```

Replace `product_name = self._path[-1]` with:

```python
        # The node name is the graph label on BOTH plot paths (in-process
        # `target.plot(..., name=node.name())` and remote
        # `add_remote_color_map(node.name())`) as well as the product-tree
        # label. Defaulting it to the path leaf means a product at
        # `radio/ilofar/X` can only be called "X"; display_name decouples the
        # two without touching the path, which is the product's identity.
        product_name = display_name or self._path[-1]
```

Change the metadata construction so a supplied description wins:

```python
        metadata = {
            "description": f"Virtual {parameter_type.name} product built from Python function: {self.name}",
            **metadata,
            "stable_id": path,
            **({"remote": "True"} if out_of_process else {}),
        }
```

Moving the generated `description` *before* the `**metadata` spread makes it a default that the caller's value overrides, while `stable_id` and `remote` stay authoritative after it.

- [ ] **Step 4: Thread it through the public API**

Two call sites in `SciQLop/user_api/virtual_products/__init__.py`.

`VirtualSpectrogram.__init__` (line 88) — **required**, because `dock.py:458` registers live radio streams through this class rather than through `make_rich_vp`:

```python
class VirtualSpectrogram(VirtualProduct):
    def __init__(self, path: str, callback: VirtualProductCallback, debug: Optional[bool] = False,
                 cachable: Optional[bool] = False,
                 knobs_model=None, knobs_kwarg_name="knobs", out_of_process: bool = False,
                 display_name: Optional[str] = None):
        super(VirtualSpectrogram, self).__init__(path, callback, VirtualProductType.Spectrogram)
        self._impl = _EasySpectrogram(path, callback, metadata={}, debug=debug, cacheable=cachable,
                                      knobs_model=knobs_model, knobs_kwarg_name=knobs_kwarg_name,
                                      out_of_process=out_of_process,
                                      display_name=display_name)
```

`create_virtual_product` (line 97) — add `display_name: Optional[str] = None` after `knobs_kwarg_name="knobs"`, forward it to the provider it constructs, and document it in the docstring's Parameters section:

```
    display_name : Optional[str]
        Name shown in the product tree and used as the plot label. Defaults to
        the last segment of `path`.
```

Leave the sibling `VirtualScalar`/`VirtualVector`/`VirtualMultiComponent` classes alone — nothing in this plan registers through them, and adding unused parameters is scope creep.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd /var/home/jeandet/Documents/prog/SciQLop && \
  QT_QPA_PLATFORM=xcb .venv/bin/python -m pytest tests/test_virtual_products -q
```

Expected: 5 passed in the new file, and every pre-existing test in `tests/test_virtual_products` still passing.

- [ ] **Step 6: Commit**

```bash
cd /var/home/jeandet/Documents/prog/SciQLop
git add SciQLop/components/plotting/backend/easy_provider.py \
        SciQLop/user_api/virtual_products/__init__.py \
        tests/test_virtual_products/test_easy_provider_display_name.py
git commit -m "feat(vp): display_name on EasyProvider; keep caller's description"
```

---

### Task 2: Path segment and display string move off `source_key`

**Files:**
- Modify: `sciqlop_radio/sources.py` (the `RadioSource` model, ~line 12-37, and the `SOURCES` entries)
- Modify: `sciqlop_radio/streams.py` (the `StreamRule` dataclass ~line 29-33, `STREAM_RULES` ~35-43, `StreamIdentity` ~56-70)
- Test: `sciqlop_radio/tests/test_streams.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: `RadioSource.path_name: str = ""` (falls back to `key`); `StreamRule.channel_suffix: str = ""`; `StreamIdentity.path_name: str = ""` plus a new `StreamIdentity.display_name` property. `StreamIdentity.vp_path` now composes from `path_name`. Tasks 3 and 4 consume `vp_path` and `display_name`.

- [ ] **Step 1: Write the failing tests**

Append to `sciqlop_radio/tests/test_streams.py`:

```python
def test_source_keys_are_unchanged():
    """path_name is presentation only. source_key stays the identity — it keys
    STREAM_RULES, the day-cache search signature and the dock's combo box — so
    adding a display concept must not move it."""
    from sciqlop_radio.sources import SOURCES
    assert {s.key for s in SOURCES} == {
        "psp_rfs", "ecallisto", "eovsa", "ilofar", "rstn", "custom"}


def test_curated_sources_carry_the_capitalised_path_names():
    from sciqlop_radio.sources import SOURCES
    by_key = {s.key: s for s in SOURCES}
    assert by_key["ilofar"].path_name == "I-LOFAR"
    assert by_key["ecallisto"].path_name == "e-CALLISTO"
    assert by_key["eovsa"].path_name == "EOVSA"
    assert by_key["rstn"].path_name == "RSTN"


def test_vp_path_uses_path_name_not_source_key():
    from sciqlop_radio.streams import StreamIdentity
    ident = StreamIdentity(source_key="ilofar", instrument="ILOFAR",
                           path_name="I-LOFAR", channel="X")
    assert ident.vp_path == "radio/I-LOFAR/X"


def test_vp_path_falls_back_to_source_key_when_path_name_is_unset():
    from sciqlop_radio.streams import StreamIdentity
    ident = StreamIdentity(source_key="custom", instrument="", channel="")
    assert ident.vp_path == "radio/custom"


def test_display_name_is_self_contained():
    """One name serves the tree and the plot, and a panel may stack products
    from several instruments — so 'X pol' alone would be ambiguous."""
    from sciqlop_radio.streams import StreamIdentity
    ilofar = StreamIdentity(source_key="ilofar", instrument="ILOFAR",
                            path_name="I-LOFAR", channel="X")
    assert ilofar.display_name == "I-LOFAR X pol"

    ecallisto = StreamIdentity(source_key="ecallisto", instrument="eCALLISTO",
                               path_name="e-CALLISTO",
                               station="AUSTRIA-Krumbach", channel="01")
    assert ecallisto.display_name == "e-CALLISTO AUSTRIA-Krumbach 01"

    eovsa = StreamIdentity(source_key="eovsa", instrument="EOVSA",
                           path_name="EOVSA")
    assert eovsa.display_name == "EOVSA"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && \
  QT_QPA_PLATFORM=xcb /var/home/jeandet/Documents/prog/SciQLop/.venv/bin/python \
  -m pytest sciqlop_radio/tests/test_streams.py -q
```

Expected: FAIL — `path_name` is not a field on `RadioSource` or `StreamIdentity`, and `display_name` does not exist.

- [ ] **Step 3: Add `path_name` to `RadioSource` (`sources.py`)**

After the `label` field:

```python
    path_name: str = Field(
        default="",
        description=(
            "Segment used under `radio/` in the product path, e.g. 'I-LOFAR'."
            " Empty means fall back to `key`. Kept separate from `key` because"
            " `key` is the identity (STREAM_RULES, search-cache signature, dock"
            " combo box) and must not move when presentation changes."
        ),
    )
```

Then set it on the four curated entries: `ilofar` → `"I-LOFAR"`, `ecallisto` → `"e-CALLISTO"`, `eovsa` → `"EOVSA"`, `rstn` → `"RSTN"`. Leave `psp_rfs` and `custom` unset — `psp_rfs` is served by the catalog under `radio/PSP/...` and `custom` is local-file-only.

- [ ] **Step 4: Add `channel_suffix` and the identity changes (`streams.py`)**

On `StreamRule`, after `channel_column`:

```python
    channel_suffix: str = ""   # rendered after the channel token in display names
```

In `STREAM_RULES`, give I-LOFAR its suffix (the channel token is a polarisation, so a bare "X" reads as an axis):

```python
    "ilofar": StreamRule(per_station=False, server_side=False,
                         channel_column="Polarisation", channel_suffix="pol"),
```

On `StreamIdentity`, add the field and the property, and switch `vp_path` over:

```python
    path_name: str = ""   # path/display segment; "" falls back to source_key

    @property
    def vp_path(self) -> str:
        parts = ["radio", self.path_name or self.source_key]
        if self.station:
            parts.append(_sanitize(self.station))
        if self.channel:
            parts.append(_sanitize(self.channel))
        return "/".join(parts)

    @property
    def display_name(self) -> str:
        """Tree and plot label. Self-contained on purpose: one name serves
        both, and a panel may stack several instruments."""
        channel = self.channel
        if channel:
            suffix = rule_for(self.source_key).channel_suffix
            if suffix:
                channel = f"{channel} {suffix}"
        parts = [self.path_name or self.source_key, self.station, channel]
        return " ".join(p for p in parts if p)
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && \
  QT_QPA_PLATFORM=xcb /var/home/jeandet/Documents/prog/SciQLop/.venv/bin/python \
  -m pytest sciqlop_radio/tests/test_streams.py sciqlop_radio/tests/test_sources_registry.py -q
```

Expected: the new tests pass and every pre-existing test in both files still passes.

- [ ] **Step 6: Commit**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop
git add sciqlop_radio/sciqlop_radio/sources.py sciqlop_radio/sciqlop_radio/streams.py \
        sciqlop_radio/sciqlop_radio/tests/test_streams.py
git commit -m "feat(sciqlop_radio): path_name and display_name on StreamIdentity"
```

---

### Task 3: One definition per product — derive the I-LOFAR registry entries

**Files:**
- Modify: `sciqlop_radio/continuous.py` (imports ~line 36-38; `CONTINUOUS_SOURCES` ~146-177; `make_stream_source` ~512-533)
- Test: `sciqlop_radio/tests/test_continuous.py` (append), plus path updates in `sciqlop_radio/tests/test_dock.py` and `sciqlop_radio/tests/test_continuous_cache.py`

**Interfaces:**
- Consumes: `StreamIdentity` (with `path_name`, `vp_path`, `display_name`) from Task 2.
- Produces: `CONTINUOUS_SOURCES` entries whose `vp_path` and `search_signature` are computed by the same code the dock uses; `make_stream_source(identity, freq_signature)` unchanged in signature.

**Background — the defect being removed.** `CONTINUOUS_SOURCES` spells out `vp_path="radio/ilofar/X"` and `search_signature="ILOFAR"`, while `make_stream_source` computes `vp_path` from `StreamIdentity` and `search_signature=f"{instrument}|{server_station}"` → `"ILOFAR|"`. Same product, two definitions, and they already disagree on the cache key. The dock reuses the registered VP by path (`test_dock.py:313`) and discards the source it just built, which masks the drift rather than preventing it.

**EOVSA is not duplicated** and stays an explicit entry: `SOURCES`' `eovsa` has `fido_instrument=None` (registration required), so no dock stream is ever built for it, while `CONTINUOUS_SOURCES` needs `a.Instrument("EOVSA")` via `_attrs_eovsa`. Only its `vp_path` changes.

`continuous.py → streams.py` at module scope is safe: `streams.py` imports only `from .fetch import _row_field`, and `fetch.py` imports nothing from this package.

- [ ] **Step 1: Write the failing tests**

Append to `sciqlop_radio/tests/test_continuous.py`:

```python
def test_registered_paths_use_the_capitalised_path_names():
    from sciqlop_radio.continuous import CONTINUOUS_SOURCES
    paths = {s.vp_path for s in CONTINUOUS_SOURCES}
    assert paths == {"radio/EOVSA", "radio/I-LOFAR/X", "radio/I-LOFAR/Y"}


def test_ilofar_registry_entries_agree_with_the_dock_derived_stream():
    """The registered VP and the stream the dock derives from an I-LOFAR row
    are the SAME product — the vp_path is its identity, which is why the dock
    reuses the registered entry instead of registering a second copy. They must
    therefore agree on every field that identifies the product, not just the
    path: search_signature used to be 'ILOFAR' here and 'ILOFAR|' there, giving
    one product two day-cache keys."""
    from sciqlop_radio.continuous import CONTINUOUS_SOURCES, make_stream_source
    from sciqlop_radio.streams import StreamIdentity

    registered = {s.vp_path: s for s in CONTINUOUS_SOURCES}
    for pol in ("X", "Y"):
        derived = make_stream_source(
            StreamIdentity(source_key="ilofar", instrument="ILOFAR",
                           path_name="I-LOFAR", channel=pol),
            freq_signature=None)
        entry = registered[f"radio/I-LOFAR/{pol}"]
        assert entry.search_signature == derived.search_signature
        assert entry.channel_column == derived.channel_column
        assert entry.channel_value == derived.channel_value


def test_ilofar_registry_entries_keep_their_static_meta():
    """Deriving from StreamIdentity must not drop the plot-hints metadata the
    product tree needs before the first fetch."""
    from sciqlop_radio.continuous import CONTINUOUS_SOURCES
    for s in CONTINUOUS_SOURCES:
        if s.vp_path.startswith("radio/I-LOFAR"):
            assert s.static_meta["DISPLAY_TYPE"] == "spectrogram"
            assert s.static_meta["SCALETYP"] == "log"
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && \
  QT_QPA_PLATFORM=xcb /var/home/jeandet/Documents/prog/SciQLop/.venv/bin/python \
  -m pytest sciqlop_radio/tests/test_continuous.py -q -k "path_names or agree or static_meta"
```

Expected: FAIL — paths are still `radio/eovsa` / `radio/ilofar/X`, and `search_signature` is `"ILOFAR"` vs the derived `"ILOFAR|"`.

- [ ] **Step 3: Derive the I-LOFAR entries**

Add to `continuous.py`'s module-level imports, after `from .plot import frequency_signature`:

```python
from .streams import StreamIdentity
```

Move `make_stream_source` **above** `CONTINUOUS_SOURCES` (it is currently defined near the bottom, at ~line 512) so the list can call it, and change its lazy `from .streams import rule_for, stream_fido_attrs` to a module-level import alongside `StreamIdentity`.

Then replace the two hand-written I-LOFAR entries with derived ones:

```python
def _ilofar_source(pol: str) -> ContinuousSource:
    """Derived from the same StreamIdentity the dock builds for an I-LOFAR row:
    the registered VP and that stream are one product, so there is one
    definition. Only the pre-fetch plot-hints metadata is added on top."""
    return replace(
        make_stream_source(
            StreamIdentity(source_key="ilofar", instrument="ILOFAR",
                           path_name="I-LOFAR", channel=pol),
            freq_signature=None),
        static_meta=_ilofar_meta(pol),
    )


CONTINUOUS_SOURCES: list[ContinuousSource] = [
    ContinuousSource(
        vp_path="radio/EOVSA",
        label="EOVSA",
        attrs_factory=_attrs_eovsa,
        static_meta=_EOVSA_META,
        search_signature="EOVSA",
    ),
    _ilofar_source("X"),
    _ilofar_source("Y"),
]
```

Add `replace` to the existing `dataclasses` import at the top of the file:

```python
from dataclasses import dataclass, field, replace
```

Keep the existing comment above the I-LOFAR entries explaining why two entries exist at all (one file per polarisation per timestamp); it is still true and still load-bearing.

- [ ] **Step 4: Update the tests that assert the old paths**

These assert product identity, not spelling, so update the literals in place:

- `sciqlop_radio/tests/test_continuous.py` — `test_continuous_sources_registry_covers_known_channels` expects `{"radio/eovsa", "radio/ilofar/X", "radio/ilofar/Y"}`; change to the new set.
- `sciqlop_radio/tests/test_dock.py:308` — `"radio/ecallisto/AUSTRALIA-ASSA/01"` → `"radio/e-CALLISTO/AUSTRALIA-ASSA/01"`; lines 332/355/395 — `"radio/ilofar/X"` / `"radio/ilofar/Y"` → `"radio/I-LOFAR/X"` / `"radio/I-LOFAR/Y"`; line 565 — `["radio/ecallisto/BIR/01", "radio/ecallisto/BIR/02"]` → the `e-CALLISTO` spelling.
- `sciqlop_radio/tests/test_continuous_cache.py:29,106` — `vp_path="radio/ecallisto/BIR/01"` and `"radio/ecallisto/BIR/race"` → the `e-CALLISTO` spelling.

Do **not** change `test_ilofar_stream_reuses_preexisting_continuous_vp_by_path`'s behaviour — only its path literal. Reuse-by-path is exactly what this task preserves.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && \
  QT_QPA_PLATFORM=xcb /var/home/jeandet/Documents/prog/SciQLop/.venv/bin/python \
  -m pytest sciqlop_radio/tests/ -q -m "not live"
```

Expected: the whole plugin suite green — the new tests plus every pre-existing one. Read the real counts and the exit code.

- [ ] **Step 6: Commit**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop
git add sciqlop_radio/sciqlop_radio/continuous.py sciqlop_radio/sciqlop_radio/tests/
git commit -m "refactor(sciqlop_radio): one definition per radio product"
```

---

### Task 4: Pass display names at registration

**Files:**
- Modify: `sciqlop_radio/hints.py` (`make_rich_vp`, ~line 193-225)
- Modify: `sciqlop_radio/continuous.py` (`register_continuous_products`, ~line 543-580)
- Modify: `sciqlop_radio/lofar.py` (`register_lofar_product`, ~line 351-381)
- Modify: `sciqlop_radio/catalog.py` (the registration loop, ~line 152-176)
- Modify: `sciqlop_radio/dock.py` (stream registration, ~line 528-539 and its `_PlotGroup` consumer)
- Test: `sciqlop_radio/tests/test_hints.py` (append), `sciqlop_radio/tests/test_continuous.py` (append), `sciqlop_radio/tests/test_lofar.py` (append), `sciqlop_radio/tests/test_catalog.py` (append)

**Interfaces:**
- Consumes: `EasyProvider(..., display_name=...)` from Task 1 (present once the SciQLop branch is installed); `StreamIdentity.display_name` from Task 2; `ContinuousSource.label` unchanged.
- Produces: every radio product registers with a display name.

**Note:** Task 1 lives in the SciQLop repo. Its change must be on the SciQLop venv's `sys.path` for this task's tests to pass — SciQLop is loaded from the git checkout, so committing on the SciQLop branch is enough; nothing needs reinstalling.

- [ ] **Step 1: Write the failing tests**

Append to `sciqlop_radio/tests/test_hints.py`:

```python
def test_make_rich_vp_forwards_display_name():
    """make_rich_vp is the only registration path in this plugin, so the
    display name has to survive it to reach the node."""
    import sciqlop_radio.hints as hints

    captured = {}

    class _Spy:
        def __init__(self, path, callback, **kwargs):
            captured.update(path=path, **kwargs)

    monkey = hints.RichEasySpectrogram
    hints.RichEasySpectrogram = _Spy
    try:
        from SciQLop.user_api.virtual_products import VirtualProductType
        hints.make_rich_vp("radio/I-LOFAR/X", lambda s, e: None,
                           VirtualProductType.Spectrogram,
                           metadata={"DISPLAY_TYPE": "spectrogram"},
                           display_name="I-LOFAR X pol", out_of_process=True)
    finally:
        hints.RichEasySpectrogram = monkey

    assert captured["display_name"] == "I-LOFAR X pol"
```

Append to `sciqlop_radio/tests/test_continuous.py`:

```python
def test_continuous_registration_passes_display_names(tmp_path):
    from sciqlop_radio.continuous import register_continuous_products

    seen = {}

    def _vp_factory(path, cb, vptype, *, metadata, display_name=None, **kwargs):
        seen[path] = display_name
        return object()

    register_continuous_products(tmp_path, lambda p: None,
                                 vp_factory=_vp_factory, out_of_process=False)
    assert seen == {
        "radio/EOVSA": "EOVSA",
        "radio/I-LOFAR/X": "I-LOFAR X pol",
        "radio/I-LOFAR/Y": "I-LOFAR Y pol",
    }
```

Append to `sciqlop_radio/tests/test_lofar.py`:

```python
def test_lofar_registration_passes_a_display_name(tmp_path):
    from sciqlop_radio.lofar import register_lofar_product

    seen = {}

    def _vp_factory(path, cb, vptype, *, metadata, display_name=None, **kwargs):
        seen[path] = display_name
        return object()

    register_lofar_product(cache_dir=tmp_path, vp_factory=_vp_factory,
                           out_of_process=False)
    assert seen == {"radio/LOFAR/LBA": "LOFAR LBA"}
```

Append to `sciqlop_radio/tests/test_catalog.py` — a catalog entry's curated YAML `label:` becomes its display name. This mirrors the file's existing `test_register_entries_*` pattern exactly (`_fake_speasy` / `_fake_index` / `_fake_vp_types` are already defined in that module):

```python
def test_register_entries_passes_the_curated_label_as_display_name():
    """The YAML `label:` was previously unused at registration — catalog.py
    builds node metadata from `e.labels` (the *component* names), never
    `e.label`, so the curated string never reached the product tree."""
    from sciqlop_radio.catalog import CuratedRadioProduct, _register_entries
    sp = _fake_speasy({"amda": {"ok": _fake_index("ok", "amda")}})
    entries = [CuratedRadioProduct(path="Wind/WAVES/RAD1", speasy_id="amda/ok",
                                   label="Wind/WAVES RAD1")]
    captured = []

    def vp_factory(path, cb, vptype, *, metadata, labels=None,
                   out_of_process=False, display_name=None):
        captured.append((path, display_name))
        return f"VP[{path}]"

    _register_entries(entries, vp_factory, _fake_vp_types(), sp)
    assert captured == [("radio/Wind/WAVES/RAD1", "Wind/WAVES RAD1")]


def test_register_entries_display_name_defaults_to_the_path():
    """CuratedRadioProduct.__init__ already defaults `label` to `path` when the
    YAML omits it, so a label-less entry still gets a usable display name."""
    from sciqlop_radio.catalog import CuratedRadioProduct, _register_entries
    sp = _fake_speasy({"amda": {"ok": _fake_index("ok", "amda")}})
    entries = [CuratedRadioProduct(path="Wind/WAVES/RAD1", speasy_id="amda/ok")]
    captured = []

    def vp_factory(path, cb, vptype, *, metadata, labels=None,
                   out_of_process=False, display_name=None):
        captured.append(display_name)
        return "VP"

    _register_entries(entries, vp_factory, _fake_vp_types(), sp)
    assert captured == ["Wind/WAVES/RAD1"]
```

The three existing `test_register_entries_*` tests define their `vp_factory` with an explicit keyword list and no `**kwargs`, so they will raise `TypeError` once `_register_entries` starts passing `display_name`. Add `display_name=None` to each of their signatures (`test_catalog.py:177`, `:196`, `:214`) — they are not asserting on it, they just have to accept it.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && \
  QT_QPA_PLATFORM=xcb /var/home/jeandet/Documents/prog/SciQLop/.venv/bin/python \
  -m pytest sciqlop_radio/tests/ -q -m "not live" -k "display_name"
```

Expected: FAIL — `make_rich_vp` takes no `display_name`, and no registration passes one.

- [ ] **Step 3: Thread `display_name` through `make_rich_vp`**

Add the parameter and forward it to all four `RichEasy*` constructions:

```python
def make_rich_vp(path: str, callback, vp_type, *, metadata: dict,
                 labels: Optional[list[str]] = None,
                 out_of_process: bool = False,
                 display_name: Optional[str] = None):
```

Each branch gains `display_name=display_name`, e.g.:

```python
    if vp_type == VirtualProductType.Spectrogram:
        return RichEasySpectrogram(path, callback, metadata=metadata,
                                    out_of_process=out_of_process,
                                    display_name=display_name)
```

- [ ] **Step 4: Pass a display name from each registration site**

`continuous.py` — `ContinuousSource.label` already holds the composed string (`make_stream_source` sets it from `StreamIdentity`, and the EOVSA entry spells it out), so in `register_continuous_products`'s loop:

```python
        vp = vp_factory(src.vp_path, cb, VirtualProductType.Spectrogram,
                         metadata=src.static_meta, out_of_process=out_of_process,
                         display_name=src.label)
```

For that to yield `I-LOFAR X pol`, `make_stream_source` must set `label=identity.display_name` rather than composing its own `" ".join(...)`. Make that change — it removes the third place that composes a label:

```python
    return ContinuousSource(
        vp_path=identity.vp_path,
        label=identity.display_name,
        ...
```

and drop the now-unused local `label = " ".join(...)` line above it.

`lofar.py` — add a module-level constant next to `LOFAR_VP_PATH` and pass it:

```python
LOFAR_DISPLAY_NAME = "LOFAR LBA"
```

```python
        vp = vp_factory(
            LOFAR_VP_PATH, cb, VirtualProductType.Spectrogram,
            metadata=LOFAR_META, out_of_process=out_of_process,
            display_name=LOFAR_DISPLAY_NAME,
        )
```

`catalog.py` — pass the curated YAML label in the registration call:

```python
            vp = vp_factory(path, cb, vptype, metadata=meta, labels=e.labels,
                             out_of_process=out_of_process,
                             display_name=e.label)
```

`dock.py` — the dock registers stream VPs itself, through `VirtualSpectrogram` (not `make_rich_vp`). Three edits:

1. `_PlotGroup` (line 576) gains a field, defaulted so the static-snapshot branch is unaffected:

```python
    out_of_process: bool = False
    display_name: str = ""
```

2. `_finalize_group`'s stream branch (line 537) carries the identity's name:

```python
            return _PlotGroup(vp_path=identity.vp_path, callback=callback,
                              first_name=paths[0].name, n_files=len(paths),
                              t0=t0, t1=t1, out_of_process=True,
                              display_name=identity.display_name)
```

3. The stream registration (line 458) forwards it:

```python
                        vp = VirtualSpectrogram(
                            g.vp_path, g.callback, out_of_process=True,
                            display_name=g.display_name,
                        )
```

Leave the `create_virtual_product` call in the `else` branch (line 470) alone — that is the static local-file path, whose `_PlotGroup` has no `StreamIdentity` and whose `display_name` is therefore `""`, which correctly falls back to the path leaf.

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && \
  QT_QPA_PLATFORM=xcb /var/home/jeandet/Documents/prog/SciQLop/.venv/bin/python \
  -m pytest sciqlop_radio/tests/ -q -m "not live"
```

Expected: the whole plugin suite green. Read the real counts and the exit code.

- [ ] **Step 6: Commit**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop
git add sciqlop_radio/sciqlop_radio/ 
git commit -m "feat(sciqlop_radio): register products with display names"
```

---

### Task 5: End-to-end verification

**Files:** none — this task runs things and reports.

- [ ] **Step 1: Run both suites**

```bash
cd /var/home/jeandet/Documents/prog/SciQLop && \
  QT_QPA_PLATFORM=xcb .venv/bin/python -m pytest tests/test_virtual_products -q; echo "SciQLop exit=$?"

cd /var/home/jeandet/Documents/prog/plugins_sciqlop/sciqlop_radio && \
  QT_QPA_PLATFORM=xcb /var/home/jeandet/Documents/prog/SciQLop/.venv/bin/python \
  -m pytest sciqlop_radio/tests/ -q -m "not live"; echo "plugin exit=$?"
```

Expected: both exit 0, plugin at ≥ 207 passed. Report the real numbers, not an impression.

- [ ] **Step 2: Verify the registered names without a GUI**

```python
# run from /tmp with PYTHONPATH=<plugin dir>
seen = {}
def vp_factory(path, cb, vptype, *, metadata, labels=None, display_name=None, **kw):
    seen[path] = display_name
    return object()

from pathlib import Path
from sciqlop_radio.continuous import register_continuous_products
from sciqlop_radio.lofar import register_lofar_product
register_continuous_products(Path('/tmp'), lambda p: None,
                             vp_factory=vp_factory, out_of_process=False)
register_lofar_product(cache_dir=Path('/tmp'), vp_factory=vp_factory,
                       out_of_process=False)
for path, name in sorted(seen.items()):
    print(f"{path:32s} -> {name}")
```

Expected:

```
radio/EOVSA                      -> EOVSA
radio/I-LOFAR/X                  -> I-LOFAR X pol
radio/I-LOFAR/Y                  -> I-LOFAR Y pol
radio/LOFAR/LBA                  -> LOFAR LBA
```

- [ ] **Step 3: Manual GUI check**

Launch SciQLop, open the product tree under `radio/`, and confirm: the tree reads `I-LOFAR X pol` under `I-LOFAR` rather than `X`; dragging it onto a panel gives a plot labelled `I-LOFAR X pol`; and the tooltip shows the curated description rather than "Virtual Spectrogram product built from Python function: …".

This needs a display. If you cannot run it, say so explicitly and report it as not performed — do not infer it from the tests.

- [ ] **Step 4: Commit any fixes**

Skip if Steps 1-3 needed no changes.

## Notes for the implementer

- **Do not push.** Both repos are already several commits ahead of their remotes.
- If a pre-existing test fails for a reason this plan does not anticipate, stop and report it rather than editing the test to pass.
- `source_key` must not change. If you find yourself editing `STREAM_RULES` keys or `RadioSource.key`, you have taken a wrong turn.
