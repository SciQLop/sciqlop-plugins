from __future__ import annotations
import logging
import re
import sys
from pathlib import PurePosixPath
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Optional
import numpy as np

if TYPE_CHECKING:
    from SciQLop.core.plot_hints import PlotHints
from PySide6.QtCore import (
    Qt, QProcess, QRunnable, QThread, QThreadPool, QTimer, Signal, QObject, QSortFilterProxyModel,
)
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTreeView, QLineEdit, QMenu, QCheckBox, QLabel,
    QInputDialog, QMessageBox, QFileDialog,
)
import pycdfpp

from .attribute_dialog import AttributeDialog
from .export import write_csv, write_npz
from .document import (
    Attribute, Document, DocumentSession, GlobalAttribute, attribute_lists, global_attribute_lists, to_cdf,
)
from .edits import (
    add_variable, decode_text, delete_variable, format_value, new_variable, references_to, remove_global_attribute,
    remove_variable_attribute, rename_variable, set_global_attribute, set_variable_attribute,
    set_variable_values, values_editable,
)
from .values_dialog import ValuesDialog
from .variable_dialog import VariableDialog
from .axis_bar import Axis, AxisModeBar
from .memory import available_memory, decoded_nbytes, memory_problem
from .reduce import Mode, axis_attribute, default_modes, needs_reduction, reduce_values, reduced_info
from .tree_model import CdfTreeModel, CdfItemDelegate, VariableInfo
from .inspector import CdfInspectorWidget
from .preview import CdfPreviewWidget
from .quality import analyze_quality, fill_mask, QualityReport
from . import lint
from .lint import LintReport, report_from_json

logger = logging.getLogger(__name__)

# Size threshold for skipping sparklines (100 MB)
SPARKLINE_SIZE_LIMIT = 100 * 1024 * 1024

# A 2D variable without DISPLAY_TYPE=spectrogram is drawn as N line components.
# Above this threshold the plot becomes unusable and freezes the UI (e.g. CDFs
# where axis-1 is samples-per-record, not components).
MAX_LINE_COMPONENTS = 32


@dataclass(frozen=True)
class PlotBundle:
    """Everything needed to render a CDF variable, in any of the 3 sinks."""
    x: np.ndarray
    values: np.ndarray
    depend_1: Optional[np.ndarray]
    hints: "PlotHints"
    is_time_axis: bool

    @property
    def is_spectrogram(self) -> bool:
        return self.hints.display_type == "spectrogram" and self.values.ndim == 2

    @property
    def _y_hints_name(self) -> str:
        return "y2" if self.is_spectrogram else "y"

    @property
    def y_scale(self) -> str:
        return getattr(self.hints, self._y_hints_name).scale or "linear"

    @property
    def log_y_allowed(self) -> bool:
        """A spectrogram's y axis is its bins: log needs them all positive (not azimuths)."""
        if not self.is_spectrogram:
            return True
        if self.depend_1 is None:
            return False
        bins = self.depend_1[np.isfinite(self.depend_1)]
        return bins.size > 0 and bool(np.all(bins > 0))

    def with_y_scale(self, scale: str) -> "PlotBundle":
        """On a log line plot, values <= 0 are hidden."""
        name = self._y_hints_name
        axis = getattr(self.hints, name).model_copy(update={"scale": scale})
        values = self.values
        if scale == "log" and not self.is_spectrogram:
            values = np.where(values > 0, values, np.nan)
        return replace(self, values=values, hints=self.hints.model_copy(update={name: axis}))


def _make_ascending(depend_1: Optional[np.ndarray],
                    values: np.ndarray) -> tuple[Optional[np.ndarray], np.ndarray]:
    """Flip both axes when DEPEND_1 channels are stored high-to-low.

    Returns C-contiguous arrays — `arr[..., ::-1]` is a strided view, and
    SciQLop's PyBuffer wrapper assumes contiguous memory; a non-contiguous
    float64 array passes user_api's `ensure_arrays_of_double` (dtype check
    only) and then segfaults / SystemErrors inside the Shiboken binding.
    """
    if not _is_descending(depend_1):
        return depend_1, values
    return (np.ascontiguousarray(depend_1[..., ::-1]),
            np.ascontiguousarray(values[..., ::-1]))


def _is_descending(depend_1: Optional[np.ndarray]) -> bool:
    if depend_1 is None or depend_1.size <= 1:
        return False
    ref = depend_1.ravel() if depend_1.ndim == 1 else depend_1[0, :]
    finite = ref[np.isfinite(ref)]
    return len(finite) >= 2 and finite[0] > finite[-1]


def _replace_fill(values: np.ndarray, fill_value) -> np.ndarray:
    if fill_value is None:
        return values
    return np.where(fill_mask(values, fill_value), np.nan, values.astype(float))


def _hints_from(info: VariableInfo, depend_1_meta: Optional[dict],
                labels: list[str]):
    from SciQLop.core.istp_hints import istp_metadata_to_hints
    meta = dict(info.all_attributes)
    if depend_1_meta is not None:
        meta["_depend_1"] = depend_1_meta
    hints = istp_metadata_to_hints(meta)
    if labels:
        hints = hints.model_copy(update={"component_labels": labels})
    return hints


def _fit_zoom(panel, x: np.ndarray) -> None:
    if len(x) < 2:
        return
    span = float(x.max() - x.min())
    if 0 < panel.zoom_limit_seconds < span:
        panel.zoom_limit_seconds = span


def _apply_data_time_range(panel, x: np.ndarray) -> None:
    from SciQLop.user_api.plot import TimeRange
    if len(x) >= 2:
        panel.time_range = TimeRange(float(x.min()), float(x.max()))


def _send_line(panel, bundle: PlotBundle):
    plot, _ = panel.plot_data(bundle.x, bundle.values)
    return plot


def _send_spectrogram(panel, bundle: PlotBundle):
    y = (bundle.depend_1 if bundle.depend_1 is not None
         else np.arange(bundle.values.shape[1], dtype=np.float64))
    plot, _ = panel.plot_data(bundle.x, y, bundle.values)
    return plot


def _record_axis(depend_0) -> np.ndarray:
    if depend_0.type in _TIME_TYPES:
        return pycdfpp.to_datetime64(depend_0.values)
    return depend_0.values


class AnalysisWorker(QObject):
    """Runs quality analysis and sparkline extraction in a background thread."""
    # Use Signal(str, object) for cross-thread safety with custom types
    quality_ready = Signal(str, object)   # var_name, QualityReport
    sparkline_ready = Signal(str, object) # var_name, list[float]
    done = Signal()

    def __init__(self, doc: Document, variable_infos: dict[str, VariableInfo]):
        super().__init__()
        self._doc = doc
        self._infos = variable_infos
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            self._analyze_all()
        finally:
            self.done.emit()

    def _analyze_all(self):
        for name, info in self._infos.items():
            if self._cancelled:
                return
            try:
                var = self._doc[name]
                if memory_problem(name, var, available_memory()):
                    continue
                estimated_size = np.prod(var.shape) * 8
                values = var.values

                # Quality analysis
                epochs = None
                if info.depend_0 and info.depend_0 in self._doc:
                    epochs = _record_axis(self._doc[info.depend_0])
                report = analyze_quality(
                    values=values,
                    epochs=epochs,
                    fill_value=info.fill_value,
                    valid_min=info.valid_min,
                    valid_max=info.valid_max,
                )
                self.quality_ready.emit(name, report)

                # Sparkline: one value per time record, downsampled to ~60.
                # Collapse every non-record axis with nansum so 1D, 2D and
                # higher-rank variables all become a per-record series. A flat
                # ravel() would interleave time and channels into a fake time
                # series (a 1×N burst variable would show its energy spectrum
                # instead of its time evolution).
                if estimated_size < SPARKLINE_SIZE_LIMIT:
                    arr = values.astype(float, copy=False)
                    arr = np.where(fill_mask(values, info.fill_value), np.nan, arr)
                    rows = arr.reshape(len(arr), -1)
                    per_record = np.where(np.isfinite(rows).any(axis=1), np.nansum(rows, axis=1), np.nan)
                    if len(per_record) > 60:
                        indices = np.linspace(0, len(per_record) - 1, 60, dtype=int)
                        per_record = per_record[indices]
                    samples = [float(v) for v in per_record if np.isfinite(v)]
                    if samples:
                        self.sparkline_ready.emit(name, samples)
            except Exception:
                logger.debug("Analysis failed for %s", name, exc_info=True)


_NON_PLOTTABLE_TYPES = {pycdfpp.DataType.CDF_CHAR, pycdfpp.DataType.CDF_UCHAR, pycdfpp.DataType.CDF_NONE}
_TEXT_TYPES = {pycdfpp.DataType.CDF_CHAR, pycdfpp.DataType.CDF_UCHAR}
_TIME_TYPES = {pycdfpp.DataType.CDF_EPOCH, pycdfpp.DataType.CDF_EPOCH16, pycdfpp.DataType.CDF_TIME_TT2000}


def _parse_lint_output(stdout: bytes) -> Optional[LintReport]:
    """None for anything but the child's JSON: a library printing to stdout must not leave the
    previous report on screen as if it were current."""
    try:
        return report_from_json(stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, TypeError) as e:
        logger.debug("Unreadable lint output: %s", e)
        return None


def _with_filter_suffix(path: str, chosen_filter: str) -> str:
    """A name typed without extension gets the one of the chosen filter, e.g. "NumPy (*.npz)"."""
    if PurePosixPath(path).suffix:
        return path
    match = re.search(r"\*(\.\w+)", chosen_filter)
    return path + match.group(1) if match else path


def _problem_text(error: Exception, action: str, name: str) -> str:
    """A MemoryError already says what is needed; other errors get some context."""
    return str(error) if isinstance(error, MemoryError) else f"Can't {action} {name}: {error}"


def _text_labels(raw: np.ndarray) -> list[str]:
    # pycdfpp returns CDF_CHAR as ndarray of bytes, shape varies:
    # NRV scalar: (n_components,) or (1, n_components)
    # time-varying: (n_records, n_components)
    while raw.ndim > 1:
        raw = raw[-1]
    return [decode_text(s).strip() if isinstance(s, bytes) else str(s).strip() for s in raw.tolist()]


def _is_plottable(info: VariableInfo) -> bool:
    if info.cdf_type in _NON_PLOTTABLE_TYPES:
        return False
    if info.display_type.lower() == "no_plot":
        return False
    ndim = len(info.shape)
    if ndim == 0 or any(s == 0 for s in info.shape):
        return False
    if needs_reduction(info):
        return True
    if ndim > 2:
        return False
    if ndim == 2 and info.display_type.lower() != "spectrogram" and info.shape[1] > MAX_LINE_COMPONENTS:
        return False
    return True


# Linting an edited document holds a second full copy of it in memory: above this, skip it.
LINT_SIZE_LIMIT = 200 * 1024 * 1024
AFTER_EDIT_DELAY_MS = 1000


def _document_bytes(doc: Document) -> Optional[bytes]:
    if sum(decoded_nbytes(var) for _, var in doc.items()) > LINT_SIZE_LIMIT:
        return None
    return bytes(pycdfpp.save(to_cdf(doc)))


class _SerializeSignals(QObject):
    done = Signal(int, object)  # lint generation, CDF bytes


class _SerializeTask(QRunnable):
    """Builds the lint input off the GUI thread: to_cdf reads every value."""

    def __init__(self, doc: Document, generation: int, signals: _SerializeSignals):
        super().__init__()
        self._doc, self._generation, self._signals = doc, generation, signals

    def run(self):
        try:
            data = _document_bytes(self._doc)
        except Exception:  # e.g. an edited CDF_BYTE attribute pycdfpp can't write: no lint
            logger.debug("Can't serialize the document for lint", exc_info=True)
            return
        if data is None:
            return
        try:
            self._signals.done.emit(self._generation, data)
        except RuntimeError:  # the view was closed meanwhile
            pass


# Analyses outlive the view that started them: destroying a running QThread aborts the process.
_RUNNING_ANALYSES: set = set()


def _run_analysis(worker: AnalysisWorker) -> QThread:
    thread = QThread()
    worker.moveToThread(thread)
    entry = (thread, worker)
    _RUNNING_ANALYSES.add(entry)
    thread.started.connect(worker.run)
    worker.done.connect(thread.quit)
    thread.finished.connect(lambda: _forget_analysis(entry))
    thread.start()
    return thread


def _forget_analysis(entry: tuple) -> None:
    """Runs on the GUI thread (PySide queues the lambda there); `finished` is emitted just before
    the thread exits, so wait for it before dropping the last reference."""
    thread, _worker = entry
    thread.wait()
    _RUNNING_ANALYSES.discard(entry)


class CdfFileView(QWidget):
    def __init__(self, session: DocumentSession, source: str = "", main_window=None, parent=None):
        super().__init__(parent)
        self._session = session
        self._modes: dict[str, tuple[Mode, ...]] = {}
        self._y_scales: dict[str, str] = {}
        self._previewed: Optional[VariableInfo] = None
        self._source = source
        self._main_window = main_window
        self._quality_reports: dict[str, QualityReport] = {}
        self._lint_report: LintReport | None = None
        self._setup_ui()
        session.changed.connect(self._on_document_changed)
        self._start_quality_analysis()
        self._lint_process: Optional[QProcess] = None
        self._lint_generation = 0
        self._serialize_signals = _SerializeSignals(self)
        self._serialize_signals.done.connect(self._on_document_serialized)
        self._lint_finished = False
        self._lint_exit_code: Optional[int] = None
        self._after_edit = QTimer(self)
        self._after_edit.setSingleShot(True)
        self._after_edit.setInterval(AFTER_EDIT_DELAY_MS)
        self._after_edit.timeout.connect(self._refresh_derived)
        self._lint_on_open()

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

        self._tree_model = CdfTreeModel(self._doc)
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
        self._inspector.dependency_clicked.connect(self.select_variable)
        self._inspector.plot_new_panel.connect(self._plot_new_panel)
        self._inspector.plot_to_panel.connect(self._plot_to_panel)
        self._inspector.edit_attribute.connect(self._edit_attribute)
        self._inspector.delete_attribute.connect(self._delete_attribute)
        self._inspector.add_attribute.connect(self._add_attribute)
        right_splitter.addWidget(self._inspector)

        if self._main_window is not None:
            self._inspector.set_panel_names(self._main_window.plot_panels())
            self._main_window.panels_list_changed.connect(self._inspector.set_panel_names)

        preview_pane = QWidget()
        preview_layout = QVBoxLayout(preview_pane)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self._axis_bar = AxisModeBar()
        self._axis_bar.modes_changed.connect(self._on_modes_changed)
        self._log_y = QCheckBox("log y")
        self._log_y.setToolTip("Override SCALETYP. On a log axis, values <= 0 are hidden.")
        self._log_y.clicked.connect(self._on_log_y_clicked)
        self._log_y.hide()
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 4, 0)
        controls.addWidget(self._axis_bar, 1)
        controls.addWidget(self._log_y)
        preview_layout.addLayout(controls)
        self._preview = CdfPreviewWidget()
        preview_layout.addWidget(self._preview)
        self._preview_message = QLabel()
        self._preview_message.setWordWrap(True)
        self._preview_message.hide()
        preview_layout.addWidget(self._preview_message)
        right_splitter.addWidget(preview_pane)

        self._right_splitter = right_splitter

        splitter.addWidget(right_splitter)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(splitter)
        self._show_global_attributes()

    @property
    def session(self) -> Optional[DocumentSession]:
        return self._session

    @property
    def _doc(self) -> Optional[Document]:
        return self._session.document if self._session is not None else None

    def _on_document_changed(self):
        """Rebuild what was derived from the document, keeping the selected variable."""
        if self._doc is None:
            return
        current = self._inspector.current_variable
        self._tree_model = CdfTreeModel(self._doc)
        self._proxy_model.setSourceModel(self._tree_model)
        self._tree_view.expandAll()
        self._after_edit.start()
        if current is not None and current in self._doc:
            self.select_variable(current)
        else:
            self._show_global_attributes()
            self._clear_preview()

    def _ask_attribute(self, title: str, name: str, data_type, entries: list[str], multi_entry: bool):
        dialog = AttributeDialog(title, name, data_type, entries, multi_entry, self)
        return dialog.result_attribute() if dialog.exec() else None

    def _edit_attribute(self, var_name: str, attr_name: str):
        if var_name:
            attr = self._doc[var_name].attributes[attr_name]
            data_type, entries = attr.type, [format_value(attr.value)]
        else:
            attr = self._doc.attributes[attr_name]
            data_type = attr.entries[0].type if attr.entries else pycdfpp.DataType.CDF_CHAR
            entries = [format_value(e.value) for e in attr.entries]
        answer = self._ask_attribute(f"Edit {attr_name}", attr_name, data_type, entries, not var_name)
        if answer is not None:
            self._set_attribute(var_name, attr_name, *answer)

    def _add_attribute(self, var_name: str):
        answer = self._ask_attribute("Add attribute", "", pycdfpp.DataType.CDF_CHAR, [], not var_name)
        if answer is not None:
            self._set_attribute(var_name, None, *answer)

    def _set_attribute(self, var_name: str, old_name: Optional[str], name: str, data_type, values: list):
        if var_name:
            edit = lambda d: set_variable_attribute(d, var_name, old_name, name, Attribute(values[0], data_type))
        else:
            entries = GlobalAttribute(tuple(Attribute(v, data_type) for v in values))
            edit = lambda d: set_global_attribute(d, old_name, name, entries)
        self._apply(edit)

    def _delete_attribute(self, var_name: str, attr_name: str):
        self._apply(lambda d: remove_variable_attribute(d, var_name, attr_name) if var_name
                    else remove_global_attribute(d, attr_name))

    def _ask_new_name(self, name: str) -> str:
        new, ok = QInputDialog.getText(self, "Rename variable", "New name:", text=name)
        return new if ok else ""

    def _ask_update_references(self, name: str, references: list[tuple[str, str]]) -> str:
        """'yes', 'no' or 'cancel'."""
        listed = "\n".join(f"{var}.{attr}" for var, attr in references)
        answer = QMessageBox.question(
            self, "Update references", f"Also rename {name} in these attributes?\n\n{listed}",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Yes)
        return {QMessageBox.Yes: "yes", QMessageBox.No: "no"}.get(answer, "cancel")

    def _confirm_delete(self, name: str, references: list[tuple[str, str]]) -> bool:
        listed = "".join(f"\n{var}.{attr}" for var, attr in references)
        warning = f"\n\nThese attributes still point at it:{listed}" if references else ""
        answer = QMessageBox.question(self, "Delete variable", f"Delete {name}?{warning}")
        return answer == QMessageBox.Yes

    def _rename_variable(self, name: str):
        new = self._ask_new_name(name).strip()
        if not new or new == name:
            return
        references = references_to(self._doc, name)
        answer = self._ask_update_references(name, references) if references else "no"
        if answer == "cancel":
            return
        was_selected = self._inspector.current_variable == name
        for per_variable in (self._modes, self._y_scales):
            if name in per_variable:
                per_variable[new] = per_variable.pop(name)
        self._apply(lambda d: rename_variable(d, name, new, update_references=answer == "yes"))
        if was_selected and new in self._doc:
            self.select_variable(new)

    def _ask_variable(self):
        dialog = VariableDialog(self)
        return dialog.result_variable() if dialog.exec() else None

    def _new_variable(self):
        answer = self._ask_variable()
        if answer is not None:
            name, data_type, is_nrv, values = answer
            try:
                self.add_variable(name, values, data_type=data_type, is_nrv=is_nrv)
            except ValueError as e:
                self.show_problem(str(e))

    def add_variable(self, name: str, values, attributes: Optional[dict] = None, is_nrv: bool = False,
                     data_type=None):
        """Raises ValueError on a bad name or values; the new variable gets selected."""
        var = new_variable(values, data_type, is_nrv, attributes)
        self._session.apply(lambda d: add_variable(d, name, var))
        self.select_variable(name.strip())

    def _ask_values(self, name: str, var):
        dialog = ValuesDialog(name, var, self)
        return dialog.result_values() if dialog.exec() else None

    def _edit_values(self, name: str):
        try:
            values = self._ask_values(name, self._doc[name])
        except Exception as e:
            logger.warning("Can't edit the values of %s", name, exc_info=True)
            self.show_problem(_problem_text(e, "edit", name))
            return
        if values is not None:
            self._apply(lambda d: set_variable_values(d, name, values))

    def _delete_variable(self, name: str):
        if self._confirm_delete(name, references_to(self._doc, name)):
            self._apply(lambda d: delete_variable(d, name))

    def _apply(self, edit):
        try:
            self._session.apply(edit)
        except ValueError as e:
            self.show_problem(str(e))

    def showEvent(self, event):
        super().showEvent(event)
        h = self._right_splitter.height()
        if h > 0:
            self._right_splitter.setSizes([h * 3 // 4, h // 4])

    def _show_global_attributes(self):
        self._inspector.show_global_attributes(global_attribute_lists(self._doc))

    def _on_filter_changed(self, text: str):
        self._proxy_model.setFilterFixedString(text)

    def _on_variable_selected(self, current, previous):
        source_index = self._proxy_model.mapToSource(current)
        node = source_index.internalPointer()
        if node is None or node.variable_info is None:
            self._show_global_attributes()
            self._clear_preview()
            return

        info = node.variable_info
        quality = self._quality_reports.get(info.name)
        self._inspector.update_variable(info, quality)
        self._update_preview(info)

    def _text_variable(self, name: str):
        var = self._doc[name] if name and name in self._doc else None
        return var if var is not None and var.type in _TEXT_TYPES else None

    def _resolve_labels(self, info: VariableInfo) -> list[str]:
        if info.labl_ptr_1 and info.labl_ptr_1 in self._doc:
            return _text_labels(self._doc[info.labl_ptr_1].values)
        if (depend_1 := self._text_variable(info.depend_1)) is not None:
            return _text_labels(depend_1.values)
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
        if info.depend_0 and info.depend_0 in self._doc:
            dep0_var = self._doc[info.depend_0]
            if dep0_var.shape[0] == n_records:
                if dep0_var.type in _TIME_TYPES:
                    return pycdfpp.to_datetime64(dep0_var.values).astype(np.int64).astype(np.float64) / 1e9, True
                return dep0_var.values.astype(np.float64), False

        # Fallback: DEPEND_TIME attribute (THEMIS-style non-ISTP files)
        depend_time_name = info.all_attributes.get("DEPEND_TIME", [""])[0] if "DEPEND_TIME" in info.all_attributes else ""
        if depend_time_name and depend_time_name in self._doc:
            dt_var = self._doc[depend_time_name]
            if dt_var.shape[0] == n_records:
                return dt_var.values.astype(np.float64), True

        return None, False

    def _read_depend_1(self, info: VariableInfo) -> tuple[Optional[np.ndarray], Optional[dict]]:
        if not (info.depend_1 and info.depend_1 in self._doc) or self._text_variable(info.depend_1):
            return None, None
        d1 = self._doc[info.depend_1]
        return d1.values.astype(np.float64), attribute_lists(d1)

    def _modes_for(self, info: VariableInfo) -> Optional[tuple[Mode, ...]]:
        if not needs_reduction(info):
            return None
        return self._modes.setdefault(info.name, default_modes(info))

    def _read_raw_values(self, name: str) -> np.ndarray:
        var = self._doc[name]
        problem = memory_problem(name, var, available_memory())
        if problem:
            raise MemoryError(problem)
        return var.values

    def _read_values(self, info: VariableInfo) -> tuple[VariableInfo, np.ndarray]:
        values = self._read_raw_values(info.name)
        modes = self._modes_for(info)
        if modes is None:
            return info, values
        reduced = reduce_values(values, modes, info.fill_value, info.valid_min, info.valid_max)
        return reduced_info(info, modes), reduced

    def _slice_labels(self, info: VariableInfo, axis: int) -> tuple[str, ...]:
        size = info.shape[axis + 1]
        indices = tuple(str(i) for i in range(size))
        name = axis_attribute(info, "DEPEND", axis)
        if not name or name not in self._doc:
            return indices
        raw = self._doc[name].values
        if raw.size == 0:
            return indices
        if self._text_variable(name) is not None:
            labels = _text_labels(raw)
        else:
            labels = [f"{v:g}" for v in (raw.ravel() if raw.ndim == 1 else raw[0].ravel())]
        return tuple(labels) if len(labels) == size else indices

    def _axes_of(self, info: VariableInfo) -> list[Axis]:
        return [Axis(axis_attribute(info, "DEPEND", k) or f"dim {k + 1}", self._slice_labels(info, k))
                for k in range(len(info.shape) - 1)]

    def _on_log_y_clicked(self, checked: bool):
        if self._previewed is None:
            return
        self._y_scales[self._previewed.name] = "log" if checked else "linear"
        self._render_preview(self._previewed)

    def _with_chosen_y_scale(self, name: str, bundle: PlotBundle) -> PlotBundle:
        scale = self._y_scales.get(name, bundle.y_scale)
        return bundle.with_y_scale(scale if bundle.log_y_allowed else "linear")

    def _on_modes_changed(self, modes: tuple[Mode, ...]):
        if self._previewed is None:
            return
        self._modes[self._previewed.name] = modes
        self._render_preview(self._previewed)

    def _read_bundle(self, info: VariableInfo) -> PlotBundle:
        return self._with_chosen_y_scale(info.name, self._read_unscaled_bundle(info))

    def _read_unscaled_bundle(self, info: VariableInfo) -> PlotBundle:
        info, raw_values = self._read_values(info)
        raw_depend_1, depend_1_meta = self._read_depend_1(info)
        depend_1, values = _make_ascending(raw_depend_1, raw_values)
        values = _replace_fill(values, info.fill_value)
        epochs, is_time_axis = self._resolve_epochs(info, values)
        x = (epochs if epochs is not None
             else np.arange(values.shape[0], dtype=np.float64))
        labels = self._resolve_labels(info)
        if _is_descending(raw_depend_1) and len(labels) > 1:
            labels = labels[::-1]
        hints = _hints_from(info, depend_1_meta, labels)
        return PlotBundle(x=x, values=values, depend_1=depend_1,
                          hints=hints, is_time_axis=is_time_axis)

    def _update_preview(self, info: VariableInfo):
        if not _is_plottable(info):
            self._clear_preview()
            return
        self._previewed = info
        modes = self._modes_for(info)
        if modes is None:
            self._axis_bar.clear()
        else:
            self._axis_bar.show_axes(self._axes_of(info), modes)
        self._render_preview(info)

    def _clear_preview(self):
        self._previewed = None
        self._axis_bar.clear()
        self._log_y.hide()
        self._preview_message.hide()
        self._preview.clear()

    def _render_preview(self, info: VariableInfo):
        try:
            bundle = self._read_bundle(info)
            self._show_log_y(bundle)
            self._preview.plot_variable(
                values=bundle.values,
                epochs=bundle.x if bundle.is_time_axis else None,
                depend_1=bundle.depend_1,
                hints=bundle.hints,
                is_time_axis=bundle.is_time_axis,
            )
            self._preview_message.hide()
        except Exception as e:
            logger.debug("Preview failed for %s", info.name, exc_info=True)
            self._preview.clear()
            self.show_problem(_problem_text(e, "preview", info.name))

    def show_problem(self, message: str):
        self._preview_message.setText(message)
        self._preview_message.show()

    def _show_log_y(self, bundle: PlotBundle):
        self._log_y.setEnabled(bundle.log_y_allowed)
        self._log_y.setChecked(bundle.y_scale == "log")
        self._log_y.show()

    def select_variable(self, var_name: str):
        for group_row in range(self._tree_model.rowCount()):
            group_idx = self._tree_model.index(group_row, 0)
            for var_row in range(self._tree_model.rowCount(group_idx)):
                var_idx = self._tree_model.index(var_row, 0, group_idx)
                node = var_idx.internalPointer()
                if node and node.name == var_name:
                    proxy_idx = self._proxy_model.mapFromSource(var_idx)
                    self._tree_view.setCurrentIndex(proxy_idx)
                    return

    def _render(self, panel, info: VariableInfo, frame_to_data: bool):
        from SciQLop.core.plot_hints import apply_plot_hints
        bundle = self._read_bundle(info)
        if frame_to_data and bundle.is_time_axis:
            _fit_zoom(panel, bundle.x)
        plot = (_send_spectrogram(panel, bundle) if bundle.is_spectrogram
                else _send_line(panel, bundle))
        # Time range must be set BEFORE rescale_axes — for line plots,
        # rescale_axes only fits y over the visible x window. If x is still
        # the panel's default (epoch ~1970) at rescale time, y has no data in
        # range and stays at [0, 5] regardless of the real data.
        if frame_to_data and bundle.is_time_axis:
            _apply_data_time_range(panel, bundle.x)
        if plot is not None:
            plot_impl = getattr(plot, "_impl", plot)
            apply_plot_hints(plot_impl, bundle.hints)
            plot_impl.rescale_axes()

    def _plot_new_panel(self, var_name: str):
        info = self._lookup_plottable(var_name)
        if info is None:
            return
        try:
            from SciQLop.user_api.plot import create_plot_panel
            self._render(create_plot_panel(), info, frame_to_data=True)
        except Exception as e:
            logger.warning("Failed to plot %s", var_name, exc_info=True)
            self.show_problem(_problem_text(e, "plot", var_name))

    def _plot_to_panel(self, var_name: str, panel_name: str):
        info = self._lookup_plottable(var_name)
        if info is None:
            return
        try:
            from SciQLop.user_api.plot import plot_panel
            panel = plot_panel(panel_name)
            if panel is None:
                return
            self._render(panel, info, frame_to_data=False)
        except Exception as e:
            logger.warning("Failed to plot %s to panel %s", var_name, panel_name, exc_info=True)
            self.show_problem(_problem_text(e, "plot", var_name))

    def _lookup_plottable(self, var_name: str) -> Optional[VariableInfo]:
        if self._main_window is None:
            return None
        info = self._tree_model.variable_info(var_name)
        if info is None or not _is_plottable(info):
            return None
        return info

    def _show_context_menu(self, pos):
        index = self._tree_view.indexAt(pos)
        menu = QMenu(self)

        if index.isValid():
            source_index = self._proxy_model.mapToSource(index)
            node = source_index.internalPointer()
            if node is not None and node.variable_info is not None:
                menu.addAction("Plot in New Panel", lambda: self._plot_new_panel(node.name))
                menu.addAction("Send to Console", lambda: self._send_to_console(node.name))
                menu.addAction("Export data…", lambda: self._export_data(node.name))
                menu.addSeparator()
                if values_editable(self._doc[node.name]):
                    menu.addAction("Edit values…", lambda: self._edit_values(node.name))
                menu.addAction("Rename…", lambda: self._rename_variable(node.name))
                menu.addAction("Delete", lambda: self._delete_variable(node.name))
                menu.addSeparator()

        menu.addAction("New variable…", self._new_variable)
        menu.exec(self._tree_view.viewport().mapToGlobal(pos))

    def _ask_export_path(self, name: str, filters: str) -> str:
        path, chosen_filter = QFileDialog.getSaveFileName(self, "Export data", name, filters)
        return _with_filter_suffix(path, chosen_filter) if path else ""

    def _export_data(self, var_name: str):
        """What the plot shows (masked, reduced, flipped): CSV, or .npz with the axes."""
        info = self._tree_model.variable_info(var_name)
        if info is None or not _is_plottable(info):
            self.show_problem(f"Can't export {var_name}: it isn't plottable")
            return
        path = self._ask_export_path(f"{var_name}.csv", "CSV (*.csv);;NumPy (*.npz)")
        if not path:
            return
        try:
            (write_npz if path.endswith(".npz") else write_csv)(path, self._read_bundle(info))
        except Exception as e:
            logger.warning("Failed to export %s", var_name, exc_info=True)
            self.show_problem(_problem_text(e, "export", var_name))

    def _send_to_console(self, var_name: str):
        if self._main_window is None or self._doc is None:
            return
        try:
            data = self._read_raw_values(var_name)
            self._main_window.push_variables_to_console({var_name: data})
        except Exception as e:
            logger.warning("Failed to send %s to console", var_name, exc_info=True)
            self.show_problem(_problem_text(e, "send", var_name))

    def _refresh_derived(self):
        """After a burst of edits: what was computed from the document follows it."""
        self._lint_document()
        self._stop_quality_analysis()
        self._start_quality_analysis()

    def _stop_quality_analysis(self):
        """Disconnected first, so a late result can't overwrite a newer one."""
        if getattr(self, "_analysis_worker", None) is not None:
            self._analysis_worker.quality_ready.disconnect(self._on_quality_result)
            self._analysis_worker.sparkline_ready.disconnect(self._on_sparkline_result)
            self._analysis_worker.cancel()
            self._analysis_worker = None

    def _start_quality_analysis(self):
        infos = {
            name: info
            for name, info in self._tree_model.variable_infos().items()
            if info.var_type.lower() == "data"
        }
        if not infos:
            return

        self._analysis_worker = AnalysisWorker(self._doc, infos)
        self._analysis_worker.quality_ready.connect(self._on_quality_result)
        self._analysis_worker.sparkline_ready.connect(self._on_sparkline_result)
        _run_analysis(self._analysis_worker)

    def _on_quality_result(self, var_name: str, report: QualityReport):
        self._quality_reports[var_name] = report
        if hasattr(self, "_delegate"):
            self._delegate.set_quality(var_name, report.valid_percentage)
            self._tree_view.viewport().update()

    def _on_sparkline_result(self, var_name: str, samples: list):
        if hasattr(self, "_delegate"):
            self._delegate.set_sparkline(var_name, samples)
            self._tree_view.viewport().update()

    def _lint_on_open(self):
        """A local file is linted from disk; a URL from memory, so it isn't downloaded again."""
        if self._source.startswith(("http://", "https://")):
            self._lint_document()
        elif self._source:
            self._start_lint(self._source)

    def _lint_document(self):
        if self._doc is None:
            return
        self._lint_generation += 1
        QThreadPool.globalInstance().start(
            _SerializeTask(self._doc, self._lint_generation, self._serialize_signals))

    def _on_document_serialized(self, generation: int, data: bytes):
        """Results of older edits, or arriving after release(), are dropped."""
        if generation == self._lint_generation and self._session is not None:
            self._start_lint(data)

    def _start_lint(self, source: str | bytes):
        """lint.py runs as a script with `-I`: it needs nothing from the plugin, and the
        plugin's own directory isn't put on the child's sys.path to shadow anything."""
        self._stop_lint()
        process = QProcess(self)
        process.finished.connect(lambda code, _status, p=process: self._on_lint_finished(p, code))
        process.finished.connect(process.deleteLater)
        from_stdin = isinstance(source, bytes)
        process.start(sys.executable, ["-I", lint.__file__, "-" if from_stdin else source])
        if from_stdin:
            process.write(source)
            process.closeWriteChannel()
        self._lint_process = process
        self._lint_finished = False

    def _stop_lint(self):
        process, self._lint_process = self._lint_process, None
        if process is not None and process.state() != QProcess.NotRunning:
            process.kill()
            process.waitForFinished(1000)

    def _on_lint_finished(self, process: QProcess, exit_code: int):
        if process is not self._lint_process:
            return
        self._lint_process = None  # deleteLater'd once this slot returns
        self._lint_finished, self._lint_exit_code = True, exit_code
        if exit_code != 0:
            stderr = bytes(process.readAllStandardError()).decode("utf-8", "replace")
            logger.debug("Lint failed: %s", stderr[-2000:])
            return
        report = _parse_lint_output(bytes(process.readAllStandardOutput()))
        if report is not None:
            self._lint_report = report
            self._inspector.set_lint_report(report)

    def release(self):
        """Safe to call twice. A running analysis stops after its current variable."""
        self._stop_quality_analysis()
        self._after_edit.stop()
        self._stop_lint()
        self._session = None
