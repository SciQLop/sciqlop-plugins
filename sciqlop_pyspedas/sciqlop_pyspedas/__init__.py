"""sciqlop_pyspedas — experimental MMS particle spectra from pyspedas."""

__version__ = "0.1.1"

_REGISTERED: dict = {}


def load(main_window):
    """SciQLop entry point: register the MMS spectra products once."""
    from . import virtual_products

    if not _REGISTERED:
        _REGISTERED.update(virtual_products.register_all())
