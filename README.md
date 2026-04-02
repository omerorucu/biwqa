# BiWQA – Bitemporal Water Quality Analyzer

**BiWQA** is a QGIS plugin for bitemporal analysis of surface water quality using remote sensing indices.  
It supports scientifically validated classification thresholds and change detection between two time periods.

![BiWQA Logo](icon.png)

---

## ✨ Features

- **Multi-index support**  
  Chlorophyll-a (Ensemble, NDCI, 2-Band, Moses), Turbidity (NDTI, Dogliotti), CDOM, Secchi Depth, Trophic State Index (TSI), NDWI, MNDWI, and more.

- **Bitemporal change detection**  
  Pixel-level change maps, class transition matrices, and area-based statistics.

- **Advanced analytics**  
  - Cohen's Kappa coefficient for change agreement  
  - Uncertainty propagation (quadrature error)  
  - Sensitivity analysis for threshold perturbations  
  - ISO 19115-inspired provenance logging

- **Performance & memory**  
  Vectorized change matrix (`np.bincount`), uint16 change maps, and efficient NoData handling.

- **QGIS 4.0 ready**  
  Full compatibility with PyQt6, QGIS 4.0 APIs, and Python 3.12+.

- **User-friendly GUI**  
  Tabbed results, export to CSV/JSON, automatic classified layer loading, and temp file cleanup.

---

## 📋 Supported Indices

| Index | Method / Reference |
|-------|---------------------|
| Chlorophyll-a Ensemble | Weighted average (NDCI + 2-Band + Moses) |
| Chlorophyll-a NDCI | Mishra & Mishra (2012) |
| Chlorophyll-a 2-Band | Gitelson et al. (2008) |
| Chlorophyll-a Moses | Moses et al. (2012) |
| TSI (Carlson) | Carlson (1977) |
| Secchi Depth | Kutser et al. (2005) |
| TSS | Nechad et al. (2010) |
| Turbidity | Dogliotti et al. (2015) |
| NDCI, NDVI, FAI, MNDWI | Standard spectral indices |

---

## 🚀 Quick Start

### 1. Installation
- Download the plugin as a ZIP from the [Releases](https://github.com/omerorucu/biwqa/releases) page.
- In QGIS: `Plugins → Manage and Install Plugins → Install from ZIP`.

### 2. Usage
1. Open the plugin from the toolbar or `Plugins → BiWQA`.
2. For each index, load **Time 1** and **Time 2** GeoTIFF files.
3. (Optional) Enable MNDWI water masking – add a second band (MNDWI) to your rasters.
4. Set the pixel size (e.g., 10 m for Sentinel-2).
5. Click **🚀 START CHANGE ANALYSIS**.
6. View results in the tabs: Statistics, Change Matrix, Change Types, Detailed Report, Summary.
7. Export results to CSV, JSON, and text files.

---

## 📁 Outputs

| File | Description |
|------|-------------|
| `statistics.csv` | Area per class, change area, Kappa, bitemporal direction |
| `change_types.csv` | From‑class → To‑class transitions with area and percentage |
| `detailed_report.txt` | Full human-readable report per index |
| `summary.txt` | Overall summary across indices |
| `*_change_matrix.csv` | Class transition matrix (rows = From, cols = To) |
| `*_provenance.json` | ISO 19115-style metadata (inputs, parameters, quality) |

Additionally, the plugin adds the following layers to your QGIS project:
- `{Index}_Time1` / `{Index}_Time2` – classified rasters
- `{Index}_Change_Map` – uint16 change map (0 = unchanged, otherwise code = From×100 + To)

---

## 🧪 Requirements

- **QGIS** 3.16 or later (including QGIS 4.x)
- **Python** 3.9+
- **NumPy** (bundled with QGIS)
- **GDAL** (bundled with QGIS)

No external Python packages are required – all dependencies are included in QGIS.

---

## 📚 Citation

If you use BiWQA in your research, please cite:

> Orucu, O. K. (2026). BiWQA – Bitemporal Water Quality Analyzer (Version 1.1.0). QGIS Plugin. https://github.com/omerorucu/biwqa

---

## 🤝 Contributing

Contributions are welcome! Please open an issue or pull request for:
- Bug reports
- New water quality indices
- Improved classification thresholds
- Translation/localization

---

## 📄 License

This project is licensed under the **GNU General Public License v3.0 or later**.  
See the [LICENSE](LICENSE) file for details.

---

## 👤 Author

**Ömer K. ORUCU**  
[omerorucu@sdu.edu.tr](mailto:omerorucu@sdu.edu.tr)  
Süleyman Demirel University, Türkiye

---

## 🙏 Acknowledgements

- Developed with the assistance of **DeepSeek AI** and **Claude AI (Anthropic)**.
- Classification thresholds based on Carlson (1977), Mishra & Mishra (2012), Gitelson et al. (2008), Dogliotti et al. (2015), and others.