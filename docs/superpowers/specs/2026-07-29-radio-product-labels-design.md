# Radio product labels — design

**Date:** 2026-07-29
**Repos:** `SciQLop` (generic half) + `plugins_sciqlop/sciqlop_radio` (the metadata)

## The problem

A panel of three radio spectrograms is labelled **`X`**, **`01`**, **`FLUX`**.

Every radio virtual product registers with `out_of_process=True`. The remote plot path
(`SciQLop/components/plotting/backend/remote/plot_remote.py:31`) names the graph
`add_remote_color_map(node.name())`, and `node.name()` is the **last segment of the vp_path**
(`easy_provider.py:134` does `self._path = path.split('/')`). So:

| Product | Plot label today |
|---|---|
| `radio/ilofar/X` | `X` |
| `radio/ilofar/Y` | `Y` |
| `radio/ecallisto/AUSTRIA-Krumbach/01` | `01` |
| `radio/eovsa` | `eovsa` |
| `radio/LOFAR/LBA` | `LBA` |
| `radio/PSP/FIELDS/RFS_LFR/FLUX` | `FLUX` |

Two independent products can also share a label outright: the I-LOFAR X and Y polarisations both
produce a `SpeasyVariable` named `ILOFAR.spectrogram` with `columns=['ILOFAR']`.

## Why the obvious fix doesn't work

The variable's own name and metadata are the wrong lever, and it takes a measurement to see why.

`SciQLop/core/speasy_hints.py:83-85` does `meta.setdefault("LABLAXIS", variable.name)` — so
metadata on the fetched variable *wins* over its `.name`, and `istp_hints._primary_label` reads
`LABLAXIS` then `FIELDNAM`. That is a genuine metadata mechanism, but it only runs **in process**.

For an `out_of_process=True` product it never runs at all: `time_sync_panel.py:666-676` returns on
the `is_remote` branch before `_post_plot` constructs any plot hints, and the remote protocol
transports handles and layout only — `variable.meta` never leaves the worker process. This is the
same reason the `SCALETYP` override from the background-removal work is inert on the default path.

So renaming the variable, or setting `LABLAXIS` on it, would change nothing for these products.

## The lever

**Node** metadata, not variable metadata. `plot_remote.py` already holds the `node` at the point it
names the graph, and `ProductsModelNode.metadata()` round-trips whatever the plugin passed at
registration (verified: a node built as `ProductsModelNode('X', {'LABLAXIS': 'I-LOFAR X pol'})`
reports `name() == 'X'` and `metadata() == {'LABLAXIS': 'I-LOFAR X pol'}`).

`LABLAXIS` is the right key rather than a new plugin-specific one: `hints.py`'s
`_plot_hints_from_node` already feeds `node.metadata()` through `istp_metadata_to_hints`, whose
`_primary_label` reads exactly `LABLAXIS` → `FIELDNAM`. Reusing it makes the remote and in-process
paths agree instead of diverging.

**Known trade-off, accepted.** `LABLAXIS` is overloaded: `istp_hints.py:128-132` also feeds
`_primary_label` into the plot's *main axis* label, which for a spectrogram is the colour axis. So
on a hints-consuming path a long product label like `PSP/FIELDS RFS LFR (PSD flux)` would also
become the colorbar label. That does not bite the products this spec targets — they are all
`out_of_process=True`, where node hints are never consulted at all (same branch that strands the
variable metadata) — but it is the reason not to extend this to in-process products without
looking. Two further consequences of the same overload: for a catalog entry the curated YAML label
deliberately overrides any `LABLAXIS` the Speasy index supplied, and anything that later starts
consuming node hints for these products inherits the colorbar behaviour. A dedicated key would
avoid the overload at the cost of the remote and in-process paths disagreeing again; the agreement
is worth more here.

## Changes

### SciQLop — the generic half

In `plot_remote.py`, replace the bare `node.name()` argument with a helper that resolves a display
label from the node: `LABLAXIS`, then `FIELDNAM`, then `node.name()`. Same precedence
`istp_hints._primary_label` uses.

This benefits every remote spectrogram product in SciQLop, not only radio's. It is additive: a node
carrying neither key behaves exactly as today.

### sciqlop_radio — the metadata

Four product families, all of which already have the descriptive string and simply never route it
to the node. `ContinuousSource.label` is currently used *only* by the dock UI (`dock.py`'s combo
box and status messages); the catalog's YAML `label:` is likewise unused at registration
(`catalog.py:169` builds node metadata from `e.labels`, the component names, not `e.label`).

| File | Change |
|---|---|
| `continuous.py` | Route `src.label` into the registered node's metadata as `LABLAXIS`. |
| `continuous.py` (`make_stream_source`) | Carry the composed `"eCALLISTO AUSTRIA-Krumbach 01"` label into the stream source's metadata. |
| `lofar.py` | Add `LABLAXIS` to `LOFAR_META`. |
| `catalog.py` | Set `meta["LABLAXIS"] = e.label` on the single `meta` immediately before the `vp_factory(...)` call (~line 172). `catalog.py` builds `meta` on **two** branches — the rich `extract_speasy_index_meta` path and the minimal fallback after an extraction failure — so setting it after they join covers both with one line. |

### Result

| Product | Label after |
|---|---|
| `radio/ilofar/X` | `ILOFAR (mode 357 BST, X pol)` |
| `radio/ilofar/Y` | `ILOFAR (mode 357 BST, Y pol)` |
| `radio/ecallisto/AUSTRIA-Krumbach/01` | `eCALLISTO AUSTRIA-Krumbach 01` |
| `radio/eovsa` | `EOVSA` |
| `radio/LOFAR/LBA` | `LOFAR LBA tied-array dynamic spectrum (10-90 MHz)` |
| `radio/PSP/FIELDS/RFS_LFR/FLUX` | `PSP/FIELDS RFS LFR (PSD flux)` |

No `vp_path` changes, so saved panels, workspaces, and `plot("radio/ilofar/X")` keep working.

## Testing

**SciQLop:** unit-test the resolver's precedence — `LABLAXIS` wins; `FIELDNAM` when `LABLAXIS` is
absent; `node.name()` when neither is present; and a node with empty metadata still yields its name
rather than raising or returning an empty label.

**sciqlop_radio:** assert each of the four families registers node metadata carrying the expected
`LABLAXIS`. The existing tests already drive these registrations with fake `vp_factory`s that
capture the `metadata=` kwarg, so this is an assertion on machinery that is already under test.

Because the labels only become visible through the GUI, the automated tests pin the metadata and
the resolver; a single manual check that a panel shows the new labels is worth doing once.

## Out of scope

- **`vp_path` casing.** `radio/eovsa` and `radio/ecallisto/...` are lowercase while the catalog uses
  `radio/PSP/...`, `radio/Wind/...` and `lofar.py` uses `radio/LOFAR/LBA`. Real inconsistency, but
  changing it is breaking for saved panels and hardcoded paths, and it is separable from the label
  problem this spec fixes.
- **Knob-reactive labels.** A `[bg-sub db]` suffix reflecting the `bg_mode` knob is *not* achievable
  through node metadata: node metadata is static, set once at registration, while `bg_mode` changes
  per graph at runtime. Making a label track a knob means updating the graph name on knob change,
  which nothing currently does. Explicitly dropped, not deferred-by-oversight.
- **`add_remote_line_graph`'s label path** (`plot_remote.py:34`), which takes `provider.labels(node)`.
  Every radio product is a spectrogram, so it is untouched here.
- The duplicate `ILOFAR.spectrogram` variable name itself. Once node metadata drives the label the
  variable name is not user-visible on this path; renaming it would be churn without effect.
