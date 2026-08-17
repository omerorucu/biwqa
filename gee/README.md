# Google Earth Engine companion script

`lake_water_quality_gee.js` produces the raster layers that the BiWQA QGIS
plugin consumes. It is the code published as **Online Resource 2 (ESM_2)** of
the article listed at the bottom of this page.

## What it does

For a lake polygon you draw on the map, the script builds a cloud-masked
seasonal composite from Landsat 5/8/9 or Sentinel-2, applies a water mask
(MNDWI > 0.1, Xu 2006) and computes:

| Output band | Parameter | Reference |
|---|---|---|
| `ChlA_NDCI` | Chlorophyll-a, NDCI polynomial | Mishra & Mishra (2012) |
| `ChlA_2Band` | Chlorophyll-a, 2-band NIR/Red | Gitelson et al. (2008) |
| `ChlA_Moses` | Chlorophyll-a, Red/Green log-ratio | Moses et al. (2012) |
| `ChlA_Final` | Chlorophyll-a, ensemble mean of the three | — |
| `TSI_Carlson` | Carlson Trophic State Index | Carlson (1977) |
| `Trophic_Level` | Trophic class 1–4 (oligo → hypereutrophic) | Carlson (1977) |
| `Secchi_m` | Secchi disk depth (m) | Kutser et al. (2005) |
| `TSS_mg_L` | Total suspended solids (mg/L) | Nechad et al. (2010) |
| `Turbidity_NTU` | Turbidity (NTU, linear approximation) | Dogliotti et al. (2015) |
| `NDCI` | Normalised Difference Chlorophyll Index | Mishra & Mishra (2012) |
| `NDVI` | Normalised Difference Vegetation Index | Rouse et al. (1974) |
| `FAI` | Floating Algae Index (simplified) | Hu (2009) |
| `MNDWI` | Modified Normalised Difference Water Index | Xu (2006) |

All 13 bands are exported as separate Cloud-Optimised GeoTIFFs, plus a CSV
with mean / SD / min / max / median statistics for the polygon.

## How to run

1. Open the [GEE Code Editor](https://code.earthengine.google.com) and paste
   the contents of `lake_water_quality_gee.js`.
2. Draw a polygon over the lake with the drawing tools — the Code Editor
   creates the `geometry` import the script expects.
3. In the side panel: pick the satellite, the year range and the season, then
   click **RUN ANALYSIS**.
4. Click **EXPORT SEPARATE GeoTIFFs (13 Files)** and start the tasks from the
   **Tasks** panel. Files land in the Drive folder `Lake_Water_Quality`.
5. Repeat for the second period (e.g. summer 2020 and summer 2025).
6. Load the two sets of GeoTIFFs into BiWQA as **Time 1** and **Time 2** and
   run the bitemporal change analysis.

Export resolution is 10 m for Sentinel-2 and 30 m for Landsat — use the same
value in the plugin's *pixel size* field so the area statistics are correct.

## Known limitations

- On Landsat sensors NDCI reduces to NDVI, because there is no red-edge band.
  For a true NDCI use Sentinel-2 and substitute B5 (705 nm) for NIR.
- FAI is a simplified proxy, not the standard wavelength-weighted formulation.
- Turbidity is a linear approximation of the Dogliotti et al. (2015) model.
- Retrievals are not calibrated against in-situ measurements. Validate against
  field data before operational use.

## Citation

> Örücü, Ö. K., & Örücü, S. (2026). Landscape-based assessment of trophic
> shift: integrating remote sensing for sustainable management of Lake
> Beyşehir. *International Journal of Environmental Science and Technology*,
> 23, 554. https://doi.org/10.1007/s13762-026-07323-w
