# sciqlop_sismo

SciQLop plugin for seismic waveforms.

Produces `SpeasyVariable` products from FDSN web services (via ObsPy
`RoutingClient`). Each NSLC channel is exposed as three parameters in
the `sismo/` Speasy tree: `waveform` (preprocessed time-series),
`raw` (instrument counts) and `spectrogram` (2-D time × frequency).

The dock is a *browser* — it discovers channels and adds them to the
inventory. Plotting happens on the SciQLop main timeline via drag-drop
or `panel.plot_product(uid)`.

Design: `docs/superpowers/specs/2026-05-12-sciqlop_sismo-design.md`
