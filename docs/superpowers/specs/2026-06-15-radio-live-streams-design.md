# Design: live per-channel radio streams

**Date:** 2026-06-15
**Branch:** `feat/radio-live-streams`
**Plugin:** `sciqlop_radio`

## Problem

When the user plots fetched search results, the dock (`_plot_paths` in `dock.py`)
registers each merged group as a virtual product backed by
`_build_static_callback` — a closure returning a *fixed* `SpeasyVariable` for any
`(start, stop)`. The product-tree node is a frozen snapshot of exactly what was
fetched; dragging it to another time range only re-clips the same array.

The wanted behavior: the registered product should be a **real stream** for the
physical channel (station / receiver), so dragging it to any time range
re-fetches the data for that channel on demand.

## Key facts established (verified on the dev venv, sunpy 7.1.2 + radiospectra main)

1. **Server-side station filtering works** via `radiospectra.net.Observatory`
   (a.k.a. `radiospectra.net.attrs.Observatory`). The eCALLISTO and RSTN clients
   use it in `pre_search_hook` to build a station-specific URL.
   - `sunpy.net.attrs.Observatory` is `None` in sunpy 7.1.2 (the prior
     "observatory filter broken" conclusion was about *this* attr). The
     radiospectra attr is the correct one and is unaffected.
2. **Focus code is a Fido column, not a filename scrape.** The eCALLISTO client's
   `post_search_hook` sets `row["ID"] = suffix` (e.g. `_01`/`_02` → `"01"`/`"02"`).
   The FITS header carries `FRQFILE` (`FRQ00066.CFG`), confirming each focus code
   is a distinct frequency program at the same station/time. So a channel can be
   identified *before* downloading.
3. eCALLISTO Fido row columns: `Start Time`, `Provider`, `Instrument`,
   `Observatory` (station, e.g. `BIR`/`ALASKA`), `ID` (focus code).
4. Parsed eCALLISTO `meta`: `observatory` (`BIR`), `instrument` (`e-CALLISTO`),
   `fits_meta["FRQFILE"]`.

## Stream identity

A stream = `(instrument, station, channel-token)`, with the parsed **frequency
signature** (`plot.frequency_signature`) as a post-download backstop. A file
joins a stream only if *all* match — so `_01` and `_02` at the same station/time
never merge.

| Instrument | station (server-side filter) | channel-token (client-side) |
|---|---|---|
| eCALLISTO | `Observatory` col → `net.Observatory(x)` | `ID` col (focus code) |
| RSTN | `Observatory` col → `net.Observatory(x)` | — (one stream per station) |
| ILOFAR / RFS | — (single channel) | — |

**Tree node path:** `radio/<instrument>/<station>[/<channel>]`
(e.g. `radio/eCALLISTO/BIR/01`, `radio/RSTN/learmonth`, `radio/ILOFAR`).
Stable across time, so re-plotting the same channel reuses the node rather than
spawning `__+Nmore` variants.

## Streaming callback `(t0, t1) → SpeasyVariable | None`

1. `Fido.search(a.Time(t0, t1), a.Instrument(inst), *station_attrs)` — station
   filtered server-side via `net.Observatory` where supported.
2. Drop rows whose channel-token ≠ the node's (client-side focus-code filter).
3. Fetch (disk-cached) → parse (`_open_and_convert`, Speasy `@CacheCall`-cached)
   → keep only files matching the node's frequency signature → concat along time.
4. Empty window → `None` (consistent with existing EOVSA/ILOFAR VPs).
5. **No file cap** — a wide window fetches whatever it needs. The callback runs
   on SciQLop's data thread; slowness ≠ frozen UI, and repeat pans hit the cache.

### Crash guard

Past memory claims a streaming callback returning `None` crashes SciQLop with
`x, y, z = []` unpack. The shipped EOVSA/ILOFAR continuous VPs already return
`None`, so the note may be stale or path-specific. **Verify on the dev venv that
`None` does not crash before claiming done**; only if it genuinely crashes do we
revisit (and surface it to the user rather than silently inventing an
empty-variable path).

## Where it slots in

- `continuous.py` is generalized: a stream descriptor carries `instrument`,
  `station`, `channel`, the `station_attrs` factory, and a `row → channel-token`
  extractor. `_build_callback` gains the server-side station attrs + the
  client-side channel + frequency-signature filter. EOVSA/ILOFAR load-time
  registration is unchanged (they have no station/channel).
- `_plot_paths` stops building static snapshots for **fetched** results. It groups
  the selected **rows** (carrying `Observatory`/`ID`) by stream-identity, registers
  one streaming VP per group, and plots each onto a shared panel as a stacked
  subplot (today's plotting UX; each subplot keeps a single colormap, respecting
  the one-colormap-per-plot rule).
- The rows must reach `_plot_paths`. Today the fetch path discards rows and passes
  only paths (`_on_fetch_completed`). Thread the originating row (or its
  `Observatory`/`ID`/instrument identity) alongside each fetched path so plot-time
  grouping can key on stream-identity.
- **Local `Open local…` files keep the static callback** — there is nothing
  remote to stream.

## Testing

Pure-function unit tests (no network):
- Stream-identity extraction from real Fido row columns (`Observatory`, `ID`),
  using a dict-backed `FakeRow` (never bare `MagicMock`).
- Channel-token + frequency-signature splitting: assert two `_01`/`_02` rows at
  the same station produce two streams and never merge.
- `vp_path` shape per instrument.
- Callback wiring with a fake Fido returning canned rows: assert the correct
  `net.Observatory` attr is passed, and cross-station / cross-focus rows are
  dropped before concat.

Integration:
- A `@pytest.mark.live` test against real eCALLISTO over a known window
  (`2011-06-07`), asserting a per-station stream returns a non-empty variable.

Manual verification on the dev venv (`/home/jeandet/Documents/prog/SciQLop/.venv`):
- `net.Observatory` round-trips as a real server-side filter.
- Returning `None` from the callback does not crash a panel.

## Out of scope

- The eCALLISTO non-monotonic / duplicated frequency axis (pre-existing).
- LOFAR multi-beam streams — the mechanism (per-instrument channel extractor) is
  built generically so LOFAR slots in later, but the dock's current ILOFAR client
  is single beam-formed (mode 357); no multi-beam files flow through today.
- Per-observatory pickers in the dock UI (the stream is created from search
  results, not a new UI control).
