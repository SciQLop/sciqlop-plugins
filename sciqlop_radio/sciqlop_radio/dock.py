"""RadioSpectraDock — Fido search/fetch dock that pushes results onto the
SciQLop main timeline as virtual products (per `user_api/virtual_products`).

The dock owns no plot widgets. Each fetched (or local) spectrogram is
converted to a 2-D `SpeasyVariable`, registered as a
`VirtualProductType.Spectrogram` at path `radio/<source>/<file-stem>`,
then plotted on a fresh `create_plot_panel()`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QDateTime, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDateTimeEdit, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QAbstractItemView, QLineEdit, QTableWidget, QTableWidgetItem,
    QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from .fetch import RadioFetchService, _row_field, _row_url
from .plot import (
    RadioPlotError, concat_variables_along_time, frequency_signature,
    spectrogram_to_speasy_variable,
)
from .query import RadioQuery
from .reader import open_spectrogram
from .settings import RadioSettings
from .sources import SOURCES, RadioSource


def _file_signature(path: Path) -> tuple[str, int, int]:
    """Stable cache key for a file on disk: (abs path, mtime_ns, size)."""
    stat = path.stat()
    return (str(path.resolve()), int(stat.st_mtime_ns), int(stat.st_size))


def _open_and_convert_uncached(sig):  # noqa: ARG001 — sig is the cache key only
    """Inner worker for the cached open+convert step."""
    return spectrogram_to_speasy_variable(open_spectrogram(Path(sig[0])))


def _make_cached_open_and_convert():
    from datetime import timedelta
    from speasy.core.cache import CacheCall

    @CacheCall(cache_retention=timedelta(days=30), is_pure=True)
    def _cached(sig):  # noqa: ARG001
        return _open_and_convert_uncached(sig)

    return _cached


_cached_open_and_convert = None


def _open_and_convert(path: Path):
    """Open a file and convert to SpeasyVariable, hitting Speasy's disk
    cache when possible. Cross-session: re-plotting an already-seen file
    skips both the radiospectra parse and the numpy reshape. Falls back
    to a direct parse if Speasy's cache layer isn't importable."""
    global _cached_open_and_convert
    sig = _file_signature(path)
    try:
        if _cached_open_and_convert is None:
            _cached_open_and_convert = _make_cached_open_and_convert()
        return _cached_open_and_convert(sig)
    except Exception:  # noqa: BLE001 — Speasy cache may be unavailable in tests
        return _open_and_convert_uncached(sig)


# Extensions radiospectra has a parser for. Anything else Fido returns
# (e.g. STEREO/SWAVES TDS-max .txt summaries, which are peak-amplitude
# time series rather than dynamic spectra) is dropped from the results
# list — the plugin only does radio spectrograms.
_SUPPORTED_EXTENSIONS = (
    ".cdf", ".fits", ".fit", ".fits.gz", ".fit.gz",
    ".srs",          # RSTN ASCII flux
    ".r1", ".r2",    # Wind/WAVES daily binaries
    ".dat",          # I-LOFAR mode 357 BST (radiospectra parses by filename)
)


def _is_supported_filename(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(ext) for ext in _SUPPORTED_EXTENSIONS)


def _safe_basename(path: Path) -> str:
    """Filesystem name minus extensions, lowercased, slashes stripped — safe to
    embed in a virtual-product tree path."""
    name = path.name
    for ext in (".fits.gz", ".fit.gz", ".fits", ".fit", ".cdf", ".dat"):
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
            break
    return name.replace("/", "_")


def _parse_float(text: str) -> float | None:
    text = (text or "").strip()
    try:
        return float(text) if text else None
    except ValueError:
        return None


def _source_for_instrument(instrument: str | None) -> RadioSource | None:
    """Find the curated source whose Fido instrument matches (case-insensitive)."""
    if not instrument:
        return None
    inst = instrument.strip().lower()
    return next((s for s in SOURCES
                 if s.fido_instrument and s.fido_instrument.lower() == inst), None)


class RadioSpectraDock(QWidget):
    """Source picker + time range + result list. No embedded plots."""

    _results_changed = Signal()
    _status_changed = Signal()

    def __init__(
        self,
        main_window=None,
        fetch_service: Optional[RadioFetchService] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Radio Spectra")
        self._main_window = main_window
        _cfg = RadioSettings()
        self._svc = fetch_service or RadioFetchService(
            cache_dir=_cfg.cache_dir,
            timeout_s=_cfg.download_timeout_s,
        )
        # Keep VirtualProduct refs alive; SciQLop tree holds the callback weakly.
        self._virtual_products: dict[str, object] = {}
        self._current_source: RadioSource | None = None
        self._current_expect_spectrogram = True

        root = QVBoxLayout(self)

        controls = QHBoxLayout()
        self.source_combo = QComboBox()
        for src in SOURCES:
            self.source_combo.addItem(src.label, src)
        controls.addWidget(QLabel("Source:"))
        controls.addWidget(self.source_combo, 1)

        self.open_local_button = QPushButton("Open local…")
        controls.addWidget(self.open_local_button)
        root.addLayout(controls)

        times = QHBoxLayout()
        now = QDateTime.currentDateTimeUtc()
        self.start_picker = QDateTimeEdit(now.addDays(-1))
        self.end_picker = QDateTimeEdit(now)
        for w in (self.start_picker, self.end_picker):
            w.setCalendarPopup(True)
            w.setDisplayFormat("yyyy-MM-dd HH:mm")
        times.addWidget(QLabel("Start (UTC):"))
        times.addWidget(self.start_picker)
        times.addWidget(QLabel("End (UTC):"))
        times.addWidget(self.end_picker)
        self.fetch_button = QPushButton("Fetch")
        times.addWidget(self.fetch_button)
        root.addLayout(times)

        self.advanced_group = QGroupBox("Advanced")
        self.advanced_group.setCheckable(True)
        self.advanced_group.setChecked(False)
        adv = QVBoxLayout(self.advanced_group)
        adv_row1 = QHBoxLayout()
        self.adv_instrument = QComboBox()
        self.adv_instrument.setEditable(True)
        for name in ("RFS", "eCALLISTO", "ILOFAR", "RSTN"):
            self.adv_instrument.addItem(name)
        self.adv_wl_min = QLineEdit()
        self.adv_wl_min.setPlaceholderText("λ min")
        self.adv_wl_max = QLineEdit()
        self.adv_wl_max.setPlaceholderText("λ max")
        adv_row1.addWidget(QLabel("Instrument:"))
        adv_row1.addWidget(self.adv_instrument, 1)
        adv_row1.addWidget(QLabel("λ (MHz):"))
        adv_row1.addWidget(self.adv_wl_min)
        adv_row1.addWidget(QLabel("–"))
        adv_row1.addWidget(self.adv_wl_max)
        adv.addLayout(adv_row1)
        adv_row2 = QHBoxLayout()
        self.adv_raw = QLineEdit()
        self.adv_raw.setPlaceholderText("Raw Fido query, e.g. a.Time('…','…'), a.Instrument('…')")
        adv_row2.addWidget(QLabel("Raw:"))
        adv_row2.addWidget(self.adv_raw, 1)
        adv.addLayout(adv_row2)
        adv.addWidget(QLabel("⚠ Advanced/raw results may not be plottable spectrograms."))
        root.addWidget(self.advanced_group)

        filters = QHBoxLayout()
        self.text_filter = QLineEdit()
        self.text_filter.setPlaceholderText("Filter results…")
        self.station_filter = QComboBox()
        self.station_filter.addItem("All stations", "")
        filters.addWidget(QLabel("Filter:"))
        filters.addWidget(self.text_filter, 1)
        filters.addWidget(QLabel("Station:"))
        filters.addWidget(self.station_filter)
        root.addLayout(filters)

        self.text_filter.textChanged.connect(self._apply_filters)
        self.station_filter.currentIndexChanged.connect(self._apply_filters)

        self.results_table = QTableWidget(0, 3)
        self.results_table.setHorizontalHeaderLabels(["Start Time", "Station", "File"])
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.setSortingEnabled(True)
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        root.addWidget(self.results_table, 1)
        self.plot_button = QPushButton("Plot selected")
        root.addWidget(self.plot_button)

        self.status_label = QLabel("ready")
        self.status_label.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.fetch_button.clicked.connect(self._on_fetch_clicked)
        self.open_local_button.clicked.connect(self._on_open_local_clicked)
        self.plot_button.clicked.connect(self._on_plot_selected_clicked)
        self._svc.searchCompleted.connect(self._on_search_completed)
        self._svc.searchFailed.connect(self._on_search_failed)
        self._svc.fetchCompleted.connect(self._on_fetch_completed)
        self._svc.fetchFailed.connect(self._on_fetch_failed)

    def _on_fetch_clicked(self):
        query = (self._build_advanced_query() if self.advanced_group.isChecked()
                 else self._build_simple_query())
        if query is None:
            return
        self._clear_results()
        self._svc.search(query)

    def _build_simple_query(self) -> "RadioQuery | None":
        source: RadioSource = self.source_combo.currentData()
        if source.unavailable_reason:
            self._set_status(source.unavailable_reason)
            return None
        if not source.fido_instrument:
            self._set_status(f"{source.label} is local-only — use 'Open local…'")
            return None
        t0, t1 = self._time_range()
        if t1 <= t0:
            self._set_status("End time must be after start time")
            return None
        self._current_source = source
        self._current_expect_spectrogram = True
        self._set_status(f"Searching {source.label}…")
        return RadioQuery.from_source(source, t0, t1)

    def _build_advanced_query(self) -> "RadioQuery | None":
        t0, t1 = self._time_range()
        if t1 <= t0:
            self._set_status("End time must be after start time")
            return None
        raw = self.adv_raw.text().strip()
        self._current_source = None
        if raw:
            self._current_expect_spectrogram = False
            self._set_status("Searching (raw query)…")
            return RadioQuery(t_start=t0, t_end=t1, raw_attrs_text=raw,
                              expect_spectrogram=False)
        instrument = self.adv_instrument.currentText().strip() or None
        wl_min = _parse_float(self.adv_wl_min.text())
        wl_max = _parse_float(self.adv_wl_max.text())
        # Matching the instrument back to a curated source lets advanced
        # searches reuse its key (for the virtual-product path) and its
        # example_range (for the empty-results hint).
        self._current_source = _source_for_instrument(instrument)
        self._current_expect_spectrogram = True
        self._set_status(f"Searching {instrument or 'advanced'}…")
        return RadioQuery(t_start=t0, t_end=t1, instrument=instrument,
                          wavelength_min_mhz=wl_min, wavelength_max_mhz=wl_max,
                          expect_spectrogram=True)

    def _time_range(self):
        t0 = self.start_picker.dateTime().toPython().replace(tzinfo=timezone.utc)
        t1 = self.end_picker.dateTime().toPython().replace(tzinfo=timezone.utc)
        return t0, t1

    def _on_open_local_clicked(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Open local radio file", "", "Radio data (*.cdf *.fits *.fit *.fit.gz *.dat);;All files (*)"
        )
        if paths:
            self._plot_paths([Path(p) for p in paths], source_key="local")

    def _on_plot_selected_clicked(self):
        rows = self._selected_rows()
        if not rows:
            self._set_status("No rows selected")
            return
        self._set_status(f"Fetching {len(rows)} file(s)…")
        self._svc.fetch(rows)

    def _on_search_completed(self, rows: list):
        self.results_table.setSortingEnabled(False)
        self.results_table.setRowCount(0)
        skipped = 0
        for row in rows:
            url = _row_url(row)
            name = url.rsplit("/", 1)[-1] if url else repr(row)
            if self._current_expect_spectrogram and not _is_supported_filename(name):
                skipped += 1
                continue
            r = self.results_table.rowCount()
            self.results_table.insertRow(r)
            start_item = QTableWidgetItem(_row_field(row, "Start Time"))
            start_item.setData(Qt.UserRole, row)
            self.results_table.setItem(r, 0, start_item)
            self.results_table.setItem(r, 1, QTableWidgetItem(_row_field(row, "Observatory")))
            self.results_table.setItem(r, 2, QTableWidgetItem(name))
        self.results_table.setSortingEnabled(True)
        count = self.results_table.rowCount()
        if count == 0 and not skipped:
            self._set_status(self._empty_results_message())
        else:
            msg = f"Found {count} spectrogram file(s)"
            if skipped:
                msg += f" ({skipped} non-spectrogram row(s) hidden)"
            self._set_status(msg)
        self._refresh_station_filter()
        self._apply_filters()
        self._results_changed.emit()

    def _empty_results_message(self) -> str:
        src = self._current_source
        if src is not None and src.example_range:
            return (f"No data for {src.label} in this range. "
                    f"Coverage may be sparse; try e.g. {src.example_range}.")
        return "No spectrogram files found in this range."

    def _table_filename(self, rowidx: int) -> str:
        item = self.results_table.item(rowidx, 2)
        return item.text() if item else ""

    def _table_station(self, rowidx: int) -> str:
        item = self.results_table.item(rowidx, 1)
        return item.text() if item else ""

    def _refresh_station_filter(self):
        stations = sorted({self._table_station(i)
                           for i in range(self.results_table.rowCount())
                           if self._table_station(i)})
        self.station_filter.blockSignals(True)
        self.station_filter.clear()
        self.station_filter.addItem("All stations", "")
        for s in stations:
            self.station_filter.addItem(s, s)
        self.station_filter.blockSignals(False)

    def _apply_filters(self):
        needle = self.text_filter.text().strip().lower()
        station = self.station_filter.currentData() or ""
        for i in range(self.results_table.rowCount()):
            start_item = self.results_table.item(i, 0)
            start_text = start_item.text().lower() if start_item else ""
            text_hit = (needle in self._table_filename(i).lower()
                        or needle in self._table_station(i).lower()
                        or needle in start_text)
            station_hit = (not station) or self._table_station(i) == station
            self.results_table.setRowHidden(i, not (text_hit and station_hit))

    def _selected_rows(self) -> list:
        rows = []
        for idx in self.results_table.selectionModel().selectedRows():
            # Filtering hides rows without deselecting them; only act on rows
            # the user can actually see as selected.
            if self.results_table.isRowHidden(idx.row()):
                continue
            item = self.results_table.item(idx.row(), 0)
            if item is not None:
                rows.append(item.data(Qt.UserRole))
        return rows

    def _on_search_failed(self, message: str):
        self._clear_results()
        self._set_status(f"Search failed: {message}")

    def _on_fetch_completed(self, ok: list, failed: list):
        # Use the source the active search was built from, not whatever the
        # dropdown currently shows — advanced/raw fetches have no live source.
        source = self._current_source
        source_key = source.key if source is not None else "advanced"
        self._plot_paths(list(ok), source_key=source_key)
        msg = f"Downloaded {len(ok)} file(s)"
        if failed:
            msg += f"; {len(failed)} failed"
        self._set_status(msg)

    def _on_fetch_failed(self, message: str):
        self._set_status(f"Fetch failed: {message}")

    def _plot_paths(self, paths: list[Path], source_key: str):
        """Convert each spectrogram → SpeasyVariable, register as a virtual
        product, then push onto a fresh main-timeline panel. The panel's
        time range is set to span all loaded variables — otherwise it
        defaults to "now" and the data looks empty."""
        errors: list[tuple[str, str]] = []
        plotted = 0
        try:
            from SciQLop.core import TimeRange
            from SciQLop.user_api.plot import create_plot_panel
            from SciQLop.user_api.virtual_products import (
                create_virtual_product, VirtualProductType,
            )
        except ImportError as exc:
            self._set_status(f"SciQLop user-API unavailable: {exc}")
            return

        # Convert all selected files (cached per file), collecting errors.
        converted: list[tuple[Path, object]] = []
        for path in paths:
            try:
                converted.append((path, _open_and_convert(path)))
            except RadioPlotError as e:
                errors.append((path.name, str(e)))
            except Exception as e:  # noqa: BLE001 — final user-facing safety net
                errors.append((path.name, f"{type(e).__name__}: {e}"))

        # Group files that share a frequency grid so the same instrument at
        # different times merges into one continuous spectrogram on one plot.
        # Different grids (e.g. distinct eCALLISTO stations) stay separate.
        groups: dict = {}
        order: list = []
        for path, variable in converted:
            try:
                sig = frequency_signature(variable)
            except Exception:  # noqa: BLE001 — unkeyable → never merge
                sig = ("unkeyed", id(variable))
            if sig not in groups:
                groups[sig] = []
                order.append(sig)
            groups[sig].append((path, variable))

        panel = None
        files_plotted = 0
        t_min: float | None = None
        t_max: float | None = None
        for sig in order:
            member_paths = [p for p, _ in groups[sig]]
            member_vars = [v for _, v in groups[sig]]
            try:
                merged = (concat_variables_along_time(member_vars)
                          if len(member_vars) > 1 else member_vars[0])
            except Exception as e:  # noqa: BLE001
                for p in member_paths:
                    errors.append((p.name, f"merge: {type(e).__name__}: {e}"))
                continue
            vp_path = _group_vp_path(source_key, member_paths)
            try:
                vp = create_virtual_product(
                    vp_path, _build_static_callback(merged), VirtualProductType.Spectrogram,
                )
            except Exception as e:  # noqa: BLE001
                errors.append((member_paths[0].name, f"create_virtual_product: {type(e).__name__}: {e}"))
                continue
            self._virtual_products[vp_path] = vp
            if panel is None:
                panel = create_plot_panel()
            try:
                panel.plot(vp)
                plotted += 1
                files_plotted += len(member_paths)
                v_t0, v_t1 = _variable_time_bounds(merged)
                if v_t0 is not None and v_t1 is not None:
                    t_min = v_t0 if t_min is None else min(t_min, v_t0)
                    t_max = v_t1 if t_max is None else max(t_max, v_t1)
            except Exception as e:  # noqa: BLE001
                errors.append((member_paths[0].name, f"plot: {type(e).__name__}: {e}"))

        if panel is not None and t_min is not None and t_max is not None:
            try:
                panel.time_range = TimeRange(t_min, t_max)
            except Exception as e:  # noqa: BLE001
                errors.append(("<panel time range>", f"set_time_range: {type(e).__name__}: {e}"))

        if errors and plotted == 0:
            detail = "\n\n".join(f"{name}:\n  {err}" for name, err in errors)
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Could not plot")
            box.setText(f"None of the {len(paths)} file(s) could be plotted.")
            box.setDetailedText(detail)
            box.setTextInteractionFlags(Qt.TextSelectableByMouse)
            box.exec()
            self._set_status(f"Plot failed for {len(errors)} file(s); see dialog for details")
        elif errors:
            self._set_status(
                f"Plotted {files_plotted} file(s) in {plotted} plot(s); "
                f"{len(errors)} failed — last: {errors[-1][1][:120]}"
            )
        elif plotted:
            self._set_status(f"Plotted {files_plotted} file(s) in {plotted} plot(s)")

    def _clear_results(self):
        self.results_table.setRowCount(0)
        self._results_changed.emit()

    def _set_status(self, text: str):
        self.status_label.setText(text)
        self._status_changed.emit()


def _group_vp_path(source_key: str, paths: list[Path]) -> str:
    """Virtual-product tree path for a (possibly merged) group of files."""
    first = _safe_basename(paths[0])
    if len(paths) == 1:
        return f"radio/{source_key}/{first}"
    return f"radio/{source_key}/{first}__+{len(paths) - 1}more"


def _build_static_callback(variable):
    """Closure SciQLop will call as `f(start, stop) → SpeasyVariable`.

    Radio data is a fixed time window (whatever was fetched); we return
    the same SpeasyVariable regardless of the requested range — SciQLop
    handles display clipping itself.
    """
    def _callback(start, stop):  # noqa: ARG001
        return variable
    return _callback


def _variable_time_bounds(variable) -> tuple[float | None, float | None]:
    """Return (start_epoch, stop_epoch) seconds of a SpeasyVariable, or
    (None, None) if it has no time data."""
    try:
        time = variable.time
        if time is None or len(time) == 0:
            return None, None
        t_ns = time.astype("datetime64[ns]").astype("int64")
        return float(t_ns[0]) / 1e9, float(t_ns[-1]) / 1e9
    except Exception:  # noqa: BLE001
        return None, None
