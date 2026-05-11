def test_package_imports():
    import sciqlop_radio
    assert sciqlop_radio.__version__ == "0.1.0"


# Transient: delete this test when Task 8 wires the real load(); the
# replacement load-test requires QApplication and lives in test_load.py.
def test_load_is_not_implemented_yet():
    import sciqlop_radio
    import pytest
    with pytest.raises(NotImplementedError):
        sciqlop_radio.load(main_window=None)
