# Radio Live Per-Channel Streams — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the dock's auto-exposed radio products *live streams* keyed by physical channel (station + focus code), so dragging one to any time range re-fetches that channel's data — instead of the current frozen snapshot.

**Architecture:** A new pure `streams.py` derives a stream identity `(source_key, instrument, station, channel)` from a Fido row and yields a stable `vp_path` + the sunpy/radiospectra search attrs. `continuous.py`'s on-demand callback is generalized to filter rows by station + channel (client-side, with eCALLISTO additionally filtered server-side via `radiospectra.net.Observatory`) and by frequency signature, with the file cap removed. The dock threads the originating rows through fetch→plot and groups fetched results by stream identity, registering one streaming VP per channel; local files keep the static snapshot path.

**Tech Stack:** Python 3.12, sunpy 7.1.2 + radiospectra (main), speasy, PySide6, pytest/pytest-qt.

**Dev venv (for manual checks only):** `/home/jeandet/Documents/prog/SciQLop/.venv/bin/python`. Run the unit tests with the same interpreter: `cd sciqlop_radio && /home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest`.

---

## File Structure

- **Create** `sciqlop_radio/sciqlop_radio/streams.py` — pure stream-identity logic (no Qt, no SciQLop): `StreamRule`, `STREAM_RULES`, `rule_for`, `StreamIdentity`, `stream_identity_for_row`, `stream_fido_attrs`.
- **Create** `sciqlop_radio/sciqlop_radio/tests/test_streams.py` — unit tests for the above.
- **Modify** `sciqlop_radio/sciqlop_radio/continuous.py` — extend `ContinuousSource` with `station` / `channel_column` / `channel_value` / `freq_signature`; add the row + frequency filters to `_build_callback`; remove the `max_files` cap; add `make_stream_source`.
- **Modify** `sciqlop_radio/sciqlop_radio/tests/test_continuous.py` — add callback-filter tests with a fake Fido.
- **Modify** `sciqlop_radio/sciqlop_radio/dock.py` — thread rows through fetch→plot; replace `_plot_paths` with `_plot_items` that groups streamable results by stream identity (streaming VP) and local/raw results by frequency signature (static VP).
- **Modify** `sciqlop_radio/sciqlop_radio/tests/test_dock.py` — rewrite the curated-source test for streaming; add focus-code separation tests.

---

## Task 1: `streams.py` — stream identity & vp_path (pure)

**Files:**
- Create: `sciqlop_radio/sciqlop_radio/streams.py`
- Test: `sciqlop_radio/sciqlop_radio/tests/test_streams.py`

- [ ] **Step 1: Write the failing tests**

Create `sciqlop_radio/sciqlop_radio/tests/test_streams.py`:

```python
"""Tests for stream-identity derivation (pure, no Fido)."""
from __future__ import annotations

from sciqlop_radio.sources import SOURCES
from sciqlop_radio.streams import StreamIdentity, rule_for, stream_identity_for_row


class FakeRow(dict):
    """Dict-backed stand-in for a Fido QueryResponseRow (column access)."""


def _src(key):
    return next(s for s in SOURCES if s.key == key)


def test_ecallisto_identity_includes_station_and_focus_code():
    row = FakeRow({"Observatory": "BIR", "ID": "01",
                   "url": "http://a/BIR_20110607_120000_01.fit.gz"})
    ident = stream_identity_for_row(row, _src("ecallisto"))
    assert ident.station == "BIR"
    assert ident.channel == "01"
    assert ident.instrument == "eCALLISTO"
    assert ident.vp_path == "radio/ecallisto/BIR/01"


def test_ecallisto_focus_codes_get_distinct_paths():
    src = _src("ecallisto")
    r1 = FakeRow({"Observatory": "BIR", "ID": "01"})
    r2 = FakeRow({"Observatory": "BIR", "ID": "02"})
    assert (stream_identity_for_row(r1, src).vp_path
            != stream_identity_for_row(r2, src).vp_path)


def test_rstn_identity_is_per_station_no_channel():
    row = FakeRow({"Observatory": "learmonth", "ID": "x"})
    ident = stream_identity_for_row(row, _src("rstn"))
    assert ident.station == "learmonth"
    assert ident.channel == ""
    assert ident.vp_path == "radio/rstn/learmonth"


def test_ilofar_identity_reuses_continuous_single_stream_path():
    # ILOFAR is single-channel: no station/channel, so its path matches the
    # load-time continuous VP (radio/ilofar) and gets reused, not duplicated.
    row = FakeRow({"Observatory": "IE613", "ID": "00X"})
    ident = stream_identity_for_row(row, _src("ilofar"))
    assert ident.station == ""
    assert ident.channel == ""
    assert ident.vp_path == "radio/ilofar"


def test_station_with_space_is_sanitized():
    row = FakeRow({"Observatory": "Sagamore Hill"})
    ident = stream_identity_for_row(row, _src("rstn"))
    assert ident.vp_path == "radio/rstn/Sagamore_Hill"


def test_missing_columns_default_to_empty():
    row = FakeRow({})  # real rows can lack a column
    ident = stream_identity_for_row(row, _src("ecallisto"))
    assert ident.station == "" and ident.channel == ""
    assert ident.vp_path == "radio/ecallisto"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd sciqlop_radio && /home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_radio/tests/test_streams.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'sciqlop_radio.streams'`.

- [ ] **Step 3: Implement `streams.py`**

Create `sciqlop_radio/sciqlop_radio/streams.py`:

```python
"""Pure stream-identity logic for live per-channel radio products.

A *stream* is one physical signal chain: an instrument at a station running a
particular receiver/focus code. The dock turns each fetched search-result group
into one stream so dragging it to any time range re-fetches that channel.

No Qt, no SciQLop imports here. The only function that touches sunpy/radiospectra
(`stream_fido_attrs`) imports them lazily at call time.
"""
from __future__ import annotations

from dataclasses import dataclass

from .fetch import _row_field


@dataclass(frozen=True)
class StreamRule:
    """Per-instrument rules for how a stream is identified and searched.

    `per_station`   — this instrument has many stations; key streams by station.
    `server_side`   — also pass `radiospectra.net.Observatory` so the archive
                      filters by station (eCALLISTO has hundreds of stations;
                      RSTN has five, so we just filter client-side for it).
    `channel_column`— Fido column carrying the sub-station channel token
                      (eCALLISTO focus code lives in the `ID` column).
    """

    per_station: bool = False
    server_side: bool = False
    channel_column: str | None = None


# Keyed by RadioSource.key. Anything absent is single-channel (one stream).
STREAM_RULES: dict[str, StreamRule] = {
    "ecallisto": StreamRule(per_station=True, server_side=True, channel_column="ID"),
    "rstn": StreamRule(per_station=True, server_side=False, channel_column=None),
}

_DEFAULT_RULE = StreamRule()


def rule_for(source_key: str) -> StreamRule:
    return STREAM_RULES.get(source_key, _DEFAULT_RULE)


def _sanitize(token: str) -> str:
    return token.strip().replace("/", "_").replace(" ", "_")


@dataclass(frozen=True)
class StreamIdentity:
    source_key: str       # curated RadioSource.key, e.g. "ecallisto"
    instrument: str       # sunpy a.Instrument value, e.g. "eCALLISTO"
    station: str = ""     # Observatory column value ("" = single-station)
    channel: str = ""     # channel token, e.g. focus code ("" = single-channel)

    @property
    def vp_path(self) -> str:
        parts = ["radio", self.source_key]
        if self.station:
            parts.append(_sanitize(self.station))
        if self.channel:
            parts.append(_sanitize(self.channel))
        return "/".join(parts)


def stream_identity_for_row(row, source) -> StreamIdentity:
    """Derive the stream identity of a fetched Fido `row` under its `source`."""
    rule = rule_for(source.key)
    station = _row_field(row, "Observatory") if rule.per_station else ""
    channel = _row_field(row, rule.channel_column) if rule.channel_column else ""
    return StreamIdentity(
        source_key=source.key,
        instrument=source.fido_instrument or "",
        station=station,
        channel=channel,
    )


def stream_fido_attrs(identity: StreamIdentity) -> list:
    """sunpy/radiospectra attrs scoping this stream's search (excluding a.Time).

    Imports sunpy/radiospectra lazily — only fires when the stream callback runs.
    Uses `radiospectra.net.Observatory` (NOT `sunpy.net.attrs.Observatory`, which
    is absent in sunpy 7.1.2) for server-side station filtering where supported.
    """
    from sunpy.net import attrs as a  # type: ignore

    attrs: list = []
    if identity.instrument:
        attrs.append(a.Instrument(identity.instrument))
    rule = rule_for(identity.source_key)
    if rule.server_side and identity.station:
        from radiospectra.net import Observatory  # type: ignore
        attrs.append(Observatory(identity.station))
    return attrs
```

- [ ] **Step 4: Run to verify pass**

Run: `cd sciqlop_radio && /home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_radio/tests/test_streams.py -q`
Expected: PASS (7 passed).

- [ ] **Step 5: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/streams.py sciqlop_radio/sciqlop_radio/tests/test_streams.py
git commit -m "feat(sciqlop_radio): pure stream-identity (station+focus → vp_path)"
```

---

## Task 2: `streams.py` — server-side `Observatory` attr

**Files:**
- Test: `sciqlop_radio/sciqlop_radio/tests/test_streams.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `sciqlop_radio/sciqlop_radio/tests/test_streams.py`:

```python
def test_ecallisto_attrs_include_server_side_observatory():
    from sciqlop_radio.streams import StreamIdentity, stream_fido_attrs
    ident = StreamIdentity(source_key="ecallisto", instrument="eCALLISTO",
                           station="BIR", channel="01")
    names = [type(a).__name__ for a in stream_fido_attrs(ident)]
    assert "Instrument" in names
    assert "Observatory" in names  # radiospectra's, server-side station filter


def test_rstn_attrs_have_no_observatory():
    from sciqlop_radio.streams import StreamIdentity, stream_fido_attrs
    ident = StreamIdentity(source_key="rstn", instrument="RSTN",
                           station="learmonth")
    names = [type(a).__name__ for a in stream_fido_attrs(ident)]
    assert "Instrument" in names
    assert "Observatory" not in names  # RSTN filtered client-side only
```

- [ ] **Step 2: Run to verify pass**

`stream_fido_attrs` already exists from Task 1, so these should pass immediately.
Run: `cd sciqlop_radio && /home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_radio/tests/test_streams.py -q`
Expected: PASS (9 passed). If `radiospectra.net.Observatory` import fails, STOP — the whole design depends on it; re-verify the import path on the dev venv.

- [ ] **Step 3: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/tests/test_streams.py
git commit -m "test(sciqlop_radio): assert server-side Observatory attr per instrument"
```

---

## Task 3: `continuous.py` — channel/frequency filters, no cap

**Files:**
- Modify: `sciqlop_radio/sciqlop_radio/continuous.py`
- Test: `sciqlop_radio/sciqlop_radio/tests/test_continuous.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `sciqlop_radio/sciqlop_radio/tests/test_continuous.py`:

```python
# ---------------------------------------------------------------------------
# streaming callback: station/channel/frequency filters + no cap
# ---------------------------------------------------------------------------


def _ecallisto_source(**over):
    from sciqlop_radio.continuous import ContinuousSource
    base = dict(vp_path="radio/ecallisto/BIR/01", label="BIR/01",
                attrs_factory=lambda: [], station="BIR",
                channel_column="ID", channel_value="01")
    base.update(over)
    return ContinuousSource(**base)


def test_stream_callback_filters_rows_by_station_and_channel(monkeypatch, tmp_path):
    from sciqlop_radio import continuous as C
    rows = [
        {"Observatory": "BIR", "ID": "01", "url": "http://a/BIR_x_01.fit.gz"},
        {"Observatory": "BIR", "ID": "02", "url": "http://a/BIR_x_02.fit.gz"},
        {"Observatory": "ALMATY", "ID": "01", "url": "http://a/ALMATY_x_01.fit.gz"},
    ]
    captured = {}
    monkeypatch.setattr(C, "_fido_search", lambda t0, t1, src: [dict(r) for r in rows])
    monkeypatch.setattr(C, "_fetch_paths",
                        lambda rws, cd: (captured.__setitem__("rows", list(rws)) or []))
    cb = C._build_callback(_ecallisto_source(), tmp_path, lambda p: None)
    cb(0.0, 100.0)
    assert len(captured["rows"]) == 1
    assert captured["rows"][0]["Observatory"] == "BIR"
    assert captured["rows"][0]["ID"] == "01"


def test_stream_callback_drops_files_off_frequency_signature(
        monkeypatch, tmp_path, speasy_variable_factory):
    from sciqlop_radio import continuous as C
    from sciqlop_radio.plot import frequency_signature
    v_good = speasy_variable_factory("2024-01-01T00:00:00", 3, 4)
    v_bad = speasy_variable_factory("2024-01-01T00:01:00", 3, 5)
    sig = frequency_signature(v_good)
    rows = [{"Observatory": "BIR", "ID": "01", "url": "http://a/g.fit.gz"},
            {"Observatory": "BIR", "ID": "01", "url": "http://a/b.fit.gz"}]
    monkeypatch.setattr(C, "_fido_search", lambda *a: [dict(r) for r in rows])
    monkeypatch.setattr(C, "_fetch_paths",
                        lambda rws, cd: [tmp_path / "g.fit.gz", tmp_path / "b.fit.gz"])
    mapping = {"g.fit.gz": v_good, "b.fit.gz": v_bad}
    src = _ecallisto_source(freq_signature=sig)
    out = C._build_callback(src, tmp_path, lambda p: mapping[p.name])(0.0, 100.0)
    assert out is not None
    assert out.values.shape[1] == 4  # only the matching-grid file survives


def test_stream_callback_has_no_file_cap(monkeypatch, tmp_path, speasy_variable_factory):
    from sciqlop_radio import continuous as C
    v = speasy_variable_factory("2024-01-01T00:00:00", 2, 3)
    rows = [{"Observatory": "BIR", "ID": "01", "url": f"http://a/{i}.fit.gz"}
            for i in range(50)]
    monkeypatch.setattr(C, "_fido_search", lambda *a: [dict(r) for r in rows])
    monkeypatch.setattr(C, "_fetch_paths",
                        lambda rws, cd: [tmp_path / f"{i}.fit.gz" for i in range(len(rws))])
    out = C._build_callback(_ecallisto_source(), tmp_path, lambda p: v)(0.0, 100.0)
    assert out is not None
    assert out.values.shape[0] == 50 * 2  # all 50 files concatenated, not capped


def test_stream_callback_returns_none_on_empty_window(monkeypatch, tmp_path):
    from sciqlop_radio import continuous as C
    monkeypatch.setattr(C, "_fido_search", lambda *a: [])
    out = C._build_callback(_ecallisto_source(), tmp_path, lambda p: None)(0.0, 100.0)
    assert out is None
```

- [ ] **Step 2: Run to verify failure**

Run: `cd sciqlop_radio && /home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_radio/tests/test_continuous.py -q`
Expected: FAIL — `ContinuousSource.__init__` rejects `station`/`channel_column`/`channel_value`/`freq_signature` (unexpected keyword args), and the filter tests fail.

- [ ] **Step 3: Extend `ContinuousSource`**

In `sciqlop_radio/sciqlop_radio/continuous.py`, replace the `ContinuousSource` dataclass (currently ending at `static_meta: dict = field(default_factory=dict)`) by adding the four fields:

```python
@dataclass(frozen=True)
class ContinuousSource:
    """One entry in the continuous-source registry. (docstring unchanged above)"""

    vp_path: str
    label: str
    attrs_factory: Callable[[], list]
    max_files: int = MAX_FILES_PER_CALL
    static_meta: dict = field(default_factory=dict)
    # Per-channel stream filters (empty/None = whole-source, e.g. EOVSA/ILOFAR):
    station: str = ""                       # client-side Observatory-column filter
    channel_column: str | None = None       # Fido column for the channel token
    channel_value: str = ""                 # required value in channel_column
    freq_signature: tuple | None = None     # post-parse frequency-grid filter
```

- [ ] **Step 4: Add filters to `_build_callback`, remove the cap**

In `_build_callback` (`continuous.py`), replace the body from the `if not rows:` check through the `paths = _fetch_paths(...)` line. Specifically:

Replace this block:

```python
        if not rows:
            return None

        # Cap: if the user's visible range covers more files than we'll
        # download in one go, return None and tell them to zoom in. Silent
        # truncation would only show data at one end of the range — confusing.
        if len(rows) > source.max_files:
            log.warning(
                "continuous(%s): %d rows for [%s..%s] exceeds max_files=%d. "
                "Zoom in to a window that covers fewer files (or raise "
                "ContinuousSource.max_files).",
                source.vp_path, len(rows), t0.isoformat(), t1.isoformat(),
                source.max_files,
            )
            return None

        t_fetch = time.monotonic()
        paths = _fetch_paths(rows, cache_dir)
```

with:

```python
        rows = _filter_rows_for_stream(rows, source)
        if not rows:
            return None

        t_fetch = time.monotonic()
        paths = _fetch_paths(rows, cache_dir)
```

Then, after the parse loop builds `variables` (just before `out = _concat_spectrograms(variables)`), insert the frequency filter:

```python
        if source.freq_signature is not None:
            variables = [v for v in variables
                         if _frequency_signature_safe(v) == source.freq_signature]
```

- [ ] **Step 5: Add the filter helpers**

Add near the top of `continuous.py` (after the imports / `MAX_FILES_PER_CALL`):

```python
from .fetch import _row_field


def _filter_rows_for_stream(rows: list, source: "ContinuousSource") -> list:
    """Client-side station + channel filter. Server-side station filtering
    (radiospectra.net.Observatory) narrows eCALLISTO already; this guarantees
    correctness for every instrument and never folds two channels together."""
    if source.station:
        rows = [r for r in rows if _row_field(r, "Observatory") == source.station]
    if source.channel_column:
        rows = [r for r in rows
                if _row_field(r, source.channel_column) == source.channel_value]
    return rows


def _frequency_signature_safe(variable):
    from .plot import frequency_signature
    try:
        return frequency_signature(variable)
    except Exception:  # noqa: BLE001 — unkeyable variable never matches
        return None
```

- [ ] **Step 6: Add `make_stream_source` factory**

Add to `continuous.py` (near `register_continuous_products`):

```python
def make_stream_source(identity, freq_signature) -> ContinuousSource:
    """Build a per-channel streaming source from a dock-fetched group's identity
    (`sciqlop_radio.streams.StreamIdentity`) and its reference frequency grid."""
    from .streams import rule_for, stream_fido_attrs

    rule = rule_for(identity.source_key)
    label = " ".join(p for p in (identity.instrument, identity.station,
                                 identity.channel) if p)
    return ContinuousSource(
        vp_path=identity.vp_path,
        label=label or identity.source_key,
        attrs_factory=lambda: stream_fido_attrs(identity),
        station=identity.station if rule.per_station else "",
        channel_column=rule.channel_column,
        channel_value=identity.channel,
        freq_signature=freq_signature,
    )
```

- [ ] **Step 7: Run to verify pass**

Run: `cd sciqlop_radio && /home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_radio/tests/test_continuous.py -q`
Expected: PASS (all existing + 4 new). The pre-existing registry/concat/static_meta tests must still pass (the cap removal and new optional fields don't change EOVSA/ILOFAR defaults).

- [ ] **Step 8: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/continuous.py sciqlop_radio/sciqlop_radio/tests/test_continuous.py
git commit -m "feat(sciqlop_radio): per-channel stream filters in continuous callback; drop file cap"
```

---

## Task 4: dock — thread rows through fetch→plot, group by stream identity

**Files:**
- Modify: `sciqlop_radio/sciqlop_radio/dock.py`
- Test: `sciqlop_radio/sciqlop_radio/tests/test_dock.py`

- [ ] **Step 1: Write/rewrite the failing tests**

In `sciqlop_radio/sciqlop_radio/tests/test_dock.py`, add a callisto-row helper next to `_erow`:

```python
def _crow(url, observatory, idcode, start=""):
    return FakeRow({"url": url, "Observatory": observatory, "ID": idcode,
                    "Start Time": start})
```

Replace `test_curated_source_fetched_files_use_static_vp` with:

```python
def test_curated_source_fetched_files_use_streaming_vp(dock, qtbot, tmp_path, monkeypatch):
    """A fetched eCALLISTO file registers a live stream keyed by station+focus,
    at radio/ecallisto/<station>/<focus> — not a per-file static snapshot."""
    import types as _t
    w, svc = dock
    for i in range(w.source_combo.count()):
        if w.source_combo.itemData(i).key == "ecallisto":
            w.source_combo.setCurrentIndex(i)
            break
    w.fetch_button.click()  # sets _current_source = eCALLISTO

    fn = "AUSTRALIA-ASSA_20110607_120000_01.fit.gz"
    p = tmp_path / fn
    p.write_bytes(b"\x00")
    w._pending_rows = [_crow(f"http://a/{fn}", "AUSTRALIA-ASSA", "01")]
    monkeypatch.setattr("sciqlop_radio.dock._open_and_convert",
                        lambda path: _t.SimpleNamespace(name=path.name))
    monkeypatch.setattr("sciqlop_radio.dock.frequency_signature", lambda v: ("ecal",))
    panel, vp_calls = _install_fake_user_api(monkeypatch)

    svc.fetchCompleted.emit([p], [])
    qtbot.wait(50)

    assert len(vp_calls) == 1
    assert vp_calls[0][0] == "radio/ecallisto/AUSTRALIA-ASSA/01"
    assert panel.plot.call_count == 1
```

Add two new tests asserting the focus-code guarantee:

```python
def test_ecallisto_focus_codes_stream_separately(dock, qtbot, tmp_path, monkeypatch):
    """Two focus codes (_01/_02) at the same station/time → two distinct streams."""
    import types as _t
    w, svc = dock
    for i in range(w.source_combo.count()):
        if w.source_combo.itemData(i).key == "ecallisto":
            w.source_combo.setCurrentIndex(i)
            break
    w.fetch_button.click()

    f1 = "BIR_20110607_120000_01.fit.gz"
    f2 = "BIR_20110607_120000_02.fit.gz"
    p1 = tmp_path / f1; p1.write_bytes(b"\x00")
    p2 = tmp_path / f2; p2.write_bytes(b"\x00")
    w._pending_rows = [_crow(f"http://a/{f1}", "BIR", "01"),
                       _crow(f"http://a/{f2}", "BIR", "02")]
    monkeypatch.setattr("sciqlop_radio.dock._open_and_convert",
                        lambda path: _t.SimpleNamespace(name=path.name))
    monkeypatch.setattr("sciqlop_radio.dock.frequency_signature", lambda v: (v.name,))
    panel, vp_calls = _install_fake_user_api(monkeypatch)

    svc.fetchCompleted.emit([p1, p2], [])
    qtbot.wait(50)

    paths = sorted(c[0] for c in vp_calls)
    assert paths == ["radio/ecallisto/BIR/01", "radio/ecallisto/BIR/02"]
    assert panel.plot.call_count == 2


def test_ecallisto_same_station_focus_merge_into_one_stream(dock, qtbot, tmp_path, monkeypatch):
    """Same station + focus at different times → one stream node, one plot."""
    import types as _t
    w, svc = dock
    for i in range(w.source_combo.count()):
        if w.source_combo.itemData(i).key == "ecallisto":
            w.source_combo.setCurrentIndex(i)
            break
    w.fetch_button.click()

    f1 = "BIR_20110607_120000_01.fit.gz"
    f2 = "BIR_20110607_121500_01.fit.gz"
    p1 = tmp_path / f1; p1.write_bytes(b"\x00")
    p2 = tmp_path / f2; p2.write_bytes(b"\x00")
    w._pending_rows = [_crow(f"http://a/{f1}", "BIR", "01"),
                       _crow(f"http://a/{f2}", "BIR", "01")]
    monkeypatch.setattr("sciqlop_radio.dock._open_and_convert",
                        lambda path: _t.SimpleNamespace(name=path.name))
    monkeypatch.setattr("sciqlop_radio.dock.frequency_signature", lambda v: ("ecal",))
    panel, vp_calls = _install_fake_user_api(monkeypatch)

    svc.fetchCompleted.emit([p1, p2], [])
    qtbot.wait(50)

    assert [c[0] for c in vp_calls] == ["radio/ecallisto/BIR/01"]
    assert panel.plot.call_count == 1
```

Note: `test_local_file_uses_static_vp`, `test_same_frequency_files_merge_into_one_plot`,
`test_different_frequency_files_plot_separately`, and
`test_plot_selected_registers_virtual_product_and_plots_on_panel` keep working
unchanged — they never set `_pending_rows`, so each path maps to `row=None` and
falls through the unchanged static branch.

- [ ] **Step 2: Run to verify failure**

Run: `cd sciqlop_radio && /home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_radio/tests/test_dock.py -q`
Expected: FAIL — `RadioSpectraDock` has no `_pending_rows`; new streaming paths not produced.

- [ ] **Step 3: Add `_pending_rows` and thread rows through fetch**

In `dock.py` `__init__`, after `self._virtual_products = ...` add:

```python
        self._pending_rows: list = []
```

Replace `_on_plot_selected_clicked`:

```python
    def _on_plot_selected_clicked(self):
        rows = self._selected_rows()
        if not rows:
            self._set_status("No rows selected")
            return
        self._pending_rows = list(rows)
        self._set_status(f"Fetching {len(rows)} file(s)…")
        self._svc.fetch(rows)
```

Replace `_on_open_local_clicked`'s plotting call so local files carry no row:

```python
    def _on_open_local_clicked(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open local radio file", "", "Radio data (*.cdf *.fits *.fit *.fit.gz *.dat);;All files (*)"
        )
        if paths:
            self._plot_items([(Path(p), None) for p in paths],
                             source=None, static_key="local")
```

Replace `_on_fetch_completed`:

```python
    def _on_fetch_completed(self, ok: list, failed: list):
        # Correlate each downloaded path back to the Fido row it came from, so
        # plot-time grouping can key streams on (station, focus). Cache paths are
        # named after the row's url basename (see fetch._cache_path_for).
        source = self._current_source
        by_name = {_row_basename(r): r for r in self._pending_rows}
        items = [(p, by_name.get(p.name)) for p in ok]
        static_key = source.key if source is not None else "advanced"
        self._plot_items(items, source=source, static_key=static_key)
        msg = f"Downloaded {len(ok)} file(s)"
        if failed:
            msg += f"; {len(failed)} failed"
        self._set_status(msg)
```

- [ ] **Step 4: Add imports + `_row_basename`**

At the top of `dock.py`, extend the `.fetch` import and add the streams import:

```python
from .fetch import RadioFetchService, _row_field, _row_url
from .streams import stream_identity_for_row
from .continuous import make_stream_source, _build_callback
```

Add a module-level helper (near `_group_vp_path`):

```python
def _row_basename(row) -> str:
    url = _row_url(row)
    return url.rsplit("/", 1)[-1] if url else ""
```

- [ ] **Step 5: Replace `_plot_paths` with `_plot_items`**

Replace the whole `_plot_paths` method with `_plot_items` plus helpers below.
`_plot_items` parses files, groups streamable rows by stream identity (streaming
callback) and everything else by frequency signature (static callback), then
registers + plots each group on one shared panel.

```python
    def _plot_items(self, items, *, source, static_key):
        """items: list[(Path, row_or_None)]. Streamable fetched rows become live
        per-channel streams; local/raw items keep the static snapshot path."""
        try:
            from SciQLop.core import TimeRange
            from SciQLop.user_api.plot import create_plot_panel
            from SciQLop.user_api.virtual_products import (
                create_virtual_product, VirtualProductType,
            )
        except ImportError as exc:
            self._set_status(f"SciQLop user-API unavailable: {exc}")
            return

        parsed, errors = self._parse_items(items)
        groups = self._group_items(parsed, source, static_key)

        panel = None
        plotted = 0
        files_plotted = 0
        t_min: float | None = None
        t_max: float | None = None
        for g in groups:
            if g.vp_path not in self._virtual_products:
                try:
                    vp = create_virtual_product(
                        g.vp_path, g.callback, VirtualProductType.Spectrogram,
                    )
                    self._virtual_products[g.vp_path] = vp
                except Exception as e:  # noqa: BLE001
                    errors.append((g.first_name,
                                   f"create_virtual_product: {type(e).__name__}: {e}"))
                    continue
            if panel is None:
                panel = create_plot_panel()
            try:
                panel.plot(self._virtual_products[g.vp_path])
                plotted += 1
                files_plotted += g.n_files
                if g.t0 is not None:
                    t_min = g.t0 if t_min is None else min(t_min, g.t0)
                if g.t1 is not None:
                    t_max = g.t1 if t_max is None else max(t_max, g.t1)
            except Exception as e:  # noqa: BLE001
                errors.append((g.first_name, f"plot: {type(e).__name__}: {e}"))

        if panel is not None and t_min is not None and t_max is not None:
            try:
                panel.time_range = TimeRange(t_min, t_max)
            except Exception as e:  # noqa: BLE001
                errors.append(("<panel time range>",
                               f"set_time_range: {type(e).__name__}: {e}"))

        self._report_plot_result(errors, plotted, files_plotted, len(items))

    def _parse_items(self, items):
        parsed: list = []
        errors: list[tuple[str, str]] = []
        for path, row in items:
            try:
                parsed.append((path, row, _open_and_convert(path)))
            except RadioPlotError as e:
                errors.append((path.name, str(e)))
            except Exception as e:  # noqa: BLE001
                errors.append((path.name, f"{type(e).__name__}: {e}"))
        return parsed, errors

    def _group_items(self, parsed, source, static_key):
        streamable = source is not None and bool(source.fido_instrument)
        buckets: dict = {}
        order: list = []
        for path, row, var in parsed:
            if streamable and row is not None:
                key = ("stream", stream_identity_for_row(row, source).vp_path)
            else:
                key = ("static", _safe_freq_sig(var))
            if key not in buckets:
                buckets[key] = []
                order.append(key)
            buckets[key].append((path, row, var))
        return [self._finalize_group(key, buckets[key], source, static_key)
                for key in order]

    def _finalize_group(self, key, members, source, static_key):
        paths = [p for p, _, _ in members]
        variables = [v for _, _, v in members]
        t0, t1 = _members_time_bounds(variables)
        if key[0] == "stream":
            row = members[0][1]
            identity = stream_identity_for_row(row, source)
            stream_src = make_stream_source(identity, _safe_freq_sig(variables[0]))
            callback = _build_callback(stream_src, self._cache_dir, _open_and_convert)
            return _PlotGroup(vp_path=identity.vp_path, callback=callback,
                              first_name=paths[0].name, n_files=len(paths),
                              t0=t0, t1=t1)
        merged = (concat_variables_along_time(variables)
                  if len(variables) > 1 else variables[0])
        return _PlotGroup(vp_path=_group_vp_path(static_key, paths),
                          callback=_build_static_callback(merged),
                          first_name=paths[0].name, n_files=len(paths),
                          t0=t0, t1=t1)

    def _report_plot_result(self, errors, plotted, files_plotted, n_items):
        if errors and plotted == 0:
            detail = "\n\n".join(f"{name}:\n  {err}" for name, err in errors)
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Could not plot")
            box.setText(f"None of the {n_items} file(s) could be plotted.")
            box.setDetailedText(detail)
            box.setTextInteractionFlags(Qt.TextSelectableByMouse)
            box.exec()
            self._set_status(f"Plot failed for {len(errors)} file(s); see dialog for details")
        elif errors:
            self._set_status(
                f"Plotted {files_plotted} file(s) in {plotted} plot(s); "
                f"{len(errors)} failed — last: {errors[-1][1][:120]}"
            )
        elif plotted:
            self._set_status(f"Plotted {files_plotted} file(s) in {plotted} plot(s)")
```

- [ ] **Step 6: Add the `_PlotGroup` record + small helpers**

Add at module level in `dock.py` (near the other module helpers at the bottom):

```python
from dataclasses import dataclass


@dataclass
class _PlotGroup:
    vp_path: str
    callback: object
    first_name: str
    n_files: int
    t0: float | None
    t1: float | None


def _safe_freq_sig(variable):
    try:
        return frequency_signature(variable)
    except Exception:  # noqa: BLE001 — unkeyable → its own static group
        return ("unkeyed", id(variable))


def _members_time_bounds(variables):
    lo = hi = None
    for v in variables:
        a, b = _variable_time_bounds(v)
        if a is not None:
            lo = a if lo is None else min(lo, a)
        if b is not None:
            hi = b if hi is None else max(hi, b)
    return lo, hi
```

Keep the existing `_group_vp_path`, `_build_static_callback`, and
`_variable_time_bounds` functions as-is.

- [ ] **Step 7: Run to verify pass**

Run: `cd sciqlop_radio && /home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_radio/tests/test_dock.py -q`
Expected: PASS (all dock tests, including the 3 new streaming tests).

- [ ] **Step 8: Run the full plugin suite**

Run: `cd sciqlop_radio && /home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest -q -m "not live"`
Expected: PASS (all non-live tests; ~129+).

- [ ] **Step 9: Commit**

```bash
git add sciqlop_radio/sciqlop_radio/dock.py sciqlop_radio/sciqlop_radio/tests/test_dock.py
git commit -m "feat(sciqlop_radio): auto-expose fetched results as live per-channel streams"
```

---

## Task 5: live integration test + dev-venv manual verification

**Files:**
- Test: `sciqlop_radio/sciqlop_radio/tests/test_continuous.py` (append a live test)

- [ ] **Step 1: Add a live integration test**

Append to `sciqlop_radio/sciqlop_radio/tests/test_continuous.py`:

```python
@pytest.mark.live
def test_live_ecallisto_stream_returns_data(tmp_path):
    """Real Fido: a per-station eCALLISTO stream over a known window returns a
    non-empty spectrogram. Confirms server-side net.Observatory + the callback
    chain end-to-end. Network-gated; run with `-m live`."""
    from datetime import datetime, timezone
    from sciqlop_radio.continuous import make_stream_source, _build_callback
    from sciqlop_radio.dock import _open_and_convert
    from sciqlop_radio.streams import StreamIdentity

    ident = StreamIdentity(source_key="ecallisto", instrument="eCALLISTO",
                           station="BIR", channel="01")
    src = make_stream_source(ident, freq_signature=None)
    cb = _build_callback(src, tmp_path, _open_and_convert)
    t0 = datetime(2011, 6, 7, 6, 0, tzinfo=timezone.utc).timestamp()
    t1 = datetime(2011, 6, 7, 7, 0, tzinfo=timezone.utc).timestamp()
    out = cb(t0, t1)
    assert out is not None
    assert out.values.shape[0] > 0
    assert out.values.shape[1] > 0
```

- [ ] **Step 2: Run the live test**

Run: `cd sciqlop_radio && /home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest sciqlop_radio/tests/test_continuous.py -q -m live -k live_ecallisto`
Expected: PASS (downloads a few BIR/01 FITS files for 2011-06-07 06:00–07:00 and returns a populated variable). If the eCALLISTO archive is unreachable, note it and move on — do not delete the test.

- [ ] **Step 3: Manual dev-venv verification of the two risk points**

Run this one-off check (not a committed test) to confirm (a) `net.Observatory`
round-trips as a real server-side filter and (b) the callback returning `None`
for an empty window is the same shape the shipped EOVSA/ILOFAR VPs already use:

```bash
/home/jeandet/Documents/prog/SciQLop/.venv/bin/python - <<'PY'
from datetime import datetime, timezone
from sciqlop_radio.continuous import make_stream_source, _build_callback
from sciqlop_radio.dock import _open_and_convert
from sciqlop_radio.streams import StreamIdentity, stream_fido_attrs

ident = StreamIdentity("ecallisto", "eCALLISTO", "BIR", "01")
print("attrs:", [type(a).__name__ for a in stream_fido_attrs(ident)])

cb = _build_callback(make_stream_source(ident, None), __import__("pathlib").Path("/tmp/radio_dev_cache"), _open_and_convert)
empty = cb(datetime(1990,1,1,tzinfo=timezone.utc).timestamp(),
           datetime(1990,1,2,tzinfo=timezone.utc).timestamp())
print("empty-window returns:", empty)   # expect None, no crash
PY
```

Expected: `attrs: ['Instrument', 'Observatory']` and `empty-window returns: None`.

If you have a running SciQLop and want to confirm `None` does not crash a panel
(the memory's `x, y, z = []` worry), load the plugin, fetch eCALLISTO BIR for
`2011-06-07`, plot, then drag the resulting `radio/ecallisto/BIR/01` node to an
empty year. It should clear/blank, not raise. Only if it genuinely raises do we
revisit the empty-return contract — and surface it to the user.

- [ ] **Step 4: Final full suite + commit**

Run: `cd sciqlop_radio && /home/jeandet/Documents/prog/SciQLop/.venv/bin/python -m pytest -q -m "not live"`
Expected: PASS.

```bash
git add sciqlop_radio/sciqlop_radio/tests/test_continuous.py
git commit -m "test(sciqlop_radio): live per-station eCALLISTO stream integration test"
```

---

## Self-Review

**Spec coverage:**
- Stream identity `(instrument, station, channel)` + freq backstop → Task 1 (`StreamIdentity`), Task 3 (`freq_signature` filter). ✓
- Server-side `radiospectra.net.Observatory`, client-side channel filter → Task 1/2 (`stream_fido_attrs`), Task 3 (`_filter_rows_for_stream`). ✓
- Stable `radio/<instrument>/<station>/<channel>` path, reused on re-plot → Task 1 (`vp_path`), Task 4 (`_virtual_products` reuse guard). ✓
- No file cap → Task 3 (cap block removed; `test_stream_callback_has_no_file_cap`). ✓
- Empty window → `None` → Task 3 (`test_stream_callback_returns_none_on_empty_window`), Task 5 (manual verify it doesn't crash). ✓
- Replace static for fetched results; local stays static → Task 4 (`_group_items` streamable branch vs static branch; `test_local_file_uses_static_vp` retained). ✓
- `_01`/`_02` never merge → Task 1 (`test_ecallisto_focus_codes_get_distinct_paths`), Task 4 (`test_ecallisto_focus_codes_stream_separately`). ✓
- Multi-station lands on one shared panel as stacked subplots → Task 4 (`_plot_items` single `panel`, `panel.plot` per group). ✓
- Rows reach `_plot_items` → Task 4 (`_pending_rows` + `_row_basename` correlation). ✓
- ILOFAR fetched reuses the load-time continuous VP → Task 1 (`test_ilofar_identity_reuses_continuous_single_stream_path`), Task 4 (reuse guard). ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type consistency:** `StreamIdentity(source_key, instrument, station, channel)` and `.vp_path` used identically in Tasks 1/3/4. `ContinuousSource` new fields (`station`, `channel_column`, `channel_value`, `freq_signature`) match between `make_stream_source`, `_build_callback`, and the tests. `_PlotGroup(vp_path, callback, first_name, n_files, t0, t1)` consumed exactly as produced. `_build_callback`/`make_stream_source` import names match continuous.py. ✓
