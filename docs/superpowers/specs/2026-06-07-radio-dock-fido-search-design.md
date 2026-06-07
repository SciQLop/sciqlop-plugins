# Radio dock — fix ILOFAR UX, remove EOVSA, columns + advanced/raw Fido search

Date: 2026-06-07
Plugin: `sciqlop_radio`

## Problem

Live testing against the installed stack (sunpy 7.1.2, radiospectra
0.6.2.dev26) revealed that the two "broken" sources have **different** root
causes, and the search UI is hard to use for high-volume sources:

1. **ILOFAR is not broken.** A query for 2021-09 returns 10 rows, no errors.
   I-LOFAR mode-357 simply has *sparse* coverage (campaign days only), so
   most date ranges return zero rows with no error. The dock shows
   "Found 0 spectrogram file(s)", indistinguishable from a real failure.
   → **UX problem**, not a fetch bug.

2. **EOVSA is broken upstream, permanently.** radiospectra's `EOVSAClient`
   crawls `https://ovsa.njit.edu/fits/synoptic/…`, which now returns Apache
   **403 on the entire `/fits/` tree** (directory access disabled). EOVSA
   rebuilt their site: `/browser/` → 302 → `/eovsadata/`, backed by
   `/eovsadata/api/*.php`. The FITS download endpoint returns
   `{"ok":false,"error":"registration_required"}` (HTTP 401) — downloads now
   require **account registration (email + captcha + session cookie)**.
   `coverage.php`/`availability.php` are public, but the FITS themselves are
   not anonymously downloadable. radiospectra itself is broken here and
   cannot be fixed without implementing the registration/session flow.

3. **eCALLISTO floods the UI.** A single day returns 600+ rows across dozens
   of ground stations; the current `QListWidget` shows only filenames with no
   columns, no sorting, and no way to filter by station.

4. **Stale dependency pin.** `pyproject.toml` pins `sunpy[net]>=6,<7` +
   `radiospectra>=0.6,<1.0` with a comment claiming sunpy≥7 returns zero
   rows. That is only true for the *released* radiospectra 0.6.1 (legacy
   `Scraper` signature). radiospectra `main` (0.6.2.dev) uses
   `Scraper(format=…)`, which **requires** sunpy≥7 — and that combo is what
   is actually installed and working (eCALLISTO: 604 rows, ILOFAR: 10 rows).
   The pin and the tested reality diverge.

## Goals

- Make ILOFAR's empty results legible (the real "fix").
- Stop presenting EOVSA as a working Fido source; tell the user why and how
  to get the data manually.
- Make the Fido search dock usable for high-volume sources (columns +
  filtering), with an advanced mode that lets power users reach any
  radiospectra Fido client and, as an escape hatch, run a raw Fido query.
- Align the dependency pin with the installed, tested stack.

## Non-goals

- Implementing EOVSA's registration/captcha/session flow (out of scope;
  fragile, dubious vs. their ToS).
- A general sunpy Fido query-builder UI for arbitrary clients beyond a raw
  text escape hatch.
- Coverage-API integration for EOVSA date suggestions (deferred).

## Design

### 1. Data model — new `query.py`

A single pydantic model is what the fetch layer consumes, replacing the
`(source, t_start, t_end)` triple threaded through `fetch`/`dock`:

```python
class RadioQuery(BaseModel):
    t_start: datetime
    t_end: datetime
    instrument: str | None = None          # a.Instrument value
    wavelength_min_mhz: float | None = None
    wavelength_max_mhz: float | None = None
    observatory: str | None = None         # eCALLISTO station, etc.
    raw_attrs_text: str | None = None      # escape hatch; overrides the above
    expect_spectrogram: bool = True        # False for raw → keep all rows

    @classmethod
    def from_source(cls, source, t_start, t_end) -> "RadioQuery": ...
```

`expect_spectrogram` is `True` for the curated/advanced-structured paths and
`False` for the raw escape hatch (so raw results are not silently dropped by
the non-spectrogram filter).

### 2. `fetch.py`

- `_build_attrs(query) -> list` — `a.Time` always; append `a.Instrument`,
  `a.Wavelength(min, max)`, `a.Observatory` when present on the query.
- Raw path: `query.raw_attrs_text` is `eval`'d in a **restricted namespace**
  containing only the sunpy attrs module and common attr names
  (`{"a": attrs, "Time": a.Time, "Instrument": a.Instrument,
  "Wavelength": a.Wavelength, "Observatory": a.Observatory, ...}`) with
  `{"__builtins__": {}}`. Failures raise a clear `RuntimeError`. Rationale:
  it is the user's own desktop tool and they can already run arbitrary Python
  via SciQLop's console; the restricted namespace blocks accidental footguns,
  not a determined adversary.
- `_run_fido_search(attrs) -> list` — the actual `Fido.search`, row
  extraction, and the existing "errors attached but zero rows → raise"
  guard (preserves the `test_do_search_surfaces_response_errors` contract).
- `_do_search(query: RadioQuery) -> list` — chooses raw vs. structured attr
  building, then calls `_run_fido_search`.
- `RadioFetchService.search(query: RadioQuery)` — cache key derived from the
  query's normalized fields (including `raw_attrs_text`).

### 3. `sources.py`

- `RadioSource` gains:
  - `unavailable_reason: str | None = None`
  - `example_range: str = ""` (human hint for the empty-state message)
- **EOVSA stays in the list but is marked unavailable** with
  `unavailable_reason="EOVSA spectrogram FITS now require registration at
  ovsa.njit.edu/eovsadata — download a .fts there and use 'Open local…'."`
  and `fido_instrument=None`. Selecting it shows the reason and disables
  Fetch.
- ILOFAR/RSTN/RFS/eCALLISTO get an `example_range` (e.g. ILOFAR
  → `"2021-09-07"`).

### 4. `dock.py` UI

Layout:

```
Source: [ PSP/RFS ▾ ]                         [ Open local… ]
Start: [..]  End: [..]                              [ Fetch ]
▸ Advanced  (checkable QGroupBox, collapsed by default)
    Instrument: [ eCALLISTO ▾✎ ]   λ: [..]–[..] MHz   Station: [..]
    Raw Fido query: [ a.Time(...), a.Instrument(...) ____ ]  ⚠ may not be plottable
Filter: [ substring… ]   Station: [ all ▾ ]
┌───────────── results (QTableWidget) ─────────────┐
│ ☑ Start Time         │ Station   │ File           │  (sortable)
└──────────────────────────────────────────────────┘
[ Plot selected ]
status: …
```

- **`QListWidget` → `QTableWidget`** with columns `Start Time | Station |
  File`, multi-row selection, sortable headers. Each row stores the Fido row
  object in `Qt.UserRole` on the first column item.
- **Filter bar**: a substring `QLineEdit` (matches across columns) plus a
  **Station** `QComboBox` populated from the distinct `Observatory` values in
  the current result set. Both are **client-side** show/hide of already-found
  rows — no re-query. This solves the eCALLISTO flood.
- **Advanced** checkable `QGroupBox` (collapsed by default):
  - editable instrument `QComboBox` prefilled with radiospectra's registered
    instruments (free-text so any instrument string is allowed — the reach
    extension);
  - optional `λ min`/`λ max` (MHz) and `Station` fields;
  - a raw Fido query `QLineEdit` with a ⚠ "results may not be plottable"
    label; when non-empty it sets `raw_attrs_text` and `expect_spectrogram
    = False`.
  - When the group is checked, Fetch builds the `RadioQuery` from these
    fields; when unchecked, from the source combo via `from_source`.
- **Empty-state (the ILOFAR fix)**: search returns 0 rows and no error →
  status reads e.g. *"No data for I-LOFAR in this range. Coverage is sparse
  (campaign days only); try e.g. 2021-09-07."* using the source's
  `example_range`.
- **EOVSA selected** → status shows `unavailable_reason`, Fetch disabled.
- Raw-query results skip the `_is_supported_filename` drop (show everything);
  plot failures continue to surface via the existing error dialog in
  `_plot_paths`.

Helper `_row_field(row, name)` for defensive column access (not every client
exposes `Observatory`/`Start Time`).

### 5. `pyproject.toml`

- `sunpy[net]>=7`
- `radiospectra @ git+https://github.com/sunpy/radiospectra.git@main`
  (swap to a version pin once radiospectra publishes the `Scraper(format=)`
  release; tracked by memory `sunpy_radiospectra_version_pin`).
- `requires-python = ">=3.12"` (radiospectra `main` + sunpy≥7 require
  Python ≥3.12; verify against radiospectra `main` at implementation time).
- Replace the misleading "pin to 6.x" comment with the real compat note:
  radiospectra `main` needs `Scraper(format=)` → sunpy≥7.

## Data flow

1. User picks a source (or fills Advanced) + time range → Fetch.
2. Dock builds a `RadioQuery`; guards: end>start, EOVSA/local-only abort
   with message.
3. `RadioFetchService.search(query)` runs `_do_search` on a thread-pool
   worker → emits `searchCompleted(rows)` / `searchFailed(msg)`.
4. `_on_search_completed` fills the table; populates the Station filter;
   applies the non-spectrogram drop only when `expect_spectrogram`;
   empty-state hint when 0 rows.
5. Plot selected → existing fetch → `open_spectrogram` →
   `spectrogram_to_speasy_variable` → virtual product → panel.

## Testing (TDD — write failing tests first)

- `test_fetch.py`
  - `RadioQuery` attr-building: wavelength and observatory map to the right
    attrs.
  - raw eval: a valid `raw_attrs_text` produces attrs and reaches
    `_run_fido_search`; an invalid one raises a clear `RuntimeError`.
  - raw search sets `expect_spectrogram=False`.
  - preserve `test_do_search_surfaces_response_errors` (errors+no rows →
    raise), updated to the `RadioQuery` signature.
- `test_dock.py`
  - table is populated (replaces the QListWidget assertions);
  - non-spectrogram rows dropped only when `expect_spectrogram`;
  - Station filter hides non-matching rows;
  - Advanced group drives a structured query and a raw query;
  - selecting EOVSA shows the unavailable message and disables Fetch;
  - empty-state hint text appears on 0 rows.
- `test_sources_registry.py`
  - EOVSA carries `unavailable_reason` and `fido_instrument is None`;
  - example ranges present for the live sources.

## Risks / mitigations

- **`eval` of the raw box**: restricted namespace (`__builtins__` removed),
  clear error surfacing, ⚠ label. Acceptable given desktop/own-tool context.
- **git-URL dependency**: not installable from a frozen index; documented and
  to be swapped for a version pin on the next radiospectra release.
- **Fido row column variability**: defensive `_row_field`; missing columns
  render blank, never crash.
```
