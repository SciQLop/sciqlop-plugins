from dataclasses import dataclass
from datetime import datetime, timezone

from .moments_fit import MODEL_CHOICES, SPECIES_MASS_TABLE
from .moments_vp import FIELDS

_L1 = "speasy/archive/BepiColombo/MSA/L1_Low_ECounts_Moments_TOF/bc_mmo_mppe_msa_l1_l_ecounts_moments_tof"
_L2 = "speasy/archive/BepiColombo/MSA/L2pre_Low_EFlux_Moments_TOF/bc_mmo_mppe_msa_l2pre_l_eflux_moments_tof"

_DEFAULT_START = datetime(2025, 1, 8, 1, 38, 50, tzinfo=timezone.utc)
_DEFAULT_STOP = datetime(2025, 1, 8, 17, 27, 23, tzinfo=timezone.utc)

SPECIES_LABELS = {"h_plus": "H⁺", "alphas": "alphas", "heavies": "heavies", "total": "total"}


@dataclass(frozen=True)
class VariantPlot:
    plot: int
    path: str
    inputs: dict
    label: str


def model_variant_plots(species: str) -> list:
    """One plot per moment, every fit model drawn in it (original noise floor)."""
    return [VariantPlot(plot=i, path=f"msa/moments_fit/{species}/{field}",
                        inputs={"model": model, "floor": "legacy"}, label=label)
            for i, field in enumerate(FIELDS) for label, model in MODEL_CHOICES.items()]


TEMPLATES = {
    "L1 Count Spectrograms": {
        "products": [
            f"{_L1}/h_plus_counts_corrected",
            f"{_L1}/alphas_counts_corrected",
            f"{_L1}/heavies_counts_corrected",
            f"{_L1}/total_counts_corrected",
        ],
    },
    "L1 Raw Count Spectrograms": {
        "products": [
            f"{_L1}/h_plus_counts_raw",
            f"{_L1}/alphas_counts_raw",
            f"{_L1}/heavies_counts_raw",
            f"{_L1}/total_counts_raw",
        ],
    },
    "L1 Moments": {
        "products": [
            f"{_L1}/all_ions_starts_density",
            f"{_L1}/h_plus_density",
            f"{_L1}/h_plus_velocity",
            f"{_L1}/alphas_density",
            f"{_L1}/heavies_density",
        ],
    },
    "L2pre Energy Flux Spectrograms": {
        "products": [
            f"{_L2}/diff_dir_en_flux_h_plus",
            f"{_L2}/diff_dir_en_flux_alphas",
            f"{_L2}/diff_dir_en_flux_heavies",
            f"{_L2}/diff_dir_en_flux_total",
        ],
    },
    "L2pre Ground Moments (Fit)": {
        "products": [
            "msa/moments_fit/h_plus/density",
            "msa/moments_fit/alphas/density",
            "msa/moments_fit/heavies/density",
            "msa/moments_fit/total/density",
            "msa/moments_fit/h_plus/T_eff",
        ],
    },
}


TEMPLATES.update({f"Ground Moments, all models — {SPECIES_LABELS[species]}": {"variants": species}
                  for species in SPECIES_MASS_TABLE})


def get_template(name: str) -> dict:
    return TEMPLATES[name]


def create_quicklook(template_name: str):
    from SciQLop.user_api.plot import create_plot_panel, TimeRange

    template = get_template(template_name)
    panel = create_plot_panel()
    panel.time_range = TimeRange(
        _DEFAULT_START.timestamp(),
        _DEFAULT_STOP.timestamp(),
    )
    if "variants" in template:
        _plot_variants(panel, model_variant_plots(template["variants"]))
    else:
        for product_path in template["products"]:
            panel.plot_product(product_path)
    return panel


def _plot_variants(panel, plots: list) -> None:
    drawn = set()
    for variant in plots:
        _, graph = panel.plot_product(variant.path, variant.plot if variant.plot in drawn else -1,
                                      product_inputs=variant.inputs)
        drawn.add(variant.plot)
        _label_once_drawn(graph._impl, variant.label)


def _label_once_drawn(graph, label: str) -> None:
    """The provider names a product's graph and user_api cannot rename it: without this
    every line of a plot is labelled with the same moment name. A product graph has no
    line until its data arrives, so the label is applied then (it survives refetches)."""
    def relabel(*_):
        if graph.line_count() == 1 and graph.labels() != [label]:
            graph.set_labels([label])

    graph.data_changed.connect(relabel)
