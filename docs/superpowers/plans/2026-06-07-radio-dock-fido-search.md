# Radio dock Fido search rework — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `sciqlop_radio` Fido search dock usable and honest — fix ILOFAR's silent empty results, mark the now-registration-walled EOVSA source as unavailable, add result columns + client-side station/substring filtering, add an advanced mode (instrument + wavelength + raw escape-hatch query), and realign the sunpy/radiospectra dependency pin with the installed/tested stack.

**Architecture:** A pydantic `RadioQuery` becomes the single value the fetch layer consumes (replacing the `(source, t0, t1)` triple). `fetch.py` builds sunpy attrs from it (structured or via a restricted-namespace `eval` of a raw query) and runs one `Fido.search` helper. `dock.py` swaps its `QListWidget` for a `QTableWidget` with client-side filters and an advanced group box.

**Tech Stack:** Python 3.12+, PySide6 (Qt6), pydantic v2, sunpy[net] ≥7, radiospectra `main`, pytest + pytest-qt.

**Reference spec:** `docs/superpowers/specs/2026-06-07-radio-dock-fido-search-design.md`

**Design refinements discovered during planning (supersede the spec where they differ):**
- `sunpy.net.attrs` has **no `Observatory`** attr → the advanced "Station" field is dropped; station filtering is **client-side only** (the result filter bar). `RadioQuery` therefore has **no `observatory` field**.
- Real Fido rows expose `url` as a **column** (`row["url"]`), not an attribute. Current `getattr(row, "url", None)` returns `None` on real rows — a latent bug that also defeats `_cache_path_for`'s cache hits. Fixed via a `_row_field`/`_row_url` helper (Task 5).

---

## File structure

- Create `sciqlop_radio/sciqlop_radio/query.py` — the `RadioQuery` model. One responsibility: describe a search.
- Modify `sciqlop_radio/sciqlop_radio/sources.py` — add `unavailable_reason` + `example_range`; mark EOVSA unavailable.
- Modify `sciqlop_radio/sciqlop_radio/fetch.py` — `RadioQuery`-driven search; attr builders; raw eval; row helpers; `_cache_path_for` fix.
- Modify `sciqlop_radio/sciqlop_radio/dock.py` — table results, filters, advanced group, EOVSA guard, empty-state.
- Modify `sciqlop_radio/pyproject.toml` — dependency realignment.
- Modify tests: `test_fetch.py`, `test_dock.py`, `test_sources_registry.py`.

---

## Task 1: Realign dependency pin

**Files:**
- Modify: `sciqlop_radio/pyproject.toml:9-18`

- [ ] **Step 1: Edit the dependency block**

Replace the `requires-python` line and the commented sunpy/radiospectra block with:

```toml
requires-python = ">=3.12"
dependencies = [
    "SciQLop>=0.12.0,<0.13.0",
    # radiospectra `main` (0.6.2.dev) uses sunpy.net.scraper.Scraper(format=...),
    # which only exists on sunpy >= 7. The previous released radiospectra 0.6.1
    # used the legacy `Scraper(url, regex=True)` signature and needed sunpy < 7.
    # The installed + tested combo is sunpy 7.x + radiospectra main. Swap the
    # git URL for a version pin once radiospectra publishes the format= release.
    "sunpy[net]>=7",
    "radiospectra @ git+https://github.com/sunpy/radiospectra.git@main",
    "astropy",
    "numpy>=1.24",
    "pydantic>=2.0",
    "speasy>=1.7",
    "pyyaml",
]
```

- [ ] **Step 2: Verify the installed env already satisfies this**

Run: `python -c "import sys,sunpy,radiospectra; assert sys.version_info[:2]>=(3,12); assert sunpy.__version__>='7'; print('ok', sunpy.__version__, radiospectra.__version__)"`
Expected: `ok 7.1.2 0.6.2.dev26+g9aa96e1d5` (or newer)

- [ ] **Step 3: Commit**

```bash
git add sciqlop_radio/pyproject.toml
git commit -m "build(sciqlop_radio): pin sunpy>=7 + radiospectra main to match tested stack"
```

---

## Task 2: `RadioQuery` model

**Files:**
- Create: `sciqlop_radio/sciqlop_radio/query.py`
- Test: `sciqlop_radio/sciqlop_radio/tests/test_query.py`

- [ ] **Step 1: Write the failing test**

Create `sciqlop_radio/sciqlop_radio/tests/test_query.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone

from sciqlop_radio.query import RadioQuery
from sciqlop_radio.sources import SOURCES


def _t(d):
    return datetime(2021, 9, d, tzinfo=timezone.utc)


def test_from_source_copies_instrument_and_times():
    src = next(s for s in SOURCES if s.fido_instrument)
    q = RadioQuery.from_source(src, _t(1), _t(2))
    assert q.instrument == src.fido_instrument
    assert q.t_start == _t(1)
    assert q.t_end == _t(2)
    assert q.expect_spectrogram is True
    assert q.raw_attrs_text is None


def test_raw_query_defaults_keep_all_rows_off_until_set():
    q = RadioQuery(t_start=_t(1), t_end=_t(2), raw_attrs_text="a.Time('x','y')",
                   expect_spectrogram=False)
    assert q.raw_attrs_text == "a.Time('x','y')"
    assert q.expect_spectrogram is False


def test_optional_wavelength_fields():
    q = RadioQuery(t_start=_t(1), t_end=_t(2), instrument="ILOFAR",
                   wavelength_min_mhz=20.0, wavelength_max_mhz=100.0)
    assert q.wavelength_min_mhz == 20.0
    assert q.wavelength_max_mhz == 100.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd sciqlop_radio && python -m pytest sciqlop_radio/tests/test_query.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sciqlop_radio.query'`

- [ ] **Step 3: Write the implementation**

Create `sciqlop_radio/sciqlop_radio/query.py`:

```python
"""The single value the fetch layer consumes to run a Fido search.

A `RadioQuery` is either structured (instrument + optional wavelength) or a
raw escape hatch (`raw_attrs_text`, eval'd against sunpy attrs). Building it
in one place keeps the dock and the fetch service decoupled and testable.
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class RadioQuery(BaseModel):
    """Describes one Fido search. `raw_attrs_text`, when set, overrides the
    structured fields. `expect_spectrogram` is False for raw queries so the
    dock does not silently drop rows the user explicitly asked for."""

    t_start: datetime
    t_end: datetime
    instrument: str | None = None
    wavelength_min_mhz: float | None = None
    wavelength_max_mhz: float | None = None
    raw_attrs_text: str | None = None
    expect_spectrogram: bool = True

    @classmethod
    def from_source(cls, source, t_start: datetime, t_end: datetime) -> "RadioQuery":
        return cls(
            t_start=t_start,
            t_end=t_end,
            instrument=source.fido_instrument,
            expect_spectrogram=True,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd sciqlop_radio && python -m pytest sciqlop_radio/tests/test_query.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/query.py sciqlop_radio/sciqlop_radio/tests/test_query.py
git commit -m "feat(sciqlop_radio): add RadioQuery model for Fido searches"
```

---

## Task 3: Mark EOVSA unavailable + add example ranges

**Files:**
- Modify: `sciqlop_radio/sciqlop_radio/sources.py:12-88`
- Test: `sciqlop_radio/sciqlop_radio/tests/test_sources_registry.py`

- [ ] **Step 1: Write the failing tests**

Append to `sciqlop_radio/sciqlop_radio/tests/test_sources_registry.py`:

```python
def test_eovsa_is_marked_unavailable():
    """EOVSA spectrogram FITS moved behind registration; it must stay visible
    (so users find it) but not be a live Fido source."""
    eovsa = next(s for s in SOURCES if s.key == "eovsa")
    assert eovsa.fido_instrument is None
    assert eovsa.unavailable_reason
    assert "registration" in eovsa.unavailable_reason.lower()
    assert eovsa.accepts_local is True


def test_live_sources_have_example_range():
    for s in SOURCES:
        if s.fido_instrument:
            assert s.example_range, f"{s.key} missing example_range"
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd sciqlop_radio && python -m pytest sciqlop_radio/tests/test_sources_registry.py -v -k "eovsa or example"`
Expected: FAIL — `AttributeError: 'RadioSource' object has no attribute 'unavailable_reason'`

- [ ] **Step 3: Add the fields to `RadioSource`**

In `sciqlop_radio/sciqlop_radio/sources.py`, add to the `RadioSource` class (after the `accepts_local` field, around line 25):

```python
    unavailable_reason: str | None = Field(
        default=None,
        description=(
            "If set, the source is shown in the picker but Fido search is"
            " disabled and this message is displayed instead."
        ),
    )
    example_range: str = Field(
        default="",
        description="A date with known data, used in the empty-results hint.",
    )
```

- [ ] **Step 4: Update the EOVSA entry and add example ranges**

Replace the EOVSA `RadioSource(...)` block (around line 63-68) with:

```python
    RadioSource(
        key="eovsa",
        label="EOVSA (registration required)",
        fido_instrument=None,
        accepts_local=True,
        unavailable_reason=(
            "EOVSA spectrogram FITS now require registration at "
            "ovsa.njit.edu/eovsadata. Download a .fts there, then use "
            "'Open local…'."
        ),
        notes="Expanded Owens Valley Solar Array; 1–18 GHz imaging spectroscopy",
    ),
```

Add `example_range=` to the live sources:
- `psp_rfs` → `example_range="2021-10-28"`
- `ecallisto` → `example_range="2011-06-07"`
- `ilofar` → `example_range="2021-09-07"`
- `rstn` → `example_range="2015-11-04"`

For example, the ILOFAR entry becomes:

```python
    RadioSource(
        key="ilofar",
        label="I-LOFAR (mode 357 BST)",
        fido_instrument="ILOFAR",
        example_range="2021-09-07",
        notes="Irish LOFAR station, beam-formed mode 357; sparse campaign-day coverage",
    ),
```

- [ ] **Step 5: Run the full sources test file**

Run: `cd sciqlop_radio && python -m pytest sciqlop_radio/tests/test_sources_registry.py -v`
Expected: PASS (all, including the existing `test_source_is_reachable` since EOVSA `accepts_local` is True)

- [ ] **Step 6: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/sources.py sciqlop_radio/sciqlop_radio/tests/test_sources_registry.py
git commit -m "feat(sciqlop_radio): mark EOVSA unavailable, add per-source example_range"
```

---

## Task 4: `RadioQuery`-driven fetch + raw eval

**Files:**
- Modify: `sciqlop_radio/sciqlop_radio/fetch.py:30-64,91-110,187-220`
- Test: `sciqlop_radio/sciqlop_radio/tests/test_fetch.py`

- [ ] **Step 1: Write the failing tests**

In `sciqlop_radio/sciqlop_radio/tests/test_fetch.py`, replace `test_do_search_surfaces_response_errors` with the `RadioQuery` version and add new tests:

```python
def _query(**kw):
    from sciqlop_radio.query import RadioQuery
    base = dict(t_start=datetime(2021, 9, 1, tzinfo=timezone.utc),
                t_end=datetime(2021, 9, 2, tzinfo=timezone.utc))
    base.update(kw)
    return RadioQuery(**base)


def test_build_attrs_includes_instrument_and_wavelength(monkeypatch):
    from types import SimpleNamespace
    import sys, types
    captured = {}
    fake_attrs = SimpleNamespace(
        Time=lambda *a, **k: ("Time", a),
        Instrument=lambda *a, **k: ("Instrument", a),
        Wavelength=lambda lo, hi: ("Wavelength", lo, hi),
    )
    monkeypatch.setitem(sys.modules, "radiospectra.net", types.ModuleType("radiospectra.net"))
    fake_net = types.ModuleType("sunpy.net")
    fake_net.attrs = fake_attrs
    monkeypatch.setitem(sys.modules, "sunpy.net", fake_net)

    from sciqlop_radio import fetch as fetch_mod
    attrs = fetch_mod._build_attrs(_query(instrument="ILOFAR",
                                         wavelength_min_mhz=20.0,
                                         wavelength_max_mhz=100.0))
    kinds = [x[0] for x in attrs]
    assert kinds == ["Time", "Instrument", "Wavelength"]


def test_eval_raw_attrs_valid(monkeypatch):
    from types import SimpleNamespace
    import sys, types
    fake_attrs = SimpleNamespace(
        Time=lambda *a, **k: ("Time", a),
        Instrument=lambda *a, **k: ("Instrument", a),
        Wavelength=lambda *a, **k: ("Wavelength", a),
    )
    monkeypatch.setitem(sys.modules, "radiospectra.net", types.ModuleType("radiospectra.net"))
    fake_net = types.ModuleType("sunpy.net")
    fake_net.attrs = fake_attrs
    monkeypatch.setitem(sys.modules, "sunpy.net", fake_net)
    import astropy  # noqa: F401 — real astropy import path inside helper

    from sciqlop_radio import fetch as fetch_mod
    attrs = fetch_mod._eval_raw_attrs("a.Time('2021-09-01','2021-09-02'), a.Instrument('ILOFAR')")
    assert [x[0] for x in attrs] == ["Time", "Instrument"]


def test_eval_raw_attrs_invalid_raises(monkeypatch):
    import sys, types
    from types import SimpleNamespace
    monkeypatch.setitem(sys.modules, "radiospectra.net", types.ModuleType("radiospectra.net"))
    fake_net = types.ModuleType("sunpy.net")
    fake_net.attrs = SimpleNamespace()
    monkeypatch.setitem(sys.modules, "sunpy.net", fake_net)

    from sciqlop_radio import fetch as fetch_mod
    with pytest.raises(RuntimeError, match="Invalid raw Fido query"):
        fetch_mod._eval_raw_attrs("import os; os.system('boom')")


def test_do_search_surfaces_response_errors(monkeypatch):
    """When Fido attaches client-side errors AND returns no rows, _do_search
    must raise so the dock shows a real message instead of 'Found 0 file(s)'."""
    from types import SimpleNamespace
    import sys, types

    from sciqlop_radio import fetch as fetch_mod

    class FakeResponse:
        errors = [TypeError("Scraper.__init__() missing 1 required positional argument: 'format'")]
        def __iter__(self):
            return iter([])

    fake_Fido = SimpleNamespace(search=lambda *args, **kwargs: FakeResponse())
    fake_attrs = SimpleNamespace(
        Time=lambda *a, **k: object(),
        Instrument=lambda *a, **k: object(),
    )
    fake_sunpy_net = types.ModuleType("sunpy.net")
    fake_sunpy_net.Fido = fake_Fido
    fake_sunpy_net.attrs = fake_attrs
    monkeypatch.setitem(sys.modules, "sunpy.net", fake_sunpy_net)
    monkeypatch.setitem(sys.modules, "radiospectra.net", types.ModuleType("radiospectra.net"))

    with pytest.raises(RuntimeError, match="Fido client errors"):
        fetch_mod._do_search(_query(instrument="ILOFAR"))


def test_row_url_reads_column_then_attribute():
    from sciqlop_radio.fetch import _row_url

    class DictRow(dict):
        pass

    assert _row_url(DictRow({"url": "https://x/a.fit.gz"})) == "https://x/a.fit.gz"

    class AttrRow:
        url = "https://y/b.cdf"
    # attribute fallback for objects without item access
    assert _row_url(AttrRow()) == "https://y/b.cdf"
```

Also update the two existing tests `test_search_emits_search_completed` and `test_search_failure_emits_search_failed` to call `svc.search` with a query instead of `source=..., t_start=..., t_end=...`:

```python
    from sciqlop_radio.query import RadioQuery
    ...
    svc.search(RadioQuery(t_start=datetime(2024, 5, 1, tzinfo=timezone.utc),
                          t_end=datetime(2024, 5, 2, tzinfo=timezone.utc),
                          instrument="ILOFAR"))
```

- [ ] **Step 2: Run to verify failures**

Run: `cd sciqlop_radio && python -m pytest sciqlop_radio/tests/test_fetch.py -v`
Expected: FAIL — `AttributeError: module 'sciqlop_radio.fetch' has no attribute '_build_attrs'` (and signature errors on `search`)

- [ ] **Step 3: Rewrite the search internals in `fetch.py`**

Replace `_do_search` (lines 30-64) with these module-level functions:

```python
def _row_field(row, name: str) -> str:
    """Defensive column access for a Fido QueryResponseRow. Returns '' for a
    missing column. Falls back to attribute access so plain test stubs work."""
    try:
        val = row[name]
    except (KeyError, TypeError, IndexError):
        val = getattr(row, name, None)
    return "" if val is None else str(val)


def _row_url(row) -> str:
    return _row_field(row, "url")


def _build_attrs(query) -> list:
    """Structured attrs from a RadioQuery. Imports radiospectra.net for the
    side-effect that registers the Fido clients (see module docstring)."""
    import radiospectra.net  # noqa: F401 — registers RFS/eCALLISTO/ILOFAR/RSTN clients
    from sunpy.net import attrs as a  # type: ignore

    attrs = [a.Time(_format_time_for_fido(query.t_start),
                    _format_time_for_fido(query.t_end))]
    if query.instrument:
        attrs.append(a.Instrument(query.instrument))
    if query.wavelength_min_mhz is not None and query.wavelength_max_mhz is not None:
        import astropy.units as u
        attrs.append(a.Wavelength(query.wavelength_min_mhz * u.MHz,
                                  query.wavelength_max_mhz * u.MHz))
    return attrs


def _eval_raw_attrs(text: str) -> list:
    """Evaluate a raw Fido query string in a restricted namespace.

    Only the sunpy attrs module and common attr names are exposed; builtins
    are removed. This is the user's own desktop tool (they can run arbitrary
    Python via SciQLop's console), so the namespace guards footguns, not a
    determined adversary.
    """
    import radiospectra.net  # noqa: F401
    from sunpy.net import attrs as a  # type: ignore
    import astropy.units as u

    ns = {
        "__builtins__": {},
        "a": a, "u": u,
        "Time": a.Time, "Instrument": a.Instrument, "Wavelength": a.Wavelength,
    }
    try:
        result = eval(text, ns)  # noqa: S307 — restricted namespace; see docstring
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Invalid raw Fido query: {type(e).__name__}: {e}") from e
    return list(result) if isinstance(result, (list, tuple)) else [result]


def _run_fido_search(attrs: list) -> list[Any]:
    """Run Fido.search with a pre-built attrs list; return flat rows. Raises
    if Fido attached errors and returned no rows (otherwise they'd surface as
    a silent zero-rows result)."""
    from sunpy.net import Fido  # type: ignore

    response = Fido.search(*attrs)
    rows: list[Any] = []
    for table in response:
        for row in table:
            rows.append(row)

    errors = list(getattr(response, "errors", []) or [])
    if errors and not rows:
        details = "; ".join(f"{type(e).__name__}: {e}" for e in errors)
        raise RuntimeError(f"Fido client errors (no rows returned): {details}")
    return rows


def _do_search(query) -> list[Any]:
    """Build attrs from a RadioQuery (structured or raw) and run the search."""
    attrs = _eval_raw_attrs(query.raw_attrs_text) if query.raw_attrs_text else _build_attrs(query)
    return _run_fido_search(attrs)
```

- [ ] **Step 4: Fix `_cache_path_for` to use the column helper**

Replace the body of `_cache_path_for` (lines 84-88) with:

```python
def _cache_path_for(row: Any, cache_dir: Path) -> Path:
    """Best-effort: derive expected cached filename from a row's url column."""
    url = _row_url(row)
    name = url.rsplit("/", 1)[-1] if url else ""
    return cache_dir / name if name else cache_dir / "__unknown__"
```

- [ ] **Step 5: Update `_SearchTask` and `RadioFetchService.search` to take a query**

Replace `_SearchTask.__init__`/`run` (lines 92-110) so it stores a `query`:

```python
class _SearchTask(QRunnable):
    def __init__(self, svc: "RadioFetchService", query, cache_key=None):
        super().__init__()
        self._svc = svc
        self._query = query
        self._cache_key = cache_key

    def run(self):
        svc = self._svc
        try:
            rows = _do_search(self._query)
            if self._cache_key is not None:
                svc._search_cache_store(self._cache_key, rows)
            svc.searchCompleted.emit(rows)
        except Exception as e:  # noqa: BLE001
            svc.searchFailed.emit(f"{type(e).__name__}: {e}")
        finally:
            svc._mark_finished()
```

Replace `_search_cache_key` (lines 187-189) and `search` (lines 206-220):

```python
    @staticmethod
    def _search_cache_key(query) -> tuple:
        return (
            query.instrument,
            query.raw_attrs_text,
            query.wavelength_min_mhz,
            query.wavelength_max_mhz,
            _format_time_for_fido(query.t_start),
            _format_time_for_fido(query.t_end),
        )

    def search(self, query) -> None:
        key = self._search_cache_key(query)
        cached = self._search_cache_hit(key)
        if cached is not None:
            self._inflight.clear()
            from PySide6.QtCore import QTimer
            def _emit():
                self.searchCompleted.emit(list(cached))
                self._mark_finished()
            QTimer.singleShot(0, _emit)
            return
        self._inflight.clear()
        self._pool.start(_SearchTask(self, query, cache_key=key))
```

- [ ] **Step 6: Run the fetch tests**

Run: `cd sciqlop_radio && python -m pytest sciqlop_radio/tests/test_fetch.py -v`
Expected: PASS (all)

- [ ] **Step 7: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/fetch.py sciqlop_radio/sciqlop_radio/tests/test_fetch.py
git commit -m "feat(sciqlop_radio): drive Fido search from RadioQuery; fix row url column access"
```

---

## Task 5: Dock — build RadioQuery on Fetch (simple path) + EOVSA guard

**Files:**
- Modify: `sciqlop_radio/sciqlop_radio/dock.py:21-25,159-180`
- Test: `sciqlop_radio/sciqlop_radio/tests/test_dock.py`

- [ ] **Step 1: Update the dock test fake + add EOVSA-guard test**

In `sciqlop_radio/sciqlop_radio/tests/test_dock.py`, change `FakeFetchService.search` to take a query, and record it:

```python
    def search(self, query):
        self.search_calls.append(query)
```

Replace `test_fetch_button_calls_fetch_service_search` with:

```python
def test_fetch_button_builds_query_from_source(dock):
    w, svc = dock
    w.start_picker.setDateTime(_qdt(2021, 9, 1))
    w.end_picker.setDateTime(_qdt(2021, 9, 2))
    # pick the first live (fido) source
    for i in range(w.source_combo.count()):
        if w.source_combo.itemData(i).fido_instrument:
            w.source_combo.setCurrentIndex(i)
            break
    w.fetch_button.click()
    assert svc.search_calls, "fetch button did not trigger search"
    q = svc.search_calls[-1]
    assert q.instrument
    assert q.t_start < q.t_end


def test_selecting_eovsa_disables_fetch_and_shows_message(dock):
    w, svc = dock
    for i in range(w.source_combo.count()):
        if w.source_combo.itemData(i).key == "eovsa":
            w.source_combo.setCurrentIndex(i)
            break
    w.fetch_button.click()
    assert not svc.search_calls, "EOVSA must not trigger a Fido search"
    assert "registration" in w.status_label.text().lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd sciqlop_radio && python -m pytest sciqlop_radio/tests/test_dock.py -v -k "build_query or eovsa"`
Expected: FAIL — `test_fetch_button_builds_query_from_source` (no `.instrument` on the recorded tuple) and EOVSA test (search still called)

- [ ] **Step 3: Update imports + rewrite `_on_fetch_clicked`**

In `dock.py`, add the import (near line 25):

```python
from .query import RadioQuery
```

Replace `_on_fetch_clicked` (lines 167-180) with:

```python
    def _on_fetch_clicked(self):
        source: RadioSource = self.source_combo.currentData()
        if source.unavailable_reason:
            self._set_status(source.unavailable_reason)
            return
        if not source.fido_instrument:
            self._set_status(f"{source.label} is local-only — use 'Open local…'")
            return
        t0 = self.start_picker.dateTime().toPython().replace(tzinfo=timezone.utc)
        t1 = self.end_picker.dateTime().toPython().replace(tzinfo=timezone.utc)
        if t1 <= t0:
            self._set_status("End time must be after start time")
            return
        self._current_source = source
        self._current_expect_spectrogram = True
        self._set_status(f"Searching {source.label}…")
        self._clear_results()
        self._svc.search(RadioQuery.from_source(source, t0, t1))
```

Add instance attributes in `__init__` (after `self._virtual_products = {}` around line 116):

```python
        self._current_source: RadioSource | None = None
        self._current_expect_spectrogram = True
```

Add a `_clear_results` helper (used here and later by the table) near `_set_status`:

```python
    def _clear_results(self):
        self.results_list.clear()
        self._results_changed.emit()
```

(Replaces the two `self.results_list.clear(); self._results_changed.emit()` lines in `_on_fetch_clicked`/`_on_search_failed`; leave `_on_search_completed` as-is for now — it is rewritten in Task 6.)

- [ ] **Step 4: Run the dock tests**

Run: `cd sciqlop_radio && python -m pytest sciqlop_radio/tests/test_dock.py -v`
Expected: PASS (existing list-based tests still pass; new query/EOVSA tests pass)

- [ ] **Step 5: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/dock.py sciqlop_radio/sciqlop_radio/tests/test_dock.py
git commit -m "feat(sciqlop_radio): build RadioQuery on fetch; guard unavailable EOVSA"
```

---

## Task 6: Dock — results table with columns

**Files:**
- Modify: `sciqlop_radio/sciqlop_radio/dock.py:16-19,146-150,199-215`
- Test: `sciqlop_radio/sciqlop_radio/tests/test_dock.py`

- [ ] **Step 1: Rewrite the result-list tests for a table**

In `test_dock.py`, add a `FakeRow` and rewrite the populate/drop tests:

```python
class FakeRow(dict):
    """Dict-backed stand-in for a Fido QueryResponseRow (column access)."""


def _erow(url, observatory="", start=""):
    return FakeRow({"url": url, "Observatory": observatory, "Start Time": start})


def test_search_results_populate_table(dock, qtbot):
    w, svc = dock
    with qtbot.waitSignal(w._results_changed, timeout=1000):
        svc.searchCompleted.emit([_erow("https://archive/example_0.cdf", "BIR", "2021-09-07 08:00")])
    assert w.results_table.rowCount() == 1
    assert "example_0.cdf" in w._table_filename(0)
    assert w._table_station(0) == "BIR"


def test_search_drops_non_spectrogram_results(dock, qtbot):
    w, svc = dock
    rows = [
        _erow("https://archive/swaves_tds_tdsmax_20240612.txt"),
        _erow("https://archive/psp_rfs_20240612.cdf"),
        _erow("https://archive/callisto_20240612.fit.gz"),
        _erow("https://archive/something_else.bin"),
    ]
    with qtbot.waitSignal(w._results_changed, timeout=1000):
        svc.searchCompleted.emit(rows)
    assert w.results_table.rowCount() == 2
    names = [w._table_filename(i) for i in range(w.results_table.rowCount())]
    assert not any(n.endswith(".txt") or n.endswith(".bin") for n in names)
    assert "2 non-spectrogram" in w.status_label.text()
```

Update `test_plot_selected_registers_virtual_product_and_plots_on_panel` — it relies on `fetchCompleted` only, so it is unaffected; leave it. Delete the old `test_search_results_populate_list` (replaced above).

- [ ] **Step 2: Run to verify failure**

Run: `cd sciqlop_radio && python -m pytest sciqlop_radio/tests/test_dock.py -v -k "populate_table or drops_non"`
Expected: FAIL — `AttributeError: 'RadioSpectraDock' object has no attribute 'results_table'`

- [ ] **Step 3: Swap the widget import and creation**

In `dock.py` imports (line 16-19), replace `QListWidget, QListWidgetItem` with `QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView`:

```python
from PySide6.QtWidgets import (
    QComboBox, QDateTimeEdit, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QAbstractItemView, QTableWidget, QTableWidgetItem, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)
```

Replace the results list creation (lines 146-148) with a table:

```python
        self.results_table = QTableWidget(0, 3)
        self.results_table.setHorizontalHeaderLabels(["Start Time", "Station", "File"])
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.setSortingEnabled(True)
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        root.addWidget(self.results_table, 1)
```

- [ ] **Step 4: Replace `_clear_results` and `_on_search_completed`; add table accessors**

```python
    def _clear_results(self):
        self.results_table.setRowCount(0)
        self._results_changed.emit()

    def _on_search_completed(self, rows: list):
        from .fetch import _row_url, _row_field
        self.results_table.setSortingEnabled(False)
        self.results_table.setRowCount(0)
        skipped = 0
        for row in rows:
            url = _row_url(row)
            name = url.rsplit("/", 1)[-1] if url else repr(row)
            if self._current_expect_spectrogram and not _is_supported_filename(name):
                skipped += 1
                continue
            r = self.results_table.rowCount()
            self.results_table.insertRow(r)
            start_item = QTableWidgetItem(_row_field(row, "Start Time"))
            start_item.setData(Qt.UserRole, row)
            self.results_table.setItem(r, 0, start_item)
            self.results_table.setItem(r, 1, QTableWidgetItem(_row_field(row, "Observatory")))
            self.results_table.setItem(r, 2, QTableWidgetItem(name))
        self.results_table.setSortingEnabled(True)
        count = self.results_table.rowCount()
        if count == 0 and not skipped:
            self._set_status(self._empty_results_message())
        else:
            msg = f"Found {count} spectrogram file(s)"
            if skipped:
                msg += f" ({skipped} non-spectrogram row(s) hidden)"
            self._set_status(msg)
        self._results_changed.emit()

    def _empty_results_message(self) -> str:
        src = self._current_source
        if src is not None and src.example_range:
            return (f"No data for {src.label} in this range. "
                    f"Coverage may be sparse; try e.g. {src.example_range}.")
        return "No spectrogram files found in this range."

    def _table_filename(self, rowidx: int) -> str:
        item = self.results_table.item(rowidx, 2)
        return item.text() if item else ""

    def _table_station(self, rowidx: int) -> str:
        item = self.results_table.item(rowidx, 1)
        return item.text() if item else ""

    def _selected_rows(self) -> list:
        rows = []
        for idx in self.results_table.selectionModel().selectedRows():
            item = self.results_table.item(idx.row(), 0)
            if item is not None:
                rows.append(item.data(Qt.UserRole))
        return rows
```

Update `_on_plot_selected_clicked` (was reading `results_list`) to use `_selected_rows()`:

```python
    def _on_plot_selected_clicked(self):
        rows = self._selected_rows()
        if not rows:
            self._set_status("No rows selected")
            return
        self._set_status(f"Fetching {len(rows)} file(s)…")
        self._svc.fetch(rows)
```

Update `_on_search_failed` to call `_clear_results()` instead of `results_list.clear()`.

- [ ] **Step 5: Run the dock tests**

Run: `cd sciqlop_radio && python -m pytest sciqlop_radio/tests/test_dock.py -v`
Expected: PASS (all)

- [ ] **Step 6: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/dock.py sciqlop_radio/sciqlop_radio/tests/test_dock.py
git commit -m "feat(sciqlop_radio): results table with Start/Station/File columns + empty-state hint"
```

---

## Task 7: Dock — client-side station + substring filters

**Files:**
- Modify: `sciqlop_radio/sciqlop_radio/dock.py` (controls area + `_on_search_completed`)
- Test: `sciqlop_radio/sciqlop_radio/tests/test_dock.py`

- [ ] **Step 1: Write the failing filter tests**

```python
def test_station_filter_hides_other_stations(dock, qtbot):
    w, svc = dock
    rows = [
        _erow("https://a/BIR_1.fit.gz", "BIR"),
        _erow("https://a/ALMATY_1.fit.gz", "ALMATY"),
        _erow("https://a/BIR_2.fit.gz", "BIR"),
    ]
    with qtbot.waitSignal(w._results_changed, timeout=1000):
        svc.searchCompleted.emit(rows)
    # station combo populated with distinct stations + "All"
    idx = w.station_filter.findText("ALMATY")
    assert idx >= 0
    w.station_filter.setCurrentIndex(idx)
    visible = [i for i in range(w.results_table.rowCount())
               if not w.results_table.isRowHidden(i)]
    assert len(visible) == 1
    assert w._table_station(visible[0]) == "ALMATY"


def test_text_filter_matches_filename(dock, qtbot):
    w, svc = dock
    rows = [_erow("https://a/BIR_1.fit.gz", "BIR"),
            _erow("https://a/ALMATY_1.fit.gz", "ALMATY")]
    with qtbot.waitSignal(w._results_changed, timeout=1000):
        svc.searchCompleted.emit(rows)
    w.text_filter.setText("almaty")
    visible = [i for i in range(w.results_table.rowCount())
               if not w.results_table.isRowHidden(i)]
    assert len(visible) == 1
    assert "ALMATY" in w._table_filename(visible[0])
```

- [ ] **Step 2: Run to verify failure**

Run: `cd sciqlop_radio && python -m pytest sciqlop_radio/tests/test_dock.py -v -k "station_filter or text_filter"`
Expected: FAIL — `AttributeError: ... has no attribute 'station_filter'`

- [ ] **Step 3: Add the filter bar widgets**

In `__init__`, after the controls layout and before the table, add:

```python
        filters = QHBoxLayout()
        self.text_filter = QLineEdit()
        self.text_filter.setPlaceholderText("Filter results…")
        self.station_filter = QComboBox()
        self.station_filter.addItem("All stations", "")
        filters.addWidget(QLabel("Filter:"))
        filters.addWidget(self.text_filter, 1)
        filters.addWidget(QLabel("Station:"))
        filters.addWidget(self.station_filter)
        root.addLayout(filters)

        self.text_filter.textChanged.connect(self._apply_filters)
        self.station_filter.currentIndexChanged.connect(self._apply_filters)
```

- [ ] **Step 4: Populate the station combo and apply filters**

At the end of `_on_search_completed` (before the final `_results_changed.emit()`), repopulate the station combo from distinct stations and apply filters:

```python
        self._refresh_station_filter()
        self._apply_filters()
```

Add the helpers:

```python
    def _refresh_station_filter(self):
        stations = sorted({self._table_station(i)
                           for i in range(self.results_table.rowCount())
                           if self._table_station(i)})
        self.station_filter.blockSignals(True)
        self.station_filter.clear()
        self.station_filter.addItem("All stations", "")
        for s in stations:
            self.station_filter.addItem(s, s)
        self.station_filter.blockSignals(False)

    def _apply_filters(self):
        needle = self.text_filter.text().strip().lower()
        station = self.station_filter.currentData() or ""
        for i in range(self.results_table.rowCount()):
            text_hit = (needle in self._table_filename(i).lower()
                        or needle in self._table_station(i).lower()
                        or needle in (self.results_table.item(i, 0).text().lower()
                                      if self.results_table.item(i, 0) else ""))
            station_hit = (not station) or self._table_station(i) == station
            self.results_table.setRowHidden(i, not (text_hit and station_hit))
```

- [ ] **Step 5: Run the dock tests**

Run: `cd sciqlop_radio && python -m pytest sciqlop_radio/tests/test_dock.py -v`
Expected: PASS (all)

- [ ] **Step 6: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/dock.py sciqlop_radio/sciqlop_radio/tests/test_dock.py
git commit -m "feat(sciqlop_radio): client-side station + substring result filters"
```

---

## Task 8: Dock — advanced search group (instrument + wavelength + raw)

**Files:**
- Modify: `sciqlop_radio/sciqlop_radio/dock.py` (controls area + `_on_fetch_clicked`)
- Test: `sciqlop_radio/sciqlop_radio/tests/test_dock.py`

- [ ] **Step 1: Write the failing advanced tests**

```python
def test_advanced_structured_query(dock):
    w, svc = dock
    w.advanced_group.setChecked(True)
    w.adv_instrument.setCurrentText("ILOFAR")
    w.adv_wl_min.setText("20")
    w.adv_wl_max.setText("100")
    w.start_picker.setDateTime(_qdt(2021, 9, 1))
    w.end_picker.setDateTime(_qdt(2021, 9, 10))
    w.fetch_button.click()
    q = svc.search_calls[-1]
    assert q.instrument == "ILOFAR"
    assert q.wavelength_min_mhz == 20.0
    assert q.wavelength_max_mhz == 100.0
    assert q.expect_spectrogram is True


def test_advanced_raw_query_sets_raw_and_keeps_all_rows(dock):
    w, svc = dock
    w.advanced_group.setChecked(True)
    w.adv_raw.setText("a.Time('2021-09-01','2021-09-10'), a.Instrument('ILOFAR')")
    w.fetch_button.click()
    q = svc.search_calls[-1]
    assert q.raw_attrs_text.startswith("a.Time(")
    assert q.expect_spectrogram is False
```

- [ ] **Step 2: Run to verify failure**

Run: `cd sciqlop_radio && python -m pytest sciqlop_radio/tests/test_dock.py -v -k "advanced"`
Expected: FAIL — `AttributeError: ... has no attribute 'advanced_group'`

- [ ] **Step 3: Add the advanced group box**

Add `QGroupBox` to the imports:

```python
from PySide6.QtWidgets import (
    QComboBox, QDateTimeEdit, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QAbstractItemView, QTableWidget, QTableWidgetItem, QLineEdit,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)
```

In `__init__`, after the `times` layout and before the filter bar, add:

```python
        self.advanced_group = QGroupBox("Advanced")
        self.advanced_group.setCheckable(True)
        self.advanced_group.setChecked(False)
        adv = QVBoxLayout(self.advanced_group)
        adv_row1 = QHBoxLayout()
        self.adv_instrument = QComboBox()
        self.adv_instrument.setEditable(True)
        for name in ("RFS", "eCALLISTO", "ILOFAR", "RSTN"):
            self.adv_instrument.addItem(name)
        self.adv_wl_min = QLineEdit()
        self.adv_wl_min.setPlaceholderText("λ min")
        self.adv_wl_max = QLineEdit()
        self.adv_wl_max.setPlaceholderText("λ max")
        adv_row1.addWidget(QLabel("Instrument:"))
        adv_row1.addWidget(self.adv_instrument, 1)
        adv_row1.addWidget(QLabel("λ (MHz):"))
        adv_row1.addWidget(self.adv_wl_min)
        adv_row1.addWidget(QLabel("–"))
        adv_row1.addWidget(self.adv_wl_max)
        adv.addLayout(adv_row1)
        adv_row2 = QHBoxLayout()
        self.adv_raw = QLineEdit()
        self.adv_raw.setPlaceholderText("Raw Fido query, e.g. a.Time('…','…'), a.Instrument('…')")
        adv_row2.addWidget(QLabel("Raw:"))
        adv_row2.addWidget(self.adv_raw, 1)
        adv.addLayout(adv_row2)
        adv.addWidget(QLabel("⚠ Advanced/raw results may not be plottable spectrograms."))
        root.addWidget(self.advanced_group)
```

- [ ] **Step 4: Branch `_on_fetch_clicked` on the advanced group**

Replace `_on_fetch_clicked` with a version that delegates:

```python
    def _on_fetch_clicked(self):
        query = (self._build_advanced_query() if self.advanced_group.isChecked()
                 else self._build_simple_query())
        if query is None:
            return
        self._clear_results()
        self._svc.search(query)

    def _build_simple_query(self) -> "RadioQuery | None":
        source: RadioSource = self.source_combo.currentData()
        if source.unavailable_reason:
            self._set_status(source.unavailable_reason)
            return None
        if not source.fido_instrument:
            self._set_status(f"{source.label} is local-only — use 'Open local…'")
            return None
        t0, t1 = self._time_range()
        if t1 <= t0:
            self._set_status("End time must be after start time")
            return None
        self._current_source = source
        self._current_expect_spectrogram = True
        self._set_status(f"Searching {source.label}…")
        return RadioQuery.from_source(source, t0, t1)

    def _build_advanced_query(self) -> "RadioQuery | None":
        t0, t1 = self._time_range()
        if t1 <= t0:
            self._set_status("End time must be after start time")
            return None
        raw = self.adv_raw.text().strip()
        self._current_source = None
        if raw:
            self._current_expect_spectrogram = False
            self._set_status("Searching (raw query)…")
            return RadioQuery(t_start=t0, t_end=t1, raw_attrs_text=raw,
                              expect_spectrogram=False)
        instrument = self.adv_instrument.currentText().strip() or None
        wl_min = _parse_float(self.adv_wl_min.text())
        wl_max = _parse_float(self.adv_wl_max.text())
        self._current_expect_spectrogram = True
        self._set_status(f"Searching {instrument or 'advanced'}…")
        return RadioQuery(t_start=t0, t_end=t1, instrument=instrument,
                          wavelength_min_mhz=wl_min, wavelength_max_mhz=wl_max,
                          expect_spectrogram=True)

    def _time_range(self):
        t0 = self.start_picker.dateTime().toPython().replace(tzinfo=timezone.utc)
        t1 = self.end_picker.dateTime().toPython().replace(tzinfo=timezone.utc)
        return t0, t1
```

Add a module-level helper near `_safe_basename`:

```python
def _parse_float(text: str) -> float | None:
    text = (text or "").strip()
    try:
        return float(text) if text else None
    except ValueError:
        return None
```

- [ ] **Step 5: Run the dock tests**

Run: `cd sciqlop_radio && python -m pytest sciqlop_radio/tests/test_dock.py -v`
Expected: PASS (all)

- [ ] **Step 6: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/dock.py sciqlop_radio/sciqlop_radio/tests/test_dock.py
git commit -m "feat(sciqlop_radio): advanced search group (instrument + wavelength + raw escape hatch)"
```

---

## Task 9: Full suite + live smoke test

**Files:** none (verification only)

- [ ] **Step 1: Run the whole plugin test suite**

Run: `cd sciqlop_radio && python -m pytest sciqlop_radio/tests/ -v -p no:cacheprovider`
Expected: PASS (no failures, no errors). If the upstream pytest-exit segfault appears, it happens *after* the summary line — confirm "passed" is printed first (see memory `feedback_sciqlopplots_exit_segfault`).

- [ ] **Step 2: Live smoke (network) — eCALLISTO columns + ILOFAR empty-state**

Run:
```bash
cd sciqlop_radio && python - <<'PY'
from datetime import datetime, timezone
from sciqlop_radio.query import RadioQuery
from sciqlop_radio.fetch import _do_search, _row_field

# eCALLISTO: rows carry Observatory + url columns
rows = _do_search(RadioQuery(t_start=datetime(2011,6,7,tzinfo=timezone.utc),
                             t_end=datetime(2011,6,7,8,tzinfo=timezone.utc),
                             instrument="eCALLISTO"))
print("eCALLISTO rows:", len(rows), "stations:",
      sorted({_row_field(r,"Observatory") for r in rows})[:5])

# ILOFAR empty range returns [] with no error (drives the empty-state hint)
empty = _do_search(RadioQuery(t_start=datetime(2017,9,6,tzinfo=timezone.utc),
                              t_end=datetime(2017,9,7,tzinfo=timezone.utc),
                              instrument="ILOFAR"))
print("ILOFAR empty-range rows:", len(empty))
PY
```
Expected: `eCALLISTO rows: 604 stations: ['ALASKA', 'ALMATY', 'BIR', ...]` and `ILOFAR empty-range rows: 0`.

- [ ] **Step 3: Commit any test-only fixups if needed**

```bash
git add -A && git commit -m "test(sciqlop_radio): radio dock Fido rework — full suite green" || echo "nothing to commit"
```

---

## Self-review notes

- **Spec coverage:** ILOFAR empty-state (Task 6 `_empty_results_message`), EOVSA remove+message (Task 3 + Task 5/8 guard), columns (Task 6), station/substring filter (Task 7), advanced instrument+wavelength+raw (Task 8), dep pin (Task 1). All spec sections mapped.
- **Spec deviations (intentional, documented above):** no `a.Observatory` attr → station filter is client-side only and `RadioQuery` drops the `observatory` field; the `getattr(row,"url")` latent bug is fixed in Task 4.
- **Type consistency:** `RadioQuery` fields (`t_start, t_end, instrument, wavelength_min_mhz, wavelength_max_mhz, raw_attrs_text, expect_spectrogram`) are used identically across `query.py`, `fetch.py`, and `dock.py`. `search(query)` signature is consistent across `RadioFetchService`, `_SearchTask`, the dock, and `FakeFetchService`. Table accessors (`_table_filename`, `_table_station`, `_selected_rows`, `results_table`) are defined in Task 6 and reused in Tasks 7–8.
