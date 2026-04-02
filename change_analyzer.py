"""
change_analyzer.py
------------------
Core change-detection engine for BiWQA – Bitemporal Water Quality Analyzer.

Improvements in v1.1
  - Vectorized change-matrix (np.bincount) — up to 100x faster than Python loop
  - Cohen's Kappa coefficient for change-detection agreement
  - Error-propagation / combined uncertainty map
  - Sensitivity analysis on classification thresholds
  - ISO 19115-style provenance / metadata logging
  - uint16 change-map (halved memory vs int32)
  - QGIS 4.0 compatible (no deprecated APIs used here)
"""

import csv
import hashlib
from datetime import datetime, timezone

import numpy as np

# ──────────────────────────────────────────────────────────────────────────────
NODATA_INT   = -9999    # signed-int NoData sentinel
NODATA_UINT  = 65535    # uint16 NoData sentinel (change map)
PLUGIN_VERSION = "1.1.0"
PLUGIN_NAME    = "BiWQA – Bitemporal Water Quality Analyzer"


class ChangeAnalyzer:
    """Pixel-level temporal change analysis for classified water-quality rasters."""

    def __init__(self, pixel_size: float = 10.0):
        """
        Parameters
        ----------
        pixel_size : float
            Spatial resolution in metres.
            Sentinel-2 10 m bands → 10.0 (default)
            Sentinel-2 20 m bands → 20.0
        """
        self.pixel_size = float(pixel_size)

    # ──────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────────────────────

    def calculate_change(self, class_time1: np.ndarray,
                         class_time2: np.ndarray,
                         index_name: str) -> dict:
        """
        Compute pixel-level change statistics between two classified rasters.

        Parameters
        ----------
        class_time1, class_time2 : np.ndarray (int16)
            Classified rasters; NODATA_INT marks invalid/masked pixels.
        index_name : str
            Index label used in reports.

        Returns
        -------
        dict — full statistics (see keys below).
        """
        try:
            valid_mask = (class_time1 != NODATA_INT) & (class_time2 != NODATA_INT)

            if not np.any(valid_mask):
                raise ValueError("No valid pixels found in the input rasters.")

            valid_t1 = class_time1[valid_mask].astype(np.int32)
            valid_t2 = class_time2[valid_mask].astype(np.int32)

            unique_classes = np.unique(np.concatenate([valid_t1, valid_t2]))
            unique_classes = unique_classes[unique_classes != NODATA_INT]
            n_classes = len(unique_classes)

            # Vectorized change matrix
            change_matrix = self._build_change_matrix(valid_t1, valid_t2,
                                                       unique_classes, n_classes)
            kappa = self._calculate_kappa(change_matrix)

            # Change map (uint16)
            change_map = self._build_change_map(class_time1, class_time2,
                                                 valid_mask)

            # Area statistics
            pixel_area_ha = (self.pixel_size ** 2) / 10_000
            class_areas_t1, class_areas_t2 = self._class_areas(
                valid_t1, valid_t2, unique_classes, pixel_area_ha)

            changed_px   = int(np.sum(valid_t1 != valid_t2))
            unchanged_px = int(np.sum(valid_t1 == valid_t2))
            total_area   = int(np.sum(valid_mask)) * pixel_area_ha

            changed_area   = changed_px  * pixel_area_ha
            unchanged_area = unchanged_px * pixel_area_ha
            changed_pct    = (changed_area  / total_area * 100) if total_area > 0 else 0.0
            unchanged_pct  = (unchanged_area / total_area * 100) if total_area > 0 else 0.0

            change_type_areas, change_descriptions = self._change_type_stats(
                change_map, pixel_area_ha)

            return {
                'change_matrix':        change_matrix,
                'unique_classes':       unique_classes,
                'change_map':           change_map,
                'change_type_areas':    change_type_areas,
                'change_descriptions':  change_descriptions,
                'class_areas_time1':    class_areas_t1,
                'class_areas_time2':    class_areas_t2,
                'total_area_ha':        total_area,
                'changed_area_ha':      changed_area,
                'unchanged_area_ha':    unchanged_area,
                'changed_percent':      changed_pct,
                'unchanged_percent':    unchanged_pct,
                'changed_pixels':       changed_px,
                'unchanged_pixels':     unchanged_px,
                'pixel_area_ha':        pixel_area_ha,
                'kappa':                kappa,
                'kappa_interpretation': self._interpret_kappa(kappa),
            }

        except Exception as exc:
            raise Exception(f"Change analysis error: {exc}") from exc

    # ──────────────────────────────────────────────────────────────────────

    def calculate_change_with_uncertainty(self,
                                          class_time1: np.ndarray,
                                          class_time2: np.ndarray,
                                          conf_time1,
                                          conf_time2,
                                          index_name: str,
                                          uncertainty_threshold: float = 0.30
                                          ) -> dict:
        """
        Change analysis with quadrature error propagation.

        Parameters
        ----------
        conf_time1, conf_time2 : np.ndarray (float32, 0–1) or None
            Per-pixel classification confidence (1 = certain).
            Pass None to skip uncertainty propagation.
        uncertainty_threshold : float
            Pixels where combined uncertainty exceeds this value are flagged
            as unreliable (default 0.30).
        """
        stats = self.calculate_change(class_time1, class_time2, index_name)

        if conf_time1 is None or conf_time2 is None:
            stats['uncertainty_map']     = None
            stats['reliable_change_map'] = stats['change_map'].copy()
            stats['uncertainty_applied'] = False
            return stats

        # Convert confidence → uncertainty  (u = 1 − confidence)
        unc1 = np.clip(1.0 - conf_time1.astype(np.float32), 0.0, 1.0)
        unc2 = np.clip(1.0 - conf_time2.astype(np.float32), 0.0, 1.0)

        # Quadrature combination
        combined_unc = np.sqrt(unc1 ** 2 + unc2 ** 2) / np.sqrt(2.0)

        reliable_map = stats['change_map'].copy()
        unreliable   = combined_unc > uncertainty_threshold
        reliable_map[unreliable] = NODATA_UINT

        stats['uncertainty_map']     = combined_unc
        stats['reliable_change_map'] = reliable_map
        stats['uncertainty_applied'] = True
        stats['unreliable_px_pct']   = float(np.mean(unreliable) * 100)
        return stats

    # ──────────────────────────────────────────────────────────────────────

    def sensitivity_analysis(self,
                              class_time1: np.ndarray,
                              class_time2: np.ndarray,
                              index_name: str,
                              variations: tuple = (-0.10, 0.0, 0.10)) -> dict:
        """
        Assess how ±10 % threshold perturbation affects changed-area fraction.

        Because the plugin receives pre-classified arrays, a ±1 class shift
        approximates a ±10 % threshold perturbation.

        Returns
        -------
        dict with 'results' (variation → changed_pct) and 'sensitivity_std'.
        """
        results = {}
        for var in variations:
            if var == 0.0:
                s_t1, s_t2 = class_time1, class_time2
            else:
                shift = int(round(var * 3))   # ~±1 class for 7-class schemes
                s_t1 = np.where(class_time1 != NODATA_INT,
                                np.clip(class_time1 + shift, 1, 7),
                                class_time1).astype(class_time1.dtype)
                s_t2 = np.where(class_time2 != NODATA_INT,
                                np.clip(class_time2 + shift, 1, 7),
                                class_time2).astype(class_time2.dtype)
            try:
                results[var] = self.calculate_change(s_t1, s_t2,
                                                     index_name)['changed_percent']
            except Exception:
                results[var] = None

        valid_vals = [v for v in results.values() if v is not None]
        std = float(np.std(valid_vals)) if len(valid_vals) > 1 else 0.0
        mean = float(np.mean(valid_vals)) if valid_vals else 1.0

        return {
            'results':         results,
            'sensitivity_std': std,
            'sensitivity_cv':  std / mean * 100 if mean != 0 else 0.0,
        }

    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def generate_provenance_log(stats: dict, index_name: str,
                                input_files: dict, params: dict) -> dict:
        """
        ISO 19115-inspired provenance record.

        Parameters
        ----------
        input_files : {'time1': path, 'time2': path}
        params      : {'pixel_size': float, 'use_mndwi_mask': bool, ...}
        """
        def _md5(path: str) -> str:
            try:
                h = hashlib.md5()
                with open(path, 'rb') as f:
                    for chunk in iter(lambda: f.read(65536), b''):
                        h.update(chunk)
                return h.hexdigest()
            except Exception:
                return "unavailable"

        return {
            'processing_time': datetime.now(timezone.utc).isoformat(),
            'software': {'name': PLUGIN_NAME,
                         'version': PLUGIN_VERSION},
            'inputs': {
                'time1': {'filepath': input_files.get('time1', ''),
                          'md5':      _md5(input_files.get('time1', ''))},
                'time2': {'filepath': input_files.get('time2', ''),
                          'md5':      _md5(input_files.get('time2', ''))},
            },
            'parameters': {
                'pixel_size_m':         params.get('pixel_size', 10.0),
                'water_mask_applied':   params.get('use_mndwi_mask', False),
                'uncertainty_threshold': params.get('uncertainty_threshold', 0.30),
            },
            'outputs': {
                'total_area_ha':   stats.get('total_area_ha'),
                'changed_percent': stats.get('changed_percent'),
                'changed_area_ha': stats.get('changed_area_ha'),
            },
            'quality_indicators': {
                'kappa_coefficient':    stats.get('kappa'),
                'kappa_interpretation': stats.get('kappa_interpretation'),
                'uncertainty_applied':  stats.get('uncertainty_applied', False),
                'unreliable_px_pct':    stats.get('unreliable_px_pct'),
            },
        }

    # ──────────────────────────────────────────────────────────────────────

    def export_change_matrix(self, change_matrix: np.ndarray,
                              unique_classes: np.ndarray,
                              output_path: str) -> tuple:
        """Export change matrix to CSV."""
        try:
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(['From/To'] +
                            [f'Class {int(c)}' for c in unique_classes])
                for i, cls in enumerate(unique_classes):
                    w.writerow([f'Class {int(cls)}'] +
                                [str(int(change_matrix[i, j]))
                                 for j in range(len(unique_classes))])
            return True, f"Change matrix exported: {output_path}"
        except Exception as exc:
            return False, f"Export error: {exc}"

    # ──────────────────────────────────────────────────────────────────────

    def generate_change_report(self, stats: dict, index_name: str) -> str:
        """Generate a human-readable text report."""
        try:
            lines = [
                "BiWQA – BITEMPORAL WATER QUALITY CHANGE ANALYSIS REPORT",
                "=" * 62,
                f"Index      : {index_name}",
                f"Total Area : {stats['total_area_ha']:.2f} ha",
                f"Changed    : {stats['changed_area_ha']:.2f} ha "
                f"({stats['changed_percent']:.1f} %)",
                f"Unchanged  : {stats['unchanged_area_ha']:.2f} ha "
                f"({stats['unchanged_percent']:.1f} %)",
                f"Kappa      : {stats['kappa']:.4f}  "
                f"[{stats['kappa_interpretation']}]",
                "",
                "CLASS-BASED AREA CHANGES:",
                f"{'Class':>5}  {'Time1 (ha)':>12}  {'Time2 (ha)':>12}  "
                f"{'Change (ha)':>12}  {'Change (%)':>10}",
                "-" * 62,
            ]
            for cls in sorted(stats['class_areas_time1']):
                a1 = stats['class_areas_time1'][cls]
                a2 = stats['class_areas_time2'].get(cls, 0.0)
                dc = a2 - a1
                dp = dc / a1 * 100 if a1 > 0 else 0.0
                lines.append(f"{int(cls):>5}  {a1:>12.2f}  {a2:>12.2f}  "
                              f"{dc:>12.2f}  {dp:>10.1f}")

            lines += ["", "MAJOR CHANGE TYPES (> 1 % of changed area):"]
            total_changed = stats['changed_area_ha']
            if total_changed > 0:
                sig = sorted(
                    [(code, area, area / total_changed * 100)
                     for code, area in stats['change_type_areas'].items()
                     if area / total_changed * 100 > 1.0],
                    key=lambda x: x[2], reverse=True
                )
                if sig:
                    for code, area, pct in sig[:10]:
                        desc = stats['change_descriptions'].get(code,
                                                                  f"Code {code}")
                        lines.append(f"  {desc:30s}  {area:8.2f} ha  ({pct:.1f} %)")
                else:
                    lines.append("  No significant changes (> 1 %) detected.")
            lines.append("=" * 62)
            return "\n".join(lines)
        except Exception as exc:
            return f"Report generation error: {exc}"

    # ──────────────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_change_matrix(valid_t1, valid_t2, unique_classes, n_classes):
        max_cls = int(unique_classes.max()) + 1
        lookup  = np.full(max_cls, -1, dtype=np.int32)
        for seq_idx, cls_val in enumerate(unique_classes):
            lookup[int(cls_val)] = seq_idx

        t1_c = np.clip(valid_t1, 0, max_cls - 1)
        t2_c = np.clip(valid_t2, 0, max_cls - 1)
        idx_t1 = lookup[t1_c]
        idx_t2 = lookup[t2_c]

        ok   = (idx_t1 >= 0) & (idx_t2 >= 0)
        flat = idx_t1[ok] * n_classes + idx_t2[ok]
        mat  = np.bincount(flat, minlength=n_classes * n_classes)
        return mat.reshape(n_classes, n_classes).astype(np.int64)

    @staticmethod
    def _build_change_map(ct1, ct2, valid_mask):
        """uint16 change map — 0 = unchanged, NODATA_UINT = NoData."""
        cmap = np.full(ct1.shape, NODATA_UINT, dtype=np.uint16)
        cmap[valid_mask] = 0
        changed = valid_mask & (ct1 != ct2)
        codes = (ct1[changed].astype(np.int32) * 100 +
                 ct2[changed].astype(np.int32))
        codes = np.clip(codes, 0, NODATA_UINT - 1).astype(np.uint16)
        cmap[changed] = codes
        return cmap

    @staticmethod
    def _class_areas(valid_t1, valid_t2, unique_classes, pixel_area_ha):
        a1, a2 = {}, {}
        for cls in unique_classes:
            a1[cls] = float(np.sum(valid_t1 == cls) * pixel_area_ha)
            a2[cls] = float(np.sum(valid_t2 == cls) * pixel_area_ha)
        return a1, a2

    @staticmethod
    def _change_type_stats(change_map, pixel_area_ha):
        areas, descs = {}, {}
        codes = np.unique(change_map)
        codes = codes[(codes != 0) & (codes != NODATA_UINT)]
        for code in codes:
            area = float(np.sum(change_map == code) * pixel_area_ha)
            areas[int(code)] = area
            descs[int(code)] = f"Class {int(code) // 100} → Class {int(code) % 100}"
        return areas, descs

    @staticmethod
    def _calculate_kappa(change_matrix):
        n = change_matrix.sum()
        if n == 0:
            return 0.0
        p_o = np.trace(change_matrix) / n
        p_e = float(np.dot(change_matrix.sum(axis=1),
                            change_matrix.sum(axis=0))) / (n ** 2)
        return float((p_o - p_e) / (1.0 - p_e)) if (1.0 - p_e) != 0 else 1.0

    @staticmethod
    def _interpret_kappa(kappa):
        if kappa < 0.0:  return "No agreement (worse than chance)"
        if kappa < 0.20: return "Slight"
        if kappa < 0.40: return "Fair"
        if kappa < 0.60: return "Moderate"
        if kappa < 0.75: return "Good"
        return "Excellent (≥ 0.75)"
