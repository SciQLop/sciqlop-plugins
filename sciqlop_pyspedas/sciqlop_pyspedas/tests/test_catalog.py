from sciqlop_pyspedas.catalog import (OUTPUTS, PROBES, SOURCES, Source, cache_key,
                                      product_path, tplot_name)

FPI_I = Source("fpi", "i", "FPI ions", ("fast", "brst"))
HPCA_H = Source("hpca", "hplus", "HPCA H+", ("srvy", "brst"))


def test_eighteen_products_with_unique_paths():
    paths = {product_path(s, o) for s in SOURCES for o in OUTPUTS}
    assert len(paths) == 18


def test_outputs_are_pyspedas_names():
    assert set(OUTPUTS) == {"energy", "pa", "gyro"}
    assert OUTPUTS["energy"].bin_log is True
    assert OUTPUTS["pa"].bin_log is False


def test_probes():
    assert PROBES == ("1", "2", "3", "4")


def test_fpi_tplot_name_matches_pyspedas():
    assert tplot_name(FPI_I, "1", "fast", "energy") == "mms1_dis_dist_fast_energy"


def test_hpca_tplot_name_matches_pyspedas():
    assert tplot_name(HPCA_H, "2", "brst", "pa") == "mms2_hpca_hplus_phase_space_density_pa"


def test_product_path():
    assert product_path(FPI_I, "pa") == "pyspedas/MMS/FPI ions/pitch angle"


def test_hpca_rates_have_distinct_cache_keys():
    assert cache_key(HPCA_H, "1", "srvy", "energy") != cache_key(HPCA_H, "1", "brst", "energy")
