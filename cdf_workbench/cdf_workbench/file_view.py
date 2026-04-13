from __future__ import annotations
import logging
import multiprocessing
import numpy as np
from PySide6.QtCore import Qt, QThread, QTimer, Signal, QObject, QSortFilterProxyModel
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QSplitter, QTreeView, QLineEdit, QMenu,
)
import pycdfpp

from .tree_model import CdfTreeModel, CdfItemDelegate, VariableInfo
from .inspector import CdfInspectorWidget
from .preview import CdfPreviewWidget
from .quality import analyze_quality, QualityReport
from .lint import run_lint, LintReport

logger = logging.getLogger(__name__)

# Size threshold for skipping sparklines (100 MB)
SPARKLINE_SIZE_LIMIT = 100 * 1024 * 1024

# A 2D variable without DISPLAY_TYPE=spectrogram is drawn as N line components.
# Above this threshold the plot becomes unusable and freezes the UI (e.g. CDFs
# where axis-1 is samples-per-record, not components).
MAX_LINE_COMPONENTS = 32


class AnalysisWorker(QObject):
    """Runs quality analysis and sparkline extraction in a background thread."""
    # Use Signal(str, object) for cross-thread safety with custom types
    quality_ready = Signal(str, object)   # var_name, QualityReport
    sparkline_ready = Signal(str, object) # var_name, list[float]

    def __init__(self, cdf: pycdfpp.CDF, variable_infos: dict[str, VariableInfo]):
        super().__init__()
        self._cdf = cdf
        self._infos = variable_infos
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        for name, info in self._infos.items():
            if self._cancelled:
                return
            try:
                var = self._cdf[name]
                estimated_size = np.prod(var.shape) * 8
                values = var.values

                # Quality analysis
                epochs = None
                if info.depend_0 and info.depend_0 in self._cdf:
                    epochs = self._cdf[info.depend_0].values.astype("datetime64[ns]")
                report = analyze_quality(
                    values=values,
                    epochs=epochs,
                    fill_value=info.fill_value,
                    valid_min=info.valid_min,
                    valid_max=info.valid_max,
                )
                self.quality_ready.emit(name, report)

                # Sparkline: downsample to ~60 points
                if estimated_size < SPARKLINE_SIZE_LIMIT:
                    flat = values.ravel()
                    if info.fill_value is not None:
                        typed_fill = np.array(info.fill_value, dtype=flat.dtype)
                        flat = flat[flat != typed_fill]
                    flat = flat.astype(float)
                    if len(flat) > 60:
                        indices = np.linspace(0, len(flat) - 1, 60, dtype=int)
                        flat = flat[indices]
                    samples = [float(v) for v in flat if np.isfinite(v)]
                    if samples:
                        self.sparkline_ready.emit(name, samples)
            except Exception:
                logger.debug("Analysis failed for %s", name, exc_info=True)


_NON_PLOTTABLE_TYPES = {pycdfpp.DataType.CDF_CHAR, pycdfpp.DataType.CDF_UCHAR, pycdfpp.DataType.CDF_NONE}
_TIME_TYPES = {pycdfpp.DataType.CDF_EPOCH, pycdfpp.DataType.CDF_EPOCH16, pycdfpp.DataType.CDF_TIME_TT2000}


def _is_plottable(info: VariableInfo) -> bool:
    if info.cdf_type in _NON_PLOTTABLE_TYPES:
        return False
    if info.display_type.lower() == "no_plot":
        return False
    ndim = len(info.shape)
    if ndim == 0 or ndim > 2 or any(s == 0 for s in info.shape):
        return False
    if ndim == 2 and info.display_type.lower() != "spectrogram" and info.shape[1] > MAX_LINE_COMPONENTS:
        return False
    return True


def _lint_in_subprocess(source: str, conn):
    """Entry point for the lint subprocess — runs lint and sends result back."""
    report = run_lint(source)
    conn.send(report)
    conn.close()


class CdfFileView(QWidget):
    def __init__(self, cdf: pycdfpp.CDF, source: str = "", main_window=None, parent=None):
        super().__init__(parent)
        self._cdf = cdf
        self._source = source
        self._main_window = main_window
        self._quality_reports: dict[str, QualityReport] = {}
        self._lint_report: LintReport | None = None
        self._setup_ui()
        self._start_quality_analysis()
        self._start_lint()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)

        # Left pane: search + tree
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Filter variables...")
        self._search.textChanged.connect(self._on_filter_changed)
        left_layout.addWidget(self._search)

        self._tree_model = CdfTreeModel(self._cdf)
        self._proxy_model = QSortFilterProxyModel()
        self._proxy_model.setSourceModel(self._tree_model)
        self._proxy_model.setRecursiveFilteringEnabled(True)
        self._proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)

        self._tree_view = QTreeView()
        self._tree_view.setModel(self._proxy_model)
        self._tree_view.setHeaderHidden(True)
        self._tree_view.expandAll()
        self._tree_view.selectionModel().currentChanged.connect(self._on_variable_selected)

        self._delegate = CdfItemDelegate()
        self._tree_view.setItemDelegate(self._delegate)

        # Context menu
        self._tree_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self._tree_view.customContextMenuRequested.connect(self._show_context_menu)

        left_layout.addWidget(self._tree_view)
        splitter.addWidget(left)

        # Right pane: inspector + preview
        right_splitter = QSplitter(Qt.Vertical)

        self._inspector = CdfInspectorWidget()
        self._inspector.dependency_clicked.connect(self._navigate_to_variable)
        self._inspector.plot_new_panel.connect(self._plot_new_panel)
        self._inspector.plot_to_panel.connect(self._plot_to_panel)
        right_splitter.addWidget(self._inspector)

        if self._main_window is not None:
            self._inspector.set_panel_names(self._main_window.plot_panels())
            self._main_window.panels_list_changed.connect(self._inspector.set_panel_names)

        self._preview = CdfPreviewWidget()
        right_splitter.addWidget(self._preview)

        self._right_splitter = right_splitter

        splitter.addWidget(right_splitter)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(splitter)
        self._show_global_attributes()

    def showEvent(self, event):
        super().showEvent(event)
        h = self._right_splitter.height()
        if h > 0:
            self._right_splitter.setSizes([h * 3 // 4, h // 4])

    def _show_global_attributes(self):
        attrs = {}
        for name, attr in self._cdf.attributes.items():
            try:
                attrs[name] = [v for v in attr]
            except Exception:
                attrs[name] = []
        self._inspector.show_global_attributes(attrs)

    def _on_filter_changed(self, text: str):
        self._proxy_model.setFilterFixedString(text)

    def _on_variable_selected(self, current, previous):
        source_index = self._proxy_model.mapToSource(current)
        node = source_index.internalPointer()
        if node is None or node.variable_info is None:
            self._show_global_attributes()
            self._preview.clear()
            return

        info = node.variable_info
        quality = self._quality_reports.get(info.name)
        self._inspector.update_variable(info, quality)
        self._update_preview(info)

    def _resolve_labels(self, info: VariableInfo) -> list[str]:
        if info.labl_ptr_1 and info.labl_ptr_1 in self._cdf:
            raw = self._cdf[info.labl_ptr_1].values
            if hasattr(raw, 'tolist'):
                # pycdfpp returns CDF_CHAR as ndarray of bytes, shape varies:
                # NRV scalar: (n_components,) or (1, n_components)
                # time-varying: (n_records, n_components)
                while raw.ndim > 1:
                    raw = raw[-1]
                return [s.decode().strip() if isinstance(s, bytes) else str(s).strip() for s in raw.tolist()]
        if info.lablaxis:
            return [info.lablaxis]
        if info.fieldnam:
            return [info.fieldnam]
        return [info.name]

    def _resolve_epochs(self, info: VariableInfo, values: np.ndarray) -> tuple[np.ndarray | None, bool]:
        """Resolve the x-axis for a variable, handling non-ISTP files.

        Returns (epochs_array_or_None, is_time_axis).
        """
        n_records = values.shape[0]

        # Try DEPEND_0 first
        if info.depend_0 and info.depend_0 in self._cdf:
            dep0_var = self._cdf[info.depend_0]
            if dep0_var.shape[0] == n_records:
                if dep0_var.type in _TIME_TYPES:
                    return pycdfpp.to_datetime64(dep0_var).astype(np.int64).astype(np.float64) / 1e9, True
                return dep0_var.values.astype(np.float64), False

        # Fallback: DEPEND_TIME attribute (THEMIS-style non-ISTP files)
        depend_time_name = info.all_attributes.get("DEPEND_TIME", [""])[0] if "DEPEND_TIME" in info.all_attributes else ""
        if depend_time_name and depend_time_name in self._cdf:
            dt_var = self._cdf[depend_time_name]
            if dt_var.shape[0] == n_records:
                return dt_var.values.astype(np.float64), True

        return None, False

    def _update_preview(self, info: VariableInfo):
        if not _is_plottable(info):
            self._preview.clear()
            return
        try:
            var = self._cdf[info.name]
            values = var.values
            epochs, is_time_axis = self._resolve_epochs(info, values)

            depend_1 = None
            depend_1_units = ""
            depend_1_scale = "linear"
            if info.depend_1 and info.depend_1 in self._cdf:
                d1_var = self._cdf[info.depend_1]
                d1 = d1_var.values.astype(np.float64)
                depend_1 = d1
                depend_1_units = str(d1_var.attributes["UNITS"][0]) if "UNITS" in d1_var.attributes else ""
                depend_1_scale = str(d1_var.attributes["SCALETYP"][0]) if "SCALETYP" in d1_var.attributes else "linear"

            # Ensure DEPEND_1 channels are ascending (some CDF files
            # store energy channels high-to-low); flip both axes together.
            if depend_1 is not None and depend_1.size > 1:
                ref = depend_1.ravel() if depend_1.ndim == 1 else depend_1[0, :]
                finite = ref[np.isfinite(ref)]
                if len(finite) >= 2 and finite[0] > finite[-1]:
                    depend_1 = depend_1[..., ::-1]
                    values = values[..., ::-1]

            if info.fill_value is not None:
                typed_fill = np.array(info.fill_value, dtype=values.dtype)
                values = np.where(values == typed_fill, np.nan, values.astype(float))

            labels = self._resolve_labels(info)

            self._preview.plot_variable(
                values=values,
                epochs=epochs,
                depend_1=depend_1,
                labels=labels,
                units=info.units,
                scale_type=info.scale_type,
                depend_1_units=depend_1_units,
                depend_1_scale=depend_1_scale,
                display_type=info.display_type,
                is_time_axis=is_time_axis,
            )
        except Exception:
            logger.debug("Preview failed for %s", info.name, exc_info=True)
            self._preview.clear()

    def _navigate_to_variable(self, var_name: str):
        for group_row in range(self._tree_model.rowCount()):
            group_idx = self._tree_model.index(group_row, 0)
            for var_row in range(self._tree_model.rowCount(group_idx)):
                var_idx = self._tree_model.index(var_row, 0, group_idx)
                node = var_idx.internalPointer()
                if node and node.name == var_name:
                    proxy_idx = self._proxy_model.mapFromSource(var_idx)
                    self._tree_view.setCurrentIndex(proxy_idx)
                    return

    def _plot_new_panel(self, var_name: str):
        if self._main_window is None:
            return
        try:
            from SciQLop.user_api.plot import create_plot_panel, TimeRange
            from speasy.core import datetime64_to_epoch
            from speasy.core.codecs import get_codec

            codec = get_codec('application/x-cdf')
            speasy_var = codec.load_variable(variable=var_name, file=self._source)
            panel = create_plot_panel()
            if speasy_var is not None:
                panel.plot_data(speasy_var)
                x = datetime64_to_epoch(speasy_var.time)
                if len(x) >= 2:
                    panel.time_range = TimeRange(float(x.min()), float(x.max()))
            else:
                var = self._cdf[var_name]
                panel.plot_data(np.arange(var.shape[0]), var.values.astype(float))
        except Exception:
            logger.warning("Failed to plot %s", var_name, exc_info=True)

    def _plot_to_panel(self, var_name: str, panel_name: str):
        if self._main_window is None:
            return
        try:
            from SciQLop.user_api.plot import plot_panel
            from speasy.core.codecs import get_codec

            panel = plot_panel(panel_name)
            if panel is None:
                return
            codec = get_codec('application/x-cdf')
            speasy_var = codec.load_variable(variable=var_name, file=self._source)
            if speasy_var is not None:
                panel.plot_data(speasy_var)
            else:
                var = self._cdf[var_name]
                panel.plot_data(np.arange(var.shape[0]), var.values.astype(float))
        except Exception:
            logger.warning("Failed to plot %s to panel %s", var_name, panel_name, exc_info=True)

    def _show_context_menu(self, pos):
        index = self._tree_view.indexAt(pos)
        menu = QMenu(self)

        if index.isValid():
            source_index = self._proxy_model.mapToSource(index)
            node = source_index.internalPointer()
            if node is not None and node.variable_info is not None:
                menu.addAction("Plot in New Panel", lambda: self._plot_new_panel(node.name))
                menu.addAction("Send to Console", lambda: self._send_to_console(node.name))
                menu.addSeparator()

        if menu.isEmpty():
            return
        menu.exec(self._tree_view.viewport().mapToGlobal(pos))

    def _send_to_console(self, var_name: str):
        if self._main_window is None or self._cdf is None:
            return
        try:
            var = self._cdf[var_name]
            data = var.values
            self._main_window.push_variables_to_console({var_name: data})
        except Exception:
            logger.warning("Failed to send %s to console", var_name, exc_info=True)

    def _start_quality_analysis(self):
        infos = {
            name: info
            for name, info in self._tree_model.variable_infos().items()
            if info.var_type.lower() == "data"
        }
        if not infos:
            return

        self._analysis_thread = QThread()
        self._analysis_worker = AnalysisWorker(self._cdf, infos)
        self._analysis_worker.moveToThread(self._analysis_thread)
        self._analysis_thread.started.connect(self._analysis_worker.run)
        self._analysis_worker.quality_ready.connect(self._on_quality_result)
        self._analysis_worker.sparkline_ready.connect(self._on_sparkline_result)
        self._analysis_thread.finished.connect(self._analysis_thread.deleteLater)
        self._analysis_thread.start()

    def _on_quality_result(self, var_name: str, report: QualityReport):
        self._quality_reports[var_name] = report
        if hasattr(self, "_delegate"):
            self._delegate.set_quality(var_name, report.valid_percentage)
            self._tree_view.viewport().update()

    def _on_sparkline_result(self, var_name: str, samples: list):
        if hasattr(self, "_delegate"):
            self._delegate.set_sparkline(var_name, samples)
            self._tree_view.viewport().update()

    def _start_lint(self):
        if not self._source or self._lint_report is not None:
            return
        parent_conn, child_conn = multiprocessing.Pipe(duplex=False)
        self._lint_process = multiprocessing.Process(
            target=_lint_in_subprocess, args=(self._source, child_conn), daemon=True,
        )
        self._lint_conn = parent_conn
        self._lint_process.start()
        child_conn.close()
        self._lint_timer = QTimer(self)
        self._lint_timer.timeout.connect(self._poll_lint)
        self._lint_timer.start(500)

    def _poll_lint(self):
        if self._lint_conn.poll():
            report = self._lint_conn.recv()
            self._lint_timer.stop()
            self._lint_process.join(timeout=1)
            if report is not None:
                self._lint_report = report
                self._inspector.set_lint_report(report)
        elif not self._lint_process.is_alive():
            self._lint_timer.stop()
            self._lint_process.join(timeout=1)

    def release(self):
        if hasattr(self, "_analysis_worker"):
            self._analysis_worker.cancel()
        if hasattr(self, "_analysis_thread") and self._analysis_thread.isRunning():
            self._analysis_thread.quit()
            self._analysis_thread.wait(1000)
        if hasattr(self, "_lint_timer"):
            self._lint_timer.stop()
        if hasattr(self, "_lint_process") and self._lint_process.is_alive():
            self._lint_process.kill()
            self._lint_process.join(timeout=1)
        self._cdf = None
