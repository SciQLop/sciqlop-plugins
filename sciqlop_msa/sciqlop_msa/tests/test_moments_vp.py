from unittest.mock import patch

import numpy as np
import pytest

from sciqlop_msa.moments_compute import DayFits


def _day_fits(day_offset_seconds=0.0):
    return DayFits(
        time=np.array([1736300000.0, 1736300060.0]) + day_offset_seconds,
        n_tot=np.array([45.0, 46.0]),
        T_c=np.array([280.0, 281.0]),
        T_eff=np.array([300.0, 301.0]),
        model=np.array(["max_kap", "max_kap"]),
        chi2=np.array([0.001, 0.002]),
    )


def _day_fits_three_points():
    return DayFits(
        time=np.array([1736300000.0, 1736300060.0, 1736300120.0]),
        n_tot=np.array([45.0, 46.0, 47.0]),
        T_c=np.array([280.0, 281.0, 282.0]),
        T_eff=np.array([300.0, 301.0, 302.0]),
        model=np.array(["max_kap", "max_kap", "max_kap"]),
        chi2=np.array([0.001, 0.002, 0.003]),
    )


def test_register_moments_vps_creates_twelve_products():
    from sciqlop_msa import moments_vp

    with patch("SciQLop.user_api.virtual_products.create_virtual_product") as mock_create:
        moments_vp.register_moments_vps()

    assert mock_create.call_count == 12
    by_path = {call.kwargs["path"]: call.kwargs for call in mock_create.call_args_list}
    assert "msa/moments_fit/h_plus/density" in by_path
    assert "msa/moments_fit/alphas/T_c" in by_path
    assert "msa/moments_fit/heavies/T_eff" in by_path
    assert "msa/moments_fit/total/density" in by_path

    # exact-mass species get no special display_name and an unmarked label
    assert by_path["msa/moments_fit/h_plus/density"]["display_name"] is None
    assert by_path["msa/moments_fit/h_plus/density"]["labels"] == ["density"]
    assert by_path["msa/moments_fit/alphas/T_c"]["display_name"] is None
    assert by_path["msa/moments_fit/alphas/T_c"]["labels"] == ["T_c"]
    # approximate-mass species (heavies, total) are flagged in both display_name
    # (currently a no-op for Scalar VPs in SciQLop, kept for forward-compat) and
    # labels (the mechanism that actually reaches the product tree today)
    assert by_path["msa/moments_fit/heavies/T_eff"]["display_name"] == "T_eff (heavies, approx.)"
    assert by_path["msa/moments_fit/heavies/T_eff"]["labels"] == ["T_eff (approx.)"]
    assert by_path["msa/moments_fit/total/density"]["display_name"] == "density (total, approx.)"
    assert by_path["msa/moments_fit/total/density"]["labels"] == ["density (approx.)"]


def test_density_callback_returns_values_sliced_to_requested_window():
    from sciqlop_msa import moments_vp

    callback = moments_vp._make_callback("h_plus", "density")

    with patch("sciqlop_msa.moments_vp.fit_day", return_value=_day_fits()):
        result = callback(1736300000.0, 1736300060.0)

    assert result is not None
    assert result.values.reshape(-1).tolist() == pytest.approx([45.0, 46.0])
    assert "ground-fit" in result.meta["CATDESC"]


def test_density_callback_narrows_to_requested_window():
    """The day-bucket has three records; the requested (start, stop) window
    covers only the first two, so the third must be clipped out."""
    from sciqlop_msa import moments_vp

    callback = moments_vp._make_callback("h_plus", "density")

    with patch("sciqlop_msa.moments_vp.fit_day", return_value=_day_fits_three_points()):
        result = callback(1736300000.0, 1736300060.0)

    assert result is not None
    assert result.values.reshape(-1).tolist() == pytest.approx([45.0, 46.0])


def test_density_callback_catdesc_flags_approximate_species():
    from sciqlop_msa import moments_vp

    callback = moments_vp._make_callback("heavies", "density")

    with patch("sciqlop_msa.moments_vp.fit_day", return_value=_day_fits()):
        result = callback(1736300000.0, 1736300060.0)

    assert result is not None
    assert "Approximate" in result.meta["CATDESC"]


def test_density_callback_returns_none_when_no_data():
    from sciqlop_msa import moments_vp

    callback = moments_vp._make_callback("h_plus", "density")

    with patch("sciqlop_msa.moments_vp.fit_day", return_value=None):
        result = callback(1577836800.0, 1577840400.0)

    assert result is None
