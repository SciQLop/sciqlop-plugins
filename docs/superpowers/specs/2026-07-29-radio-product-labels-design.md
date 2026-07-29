# Radio product labels — design

**Date:** 2026-07-29
**Repos:** `SciQLop` (generic half) + `plugins_sciqlop/sciqlop_radio`
**Supersedes:** the first draft of this file, whose central mechanism was wrong — see
*Correction* below.

## The problem

A panel of three radio spectrograms is labelled **`X`**, **`01`**, **`FLUX`**.

| Product | Plot + tree label today |
|---|---|
| `radio/ilofar/X` | `X` |
| `radio/ilofar/Y` | `Y` |
| `radio/ecallisto/AUSTRIA-Krumbach/01` | `01` |
| `radio/eovsa` | `eovsa` |
| `radio/LOFAR/LBA` | `LBA` |
| `radio/PSP/FIELDS/RFS_LFR/FLUX` | `FLUX` |

## Correction: it is not a metadata problem

The first draft claimed the remote plot path was the odd one out and that node metadata
(`LABLAXIS`) would fix the label. That is wrong, and measuring the in-process path disproves it:

- `time_sync_panel.py:693` — in-process: `target.plot(callback, name=node.name(), ...)`
- `plot_remote.py:31` — remote: `add_remote_color_map(node.name())`

**Both paths name the graph `node.name()`.** `LABLAXIS`/`FIELDNAM` feed
`istp_hints._primary_label`, which sets *axis* labels — for a spectrogram, the colour axis. They
never touch the graph label. Setting node metadata would not have changed a single plot label.

Why Speasy products look fine: they do not go through `EasyProvider`. `explore_nodes` names each
node from the Speasy inventory (`child.name`), which is already descriptive. Virtual products get
`product_name = self._path[-1]` (`easy_provider.py:135`) — the node name **is** the vp_path leaf,
hard-coded. Radio's leaves are `X`, `01`, `FLUX`.

So this is a **node-naming** problem, in two independent parts.

## Part B — decouple the node's display name from its path (SciQLop)

`EasyProvider.__init__` gains an optional `display_name: Optional[str] = None`, used for the
`ProductsModelNode` name in place of `self._path[-1]` when supplied. `make_rich_vp` and
`user_api.virtual_products.create_virtual_product` pass it through.

An explicit keyword rather than a metadata key, deliberately: it is typed and discoverable, and it
avoids overloading an ISTP key. (`LABLAXIS` in particular is already consumed as the colour-axis
label, so reusing it would couple the graph label to the colorbar label.)

This is additive — a provider that passes nothing behaves exactly as today — and it fixes tree and
plot labels together, on both the in-process and remote paths, for **every** VP-based plugin.

### Also in this file: stop clobbering `description`

`easy_provider.py:154-158` currently does:

```python
metadata = {**metadata, "description": f"Virtual {parameter_type.name} product built from Python function: {self.name}", ...}
```

which overwrites any curated `description` the plugin supplied — every radio product's tooltip is
replaced by boilerplate. Make it a fallback (`setdefault` semantics) so a supplied description
survives, keeping the generated string for providers that supply none.

## Part A — consistent, descriptive vp_paths (sciqlop_radio)

Breaking, and accepted: nobody depends on these paths yet.

| Current | New |
|---|---|
| `radio/eovsa` | `radio/EOVSA` |
| `radio/ilofar/X` | `radio/I-LOFAR/X` |
| `radio/ilofar/Y` | `radio/I-LOFAR/Y` |
| `radio/ecallisto/<station>/<focus>` | `radio/e-CALLISTO/<station>/<focus>` |
| `radio/rstn/<station>` | `radio/RSTN/<station>` |
| `radio/LOFAR/LBA` | unchanged — already correct |
| `radio/PSP/FIELDS/RFS_LFR/FLUX` (catalog) | unchanged — already correct |

This brings the continuous and stream products in line with the catalog's existing
`radio/PSP/…`, `radio/Wind/…`, `radio/STEREO-A/…` convention.

### The invariant this must not break

`StreamIdentity.vp_path` (`streams.py:64-70`) composes `"radio" / source_key [/ station]
[/ channel]`, and `CONTINUOUS_SOURCES`' hardcoded `vp_path` values must **collide exactly** with
what the dock computes for the same stream. That collision is load-bearing: the dock reuses the
already-registered VP instead of registering a duplicate, which `test_dock.py:313`
(`test_ilofar_stream_reuses_preexisting_continuous_vp_by_path`) pins.

Rename one side only and the failure is silent — duplicate products in the tree, or a stream that
never finds its pre-registered VP.

`source_key` is *not* the place to fix this: it is also the `STREAM_RULES` key (`rule_for()`), the
day-cache search signature, and the dock's combo-box identity. Conflating presentation with that
identity is what creates the trap.

**Therefore:** `RadioSource` gains a `path_name: str = ""` field defaulting to `key`, and
`StreamIdentity.vp_path` uses `path_name`. One table maps key → path segment; `CONTINUOUS_SOURCES`
and the dock both derive from it rather than repeating a literal.

A regression test asserts, for every entry in `CONTINUOUS_SOURCES` that corresponds to a stream
rule, that the dock-computed `StreamIdentity.vp_path` equals the registered `vp_path`. That test is
the point of Part A's structure — it converts a silent failure into a loud one.

## Display names

With B available, the node name is chosen for readability rather than forced to be the path leaf.
One name serves both the tree and the plot, so it must be self-contained: a panel may stack
products from several instruments, where `X pol` alone is ambiguous.

| Product | Display name |
|---|---|
| `radio/I-LOFAR/X` | `I-LOFAR X pol` |
| `radio/I-LOFAR/Y` | `I-LOFAR Y pol` |
| `radio/e-CALLISTO/AUSTRIA-Krumbach/01` | `e-CALLISTO AUSTRIA-Krumbach 01` |
| `radio/EOVSA` | `EOVSA` |
| `radio/LOFAR/LBA` | `LOFAR LBA` |
| `radio/PSP/FIELDS/RFS_LFR/FLUX` | `PSP/FIELDS RFS LFR (PSD flux)` |

The strings mostly exist already and are simply not routed anywhere the node can see them:
`ContinuousSource.label` is used only by the dock's combo box and status line; the catalog's YAML
`label:` is unused at registration (`catalog.py:159-169` builds node metadata from `e.labels`, the
*component* names, not `e.label`).

Accepted cosmetic cost: the tree shows `I-LOFAR X pol` nested under `I-LOFAR`, which is mildly
redundant. Plot unambiguity is worth more than tree brevity, and SciQLop has one name for both.

## Testing

**SciQLop**
- `display_name` overrides the node name; omitting it still yields the path leaf.
- A supplied `description` survives registration; one is still generated when absent.

**sciqlop_radio**
- Each family registers the expected display name (existing tests already capture `vp_factory`
  kwargs with fakes).
- The path-collision regression test described under Part A.
- Existing tests referencing the old literals (`test_dock.py`, `test_continuous_cache.py`) update
  to the new paths — they are asserting the invariant, not the spelling.

Labels are only visible through the GUI, so the automated tests pin the wiring; one manual check
that a panel reads `I-LOFAR X pol` rather than `X` is worth doing once.

## Out of scope

- **Knob-reactive labels.** A `[bg-sub db]` suffix tracking the `bg_mode` knob is not achievable
  here: a node name is fixed at registration, while `bg_mode` changes per graph at runtime.
  Explicitly dropped.
- **`add_remote_line_graph`'s label path** (`plot_remote.py:34`, via `provider.labels(node)`).
  Every radio product is a spectrogram.
- **The duplicate `ILOFAR.spectrogram` variable name.** Both X and Y polarisations produce a
  variable named `ILOFAR.spectrogram` with `columns=['ILOFAR']`. Not user-visible on the graph-name
  path, so renaming it is churn; worth revisiting only if something starts consuming variable names.
