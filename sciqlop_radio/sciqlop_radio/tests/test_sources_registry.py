import pytest

from sciqlop_radio.sources import RadioSource, SOURCES


EXPECTED_KEYS = {
    "ecallisto",
    "eovsa",
    "ilofar",
    "psp_rfs",
    "solo_rpw",
    "rstn",
    "stereo_swaves",
    "wind_waves",
    "custom",
}


def test_sources_list_is_non_empty():
    assert len(SOURCES) >= 9


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
