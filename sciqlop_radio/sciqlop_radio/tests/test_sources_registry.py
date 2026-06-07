import pytest

from sciqlop_radio.sources import RadioSource, SOURCES


# Only the instruments radiospectra ships a Fido client for, plus the
# local-file passthrough. RPW/WAVES/SWAVES were intentionally removed
# because radiospectra has no Fido client for them and the default
# sunpy clients return non-spectrogram data.
EXPECTED_KEYS = {
    "ecallisto",
    "eovsa",
    "ilofar",
    "psp_rfs",
    "rstn",
    "custom",
}


def test_sources_list_is_non_empty():
    assert len(SOURCES) >= 6


def test_every_source_has_unique_key():
    keys = [s.key for s in SOURCES]
    assert len(keys) == len(set(keys))


def test_expected_radiospectra_sources_present():
    keys = {s.key for s in SOURCES}
    missing = EXPECTED_KEYS - keys
    assert not missing, f"missing sources: {missing}"


@pytest.mark.parametrize("source", SOURCES, ids=lambda s: s.key)
def test_source_has_non_empty_key_and_label(source):
    assert source.key.strip()
    assert source.label.strip()


@pytest.mark.parametrize("source", SOURCES, ids=lambda s: s.key)
def test_source_is_reachable(source):
    """Every entry must be addressable: either has a Fido instrument arg
    OR can be opened from local files. The 'custom' radiospectra source
    is local-only by design (no Fido arg)."""
    assert source.fido_instrument or source.accepts_local


def test_radio_source_rejects_blank_key():
    with pytest.raises(ValueError):
        RadioSource(key="", label="foo")


def test_eovsa_is_marked_unavailable():
    """EOVSA spectrogram FITS moved behind registration; it must stay visible
    (so users find it) but not be a live Fido source."""
    eovsa = next(s for s in SOURCES if s.key == "eovsa")
    assert eovsa.fido_instrument is None
    assert eovsa.unavailable_reason
    assert "registration" in eovsa.unavailable_reason.lower()
    assert eovsa.accepts_local is True


def test_live_sources_have_example_range():
    for s in SOURCES:
        if s.fido_instrument:
            assert s.example_range, f"{s.key} missing example_range"
