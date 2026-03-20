"""Integration test: load a real CDF file from CDAWeb and verify the full pipeline."""
import pytest
import numpy as np


@pytest.fixture
def real_cdf():
    """Download a small CDF file from CDAWeb for testing."""
    from cdf_workbench.loader import load_cdf, CdfLoadError

    url = "https://cdaweb.gsfc.nasa.gov/pub/software/cdawlib/0MASTERS/ac_h5_swi_00000000_v01.cdf"
    try:
        return load_cdf(url)
    except CdfLoadError:
        pytest.skip("Cannot reach CDAWeb")


def test_full_pipeline(real_cdf):
    from cdf_workbench.tree_model import CdfTreeModel
    from cdf_workbench.quality import analyze_quality

    model = CdfTreeModel(real_cdf)
    assert model.rowCount() > 0

    # Find a data variable with actual records and analyze quality
    found = False
    for name in real_cdf:
        info = model.variable_info(name)
        if info is None:
            continue
        if info.var_type.lower() == "data":
            values = real_cdf[name].values
            if values is None or values.size == 0:
                continue
            report = analyze_quality(
                values=values,
                fill_value=info.fill_value,
                valid_min=info.valid_min,
                valid_max=info.valid_max,
            )
            assert report.total_points > 0
            found = True
            break

    if not found:
        pytest.skip("CDF file contains no data records (master/template file)")
