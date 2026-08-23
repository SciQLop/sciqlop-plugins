from datetime import date

import numpy as np
import pytest


def _make_fake_variable(flux, energy, times):
    from speasy.products import SpeasyVariable, VariableTimeAxis, VariableAxis, DataContainer

    time_axis = VariableTimeAxis(values=times.astype("datetime64[ns]"))
    energy_axis = VariableAxis(values=energy, name="energy_table_mass", is_time_dependent=False)
    values = DataContainer(
        values=flux,
        meta={"FILLVAL": -9.999999848243207e30},
        is_time_dependent=True,
    )
    return SpeasyVariable(axes=[time_axis, energy_axis], values=values)


def test_fetch_day_masks_fillval_and_noise_threshold(monkeypatch):
    from sciqlop_msa import moments_source

    energy = np.array([10.0, 100.0, 1000.0])
    times = np.array(["2025-01-08T00:00:00", "2025-01-08T00:01:00"], dtype="datetime64[s]")
    flux = np.array([
        [1e6, -9.999999848243207e30, 1e4],
        [1e7, 1e6, 1e5],
    ])
    fake_var = _make_fake_variable(flux, energy, times)

    import speasy
    monkeypatch.setattr(speasy, "get_data", lambda *a, **kw: fake_var)

    result = moments_source.fetch_day("h_plus", date(2025, 1, 8))

    assert result is not None
    assert result.energy.tolist() == pytest.approx([10.0, 100.0, 1000.0])
    assert result.flux.shape == (2, 3)
    assert np.isnan(result.flux[0, 1])  # FILLVAL -> NaN
    assert np.isnan(result.flux[0, 2])  # below NOISE_FLUX_THRESHOLD -> NaN
    assert result.flux[0, 0] == pytest.approx(1e6)
    assert result.flux[1, 2] == pytest.approx(1e5)  # exactly at threshold: kept
    assert len(result.time) == 2


def test_fetch_day_returns_none_when_speasy_has_no_data(monkeypatch):
    from sciqlop_msa import moments_source
    import speasy

    monkeypatch.setattr(speasy, "get_data", lambda *a, **kw: None)

    result = moments_source.fetch_day("h_plus", date(2020, 1, 1))

    assert result is None


def test_fetch_day_rejects_unknown_species():
    from sciqlop_msa import moments_source

    with pytest.raises(KeyError):
        moments_source.fetch_day("not_a_species", date(2025, 1, 8))


def test_species_variable_keys_match_species_mass_table():
    from sciqlop_msa import moments_fit, moments_source

    assert set(moments_source._SPECIES_VARIABLE) == set(moments_fit.SPECIES_MASS_TABLE)
