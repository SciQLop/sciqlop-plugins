TEMPLATES = {
    "MSA Spectrograms": {
        "products": [
            "speasy/archive/BepiColombo/MSA/L1_Low_Mass_Moments_TOF/bc_mmo_mppe_msa_l1_l_mass_moments_tof/h_plus_counts",
            "speasy/archive/BepiColombo/MSA/L1_Low_Mass_Moments_TOF/bc_mmo_mppe_msa_l1_l_mass_moments_tof/alphas_counts",
            "speasy/archive/BepiColombo/MSA/L1_Low_Mass_Moments_TOF/bc_mmo_mppe_msa_l1_l_mass_moments_tof/heavies_counts",
        ],
    },
    "MSA Moments": {
        "products": [
            "speasy/archive/BepiColombo/MSA/L1_Low_Mass_Moments_TOF/bc_mmo_mppe_msa_l1_l_mass_moments_tof/all_ions_starts_density",
            "speasy/archive/BepiColombo/MSA/L1_Low_Mass_Moments_TOF/bc_mmo_mppe_msa_l1_l_mass_moments_tof/h_plus_density",
            "speasy/archive/BepiColombo/MSA/L1_Low_Mass_Moments_TOF/bc_mmo_mppe_msa_l1_l_mass_moments_tof/h_plus_velocity",
            "speasy/archive/BepiColombo/MSA/L1_Low_Mass_Moments_TOF/bc_mmo_mppe_msa_l1_l_mass_moments_tof/alphas_density",
            "speasy/archive/BepiColombo/MSA/L1_Low_Mass_Moments_TOF/bc_mmo_mppe_msa_l1_l_mass_moments_tof/heavies_density",
        ],
    },
}


def get_template(name: str) -> dict:
    return TEMPLATES[name]


def create_quicklook(template_name: str):
    from SciQLop.user_api.plot import create_plot_panel

    template = get_template(template_name)
    panel = create_plot_panel()
    for product_path in template["products"]:
        panel.plot_product(product_path)
    return panel
