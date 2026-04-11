from datetime import datetime, timezone

_L1 = "speasy/archive/BepiColombo/MSA/L1_Low_ECounts_Moments_TOF/bc_mmo_mppe_msa_l1_l_ecounts_moments_tof"
_L2 = "speasy/archive/BepiColombo/MSA/L2pre_Low_EFlux_Moments_TOF/bc_mmo_mppe_msa_l2pre_l_eflux_moments_tof"

_DEFAULT_START = datetime(2025, 1, 8, 1, 38, 50, tzinfo=timezone.utc)
_DEFAULT_STOP = datetime(2025, 1, 8, 17, 27, 23, tzinfo=timezone.utc)

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
}


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
    for product_path in template["products"]:
        panel.plot_product(product_path)
    return panel
