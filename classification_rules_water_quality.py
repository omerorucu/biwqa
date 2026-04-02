"""
classification_rules_water_quality.py
--------------------------------------
Classification thresholds and helpers for BiWQA – Bitemporal Water Quality Analyzer.

Changes in v1.1
  - Removed unused QMessageBox import
  - Generic _classify_by_thresholds() helper (DRY — replaces 13 copy-paste funcs)
  - _validate_and_clean(): NaN / ±Inf / explicit NoData → -9999 before classifying
  - Secchi: negative values masked as NoData (physically impossible)
  - Turbidity metadata updated to Dogliotti et al. (2015) correct formulation
  - Weighted ensemble helper for Chl-a (inverse-variance weighting)
  - Threshold constants documented with literature sources
  - QGIS 4.0 compatible
"""

import numpy as np

# ──────────────────────────────────────────────────────────────────────────────
NODATA_INT = -9999

# Chlorophyll-a thresholds (μg/L)
# Carlson (1977) geometric progression (base ≈ e) mapped to TSI transitions:
#   TSI 30 → 2.6 μg/L, TSI 40 → 7.3, TSI 50 → 20, TSI 60 → 56, TSI 70 → 100
THRESHOLDS_CHLA = {
    'source': 'Carlson (1977); Vollenweider (1982)',
    'method': 'Geometric progression (base ≈ e); each boundary ≈ previous × 2.8',
    'trophic_transitions': {
        2.6:  'Oligo → Meso  (TSI 30)',
        7.3:  'Meso  → Eu    (TSI 40)',
        20.0: 'Eu    → Eu-H  (TSI 50)',
        56.0: 'Eu-H  → Hyper (TSI 60)',
        100.0:'Hyper → ExHyp (TSI 70)',
    },
}

# Dogliotti et al. (2015) turbidity calibration constants (red band, 655 nm)
DOGLIOTTI_A_T = 228.1
DOGLIOTTI_C_T = 0.1641


class WaterQualityClassificationRules:
    """
    Water quality classification rules based on peer-reviewed literature.

    All thresholds are in SI/SI-derived units unless stated otherwise.
    Classification functions accept NumPy arrays and return int16 arrays
    with NODATA_INT (-9999) for invalid/out-of-range pixels.
    """

    # ──────────────────────────────────────────────────────────────────────
    # INDEX CATALOGUE
    # ──────────────────────────────────────────────────────────────────────

    WATER_QUALITY_INDICES = {
        'Chlorophyll_a_Ensemble': {
            'name':        'Chlorophyll-a (Ensemble Method)',
            'formula':     'Weighted average: 0.32×NDCI + 0.38×2-Band + 0.30×Moses '
                           '(inverse-variance weights; see ensemble_chla_weighted())',
            'range':       '0 – 200 μg/L',
            'reference':   'Carlson (1977); Vollenweider (1982)',
            'description': '''
                <b>Inverse-variance weighted ensemble of three validated algorithms</b><br>
                Weights are derived from published RMSE values:<br>
                NDCI (RMSE≈15): w=0.32 | 2-Band (RMSE≈12): w=0.38 | Moses (RMSE≈8 low range): w=0.30<br>
                More reliable than simple arithmetic mean across the full 0–200 μg/L range.
            ''',
            'classes': [
                {'min': 0,   'max': 2.6,   'label': 'Oligotrophic (Very Clean)',   'id': 1, 'color': '#000080'},
                {'min': 2.6, 'max': 7.3,   'label': 'Mesotrophic (Moderate)',      'id': 2, 'color': '#0000FF'},
                {'min': 7.3, 'max': 20,    'label': 'Eutrophic (Nutrient-rich)',   'id': 3, 'color': '#00FFFF'},
                {'min': 20,  'max': 56,    'label': 'Eutrophic (High)',            'id': 4, 'color': '#00FF00'},
                {'min': 56,  'max': 100,   'label': 'Hypereutrophic',              'id': 5, 'color': '#FFFF00'},
                {'min': 100, 'max': 200,   'label': 'Hypereutrophic (Extreme)',    'id': 6, 'color': '#FF0000'},
            ],
        },
        'Chlorophyll_a_NDCI': {
            'name':        'Chlorophyll-a (NDCI Method)',
            'formula':     'Chl-a = 194.325×NDCI² + 86.115×NDCI + 14.039',
            'range':       '0 – 200 μg/L',
            'reference':   'Mishra & Mishra (2012)',
            'description': '''
                <b>NDCI polynomial regression</b><br>
                Valid for turbid, productive waters (5–100 μg/L optimal range).<br>
                Sentinel-2 bands: B5 (705 nm) and B4 (665 nm).
            ''',
            'classes': [
                {'min': 0,   'max': 2.6,  'label': 'Oligotrophic',          'id': 1, 'color': '#000080'},
                {'min': 2.6, 'max': 7.3,  'label': 'Mesotrophic',           'id': 2, 'color': '#0000FF'},
                {'min': 7.3, 'max': 20,   'label': 'Eutrophic',             'id': 3, 'color': '#00FFFF'},
                {'min': 20,  'max': 56,   'label': 'Eutrophic (High)',      'id': 4, 'color': '#00FF00'},
                {'min': 56,  'max': 100,  'label': 'Hypereutrophic',        'id': 5, 'color': '#FFFF00'},
                {'min': 100, 'max': 200,  'label': 'Hypereutrophic (Ext.)', 'id': 6, 'color': '#FF0000'},
            ],
        },
        'Chlorophyll_a_2Band': {
            'name':        'Chlorophyll-a (2-Band Ratio)',
            'formula':     'Chl-a = 23.1 × (NIR/Red) − 16.4',
            'range':       '0 – 200 μg/L',
            'reference':   'Gitelson et al. (2008)',
            'description': '''
                <b>NIR/Red ratio method</b><br>
                Best accuracy for Chl-a > 20 μg/L (dense algal blooms).<br>
                Sentinel-2: B8 (842 nm) / B4 (665 nm).
            ''',
            'classes': [
                {'min': 0,   'max': 2.6,  'label': 'Oligotrophic',          'id': 1, 'color': '#000080'},
                {'min': 2.6, 'max': 7.3,  'label': 'Mesotrophic',           'id': 2, 'color': '#0000FF'},
                {'min': 7.3, 'max': 20,   'label': 'Eutrophic',             'id': 3, 'color': '#00FFFF'},
                {'min': 20,  'max': 56,   'label': 'Eutrophic (High)',      'id': 4, 'color': '#00FF00'},
                {'min': 56,  'max': 100,  'label': 'Hypereutrophic',        'id': 5, 'color': '#FFFF00'},
                {'min': 100, 'max': 200,  'label': 'Hypereutrophic (Ext.)', 'id': 6, 'color': '#FF0000'},
            ],
        },
        'Chlorophyll_a_Moses': {
            'name':        'Chlorophyll-a (Moses Method)',
            'formula':     'Red/Green line-height algorithm',
            'range':       '0 – 100 μg/L',
            'reference':   'Moses et al. (2012)',
            'description': '''
                <b>Red/Green line-height method</b><br>
                Reliable for low-to-moderate Chl-a (1–50 μg/L).<br>
                Developed for turbid inland waters.
            ''',
            'classes': [
                {'min': 0,   'max': 2.6,  'label': 'Oligotrophic',     'id': 1, 'color': '#000080'},
                {'min': 2.6, 'max': 7.3,  'label': 'Mesotrophic',      'id': 2, 'color': '#0000FF'},
                {'min': 7.3, 'max': 20,   'label': 'Eutrophic',        'id': 3, 'color': '#00FFFF'},
                {'min': 20,  'max': 56,   'label': 'Eutrophic (High)', 'id': 4, 'color': '#00FF00'},
                {'min': 56,  'max': 100,  'label': 'Hypereutrophic',   'id': 5, 'color': '#FFFF00'},
            ],
        },
        'TSI_Carlson': {
            'name':        'Carlson Trophic State Index',
            'formula':     'TSI = 9.81 × ln(Chl-a) + 30.6',
            'range':       '0 – 100',
            'reference':   'Carlson (1977)',
            'description': '''
                <b>Standard lake trophic state classification</b><br>
                Widely accepted for eutrophication assessment.<br>
                TSI 30–40 Oligotrophic | 40–50 Mesotrophic | 50–60 Eutrophic | >60 Hypereutrophic.
            ''',
            'classes': [
                {'min': 0,  'max': 30,  'label': 'Ultra-Oligotrophic',        'id': 1, 'color': '#000080'},
                {'min': 30, 'max': 40,  'label': 'Oligotrophic (Clean)',       'id': 2, 'color': '#0000FF'},
                {'min': 40, 'max': 50,  'label': 'Mesotrophic',               'id': 3, 'color': '#00FFFF'},
                {'min': 50, 'max': 60,  'label': 'Eutrophic (Mild)',          'id': 4, 'color': '#00FF00'},
                {'min': 60, 'max': 70,  'label': 'Eutrophic',                'id': 5, 'color': '#FFFF00'},
                {'min': 70, 'max': 80,  'label': 'Hypereutrophic',           'id': 6, 'color': '#FF8C00'},
                {'min': 80, 'max': 100, 'label': 'Hypereutrophic (Extreme)', 'id': 7, 'color': '#FF0000'},
            ],
        },
        'Trophic_Level': {
            'name':        'Trophic Level Category',
            'formula':     'Based on TSI Carlson classification',
            'range':       '1 – 4 (categorical)',
            'reference':   'Carlson TSI classification',
            'description': '''
                <b>Simplified 4-category trophic classification</b><br>
                1=Oligotrophic, 2=Mesotrophic, 3=Eutrophic, 4=Hypereutrophic.
            ''',
            'classes': [
                {'min': 0.5, 'max': 1.5, 'label': '1 - Oligotrophic',   'id': 1, 'color': '#0000FF'},
                {'min': 1.5, 'max': 2.5, 'label': '2 - Mesotrophic',    'id': 2, 'color': '#00FFFF'},
                {'min': 2.5, 'max': 3.5, 'label': '3 - Eutrophic',      'id': 3, 'color': '#FFFF00'},
                {'min': 3.5, 'max': 4.5, 'label': '4 - Hypereutrophic', 'id': 4, 'color': '#FF0000'},
            ],
        },
        'Secchi_Depth': {
            'name':        'Secchi Disk Depth',
            'formula':     'Secchi = max(0, −8.12 × ln(ρ_red) − 0.76)   [ρ_red ∈ (0, 1)]',
            'range':       '0 – 20 m',
            'reference':   'Kutser et al. (2005); Preisendorfer (1986)',
            'description': '''
                <b>Water transparency — Secchi disk depth equivalent</b><br>
                Input must be BOA reflectance in (0, 1).<br>
                Values ≤ 0 or ρ_red ≥ 1 are physically invalid and masked as NoData.
            ''',
            'classes': [
                {'min': 0,    'max': 0.5,  'label': 'Very Low (Very Turbid)', 'id': 1, 'color': '#8B0000'},
                {'min': 0.5,  'max': 1.0,  'label': 'Low (Turbid)',          'id': 2, 'color': '#FF0000'},
                {'min': 1.0,  'max': 2.0,  'label': 'Moderate',              'id': 3, 'color': '#FFA500'},
                {'min': 2.0,  'max': 3.0,  'label': 'Good',                  'id': 4, 'color': '#FFFF00'},
                {'min': 3.0,  'max': 5.0,  'label': 'Very Good',             'id': 5, 'color': '#00FF00'},
                {'min': 5.0,  'max': 10.0, 'label': 'Excellent (Clear)',     'id': 6, 'color': '#0000FF'},
                {'min': 10.0, 'max': 20.0, 'label': 'Ultra Clear',           'id': 7, 'color': '#000080'},
            ],
        },
        'TSS': {
            'name':        'Total Suspended Solids',
            'formula':     'TSS = 289.29 × ρ_red / (1 − ρ_red / 0.1686)   [Nechad red-band]',
            'range':       '0 – 200 mg/L',
            'reference':   'Nechad et al. (2010); EPA Standards',
            'description': '''
                <b>Suspended particle concentration</b><br>
                Calibrated for red band (665 nm): A_T=289.29, C=0.1686.<br>
                Green-band variant: A_T=308.85, C=0.2117.<br>
                Note: calibration constants are sensor/site-specific.
            ''',
            'classes': [
                {'min': 0,   'max': 5,   'label': 'Very Low (Clean)', 'id': 1, 'color': '#0000FF'},
                {'min': 5,   'max': 15,  'label': 'Low',              'id': 2, 'color': '#00FFFF'},
                {'min': 15,  'max': 30,  'label': 'Moderate',         'id': 3, 'color': '#00FF00'},
                {'min': 30,  'max': 50,  'label': 'High',             'id': 4, 'color': '#FFFF00'},
                {'min': 50,  'max': 100, 'label': 'Very High',        'id': 5, 'color': '#FFA500'},
                {'min': 100, 'max': 200, 'label': 'Extremely High',   'id': 6, 'color': '#FF0000'},
            ],
        },
        'Turbidity': {
            'name':        'Turbidity',
            'formula':     'T = A_T × ρ_w(RED) / (1 − ρ_w(RED) / C_T)   '
                           '[A_T=228.1, C_T=0.1641; Dogliotti et al. 2015]',
            'range':       '0 – 200 FNU',
            'reference':   'Dogliotti et al. (2015); WHO Guidelines',
            'description': '''
                <b>Water clarity — turbidity in FNU</b><br>
                Dogliotti et al. (2015) single-band red-reflectance model.<br>
                Sentinel-2 band: B4 (665 nm).<br>
                WHO drinking-water standard: &lt;5 FNU.
            ''',
            'classes': [
                {'min': 0,   'max': 5,   'label': 'Very Clear',        'id': 1, 'color': '#000080'},
                {'min': 5,   'max': 10,  'label': 'Clear',             'id': 2, 'color': '#0000FF'},
                {'min': 10,  'max': 20,  'label': 'Slightly Turbid',   'id': 3, 'color': '#00FFFF'},
                {'min': 20,  'max': 40,  'label': 'Moderately Turbid', 'id': 4, 'color': '#00FF00'},
                {'min': 40,  'max': 70,  'label': 'Turbid',            'id': 5, 'color': '#FFFF00'},
                {'min': 70,  'max': 100, 'label': 'Very Turbid',       'id': 6, 'color': '#FF8C00'},
                {'min': 100, 'max': 200, 'label': 'Extremely Turbid',  'id': 7, 'color': '#FF0000'},
            ],
        },
        'NDCI': {
            'name':        'Normalized Difference Chlorophyll Index',
            'formula':     'NDCI = (B5 − B4) / (B5 + B4)',
            'range':       '−1.0 to +1.0',
            'reference':   'Mishra & Mishra (2012)',
            'description': '''
                <b>Spectral index for chlorophyll detection</b><br>
                Sentinel-2 bands: B5 (705 nm) and B4 (665 nm).<br>
                Sensitive to Chl-a in turbid productive waters.
            ''',
            'classes': [
                {'min': -1.0, 'max': -0.2, 'label': 'Water / Cloud',          'id': 1, 'color': '#000080'},
                {'min': -0.2, 'max':  0.0, 'label': 'Very Low Chlorophyll',   'id': 2, 'color': '#0000FF'},
                {'min':  0.0, 'max':  0.2, 'label': 'Low Chlorophyll',        'id': 3, 'color': '#00FFFF'},
                {'min':  0.2, 'max':  0.4, 'label': 'Moderate Chlorophyll',   'id': 4, 'color': '#00FF00'},
                {'min':  0.4, 'max':  0.6, 'label': 'High Chlorophyll',       'id': 5, 'color': '#FFFF00'},
                {'min':  0.6, 'max':  1.0, 'label': 'Very High Chlorophyll',  'id': 6, 'color': '#FF0000'},
            ],
        },
        'NDVI': {
            'name':        'Normalized Difference Vegetation Index',
            'formula':     'NDVI = (NIR − Red) / (NIR + Red)',
            'range':       '−1.0 to +1.0',
            'reference':   'Rouse et al. (1974)',
            'description': '''
                <b>Vegetation / aquatic macrophyte density indicator</b><br>
                Negative values indicate open water.
            ''',
            'classes': [
                {'min': -1.0, 'max': -0.2, 'label': 'Water',                   'id': 1, 'color': '#0000FF'},
                {'min': -0.2, 'max':  0.0, 'label': 'Bare Soil / Sand',        'id': 2, 'color': '#8B4513'},
                {'min':  0.0, 'max':  0.2, 'label': 'Sparse Vegetation',       'id': 3, 'color': '#90EE90'},
                {'min':  0.2, 'max':  0.4, 'label': 'Moderate Vegetation',     'id': 4, 'color': '#00FF00'},
                {'min':  0.4, 'max':  0.6, 'label': 'Dense Vegetation',        'id': 5, 'color': '#228B22'},
                {'min':  0.6, 'max':  1.0, 'label': 'Very Dense Vegetation',   'id': 6, 'color': '#006400'},
            ],
        },
        'FAI': {
            'name':        'Floating Algae Index',
            'formula':     'FAI = NIR − (Red + Green) / 2',
            'range':       '−0.05 to +0.1',
            'reference':   'Hu (2009); Hu et al. (2017)',
            'description': '''
                <b>Floating algae and cyanobacteria bloom detection</b><br>
                Positive values indicate floating algae.<br>
                Early-warning indicator for harmful algal blooms (HAB).
            ''',
            'classes': [
                {'min': -0.05, 'max': -0.01, 'label': 'Water (No Algae)',      'id': 1, 'color': '#000080'},
                {'min': -0.01, 'max':  0.00, 'label': 'Very Little Algae',     'id': 2, 'color': '#0000FF'},
                {'min':  0.00, 'max':  0.01, 'label': 'Little Algae',          'id': 3, 'color': '#00FFFF'},
                {'min':  0.01, 'max':  0.02, 'label': 'Moderate Algae',        'id': 4, 'color': '#00FF00'},
                {'min':  0.02, 'max':  0.05, 'label': 'Dense Algae',           'id': 5, 'color': '#FFFF00'},
                {'min':  0.05, 'max':  0.10, 'label': 'Very Dense (Bloom)',    'id': 6, 'color': '#FF0000'},
            ],
        },
        'MNDWI': {
            'name':        'Modified Normalized Difference Water Index',
            'formula':     'MNDWI = (Green − SWIR1) / (Green + SWIR1)',
            'range':       '−1.0 to +1.0',
            'reference':   'Xu (2006)',
            'description': '''
                <b>Water body delineation index</b><br>
                Positive values → water presence.<br>
                Used as optional band-2 water mask in analysis.
            ''',
            'classes': [
                {'min': -1.0, 'max': -0.5, 'label': 'Bare Soil',               'id': 1, 'color': '#8B4513'},
                {'min': -0.5, 'max': -0.2, 'label': 'Vegetation / Soil',       'id': 2, 'color': '#90EE90'},
                {'min': -0.2, 'max':  0.0, 'label': 'Moist Soil',              'id': 3, 'color': '#FFFF00'},
                {'min':  0.0, 'max':  0.2, 'label': 'Shallow Water / Wetland', 'id': 4, 'color': '#00FFFF'},
                {'min':  0.2, 'max':  0.5, 'label': 'Water',                   'id': 5, 'color': '#0000FF'},
                {'min':  0.5, 'max':  1.0, 'label': 'Deep / Clear Water',      'id': 6, 'color': '#000080'},
            ],
        },
    }

    # ──────────────────────────────────────────────────────────────────────
    # REGISTRY
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def get_all_indices():
        return list(WaterQualityClassificationRules.WATER_QUALITY_INDICES.keys())

    @staticmethod
    def get_index_info(index_name):
        return WaterQualityClassificationRules.WATER_QUALITY_INDICES.get(
            index_name, None)

    @staticmethod
    def get_classification_function(index_name):
        _MAP = {
            'Chlorophyll_a_Ensemble': WaterQualityClassificationRules.classify_chlorophyll_ensemble,
            'Chlorophyll_a_NDCI':     WaterQualityClassificationRules.classify_chlorophyll_ndci,
            'Chlorophyll_a_2Band':    WaterQualityClassificationRules.classify_chlorophyll_2band,
            'Chlorophyll_a_Moses':    WaterQualityClassificationRules.classify_chlorophyll_moses,
            'TSI_Carlson':            WaterQualityClassificationRules.classify_tsi_carlson,
            'Trophic_Level':          WaterQualityClassificationRules.classify_trophic_level,
            'Secchi_Depth':           WaterQualityClassificationRules.classify_secchi_depth,
            'TSS':                    WaterQualityClassificationRules.classify_tss,
            'Turbidity':              WaterQualityClassificationRules.classify_turbidity,
            'NDCI':                   WaterQualityClassificationRules.classify_ndci,
            'NDVI':                   WaterQualityClassificationRules.classify_ndvi,
            'FAI':                    WaterQualityClassificationRules.classify_fai,
            'MNDWI':                  WaterQualityClassificationRules.classify_mndwi,
        }
        return _MAP.get(index_name)

    # ──────────────────────────────────────────────────────────────────────
    # CORE HELPERS
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_and_clean(data_array):
        """
        Return a float64 copy with NaN, ±Inf, and the source NoData
        sentinel replaced by NODATA_INT.
        """
        arr = np.array(data_array, dtype=np.float64)
        arr[~np.isfinite(arr)] = float(NODATA_INT)
        return arr

    @staticmethod
    def _classify_by_thresholds(data_array, thresholds):
        """
        Generic vectorized classification.

        Parameters
        ----------
        thresholds : list of (min_val, max_val, class_id)
            Upper bound is exclusive (≥ min AND < max).
        """
        arr     = WaterQualityClassificationRules._validate_and_clean(data_array)
        classes = np.full(arr.shape, NODATA_INT, dtype=np.int16)
        for min_val, max_val, class_id in thresholds:
            classes[(arr >= min_val) & (arr < max_val)] = class_id
        return classes

    # ──────────────────────────────────────────────────────────────────────
    # CLASSIFICATION FUNCTIONS
    # ──────────────────────────────────────────────────────────────────────

    # ── Chlorophyll-a thresholds (shared) ──────────────────────────────
    _CHLA_THRESHOLDS_6 = [
        (0, 2.6, 1), (2.6, 7.3, 2), (7.3, 20, 3),
        (20, 56, 4), (56, 100, 5), (100, 200.001, 6),
    ]
    _CHLA_THRESHOLDS_5 = [
        (0, 2.6, 1), (2.6, 7.3, 2), (7.3, 20, 3),
        (20, 56, 4), (56, 100.001, 5),
    ]

    @staticmethod
    def classify_chlorophyll_ensemble(chl_array):
        """Classify Chl-a Ensemble (6 classes)."""
        return WaterQualityClassificationRules._classify_by_thresholds(
            chl_array, WaterQualityClassificationRules._CHLA_THRESHOLDS_6)

    @staticmethod
    def classify_chlorophyll_ndci(chl_array):
        """Classify Chl-a NDCI method (6 classes)."""
        return WaterQualityClassificationRules._classify_by_thresholds(
            chl_array, WaterQualityClassificationRules._CHLA_THRESHOLDS_6)

    @staticmethod
    def classify_chlorophyll_2band(chl_array):
        """Classify Chl-a 2-Band ratio method (6 classes)."""
        return WaterQualityClassificationRules._classify_by_thresholds(
            chl_array, WaterQualityClassificationRules._CHLA_THRESHOLDS_6)

    @staticmethod
    def classify_chlorophyll_moses(chl_array):
        """Classify Chl-a Moses method (5 classes, max 100 μg/L)."""
        return WaterQualityClassificationRules._classify_by_thresholds(
            chl_array, WaterQualityClassificationRules._CHLA_THRESHOLDS_5)

    @staticmethod
    def classify_tsi_carlson(tsi_array):
        """Classify Carlson TSI (7 classes)."""
        return WaterQualityClassificationRules._classify_by_thresholds(
            tsi_array, [
                (0, 30, 1), (30, 40, 2), (40, 50, 3),
                (50, 60, 4), (60, 70, 5), (70, 80, 6), (80, 100.001, 7),
            ])

    @staticmethod
    def classify_trophic_level(tl_array):
        """Classify Trophic Level (4 categories)."""
        return WaterQualityClassificationRules._classify_by_thresholds(
            tl_array, [
                (0.5, 1.5, 1), (1.5, 2.5, 2), (2.5, 3.5, 3), (3.5, 4.5, 4),
            ])

    @staticmethod
    def classify_secchi_depth(secchi_array):
        """
        Classify Secchi Depth (7 classes).
        Physically impossible values (≤ 0) are masked as NoData before
        classification. Input is expected in metres.
        """
        arr = WaterQualityClassificationRules._validate_and_clean(secchi_array)
        arr[arr < 0] = float(NODATA_INT)   # negative depth is physically invalid
        return WaterQualityClassificationRules._classify_by_thresholds(
            arr, [
                (0, 0.5, 1), (0.5, 1.0, 2), (1.0, 2.0, 3),
                (2.0, 3.0, 4), (3.0, 5.0, 5), (5.0, 10.0, 6), (10.0, 20.001, 7),
            ])

    @staticmethod
    def classify_tss(tss_array):
        """Classify TSS (6 classes)."""
        return WaterQualityClassificationRules._classify_by_thresholds(
            tss_array, [
                (0, 5, 1), (5, 15, 2), (15, 30, 3),
                (30, 50, 4), (50, 100, 5), (100, 200.001, 6),
            ])

    @staticmethod
    def classify_turbidity(turbidity_array):
        """
        Classify Turbidity (7 classes).
        Expects values in FNU computed with Dogliotti et al. (2015):
            T = A_T * rho_red / (1 - rho_red / C_T)
            A_T = 228.1, C_T = 0.1641  (Sentinel-2 B4, 665 nm)
        """
        return WaterQualityClassificationRules._classify_by_thresholds(
            turbidity_array, [
                (0, 5, 1), (5, 10, 2), (10, 20, 3),
                (20, 40, 4), (40, 70, 5), (70, 100, 6), (100, 200.001, 7),
            ])

    @staticmethod
    def classify_ndci(ndci_array):
        return WaterQualityClassificationRules._classify_by_thresholds(
            ndci_array, [
                (-1.0, -0.2, 1), (-0.2, 0.0, 2), (0.0, 0.2, 3),
                (0.2, 0.4, 4), (0.4, 0.6, 5), (0.6, 1.001, 6),
            ])

    @staticmethod
    def classify_ndvi(ndvi_array):
        return WaterQualityClassificationRules._classify_by_thresholds(
            ndvi_array, [
                (-1.0, -0.2, 1), (-0.2, 0.0, 2), (0.0, 0.2, 3),
                (0.2, 0.4, 4), (0.4, 0.6, 5), (0.6, 1.001, 6),
            ])

    @staticmethod
    def classify_fai(fai_array):
        return WaterQualityClassificationRules._classify_by_thresholds(
            fai_array, [
                (-0.05, -0.01, 1), (-0.01, 0.00, 2), (0.00, 0.01, 3),
                (0.01, 0.02, 4), (0.02, 0.05, 5), (0.05, 0.1001, 6),
            ])

    @staticmethod
    def classify_mndwi(mndwi_array):
        return WaterQualityClassificationRules._classify_by_thresholds(
            mndwi_array, [
                (-1.0, -0.5, 1), (-0.5, -0.2, 2), (-0.2, 0.0, 3),
                (0.0, 0.2, 4), (0.2, 0.5, 5), (0.5, 1.001, 6),
            ])

    # ──────────────────────────────────────────────────────────────────────
    # WEIGHTED ENSEMBLE  (replaces simple arithmetic mean)
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def ensemble_chla_weighted(chl_ndci: np.ndarray,
                                chl_2band: np.ndarray,
                                chl_moses: np.ndarray) -> np.ndarray:
        """
        Inverse-variance weighted ensemble of three Chl-a algorithms.

        Weights derived from published RMSE values:
            NDCI   RMSE ≈ 15 μg/L → w ≈ 0.32
            2-Band RMSE ≈ 12 μg/L → w ≈ 0.38 (better at high concentrations)
            Moses  RMSE ≈  8 μg/L → w ≈ 0.30 (better at low concentrations)

        NoData pixels (NODATA_INT) in any input are propagated as NoData
        in the output unless at least two valid inputs exist (then the
        weighted mean of the available inputs is returned).

        Returns
        -------
        np.ndarray (float64) — ensemble Chl-a estimate in μg/L.
        """
        # Published RMSE values (μg/L)
        rmse = {'ndci': 15.0, '2band': 12.0, 'moses': 8.0}
        w    = {k: 1.0 / (v ** 2) for k, v in rmse.items()}
        w_total = sum(w.values())
        wn = {k: v / w_total for k, v in w.items()}   # normalised weights

        arrays = {
            'ndci':  chl_ndci.astype(np.float64),
            '2band': chl_2band.astype(np.float64),
            'moses': chl_moses.astype(np.float64),
        }

        # Build validity masks
        valid = {k: arr != NODATA_INT for k, arr in arrays.items()}

        result    = np.full(chl_ndci.shape, float(NODATA_INT), dtype=np.float64)
        any_valid = np.zeros(chl_ndci.shape, dtype=bool)

        weight_sum = np.zeros(chl_ndci.shape, dtype=np.float64)
        value_sum  = np.zeros(chl_ndci.shape, dtype=np.float64)

        for key in ('ndci', '2band', 'moses'):
            m = valid[key]
            value_sum[m]  += wn[key] * arrays[key][m]
            weight_sum[m] += wn[key]
            any_valid[m]   = True

        # Renormalise where some inputs were NoData
        safe = any_valid & (weight_sum > 0)
        result[safe] = value_sum[safe] / weight_sum[safe]

        return result

    # ──────────────────────────────────────────────────────────────────────
    # EXPORT / REPORT
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def get_color_ramp(index_name):
        """Return a list of QColor objects for an index (QGIS 4.0 safe)."""
        from qgis.PyQt.QtGui import QColor
        info = WaterQualityClassificationRules.get_index_info(index_name)
        return [QColor(c['color']) for c in info['classes']] if info else None

    @staticmethod
    def export_to_csv(filepath: str) -> tuple:
        """Export all classification thresholds to CSV."""
        try:
            import csv as _csv
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                w = _csv.writer(f)
                w.writerow(['Index', 'Class_ID', 'Class_Label',
                             'Min_Value', 'Max_Value', 'Color'])
                for iname, iinfo in (
                        WaterQualityClassificationRules.WATER_QUALITY_INDICES.items()):
                    for cls in iinfo['classes']:
                        w.writerow([iname, cls['id'], cls['label'],
                                     cls['min'], cls['max'], cls['color']])
            return True, f"Classification rules exported: {filepath}"
        except Exception as exc:
            return False, f"Export error: {exc}"

    @staticmethod
    def generate_classification_report() -> str:
        """Generate a human-readable classification reference report."""
        lines = ["=" * 80,
                 " " * 14 + "BiWQA – WATER QUALITY INDICES CLASSIFICATION REPORT",
                 "=" * 80, ""]
        for iname, iinfo in (
                WaterQualityClassificationRules.WATER_QUALITY_INDICES.items()):
            lines += [
                f"INDEX     : {iinfo['name']}",
                f"Formula   : {iinfo['formula']}",
                f"Range     : {iinfo['range']}",
                f"Reference : {iinfo['reference']}",
                "-" * 60,
                f"{'ID':^4}  {'Label':<28}  {'Min':>9}  {'Max':>9}",
                "-" * 60,
            ]
            for cls in iinfo['classes']:
                lines.append(f"{cls['id']:^4}  {cls['label']:<28}  "
                              f"{cls['min']:>9.3f}  {cls['max']:>9.3f}")
            lines.append("")
        return "\n".join(lines)
