# BiWQA — Bitemporal Water Quality Analyzer

**BiWQA** is a QGIS plugin for bitemporal analysis of surface water quality
using remote sensing indices. It applies peer-reviewed classification
thresholds and quantifies class-level change between two time periods.

The repository also contains the **Google Earth Engine script** that produces
the input rasters (see [`gee/`](gee/)), so the full workflow — from satellite
imagery to change statistics — is reproducible end to end.

---

## Features

- **Multi-index support**
  Chlorophyll-a (Ensemble, NDCI, 2-Band, Moses), Turbidity (NDTI, Dogliotti),
  CDOM, Secchi Depth, Trophic State Index (TSI), NDWI, MNDWI, and more.

- **Bitemporal change detection**
  Pixel-level change maps, class transition matrices, and area-based statistics.

- **Advanced analytics**
  - Cohen's Kappa coefficient for change agreement
  - Uncertainty propagation (quadrature error)
  - Sensitivity analysis for threshold perturbations
  - ISO 19115-inspired provenance logging

- **Performance & memory**
  Vectorized change matrix (`np.bincount`), uint16 change maps, and efficient
  NoData handling.

- **QGIS 4.0 ready**
  Full compatibility with PyQt6, QGIS 4.0 APIs, and Python 3.12+ (PyQt5 /
  QGIS 3.16+ still supported).

- **User-friendly GUI**
  Tabbed results, export to CSV/JSON, automatic classified layer loading, and
  temp file cleanup.

---

## Supported indices

| Index | Method / Reference |
|-------|--------------------|
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

## Quick start

### 1. Produce the input rasters (optional but recommended)

Run [`gee/lake_water_quality_gee.js`](gee/lake_water_quality_gee.js) in the
[GEE Code Editor](https://code.earthengine.google.com) for each of your two
periods and export the GeoTIFFs. Details in [`gee/README.md`](gee/README.md).

Any single-band, floating-point GeoTIFF of the same index also works — the
plugin does not require the GEE script.

### 2. Installation

- Download the plugin as a ZIP from the [Releases](https://github.com/omerorucu/biwqa/releases) page
  (or download this repository as a ZIP).
- In QGIS: `Plugins → Manage and Install Plugins → Install from ZIP`.

### 3. Usage

1. Open the plugin from the toolbar or `Plugins → BiWQA`.
2. For each index, load the **Time 1** and **Time 2** GeoTIFF files.
3. (Optional) Enable MNDWI water masking — add a second band (MNDWI) to your
   rasters; pixels with MNDWI ≤ 0 are excluded.
4. Set the pixel size (e.g. 10 m for Sentinel-2, 30 m for Landsat).
5. Click **START CHANGE ANALYSIS**.
6. View results in the tabs: Statistics, Change Matrix, Change Types, Detailed
   Report, Summary.
7. Export results to CSV, JSON, and text files.

---

## Outputs

| File | Description |
|------|-------------|
| `statistics.csv` | Area per class, change area, Kappa, bitemporal direction |
| `change_types.csv` | From-class → To-class transitions with area and percentage |
| `detailed_report.txt` | Full human-readable report per index |
| `summary.txt` | Overall summary across indices |
| `*_change_matrix.csv` | Class transition matrix (rows = From, cols = To) |
| `*_provenance.json` | ISO 19115-style metadata (inputs, parameters, quality) |

Additionally, the plugin adds the following layers to your QGIS project:

- `{Index}_Time1` / `{Index}_Time2` — classified rasters
- `{Index}_Change_Map` — uint16 change map (0 = unchanged, otherwise
  code = From×100 + To)

---

## Repository layout

```
biwqa/
├── __init__.py                            # QGIS plugin entry point (classFactory)
├── biwqa.py                               # Plugin class; toolbar/menu registration
├── main_dialog_water_quality.py           # GUI, tabs, threading, exports
├── change_analyzer.py                     # Change detection, Kappa, uncertainty
├── classification_rules_water_quality.py  # Index thresholds and class definitions
├── metadata.txt                           # QGIS plugin metadata
├── LICENSE                                # GNU GPL v3
└── gee/
    ├── lake_water_quality_gee.js          # Earth Engine script (ESM_2 of the paper)
    └── README.md                          # How to run it, band list, limitations
```

---

## Requirements

- **QGIS** 3.16 or later (including QGIS 4.x)
- **Python** 3.9+
- **NumPy** (bundled with QGIS)
- **GDAL** (bundled with QGIS)

No external Python packages are required — all dependencies are included in
QGIS.

---

## Citation

If you use BiWQA in your research, please cite the article and, if you wish,
the plugin itself:

> Örücü, Ö. K., & Örücü, S. (2026). Landscape-based assessment of trophic
> shift: integrating remote sensing for sustainable management of Lake
> Beyşehir. *International Journal of Environmental Science and Technology*,
> 23, 554. https://doi.org/10.1007/s13762-026-07323-w

> Örücü, Ö. K. (2026). *BiWQA — Bitemporal Water Quality Analyzer*
> (Version 1.1.0) [QGIS plugin]. https://github.com/omerorucu/biwqa

The article is open access (CC BY 4.0); the plugin is described there as the
"Water Quality Temporal Change Analysis" plugin, renamed BiWQA in v1.1.0.

---

## Validation note

BiWQA was developed as part of the study above and has not been independently
validated on external datasets. Users are encouraged to verify results against
in-situ measurements before operational deployment.

---

## Contributing

Contributions are welcome. Please open an issue or pull request for:

- Bug reports
- New water quality indices
- Improved classification thresholds
- Translation / localization

---

## License

This project is licensed under the **GNU General Public License v3.0 or
later**. See the [LICENSE](LICENSE) file for details.

---

## Author

**Ömer K. Örücü**
Department of Landscape Architecture, Faculty of Architecture
Süleyman Demirel University, Isparta, Türkiye
[omerorucu@sdu.edu.tr](mailto:omerorucu@sdu.edu.tr)

---

## Acknowledgements

- Developed with the assistance of **DeepSeek AI** and **Claude AI (Anthropic)**.
- Classification thresholds based on Carlson (1977), Mishra & Mishra (2012),
  Gitelson et al. (2008), Dogliotti et al. (2015), Kutser et al. (2005),
  Nechad et al. (2010), Xu (2006), and others.
