# sciqlop_sismo

SciQLop plugin for seismic waveforms via FDSN / ObsPy.

## What it does

Implements a Speasy `DataProvider` (`provider_name="sismo"`) that
produces `SpeasyVariable` products from FDSN web services. Once a
channel is added to the provider's inventory, it is a first-class
SciQLop product — drag-drop onto any panel, mix with other space-
physics data, attach catalogs.

Each NSLC channel exposes three parameters:

| UID suffix     | Type            | Units    | Notes                                                  |
|----------------|-----------------|----------|--------------------------------------------------------|
| `/waveform`    | 1-D time-series | m/s      | Demean + bandpass (settings-driven, default 0.01–10 Hz)|
| `/raw`         | 1-D time-series | counts   | Unprocessed instrument output                          |
| `/spectrogram` | 2-D colormap    | dB       | scipy STFT, 256-pt window, 50 % overlap                |

## Usage

1. Open SciQLop. A "Sismo" dock appears (toggle in the toolbar or
   Tools menu).
2. **Stations tab** — fill in NSLC patterns and a time range, hit
   *Search*. Pick channels from the tree and click *Add to inventory*
   (or *Plot waveform* / *Plot spectrogram* to add + immediately drop
   on a fresh panel).
3. **Events tab** — search an earthquake catalog (USGS/EMSC/ISC), pick
   an event, hit *Find stations* to list channels in a given degree
   radius, then *Add all to inventory*.
4. **Local files tab** — open local miniSEED / SAC files; their
   channels appear in the same `sismo/` inventory tree.
5. The inventory is persisted to `~/.config/sciqlop/sismo/inventory.yaml`
   (override via `SCIQLOP_SISMO_INVENTORY_DIR`).

## Data centers

Default routing is `iris-federator`, which transparently fans a single
query out across all major FDSN data centers. Alternatives in the
dropdown:
- `eida-routing` — European Integrated Data Archive
- `IRIS`, `RESIF`, `GEOFON`, `IPGP` — direct single-center queries

## Design

See `docs/superpowers/specs/2026-05-12-sciqlop_sismo-design.md`.

## Development

```bash
pip install -e '.[test]'
pytest sciqlop_sismo/tests/             # mocked tests
pytest sciqlop_sismo/tests/ -m live     # live FDSN tests (slow)
```
