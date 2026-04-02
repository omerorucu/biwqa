"""
main_dialog_water_quality.py
-----------------------------
Main GUI dialog and analysis thread for BiWQA – Bitemporal Water Quality Analyzer.

QGIS 4.0 compatibility notes
  - PyQt5 → PyQt6: exec_() → exec(), removed Qt.AlignCenter (use AlignmentFlag)
  - QgsMessageLog.logMessage(): level arg now uses Qgis.MessageLevel enum
  - QgsRasterLayer styling: QgsSingleBandPseudoColorRenderer (unchanged API)
  - No use of deprecated QgsMapLayer.type() int comparison
  - All f-strings (Python 3.6+, safe for QGIS 4.0 / Python 3.12+)

Other improvements in v1.1
  - Configurable pixel size (QDoubleSpinBox)
  - Automatic temp-file tracking and cleanup on close
  - MNDWI band-2 water masking in load_and_classify()
  - Kappa coefficient displayed in results tables and reports
  - Provenance JSON export alongside CSV results
  - Sensitivity analysis run automatically and shown in summary
"""

import json
import os
import tempfile
import time
import traceback

import numpy as np

# ── QGIS 4.0: PyQt6 path; fall back to PyQt5 for QGIS 3.x ──────────────────
try:
    from qgis.PyQt.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QGroupBox,
        QCheckBox, QFileDialog, QTableWidget, QTableWidgetItem, QProgressBar,
        QTabWidget, QWidget, QFormLayout, QComboBox, QTextEdit, QMessageBox,
        QTextBrowser, QSplitter, QScrollArea, QDoubleSpinBox,
    )
    from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal
    from qgis.PyQt.QtGui import QColor, QFont
except ImportError:  # pragma: no cover
    from PyQt6.QtWidgets import (
        QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QGroupBox,
        QCheckBox, QFileDialog, QTableWidget, QTableWidgetItem, QProgressBar,
        QTabWidget, QWidget, QFormLayout, QComboBox, QTextEdit, QMessageBox,
        QTextBrowser, QSplitter, QScrollArea, QDoubleSpinBox,
    )
    from PyQt6.QtCore import Qt, QThread, pyqtSignal
    from PyQt6.QtGui import QColor, QFont

# Python 3.9 uyumluluğu için Optional (str | None sözdizimi Python 3.10+ gerektirir)
from typing import Optional

from qgis.core import (
    Qgis,            # QGIS 4.0: message level enum lives here
    QgsMessageLog,
    QgsProject,
    QgsRasterLayer,
)

try:
    from .change_analyzer import ChangeAnalyzer
    from .classification_rules_water_quality import WaterQualityClassificationRules
except ImportError:
    from change_analyzer import ChangeAnalyzer
    from classification_rules_water_quality import WaterQualityClassificationRules


# ── QGIS 4.0: message level constants ────────────────────────────────────────
try:
    _MSG_INFO    = Qgis.MessageLevel.Info
    _MSG_WARNING = Qgis.MessageLevel.Warning
    _MSG_CRITICAL= Qgis.MessageLevel.Critical
except AttributeError:          # QGIS 3.x fallback
    _MSG_INFO     = 0
    _MSG_WARNING  = 1
    _MSG_CRITICAL = 2

# ── QGIS 4.0: Qt alignment flags ─────────────────────────────────────────────
try:
    _ALIGN_CENTER = Qt.AlignmentFlag.AlignCenter
except AttributeError:
    _ALIGN_CENTER = Qt.AlignCenter


# ═════════════════════════════════════════════════════════════════════════════
class BiWQADialog(QDialog):
    """BiWQA – Bitemporal Water Quality Analyzer — main analysis dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("BiWQA – Bitemporal Water Quality Analyzer v1.1")
        self.setMinimumSize(1400, 900)
        self.index_buttons  = {}
        self.index_files    = {}
        self.current_results = None
        self._temp_files    = []   # paths registered for cleanup on close
        self.initUI()

    # ──────────────────────────────────────────────────────────────────────
    def initUI(self):
        main_layout = QVBoxLayout()

        # Header
        title = QLabel("🌊  BiWQA – BITEMPORAL WATER QUALITY ANALYZER")
        title.setStyleSheet("""
            font-size: 20px; font-weight: bold; color: #1e88e5;
            padding: 15px; background-color: #e3f2fd;
            border-radius: 8px;
        """)
        title.setAlignment(_ALIGN_CENTER)
        main_layout.addWidget(title)

        splitter = QSplitter(Qt.Orientation.Horizontal
                              if hasattr(Qt, 'Orientation') else Qt.Horizontal)

        left = QWidget();  ll = QVBoxLayout(left)
        self.setup_file_loading_section(ll)
        self.setup_settings_section(ll)

        right = QWidget(); rl = QVBoxLayout(right)
        self.setup_results_section(rl)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([420, 980])
        main_layout.addWidget(splitter)

        # Status bar
        self.status_label = QLabel("✅ Ready. Please load water quality index files for bitemporal analysis.")
        self.status_label.setStyleSheet("""
            background-color: #e3f2fd; padding: 10px;
            border: 2px solid #bbdefb; border-radius: 5px;
            font-weight: bold; font-size: 12px;
        """)
        main_layout.addWidget(self.status_label)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar { border: 2px solid #1e88e5; border-radius: 5px;
                           text-align: center; font-weight: bold; height: 20px; }
            QProgressBar::chunk { background-color: #1e88e5; border-radius: 3px; }
        """)
        main_layout.addWidget(self.progress_bar)

        # Control buttons
        btn_row = QHBoxLayout()
        self.analyze_btn = self._make_btn(
            "🚀 START CHANGE ANALYSIS", "#1e88e5", "#0d47a1")
        self.analyze_btn.clicked.connect(self.start_analysis)
        self.analyze_btn.setEnabled(False)

        self.export_btn = self._make_btn("💾 EXPORT RESULTS", "#43a047", "#2e7d32")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self.export_results)

        self.clear_btn = self._make_btn("🗑️ CLEAR ALL", "#f44336", "#c62828")
        self.clear_btn.clicked.connect(self.clear_all)

        self.close_btn = self._make_btn("✖️ CLOSE", "#757575", "#616161")
        self.close_btn.clicked.connect(self.close)

        for b in (self.analyze_btn, self.export_btn, self.clear_btn, self.close_btn):
            btn_row.addWidget(b)
        btn_row.addStretch()
        main_layout.addLayout(btn_row)

        self.setLayout(main_layout)

    # ──────────────────────────────────────────────────────────────────────
    @staticmethod
    def _make_btn(text, bg, border):
        btn = QPushButton(text)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg}; color: white; font-weight: bold;
                padding: 12px 20px; border-radius: 6px; font-size: 14px;
                border: 2px solid {border};
            }}
            QPushButton:hover {{ background-color: {border}; }}
            QPushButton:disabled {{ background-color: #90a4ae; border-color: #78909c; }}
        """)
        return btn

    # ──────────────────────────────────────────────────────────────────────
    def setup_file_loading_section(self, layout):
        group = QGroupBox("📁 LOAD WATER QUALITY INDICES (Time 1 & Time 2)")
        group.setStyleSheet("""
            QGroupBox { font-weight: bold; font-size: 14px;
                        border: 2px solid #1e88e5; border-radius: 8px;
                        margin-top: 10px; padding-top: 15px; }
            QGroupBox::title { subcontrol-origin: margin; left: 15px;
                               padding: 0 10px; color: #1e88e5; }
        """)
        scroll = QScrollArea()
        sw = QWidget(); sl = QVBoxLayout(sw)

        for iname in WaterQualityClassificationRules.get_all_indices():
            info = WaterQualityClassificationRules.get_index_info(iname)
            if info:
                self._create_index_row(sl, iname, info)

        scroll.setWidget(sw)
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(500)
        gl = QVBoxLayout()
        gl.addWidget(scroll)
        group.setLayout(gl)
        layout.addWidget(group)

    # ──────────────────────────────────────────────────────────────────────
    def _create_index_row(self, layout, index_name, index_info):
        grp = QGroupBox(f"{index_info['name']}  ({index_name})")
        grp.setStyleSheet("""
            QGroupBox { font-weight: bold; border: 1px solid #bbdefb;
                        border-radius: 6px; margin-top: 5px; padding-top: 10px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px;
                               padding: 0 5px; color: #0d47a1; }
        """)
        form = QFormLayout()
        form.setSpacing(10)

        for period in ('time1', 'time2'):
            label_text = "🕐 Time Period 1:" if period == 'time1' else "🕑 Time Period 2:"
            btn_color  = "#2196f3" if period == 'time1' else "#4caf50"
            btn_hover  = "#1976d2" if period == 'time1' else "#388e3c"

            row_w = QWidget(); row_l = QHBoxLayout(row_w)
            row_l.setContentsMargins(0, 0, 0, 0)

            btn = QPushButton(f"📂 {period.replace('time', 'Time ').capitalize()}")
            btn.setStyleSheet(f"""
                QPushButton {{ padding: 8px 15px; background-color: {btn_color};
                               color: white; border-radius: 4px; font-weight: bold; }}
                QPushButton:hover {{ background-color: {btn_hover}; }}
            """)
            btn.index_name = index_name
            btn.time       = period
            btn.clicked.connect(self.load_index_file)

            lbl = QLabel("No file selected")
            lbl.setMinimumWidth(300)
            lbl.setStyleSheet("""border: 2px solid #e0e0e0; padding: 8px;
                                 background-color: #fafafa; border-radius: 4px;""")

            row_l.addWidget(btn); row_l.addWidget(lbl); row_l.addStretch()
            form.addRow(label_text, row_w)

            if index_name not in self.index_buttons:
                self.index_buttons[index_name] = {}
            self.index_buttons[index_name][f'{period}_btn']   = btn
            self.index_buttons[index_name][f'{period}_label'] = lbl

        # Checkbox + info
        cb  = QCheckBox("Analyze this index"); cb.setChecked(True)
        cb.stateChanged.connect(self.check_analyze_button)

        info_btn = QPushButton("ℹ️ Info")
        info_btn.setStyleSheet("padding: 5px 10px;")
        info_btn.index_name = index_name
        info_btn.clicked.connect(self.show_index_info)

        ctrl = QWidget(); cl = QHBoxLayout(ctrl)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.addWidget(cb); cl.addStretch(); cl.addWidget(info_btn)

        form.addRow("📊 Analysis Control:", ctrl)
        self.index_buttons[index_name]['active_cb'] = cb
        grp.setLayout(form)
        layout.addWidget(grp)

    # ──────────────────────────────────────────────────────────────────────
    def setup_settings_section(self, layout):
        grp = QGroupBox("⚙️ CLASSIFICATION SETTINGS")
        grp.setStyleSheet("""
            QGroupBox { font-weight: bold; font-size: 14px;
                        border: 2px solid #ff9800; border-radius: 8px;
                        margin-top: 10px; padding-top: 15px; }
            QGroupBox::title { subcontrol-origin: margin; left: 15px;
                               padding: 0 10px; color: #ff9800; }
        """)
        sl = QVBoxLayout()

        # Index selector
        sel_row = QHBoxLayout()
        sel_row.addWidget(QLabel("Select Index:"))
        self.index_combo = QComboBox()
        self.index_combo.addItems(WaterQualityClassificationRules.get_all_indices())
        self.index_combo.currentTextChanged.connect(self.show_classification_rules)
        self.index_combo.setStyleSheet("""
            QComboBox { padding: 8px; border: 2px solid #1e88e5;
                        border-radius: 4px; font-size: 12px; }
        """)
        sel_row.addWidget(self.index_combo); sel_row.addStretch()

        # Buttons
        view_btn = QPushButton("📋 View Classification Rules")
        view_btn.setStyleSheet("""
            QPushButton { padding: 10px; background-color: #673ab7; color: white;
                          border-radius: 5px; font-weight: bold; }
            QPushButton:hover { background-color: #5e35b1; }
        """)
        view_btn.clicked.connect(self.show_all_classification_rules)

        exp_btn = QPushButton("💾 Export Rules to CSV")
        exp_btn.setStyleSheet("""
            QPushButton { padding: 10px; background-color: #009688; color: white;
                          border-radius: 5px; font-weight: bold; }
            QPushButton:hover { background-color: #00897b; }
        """)
        exp_btn.clicked.connect(self.export_classification_rules)

        btn_row = QHBoxLayout()
        btn_row.addWidget(view_btn); btn_row.addWidget(exp_btn); btn_row.addStretch()

        # Pixel size spinbox
        px_row = QHBoxLayout()
        px_row.addWidget(QLabel("Pixel Size (m):"))
        self.pixel_size_spinbox = QDoubleSpinBox()
        self.pixel_size_spinbox.setRange(1.0, 1000.0)
        self.pixel_size_spinbox.setValue(10.0)
        self.pixel_size_spinbox.setSingleStep(1.0)
        self.pixel_size_spinbox.setDecimals(1)
        self.pixel_size_spinbox.setToolTip(
            "Spatial resolution of input rasters in metres.\n"
            "Sentinel-2 B2–B8: 10 m | B8A, B11, B12: 20 m"
        )
        self.pixel_size_spinbox.setStyleSheet("""
            QDoubleSpinBox { padding: 6px; border: 2px solid #1e88e5;
                             border-radius: 4px; font-size: 12px; max-width: 100px; }
        """)
        px_row.addWidget(self.pixel_size_spinbox); px_row.addStretch()

        # Classification rules table
        self.rules_table = QTableWidget()
        self.rules_table.setColumnCount(5)
        self.rules_table.setHorizontalHeaderLabels(
            ['Class ID', 'Label', 'Min Value', 'Max Value', 'Color'])
        self.rules_table.setMaximumHeight(200)
        self.rules_table.setStyleSheet("""
            QTableWidget { background-color: white; alternate-background-color: #f5f5f5;
                           gridline-color: #e0e0e0; font-size: 11px; }
            QHeaderView::section { background-color: #424242; color: white;
                                   font-weight: bold; padding: 8px;
                                   border: 1px solid #616161; }
        """)
        self.rules_table.horizontalHeader().setStretchLastSection(True)

        sl.addLayout(sel_row)
        sl.addLayout(btn_row)
        sl.addSpacing(6)
        sl.addLayout(px_row)
        sl.addSpacing(6)
        sl.addWidget(self.rules_table)
        grp.setLayout(sl)
        layout.addWidget(grp)
        self.show_classification_rules(self.index_combo.currentText())

    # ──────────────────────────────────────────────────────────────────────
    def setup_results_section(self, layout):
        grp = QGroupBox("📊 ANALYSIS RESULTS")
        grp.setStyleSheet("""
            QGroupBox { font-weight: bold; font-size: 14px;
                        border: 2px solid #43a047; border-radius: 8px;
                        margin-top: 10px; padding-top: 15px; }
            QGroupBox::title { subcontrol-origin: margin; left: 15px;
                               padding: 0 10px; color: #43a047; }
        """)
        rl = QVBoxLayout()
        self.results_tabs = QTabWidget()
        self.results_tabs.setStyleSheet("""
            QTabWidget::pane { border: 2px solid #c8e6c9; border-radius: 5px;
                               background-color: #f1f8e9; }
            QTabBar::tab { background-color: #a5d6a7; color: #1b5e20; padding: 10px 20px;
                           margin-right: 2px; border-top-left-radius: 5px;
                           border-top-right-radius: 5px; font-weight: bold; }
            QTabBar::tab:selected { background-color: #66bb6a; color: white; }
            QTabBar::tab:hover    { background-color: #81c784; }
        """)

        # Statistics tab
        st = QWidget(); stl = QVBoxLayout(st)
        self.stats_table = QTableWidget()
        self.stats_table.setColumnCount(9)
        self.stats_table.setHorizontalHeaderLabels([
            'Index', 'Class', 'Time1 (ha)', 'Time2 (ha)',
            'Change (ha)', 'Change (%)', 'Kappa', 'Status', 'Bitemporal Comparison',
        ])
        self.stats_table.horizontalHeader().setStretchLastSection(True)
        self.stats_table.setStyleSheet("""
            QTableWidget { background-color: white; alternate-background-color: #f5f5f5;
                           gridline-color: #e0e0e0; font-size: 11px; }
            QHeaderView::section { background-color: #1e88e5; color: white;
                                   font-weight: bold; padding: 8px;
                                   border: 1px solid #0d47a1; }
        """)
        stl.addWidget(self.stats_table)
        self.results_tabs.addTab(st, "📈 Statistics")

        # Change matrix tab
        mt = QWidget(); mtl = QVBoxLayout(mt)
        self.matrix_table = QTableWidget()
        self.matrix_table.setStyleSheet("""
            QTableWidget { background-color: white; alternate-background-color: #f5f5f5;
                           gridline-color: #e0e0e0; font-size: 10px; }
            QHeaderView::section { background-color: #ff9800; color: white;
                                   font-weight: bold; padding: 6px;
                                   border: 1px solid #f57c00; }
        """)
        mtl.addWidget(self.matrix_table)
        self.results_tabs.addTab(mt, "🔄 Change Matrix")

        # Change types tab
        ct = QWidget(); ctl = QVBoxLayout(ct)
        self.changes_table = QTableWidget()
        self.changes_table.setColumnCount(6)
        self.changes_table.setHorizontalHeaderLabels(
            ['Index', 'From Class', 'To Class', 'Code', 'Area (ha)', 'Percent (%)'])
        self.changes_table.horizontalHeader().setStretchLastSection(True)
        self.changes_table.setStyleSheet("""
            QTableWidget { background-color: white; alternate-background-color: #f5f5f5;
                           gridline-color: #e0e0e0; font-size: 11px; }
            QHeaderView::section { background-color: #8e24aa; color: white;
                                   font-weight: bold; padding: 8px;
                                   border: 1px solid #6a1b9a; }
        """)
        ctl.addWidget(self.changes_table)
        self.results_tabs.addTab(ct, "📊 Change Types")

        # Detailed report tab
        rt = QWidget(); rtl = QVBoxLayout(rt)
        self.report_text = QTextBrowser()
        self.report_text.setStyleSheet("""
            QTextBrowser { font-family: 'Consolas', 'Monaco', monospace;
                           font-size: 11px; background-color: #fafafa;
                           border: 2px solid #e0e0e0; border-radius: 5px; padding: 10px; }
        """)
        rtl.addWidget(self.report_text)
        self.results_tabs.addTab(rt, "📄 Detailed Report")

        # Summary tab
        smt = QWidget(); smtl = QVBoxLayout(smt)
        self.summary_text = QTextBrowser()
        self.summary_text.setStyleSheet("""
            QTextBrowser { font-family: 'Arial', sans-serif; font-size: 12px;
                           background-color: #e8f5e8; border: 2px solid #c8e6c9;
                           border-radius: 5px; padding: 15px; }
        """)
        smtl.addWidget(self.summary_text)
        self.results_tabs.addTab(smt, "📋 Summary")

        rl.addWidget(self.results_tabs)
        grp.setLayout(rl)
        layout.addWidget(grp)

    # ──────────────────────────────────────────────────────────────────────
    # FILE LOADING
    # ──────────────────────────────────────────────────────────────────────

    def load_index_file(self):
        sender = self.sender()
        index_name  = sender.index_name
        time_period = sender.time

        filename, _ = QFileDialog.getOpenFileName(
            self, f"Select {index_name} {time_period.replace('time', 'Time ')} file",
            "", "GeoTIFF (*.tif *.tiff);;All files (*)")

        if filename:
            lbl = self.index_buttons[index_name][f'{time_period}_label']
            lbl.setText(os.path.basename(filename))
            lbl.setStyleSheet("""
                border: 2px solid #4caf50; padding: 8px;
                background-color: #e8f5e9; border-radius: 4px;
                color: #1b5e20; font-weight: bold;
            """)
            if index_name not in self.index_files:
                self.index_files[index_name] = {}
            self.index_files[index_name][time_period] = filename
            self.check_analyze_button()
            self.status_label.setText(
                f"✅ {index_name} {time_period.replace('time', 'Time ')} loaded")

    # ──────────────────────────────────────────────────────────────────────
    # INFO / RULES DISPLAY
    # ──────────────────────────────────────────────────────────────────────

    def show_index_info(self):
        sender     = self.sender()
        index_name = sender.index_name
        info       = WaterQualityClassificationRules.get_index_info(index_name)
        if not info:
            QMessageBox.warning(self, "Info",
                                f"No information available for {index_name}")
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"ℹ️ {info['name']}")
        dlg.setMinimumSize(620, 520)
        layout = QVBoxLayout()

        tb = QTextBrowser(); tb.setOpenExternalLinks(True)
        rows = "".join(
            f"<tr><td><b>{c['id']}</b></td><td>{c['label']}</td>"
            f"<td>{c['min']}</td><td>{c['max']}</td>"
            f"<td><div style='width:20px;height:20px;display:inline-block;"
            f"background:{c['color']};border:1px solid #ccc'></div> {c['color']}</td></tr>"
            for c in info['classes']
        )
        tb.setHtml(f"""<html><head><style>
            body{{font-family:Arial;margin:20px}}
            h1{{color:#1e88e5;border-bottom:2px solid #1e88e5;padding-bottom:10px}}
            h2{{color:#0d47a1;margin-top:20px}}
            .box{{background:#e3f2fd;padding:15px;border-radius:5px;margin:10px 0}}
            .formula{{background:#f1f8e9;padding:10px;border-left:4px solid #43a047;margin:10px 0}}
            table{{width:100%;border-collapse:collapse;margin:15px 0}}
            th{{background:#1e88e5;color:white;padding:8px;text-align:left}}
            td{{padding:8px;border-bottom:1px solid #ddd}}
        </style></head><body>
        <h1>{info['name']} ({index_name})</h1>
        <div class="box"><h2>📋 Description</h2>{info['description']}</div>
        <div class="formula"><h2>🧮 Formula</h2><strong>{info['formula']}</strong></div>
        <div class="box"><h2>📏 Range</h2><strong>{info['range']}</strong></div>
        <div class="box"><h2>📚 Reference</h2><em>{info['reference']}</em></div>
        <h2>🏷️ Classification Classes</h2>
        <table><tr><th>ID</th><th>Label</th><th>Min</th><th>Max</th><th>Color</th></tr>
        {rows}</table></body></html>""")

        layout.addWidget(tb)
        cb = QPushButton("Close"); cb.clicked.connect(dlg.close)
        br = QHBoxLayout(); br.addStretch(); br.addWidget(cb)
        layout.addLayout(br)
        dlg.setLayout(layout)
        dlg.exec()   # QGIS 4.0: exec() not exec_()

    def show_classification_rules(self, index_name):
        info = WaterQualityClassificationRules.get_index_info(index_name)
        if not info:
            return
        self.rules_table.setRowCount(len(info['classes']))
        for row, cls in enumerate(info['classes']):
            for col, val in enumerate([str(cls['id']), cls['label'],
                                        f"{cls['min']:.3f}",
                                        f"{cls['max']:.3f}", cls['color']]):
                item = QTableWidgetItem(val)
                item.setTextAlignment(_ALIGN_CENTER)
                if col == 4:
                    item.setBackground(QColor(cls['color']))
                self.rules_table.setItem(row, col, item)
        self.rules_table.resizeColumnsToContents()

    def show_all_classification_rules(self):
        report = WaterQualityClassificationRules.generate_classification_report()
        dlg = QDialog(self); dlg.setWindowTitle("📋 Classification Rules")
        dlg.setMinimumSize(800, 600)
        layout = QVBoxLayout()
        tb = QTextBrowser(); tb.setPlainText(report)
        tb.setFont(QFont("Consolas", 10))
        layout.addWidget(tb)
        exp = QPushButton("💾 Export to Text")
        exp.clicked.connect(lambda: self.export_text_file(report,
                                                           "classification_rules.txt"))
        cl = QPushButton("Close"); cl.clicked.connect(dlg.close)
        br = QHBoxLayout(); br.addWidget(exp); br.addStretch(); br.addWidget(cl)
        layout.addLayout(br)
        dlg.setLayout(layout)
        dlg.exec()

    def export_classification_rules(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export Classification Rules",
            "biwqa_classification_rules.csv", "CSV Files (*.csv)")
        if filename:
            ok, msg = WaterQualityClassificationRules.export_to_csv(filename)
            (QMessageBox.information if ok else QMessageBox.warning)(
                self, "Export", msg)

    # ──────────────────────────────────────────────────────────────────────
    # ANALYSIS CONTROL
    # ──────────────────────────────────────────────────────────────────────

    def check_analyze_button(self):
        for iname, files in self.index_files.items():
            if ('time1' in files and 'time2' in files
                    and self.index_buttons[iname]['active_cb'].isChecked()):
                self.analyze_btn.setEnabled(True)
                return
        self.analyze_btn.setEnabled(False)

    def start_analysis(self):
        if not self.index_files:
            QMessageBox.warning(self, "Warning", "Please load index files first!")
            return

        active = [iname for iname, files in self.index_files.items()
                  if ('time1' in files and 'time2' in files
                      and self.index_buttons[iname]['active_cb'].isChecked())]

        if not active:
            QMessageBox.warning(self, "Warning",
                                "Please select at least one index for analysis!")
            return

        reply = QMessageBox.question(
            self, 'Start Analysis',
            f'Start change analysis for {len(active)} indices?\n\n' +
            '\n'.join(f"• {i}" for i in active),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)

        if reply != QMessageBox.StandardButton.Yes:
            return

        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        pixel_size = self.pixel_size_spinbox.value()
        self.analysis_thread = BiWQAAnalysisThread(
            active, self.index_files, pixel_size, self)
        self.analysis_thread.progress_signal.connect(self.update_progress)
        self.analysis_thread.status_signal.connect(self.update_status)
        self.analysis_thread.finished_signal.connect(self.on_analysis_finished)
        self.analysis_thread.error_signal.connect(self.on_analysis_error)
        self.analysis_thread.temp_files_signal.connect(self._register_temp_files)
        # QGIS 4.0: layer addition must happen in the main thread
        self.analysis_thread.layer_ready_signal.connect(self._add_layer_to_qgis)
        self.analysis_thread.start()

        self.analyze_btn.setEnabled(False)
        self.status_label.setText("⏳ Analysis started… Please wait.")

    def update_progress(self, v):
        self.progress_bar.setValue(v)

    def update_status(self, msg):
        self.status_label.setText(msg)

    # ──────────────────────────────────────────────────────────────────────
    # RESULTS DISPLAY
    # ──────────────────────────────────────────────────────────────────────

    def on_analysis_finished(self, results):
        self.progress_bar.setVisible(False)
        self.analyze_btn.setEnabled(True)
        self.export_btn.setEnabled(bool(results))
        self.current_results = results

        self._populate_stats_table(results)
        self._populate_matrix_tab(results)
        self._populate_changes_tab(results)
        self._populate_report_tab(results)
        self._populate_summary_tab(results)

        self.status_label.setText(
            f"✅ Analysis complete — {len(results)} index(es) processed.")

    def on_analysis_error(self, msg):
        self.progress_bar.setVisible(False)
        self.analyze_btn.setEnabled(True)
        QMessageBox.critical(self, "Analysis Error", msg)
        self.status_label.setText(f"❌ Error: {msg}")

    # ── Table helpers ─────────────────────────────────────────────────────

    def _populate_stats_table(self, results):
        self.stats_table.setRowCount(0)
        for iname, r in results.items():
            kappa = r.get('kappa', float('nan'))
            for cls in sorted(r['class_areas_time1']):
                a1 = r['class_areas_time1'][cls]
                a2 = r['class_areas_time2'].get(cls, 0.0)
                dc = a2 - a1
                dp = dc / a1 * 100 if a1 > 0 else 0.0
                status = ("📈 Increased" if dc > 0
                           else "📉 Decreased" if dc < 0 else "➡️ Stable")
                bitemporal = ("T1 → T2 Increase" if dp > 10
                               else "T1 → T2 Decrease" if dp < -10
                               else "T1 ≈ T2 Stable")
                row_pos = self.stats_table.rowCount()
                self.stats_table.insertRow(row_pos)
                for col, val in enumerate([
                    iname, str(int(cls)),
                    f"{a1:.2f}", f"{a2:.2f}", f"{dc:.2f}", f"{dp:.1f}",
                    f"{kappa:.4f}", status, bitemporal,
                ]):
                    item = QTableWidgetItem(val)
                    item.setTextAlignment(_ALIGN_CENTER)
                    self.stats_table.setItem(row_pos, col, item)

    def _populate_matrix_tab(self, results):
        if not results:
            return
        # Show matrix for first result only (selector could be added later)
        first_key = next(iter(results))
        r = results[first_key]
        mat  = r['change_matrix']
        ucs  = r['unique_classes']
        n    = len(ucs)
        self.matrix_table.setRowCount(n)
        self.matrix_table.setColumnCount(n + 1)
        headers = ['From \\ To'] + [f'Cls {int(c)}' for c in ucs]
        self.matrix_table.setHorizontalHeaderLabels(headers)
        for i, cls in enumerate(ucs):
            self.matrix_table.setItem(i, 0,
                QTableWidgetItem(f"Class {int(cls)}"))
            for j in range(n):
                val = int(mat[i, j])
                item = QTableWidgetItem(f"{val:,}")
                item.setTextAlignment(_ALIGN_CENTER)
                if i == j:
                    item.setBackground(QColor('#c8e6c9'))
                elif val > 0:
                    item.setBackground(QColor('#fff9c4'))
                self.matrix_table.setItem(i, j + 1, item)

    def _populate_changes_tab(self, results):
        self.changes_table.setRowCount(0)
        for iname, r in results.items():
            total = r['changed_area_ha']
            for code, area in sorted(r['change_type_areas'].items(),
                                      key=lambda x: x[1], reverse=True):
                pct  = area / total * 100 if total > 0 else 0
                oc   = code // 100
                nc   = code %  100
                rp   = self.changes_table.rowCount()
                self.changes_table.insertRow(rp)
                for col, val in enumerate([
                    iname, str(oc), str(nc), str(code),
                    f"{area:.2f}", f"{pct:.1f}"
                ]):
                    item = QTableWidgetItem(val)
                    item.setTextAlignment(_ALIGN_CENTER)
                    self.changes_table.setItem(rp, col, item)

    def _populate_report_tab(self, results):
        analyzer = ChangeAnalyzer()
        full_report = ""
        for iname, r in results.items():
            full_report += analyzer.generate_change_report(r, iname) + "\n\n"
        self.report_text.setPlainText(full_report)

    def _populate_summary_tab(self, results):
        lines = [
            "BiWQA – BITEMPORAL ANALYSIS SUMMARY",
            "=" * 50,
            f"Total indices analysed : {len(results)}",
            "",
        ]
        total_area = total_changed = 0.0
        for iname, r in results.items():
            kappa = r.get('kappa', float('nan'))
            kinterp = r.get('kappa_interpretation', '')
            lines += [
                f"▶ {iname}",
                f"  Total area   : {r['total_area_ha']:.2f} ha",
                f"  Changed area : {r['changed_area_ha']:.2f} ha "
                f"({r['changed_percent']:.1f} %)",
                f"  Kappa        : {kappa:.4f}  [{kinterp}]",
                "",
            ]
            total_area    += r['total_area_ha']
            total_changed += r['changed_area_ha']

        if total_area > 0:
            lines.append(
                f"Overall change : {total_changed / total_area * 100:.1f} % "
                f"of total analysed area")
        lines.append("=" * 50)
        self.summary_text.setPlainText("\n".join(lines))

    # ──────────────────────────────────────────────────────────────────────
    # EXPORT
    # ──────────────────────────────────────────────────────────────────────

    def export_results(self):
        if not self.current_results:
            QMessageBox.warning(self, "Warning", "No results to export!")
            return

        folder = QFileDialog.getExistingDirectory(
            self, "Select folder to save results")
        if not folder:
            return

        ts = time.strftime("%Y%m%d_%H%M%S")
        out = os.path.join(folder, f"biwqa_analysis_{ts}")
        os.makedirs(out, exist_ok=True)

        # Statistics CSV
        with open(os.path.join(out, "statistics.csv"), 'w', encoding='utf-8') as f:
            f.write("Index,Class,Time1_ha,Time2_ha,Change_ha,Change_pct,Kappa,Bitemporal_Direction\n")
            for iname, r in self.current_results.items():
                kappa = r.get('kappa', '')
                for cls in sorted(r['class_areas_time1']):
                    a1 = r['class_areas_time1'][cls]
                    a2 = r['class_areas_time2'].get(cls, 0)
                    dc = a2 - a1
                    dp = dc / a1 * 100 if a1 > 0 else 0
                    bitemporal = ("T1 → T2 Increase" if dp > 10
                                   else "T1 → T2 Decrease" if dp < -10
                                   else "T1 ≈ T2 Stable")
                    f.write(f"{iname},{int(cls)},{a1:.4f},{a2:.4f},"
                             f"{dc:.4f},{dp:.2f},{kappa:.6f},{bitemporal}\n")

        # Change types CSV
        with open(os.path.join(out, "change_types.csv"), 'w', encoding='utf-8') as f:
            f.write("Index,From_Class,To_Class,Code,Area_ha,Percent\n")
            for iname, r in self.current_results.items():
                total = r['changed_area_ha']
                for code, area in r['change_type_areas'].items():
                    pct = area / total * 100 if total > 0 else 0
                    f.write(f"{iname},{code//100},{code%100},"
                             f"{code},{area:.4f},{pct:.2f}\n")

        # Detailed report
        with open(os.path.join(out, "detailed_report.txt"), 'w', encoding='utf-8') as f:
            f.write(self.report_text.toPlainText())

        # Summary
        with open(os.path.join(out, "summary.txt"), 'w', encoding='utf-8') as f:
            f.write(self.summary_text.toPlainText())

        # Change matrices + provenance JSON per index
        analyzer = ChangeAnalyzer()
        for iname, r in self.current_results.items():
            if 'change_matrix' in r and 'unique_classes' in r:
                analyzer.export_change_matrix(
                    r['change_matrix'], r['unique_classes'],
                    os.path.join(out, f"{iname}_change_matrix.csv"))

            # Provenance log
            in_files = self.index_files.get(iname, {})
            prov = ChangeAnalyzer.generate_provenance_log(
                r, iname, in_files,
                {'pixel_size': self.pixel_size_spinbox.value(),
                 'use_mndwi_mask': True})
            with open(os.path.join(out, f"{iname}_provenance.json"),
                       'w', encoding='utf-8') as pf:
                json.dump(prov, pf, indent=2, default=str)

        QMessageBox.information(
            self, "Export Complete",
            f"BiWQA results exported to:\n{out}\n\n"
            "Files: statistics.csv, change_types.csv, detailed_report.txt,\n"
            "summary.txt, per-index change_matrix.csv + provenance.json")
        self.status_label.setText(f"✅ Results exported to: {out}")

    def export_text_file(self, text, default_name):
        fn, _ = QFileDialog.getSaveFileName(
            self, "Save Text File", default_name, "Text Files (*.txt)")
        if fn:
            with open(fn, 'w', encoding='utf-8') as f:
                f.write(text)
            QMessageBox.information(self, "Saved", f"File saved: {fn}")

    # ──────────────────────────────────────────────────────────────────────
    # CLEAR / CLOSE
    # ──────────────────────────────────────────────────────────────────────

    def clear_all(self):
        reply = QMessageBox.question(
            self, 'Clear All', 'Clear all loaded files and results?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.stats_table.setRowCount(0)
        self.matrix_table.setRowCount(0); self.matrix_table.setColumnCount(0)
        self.changes_table.setRowCount(0)
        self.report_text.clear(); self.summary_text.clear()

        self.index_files = {}
        for iname in self.index_buttons:
            for period in ('time1', 'time2'):
                lbl = self.index_buttons[iname][f'{period}_label']
                lbl.setText("No file selected")
                lbl.setStyleSheet("""border: 2px solid #e0e0e0; padding: 8px;
                                     background-color: #fafafa; border-radius: 4px;
                                     color: #757575;""")
            self.index_buttons[iname]['active_cb'].setChecked(True)

        self.current_results = None
        self.export_btn.setEnabled(False)
        self.analyze_btn.setEnabled(False)
        self.status_label.setText("✅ All data cleared.")

    # ── Temp-file management ──────────────────────────────────────────────

    def _add_layer_to_qgis(self, path: str, layer_name: str):
        """
        QGIS 4.0: addMapLayer() MUST be called from the main (GUI) thread.
        This slot is connected to layer_ready_signal and executes in the main thread.
        """
        try:
            layer = QgsRasterLayer(path, layer_name)
            if layer.isValid():
                QgsProject.instance().addMapLayer(layer)
            else:
                QgsMessageLog.logMessage(
                    f"Layer not valid: {layer_name}", "BiWQA", _MSG_WARNING)
        except Exception as exc:
            QgsMessageLog.logMessage(
                f"Layer add error ({layer_name}): {exc}", "BiWQA", _MSG_CRITICAL)

    def _register_temp_files(self, paths: list):
        self._temp_files.extend(paths)

    def _cleanup_temp_files(self):
        remaining = []
        for p in self._temp_files:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                remaining.append(p)
        self._temp_files = remaining

    def closeEvent(self, event):
        if hasattr(self, 'analysis_thread') and self.analysis_thread.isRunning():
            reply = QMessageBox.question(
                self, 'Analysis in Progress',
                'Analysis is still running. Close anyway?',
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                # QGIS 4.0: terminate() is unsafe (no cleanup, may corrupt GDAL).
                # Use requestInterruption() — the run() loop checks isInterruptionRequested().
                self.analysis_thread.requestInterruption()
                if not self.analysis_thread.wait(5000):   # wait up to 5 s
                    self.analysis_thread.terminate()       # last resort only
                    self.analysis_thread.wait()
                self._cleanup_temp_files()
                event.accept()
            else:
                event.ignore()
        else:
            self._cleanup_temp_files()
            event.accept()


# ═════════════════════════════════════════════════════════════════════════════
class BiWQAAnalysisThread(QThread):
    """Background analysis thread — keeps QGIS UI responsive during heavy bitemporal analysis."""

    progress_signal   = pyqtSignal(int)
    status_signal     = pyqtSignal(str)
    finished_signal   = pyqtSignal(dict)
    error_signal      = pyqtSignal(str)
    temp_files_signal = pyqtSignal(list)   # emit paths → dialog registers them
    # QGIS 4.0: QgsProject.instance().addMapLayer() is NOT thread-safe.
    # Emit (path, layer_name) to the main thread for safe layer addition.
    layer_ready_signal = pyqtSignal(str, str)

    def __init__(self, active_indices, index_files, pixel_size=10.0, parent=None):
        super().__init__(parent)
        self.active_indices = active_indices
        self.index_files    = index_files
        self.pixel_size     = float(pixel_size)

    # ──────────────────────────────────────────────────────────────────────
    def run(self):
        try:
            results = {}
            total   = len(self.active_indices)

            for i, iname in enumerate(self.active_indices):
                # QGIS 4.0: honour requestInterruption() for clean cancellation
                if self.isInterruptionRequested():
                    self.status_signal.emit("⚠️ Analysis cancelled by user.")
                    break

                self.progress_signal.emit(int(i / total * 100))
                self.status_signal.emit(f"Analysing {iname}…")

                try:
                    classify_fn = (WaterQualityClassificationRules
                                   .get_classification_function(iname))
                    if classify_fn is None:
                        self.status_signal.emit(f"Skipping {iname} — no classify fn")
                        continue

                    t1_path = self.index_files[iname]['time1']
                    t2_path = self.index_files[iname]['time2']

                    ct1 = self.load_and_classify(t1_path, classify_fn)
                    ct2 = self.load_and_classify(t2_path, classify_fn)

                    analyzer = ChangeAnalyzer(pixel_size=self.pixel_size)
                    stats    = analyzer.calculate_change(ct1, ct2, iname)
                    results[iname] = stats

                    new_temps = []
                    self.add_to_qgis(ct1, f"{iname}_Time1",   t1_path,
                                      temp_files_out=new_temps)
                    self.add_to_qgis(ct2, f"{iname}_Time2",   t2_path,
                                      temp_files_out=new_temps)

                    cm_path = self.save_raster(
                        stats['change_map'], iname + "_Change_Map",
                        t1_path, gdal_dtype=None)   # auto → uint16
                    if cm_path:
                        new_temps.append(cm_path)
                        self.add_to_qgis(cm_path, f"{iname}_Change_Map")

                    if new_temps:
                        self.temp_files_signal.emit(new_temps)

                    self.status_signal.emit(f"✅ Completed {iname}")

                except Exception as exc:
                    self.status_signal.emit(f"⚠️ Error in {iname}: {exc}")
                    continue

            self.progress_signal.emit(100)
            self.finished_signal.emit(results)
            self.status_signal.emit("✅ Analysis completed successfully.")

        except Exception as exc:
            self.error_signal.emit(f"Analysis failed: {exc}\n{traceback.format_exc()}")

    # ──────────────────────────────────────────────────────────────────────

    def load_and_classify(self, filepath: str, classify_fn) -> np.ndarray:
        """
        Load band 1 from GeoTIFF, apply optional MNDWI band-2 water mask,
        then classify.

        Water mask convention
        ---------------------
        If the raster contains a second band, it is interpreted as an MNDWI
        layer.  Pixels where MNDWI ≤ 0 (non-water) are set to NoData before
        classification.  Single-band rasters are processed unchanged.
        """
        from osgeo import gdal
        ds = gdal.Open(filepath)
        if ds is None:
            raise ValueError(f"Cannot open: {filepath}")

        band1 = ds.GetRasterBand(1)
        data  = band1.ReadAsArray().astype(np.float64)

        # Propagate source NoData
        src_nd = band1.GetNoDataValue()
        if src_nd is not None:
            data[data == src_nd] = -9999.0

        # Optional band-2 MNDWI water mask
        if ds.RasterCount >= 2:
            mband = ds.GetRasterBand(2)
            mndwi = mband.ReadAsArray().astype(np.float64)
            m_nd  = mband.GetNoDataValue()
            non_water = mndwi <= 0.0
            if m_nd is not None:
                non_water |= (mndwi == m_nd)
            data[non_water] = -9999.0

        ds = None
        return classify_fn(data)

    # ──────────────────────────────────────────────────────────────────────

    def save_raster(self, array: np.ndarray, layer_name: str,
                    reference_file: str, gdal_dtype=None):
        # type: (...) -> Optional[str]
        """Save a numpy array as GeoTIFF in the system temp directory."""
        from osgeo import gdal  # gdalconst removed in GDAL 4.x — use gdal.GDT_* directly

        # Choose GDAL type automatically from array dtype
        if gdal_dtype is None:
            dtype_map = {
                np.dtype('int16'):  gdal.GDT_Int16,
                np.dtype('int32'):  gdal.GDT_Int32,
                np.dtype('uint16'): gdal.GDT_UInt16,
                np.dtype('uint8'):  gdal.GDT_Byte,
                np.dtype('float32'):gdal.GDT_Float32,
                np.dtype('float64'):gdal.GDT_Float64,
            }
            gdal_dtype = dtype_map.get(array.dtype, gdal.GDT_Int32)

        nodata_val = (65535 if array.dtype == np.uint16
                      else -9999 if np.issubdtype(array.dtype, np.signedinteger)
                      else None)

        try:
            ref = gdal.Open(reference_file)
            gt  = ref.GetGeoTransform() if ref else (0, 1, 0, 0, 0, -1)
            prj = ref.GetProjection()   if ref else ""
            ref = None
        except Exception:
            gt, prj = (0, 1, 0, 0, 0, -1), ""

        ts   = int(time.time() * 1000)
        path = os.path.join(tempfile.gettempdir(),
                             f"{layer_name}_{ts}.tif")
        rows, cols = array.shape
        drv = gdal.GetDriverByName('GTiff')
        ds  = drv.Create(path, cols, rows, 1, gdal_dtype)
        ds.SetGeoTransform(gt)
        ds.SetProjection(prj)
        band = ds.GetRasterBand(1)
        band.WriteArray(array)
        if nodata_val is not None:
            band.SetNoDataValue(nodata_val)
        band.FlushCache()
        ds = None
        return path

    # ──────────────────────────────────────────────────────────────────────

    def add_to_qgis(self, data_or_path, layer_name: str,
                     reference_file: str = None,
                     temp_files_out: list = None) -> bool:
        """
        Save raster array (or use existing path) and emit layer_ready_signal
        so the main thread adds it to QGIS.

        QGIS 4.0: QgsProject.instance().addMapLayer() is NOT thread-safe.
        Direct call from a QThread crashes or corrupts the project.
        Signal → slot ensures execution in the main (GUI) thread.
        """
        try:
            if isinstance(data_or_path, str):
                path = data_or_path
            else:
                path = self.save_raster(data_or_path, layer_name,
                                         reference_file or "")
                if path is None:
                    return False
                if temp_files_out is not None:
                    temp_files_out.append(path)

            # Emit to main thread — do NOT call QgsProject.instance() here
            self.layer_ready_signal.emit(path, layer_name)
            return True

        except Exception as exc:
            QgsMessageLog.logMessage(
                f"add_to_qgis error ({layer_name}): {exc}",
                "BiWQA", _MSG_CRITICAL)
            return False
