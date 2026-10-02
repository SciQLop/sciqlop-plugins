"""The Method tab must describe the code as it is: a changed threshold fails here, not silently in the doc."""
import tomllib
from pathlib import Path

from sciqlop_msa import moments_compute, moments_fit

PACKAGE = Path(moments_fit.__file__).parent
DOC = (PACKAGE / "moments_method.md").read_text()


def test_doc_names_every_model_choice():
    for label in moments_fit.MODEL_CHOICES:
        assert label in DOC, label


def test_doc_states_the_thresholds_the_code_uses():
    assert moments_fit.CHI2_MAX == 1.0 and "above **1**" in DOC
    assert moments_fit.NOISE_FLUX_THRESHOLD == 1e5 and "**10⁵ cm⁻² s⁻¹ sr⁻¹ eV⁻¹**" in DOC
    assert moments_compute._MIN_POINTS_TO_FIT == 6 and "fewer than **6**" in DOC
    assert set(moments_fit.AUTO_MODELS) == {"max_kap", "2max", "2max_kap"}


def test_doc_ships_in_the_wheel():
    pyproject = tomllib.loads((PACKAGE.parent / "pyproject.toml").read_text())
    assert "moments_method.md" in pyproject["tool"]["setuptools"]["package-data"]["sciqlop_msa"]
