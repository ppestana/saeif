import logging
import os

log = logging.getLogger("saeif.score")
RISK_RASTER_PATH = os.getenv("RISK_RASTER_PATH", "/data/fire_risk.tif")

try:
    import rasterio
    import numpy as np
    from pyproj import Transformer
    RASTER_OK = True
except ImportError:
    RASTER_OK = False
    log.warning("rasterio nao disponivel -- usando estimativa por zona.")

_transformer = None

def _get_transformer():
    global _transformer
    if _transformer is None and RASTER_OK:
        _transformer = Transformer.from_crs("EPSG:4326", "EPSG:3763", always_xy=True)
    return _transformer

def get_structural_risk(lat, lon):
    if RASTER_OK and os.path.exists(RISK_RASTER_PATH):
        try:
            t = _get_transformer()
            x, y = t.transform(lon, lat)
            with rasterio.open(RISK_RASTER_PATH) as src:
                row, col = rasterio.transform.rowcol(src.transform, x, y)
                data = src.read(1)
                if 0 <= row < data.shape[0] and 0 <= col < data.shape[1]:
                    val = float(data[row, col])
                    if val > -999:
                        return float(np.clip(val, 0.0, 1.0))
        except Exception as e:
            log.warning(f"Erro lookup raster ({lat},{lon}): {e}")
    return _estimate_by_zone(lat, lon)

def _estimate_by_zone(lat, lon):
    if lat > 40.5 and lon > -8.0:
        return 0.80
    if lat < 38.5 and lon > -8.0:
        return 0.65
    if lon < -8.5:
        return 0.45
    return 0.60

def calcular_score(par, meteo):
    lat = par.get("lat", 0)
    lon = par.get("lon", 0)
    risco_estrutural = get_structural_risk(lat, lon)
    fwi = meteo.get("fwi") or 0
    fwi_norm = min(1.0, fwi / 80.0)
    vento_vel = meteo.get("vento_vel") or 0
    if vento_vel >= 50:   vento_factor = 1.0
    elif vento_vel >= 30: vento_factor = 0.7
    elif vento_vel >= 15: vento_factor = 0.4
    elif vento_vel >= 5:  vento_factor = 0.2
    else:                 vento_factor = 0.1
    prociv_factor = 1.0 if par.get("prociv_confirmado") else 0.0
    score = (0.35 * risco_estrutural + 0.30 * fwi_norm +
             0.20 * vento_factor + 0.15 * prociv_factor) * 100
    confidence = (par.get("confidence") or "").lower()
    frp = par.get("frp") or 0
    if confidence == "low":    score *= 0.70
    elif confidence == "high": score *= 1.05
    if frp > 100:   score = min(100, score * 1.20)
    elif frp > 50:  score = min(100, score * 1.10)
    score = round(min(100.0, max(0.0, score)), 2)
    if score >= 76:   categoria = "CRITICO"
    elif score >= 51: categoria = "ALTO"
    elif score >= 26: categoria = "MEDIO"
    else:             categoria = "BAIXO"
    return score, categoria
