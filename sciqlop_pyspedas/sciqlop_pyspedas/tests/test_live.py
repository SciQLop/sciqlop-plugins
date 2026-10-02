"""Real MMS SDC download + mms_part_getspec. Run with: -m live"""
from datetime import datetime, timezone

import numpy as np
import pytest

pytest.importorskip("pyspedas")

from sciqlop_pyspedas import worker  # noqa: E402
from sciqlop_pyspedas.catalog import SOURCES  # noqa: E402

pytestmark = pytest.mark.live

# 2015-10-16 13:00-13:10: MMS1 magnetopause crossing (Burch et al. 2016 EDR day).
START = datetime(2015, 10, 16, 13, 0, tzinfo=timezone.utc).timestamp()
STOP = datetime(2015, 10, 16, 13, 10, tzinfo=timezone.utc).timestamp()


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SCIQLOP_WORKSPACE_DIR", str(tmp_path))


def test_fpi_ion_energy_and_pitch_angle():
    ions = next(s for s in SOURCES if s.label == "FPI ions")
    energy = worker.worker_callback(START, STOP, source=ions, output="energy", probe="1", data_rate="fast")
    pa = worker.worker_callback(START, STOP, source=ions, output="pa", probe="1", data_rate="fast")
    assert len(energy.time) > 0 and len(pa.time) > 0
    assert np.nanmax(energy.values) > 0
    assert 0 <= np.nanmin(pa.axes[1].values) and np.nanmax(pa.axes[1].values) <= 180
