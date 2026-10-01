"""Dock showing, record by record, the spectrum a moment fit used and every model it tried."""
import threading
from datetime import date, datetime, timezone

import numpy as np
from PySide6.QtCore import QDate, QObject, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QHBoxLayout, QLabel, QPushButton, QSlider,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .moments_fit import CHI2_MAX, NOISE_FLUX_THRESHOLD, SPECIES_MASS_TABLE
from .moments_inspect import BEST_CURVE_LABELS, CANDIDATE_MODELS, best_curves, candidate_totals, \
    inspectable_records, load_day, record_view

_DEFAULT_DAY = QDate(2025, 1, 8)
_TABLE_COLUMNS = ("Model", "χ²", "n (cm⁻³)", "T_c (eV)", "T_eff (eV)", "Parameters", "Status")
_USED, _DROPPED, _FLOOR = QColor("#1f2937"), QColor("#9ca3af"), QColor("#dc2626")
_BEST_COLORS = [QColor(c) for c in ("#2563eb", "#16a34a", "#ea580c", "#9333ea", "#111827")]
_CANDIDATE_COLORS = [QColor(c) for c in ("#93c5fd", "#86efac", "#fdba74")]


def _log_plot(x_label: str, y_label: str):
    from SciQLopPlots import SciQLopPlot

    plot = SciQLopPlot()
    for axis, label in ((plot.x_axis(), x_label), (plot.y_axis(), y_label)):
        axis.set_log(True)
        axis.set_label(label)
    return plot


def _where(mask: np.ndarray, values: np.ndarray) -> np.ndarray:
    return np.ascontiguousarray(np.where(mask, values, np.nan))


def _candidate_row(candidate, index: int, accepted) -> tuple:
    params = ", ".join(f"{k}={v:.3g}" for k, v in candidate.params.items() if k != "model")
    if candidate is accepted:
        status = "accepted"
    elif index == 0:
        status = f"rejected (χ² > {CHI2_MAX:g})"
    else:
        status = ""
    return (candidate.model, f"{candidate.chi2:.3g}", f"{candidate.n_tot:.3g}", f"{candidate.T_c:.3g}",
            f"{candidate.T_eff:.3g}", params, status)


class _DayLoader(QObject):
    loaded = Signal(object)

    def load(self, species: str, day: date):
        # The first fit of a day runs every record through three curve_fits: keep it off the GUI thread.
        threading.Thread(target=lambda: self.loaded.emit((species, day, load_day(species, day))),
                         daemon=True).start()


class FitInspector(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("MSA Fit Inspector")
        self._day_data = None
        self._records = []
        self._graphs = None
        self._loader = _DayLoader(self)
        self._loader.loaded.connect(self._on_day_loaded)
        self._build_ui()

    def _build_ui(self):
        self._species = QComboBox()
        self._species.addItems(list(SPECIES_MASS_TABLE))
        self._day = QDateEdit(_DEFAULT_DAY)
        self._day.setCalendarPopup(True)
        self._day.setDisplayFormat("yyyy-MM-dd")
        load = QPushButton("Load day")
        load.clicked.connect(self._request_day)
        self._record = QSlider(Qt.Horizontal)
        self._record.setEnabled(False)
        self._record.valueChanged.connect(lambda position: self._show_record(self._records[position]))
        self._fitted_only = QCheckBox("Fitted records only")
        self._fitted_only.setChecked(True)
        self._fitted_only.toggled.connect(self._reset_records)
        self._status = QLabel("Pick a species and a day, then load it.")
        self._flux_plot = _log_plot("Energy (eV)", "Energy flux (cm⁻² s⁻¹ sr⁻¹ eV⁻¹)")
        self._psd_plot = _log_plot("Energy (eV)", "Phase-space density (s³ m⁻⁶)")
        self._table = QTableWidget(0, len(_TABLE_COLUMNS))
        self._table.setHorizontalHeaderLabels(_TABLE_COLUMNS)
        self._table.horizontalHeader().setStretchLastSection(True)

        controls = QHBoxLayout()
        for widget in (QLabel("Species"), self._species, QLabel("Day"), self._day, load, self._fitted_only):
            controls.addWidget(widget)
        controls.addWidget(self._record, stretch=1)
        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self._status)
        layout.addWidget(self._flux_plot, stretch=2)
        layout.addWidget(self._psd_plot, stretch=3)
        layout.addWidget(self._table, stretch=1)

    def _request_day(self):
        self._record.setEnabled(False)
        self._status.setText("Loading and fitting the day, the first time can take a while…")
        self._loader.load(self._species.currentText(), self._day.date().toPython())

    def _on_day_loaded(self, result):
        species, day, loaded = result
        if (species, day) != (self._species.currentText(), self._day.date().toPython()):
            return
        if loaded.error:
            self._status.setText(loaded.error)
            return
        self._day_data = (species, loaded.spectra, loaded.fits)
        self._reset_records()

    def _reset_records(self):
        if self._day_data is None:
            return
        self._records = inspectable_records(self._day_data[2], self._fitted_only.isChecked())
        self._record.setEnabled(bool(self._records))
        if not self._records:
            self._status.setText("No record of this day has a fit; untick 'Fitted records only' to see them all.")
            return
        self._record.blockSignals(True)
        self._record.setRange(0, len(self._records) - 1)
        self._record.setValue(0)
        self._record.blockSignals(False)
        self._show_record(self._records[0])

    def _show_record(self, index: int):
        species, spectra, fits = self._day_data
        view = record_view(spectra, fits, index, species)
        A = SPECIES_MASS_TABLE[species][0]
        self._ensure_graphs(view.energy)
        self._update_graphs(view, A)
        self._fill_table(view)
        when = datetime.fromtimestamp(view.time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        verdict = view.accepted.model if view.accepted else "no accepted fit"
        self._status.setText(f"{species} — record {index + 1}/{len(spectra.time)} — {when} UTC — "
                             f"{int(view.used.sum())}/{len(view.used)} points used — {verdict}")

    def _ensure_graphs(self, energy: np.ndarray):
        from SciQLopPlots import GraphMarkerShape

        if self._graphs is not None:
            return
        nan = np.full(len(energy), np.nan)
        nans = lambda count: np.ascontiguousarray(np.full((len(energy), count), np.nan))
        self._graphs = {
            "flux_used": self._flux_plot.scatter(energy, nan, ["used"], [_USED], GraphMarkerShape.FilledCircle),
            "flux_dropped": self._flux_plot.scatter(energy, nan, ["dropped"], [_DROPPED], GraphMarkerShape.Circle),
            "floor": self._flux_plot.line(energy, np.full(len(energy), NOISE_FLUX_THRESHOLD), ["noise floor"],
                                          [_FLOOR]),
            "f_used": self._psd_plot.scatter(energy, nan, ["used"], [_USED], GraphMarkerShape.FilledCircle),
            "f_dropped": self._psd_plot.scatter(energy, nan, ["dropped"], [_DROPPED], GraphMarkerShape.Circle),
            "candidates": self._psd_plot.line(energy, nans(len(CANDIDATE_MODELS)),
                                              [f"{m} total" for m in CANDIDATE_MODELS], _CANDIDATE_COLORS),
            "best": self._psd_plot.line(energy, nans(len(BEST_CURVE_LABELS)),
                                        [f"best {label}" for label in BEST_CURVE_LABELS], _BEST_COLORS),
        }

    def _update_graphs(self, view, A: float):
        energy, g = view.energy, self._graphs
        g["flux_used"].set_data(energy, _where(view.used, view.flux))
        g["flux_dropped"].set_data(energy, _where(~view.used, view.flux))
        g["f_used"].set_data(energy, _where(view.used, view.f_obs))
        g["f_dropped"].set_data(energy, _where(~view.used, view.f_obs))
        g["candidates"].set_data(energy, np.ascontiguousarray(candidate_totals(view, A)))
        g["best"].set_data(energy, np.ascontiguousarray(best_curves(view, A)))
        for plot in (self._flux_plot, self._psd_plot):
            plot.rescale_axes()
            plot.replot()

    def _fill_table(self, view):
        rows = [_candidate_row(c, i, view.accepted) for i, c in enumerate(view.candidates)]
        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                self._table.setItem(r, c, QTableWidgetItem(text))
        self._table.resizeColumnsToContents()
