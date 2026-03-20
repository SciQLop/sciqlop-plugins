import pytest
import pycdfpp
import numpy as np


@pytest.fixture
def sample_cdf_bytes():
    """Create a minimal valid CDF file in memory."""
    cdf = pycdfpp.CDF()
    epochs = np.arange(
        np.datetime64("2020-01-01"),
        np.datetime64("2020-01-01T00:00:10"),
        np.timedelta64(1, "s"),
    ).astype("datetime64[ns]")
    cdf.add_variable("Epoch", values=epochs, is_nrv=False)
    cdf.add_variable(
        "Bt",
        values=np.random.rand(10).astype(np.float32),
        is_nrv=False,
    )
    # Scalar attributes must be passed as single-element lists
    cdf["Bt"].add_attribute("VAR_TYPE", "data")
    cdf["Bt"].add_attribute("DEPEND_0", "Epoch")
    cdf["Bt"].add_attribute("UNITS", "nT")
    cdf["Bt"].add_attribute("FILLVAL", [np.float32(-1e31)])
    cdf["Bt"].add_attribute("VALIDMIN", [np.float32(0.0)])
    cdf["Bt"].add_attribute("VALIDMAX", [np.float32(100.0)])
    cdf["Epoch"].add_attribute("VAR_TYPE", "support_data")
    return bytes(pycdfpp.save(cdf))
