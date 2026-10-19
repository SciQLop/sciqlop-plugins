"""The "+" tab: open a file, a URL, or one of the example files."""
import pytest

from cdf_workbench.open_page import EXAMPLES, OpenPage


@pytest.fixture
def page(qtbot):
    w = OpenPage()
    qtbot.addWidget(w)
    return w


def test_entering_a_url_requests_it(page, qtbot):
    page._url.setText("  https://example.org/a.cdf ")
    with qtbot.waitSignal(page.open_requested) as signal:
        page._url.returnPressed.emit()
    assert signal.args == ["https://example.org/a.cdf", ""]


def test_an_empty_url_requests_nothing(page, qtbot):
    with qtbot.assertNotEmitted(page.open_requested):
        page._url.returnPressed.emit()


def test_an_example_opens_on_its_variable(page, qtbot):
    with qtbot.waitSignal(page.open_requested) as signal:
        page._example_buttons[0].click()
    assert signal.args == [EXAMPLES[0].url, EXAMPLES[0].variable]


def test_examples_are_complete_https_and_unique():
    assert all(e.url.startswith("https://") and e.title and e.variable and e.size for e in EXAMPLES)
    assert len({e.title for e in EXAMPLES}) == len(EXAMPLES)
