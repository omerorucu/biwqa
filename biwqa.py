"""
biwqa.py
--------
BiWQA – Bitemporal Water Quality Analyzer
QGIS plugin entry point.

QGIS 4.0 compatibility
  - QIcon directly from path (getThemeIcon expects theme name, not path)
  - iface.addPluginToMenu / addToolBarIcon unchanged
  - No deprecated APIs used
"""

import os

from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsApplication

from .main_dialog_water_quality import BiWQADialog


class BiWQAPlugin:
    """BiWQA – Bitemporal Water Quality Analyzer — QGIS plugin wrapper."""

    def __init__(self, iface):
        self.iface      = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.dialog     = None
        self.action     = None

    def initGui(self):
        self.action = QAction(
            "BiWQA – Bitemporal Water Quality Analyzer",
            self.iface.mainWindow())
        self.action.setObjectName("BiWQABitemporalWaterQualityAnalyzer")

        icon_path = os.path.join(self.plugin_dir, 'icon.png')
        if os.path.exists(icon_path):
            from qgis.PyQt.QtGui import QIcon
            self.action.setIcon(QIcon(icon_path))

        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu("BiWQA", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        self.iface.removePluginMenu("BiWQA", self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.dialog:
            self.dialog.close()
            self.dialog = None

    def run(self):
        if self.dialog is None:
            self.dialog = BiWQADialog()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
