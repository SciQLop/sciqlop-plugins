import os
import atexit

import pytest
import pycdfpp
import numpy as np


def _force_exit():
    """Avoid segfault during interpreter shutdown.

    SciQLopPlots' PlotsModel singleton is destroyed after QApplication,
    causing a segfault.  This is an upstream issue — SciQLopPlots' own
    tests exhibit the same crash.  Force-exit to skip the problematic
    teardown.
    """
    os._exit(0)


@pytest.fixture(autouse=True, scope="session")
def _prevent_exit_segfault():
    atexit.register(_force_exit)
    yield
    # atexit handler will run after pytest returns


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
