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
    """
    Risco estrutural combinado:
    - 60% WorldCover (uso do solo permanente)
    - 40% NDVI (estado da vegetacao, dinamico)
    Se NDVI nao disponivel, usa 100% WorldCover.
    """
    if RASTER_OK and os.path.exists(RISK_RASTER_PATH):
        try:
            with rasterio.open(RISK_RASTER_PATH) as src:
                # Converter coordenadas WGS84 para row/col do raster
                row, col = src.index(lon, lat)
                if 0 <= row < src.height and 0 <= col < src.width:
                    from rasterio.windows import Window
                    window = Window(col, row, 1, 1)
                    val = float(src.read(1, window=window)[0, 0])
                    if val > -999:
                        wc_risk = float(np.clip(val, 0.0, 1.0))
                    # Fusao com NDVI e declive
                    from ingest.ndvi import get_ndvi_factor
                    from ingest.dem import get_slope_factor
                    ndvi_factor  = get_ndvi_factor(lat, lon)
                    slope_factor = get_slope_factor(lat, lon)
                    if ndvi_factor is not None and slope_factor is not None:
                        return round(0.5 * wc_risk + 0.3 * ndvi_factor + 0.2 * slope_factor, 3)
                    elif ndvi_factor is not None:
                        return round(0.6 * wc_risk + 0.4 * ndvi_factor, 3)
                    return wc_risk
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

async def get_area_ardida_factor(conn, lat, lon):
    """
    Verifica se o ponto esta numa area ardida recente (2020-2025).
    Devolve factor de risco adicional:
    - Area ardida ha menos de 2 anos: +0.25 (vegetacao em regeneracao activa)
    - Area ardida ha 2-4 anos:        +0.15 (matos jovens muito inflamaveis)
    - Area ardida ha 4-6 anos:        +0.05 (recuperacao parcial)
    - Sem historico de fogo:           0.0
    """
    import datetime
    ano_actual = datetime.datetime.now().year
    try:
        row = await conn.fetchrow("""
            SELECT ano, MIN(area_ha) as area_ha
            FROM areas_ardidas
            WHERE ST_DWithin(
                geom::geography,
                ST_SetSRID(ST_MakePoint($1,$2),4326)::geography,
                5000
            )
            GROUP BY ano
            ORDER BY ano DESC
            LIMIT 1
        """, lon, lat)
        if not row:
            return 0.0
        anos_desde = ano_actual - row["ano"]
        if anos_desde <= 2:
            return 0.25
        elif anos_desde <= 4:
            return 0.15
        else:
            return 0.05
    except Exception as e:
        import logging
        logging.getLogger("saeif.score").warning(f"area_ardida_factor ({lat},{lon}): {e}")
        return 0.0


def calcular_score(par, meteo, area_ardida_factor=0.0):
    lat = par.get("lat", 0)
    lon = par.get("lon", 0)
    risco_estrutural = min(1.0, get_structural_risk(lat, lon) + area_ardida_factor)
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
