"""The "+" tab: open a local file, a URL, or one of the example files."""
from __future__ import annotations
from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QToolButton, QVBoxLayout, QWidget,
)


@dataclass(frozen=True)
class Example:
    title: str
    description: str
    url: str
    variable: str
    size: str


_CDAWEB = "https://cdaweb.gsfc.nasa.gov/pub/data"

# Same files as the CDFpp explorer (wacdfpp/presets.js), plus a particle distribution.
EXAMPLES = (
    Example("MMS1 FPI ion distribution",
            "Phi x theta x energy per record: the omnidirectional energy spectrogram by default.",
            f"{_CDAWEB}/mms/mms1/fpi/fast/l2/dis-dist/2021/07/mms1_fpi_fast_l2_dis-dist_20210705040000_v3.4.0.cdf",
            "mms1_dis_dist_fast", "90 MB"),
    Example("MMS1 FPI ion energy spectrum",
            "Omni-directional ion spectrogram, gzip-compressed variables.",
            f"{_CDAWEB}/mms/mms1/fpi/fast/l2/dis-moms/2021/07/mms1_fpi_fast_l2_dis-moms_20210705040000_v3.4.0.cdf",
            "mms1_dis_energyspectr_omni_fast", "2 MB"),
    Example("THEMIS-A ESA electrons",
            "A day of reduced-mode electron energy flux, with a time-varying energy table.",
            f"{_CDAWEB}/themis/tha/l2/esa/2021/tha_l2_esa_20210705_v01.cdf",
            "tha_peer_en_eflux", "20 MB"),
    Example("Solar Orbiter magnetic field",
            "A day of B in RTN, 691k vectors at 8 Hz.",
            f"{_CDAWEB}/solar-orbiter/mag/science/l2/rtn-normal/2021/solo_l2_mag-rtn-normal_20210705_v01.cdf",
            "B_RTN", "12 MB"),
    Example("OMNI SYM-H, July 2021",
            "A month of the 1-min ring current index, with fill values masked.",
            f"{_CDAWEB}/omni/omni_cdaweb/hro_1min/2021/omni_hro_1min_20210701_v01.cdf",
            "SYM_H", "9 MB"),
    Example("Cluster C1 FGM",
            "Spin-resolution magnetic field in GSE, times in CDF_EPOCH.",
            f"{_CDAWEB}/cluster/c1/cp/2003/c1_cp_fgm_spin_20030115_v01.cdf",
            "B_vec_xyz_gse__C1_CP_FGM_SPIN", "0.4 MB"),
    Example("MMS1 burst electric field",
            "65 kHz waveform in burst segments: zoom down to single samples.",
            "https://lasp.colorado.edu/mms/sdc/public/files/api/v1/download/science"
            "?file=mms1_edp_brst_l2_hmfe_20210705040813_v2.0.0.cdf",
            "mms1_edp_hmfe_par_epar_brst_l2", "111 MB"),
)


def _example_button(example: Example) -> QToolButton:
    button = QToolButton()
    button.setText(f"{example.title}\n{example.variable} · {example.size}")
    button.setToolTip(f"{example.description}\n{example.url}")
    button.setToolButtonStyle(Qt.ToolButtonTextOnly)
    button.setMinimumWidth(260)
    return button


class OpenPage(QWidget):
    open_requested = Signal(str, str)  # source, variable to select ("" for none)
    browse_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.addStretch()

        layout.addWidget(QLabel("Drop CDF files here, or:"), alignment=Qt.AlignHCenter)
        browse = QPushButton("Open file…")
        browse.clicked.connect(self.browse_requested)
        layout.addWidget(browse, alignment=Qt.AlignHCenter)

        url_row = QHBoxLayout()
        self._url = QLineEdit()
        self._url.setPlaceholderText("https://… .cdf")
        self._url.setMinimumWidth(480)
        self._url.returnPressed.connect(self._request_url)
        open_url = QPushButton("Open URL")
        open_url.clicked.connect(self._request_url)
        url_row.addStretch()
        url_row.addWidget(self._url)
        url_row.addWidget(open_url)
        url_row.addStretch()
        layout.addLayout(url_row)

        self._status = QLabel()
        self._status.setWordWrap(True)
        layout.addWidget(self._status, alignment=Qt.AlignHCenter)

        layout.addWidget(QLabel("Or try one of these files:"), alignment=Qt.AlignHCenter)
        grid = QGridLayout()
        self._example_buttons = []
        for i, example in enumerate(EXAMPLES):
            button = _example_button(example)
            button.clicked.connect(lambda _=False, e=example: self.open_requested.emit(e.url, e.variable))
            grid.addWidget(button, i // 2, i % 2)
            self._example_buttons.append(button)
        grid_row = QHBoxLayout()
        grid_row.addStretch()
        grid_row.addLayout(grid)
        grid_row.addStretch()
        layout.addLayout(grid_row)
        layout.addStretch()

    def set_status(self, text: str):
        self._status.setText(text)

    def status(self) -> str:
        return self._status.text()

    def _request_url(self):
        url = self._url.text().strip()
        if url:
            self.open_requested.emit(url, "")
