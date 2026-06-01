"""
Ingest EFFIS Fire Danger Forecast via WMS.
Descarrega 3 rasters para a Península Ibérica:
  - mf010.fwi      → Fire Weather Index
  - mf010.ranking  → Percentil histórico 40 anos (0-100)
  - mf010.anomaly  → Desvio padrão face à média histórica

Resolução: ~2.5km (560x320 px para bbox ibérica)
Fonte: https://maps.effis.emergency.copernicus.eu/effis
Frequência: a cada 6 horas (agendado no main.py)
"""
import os, logging, asyncio
from datetime import datetime, timezone, date
import httpx

log = logging.getLogger('saeif.effis')

EFFIS_WMS  = "https://maps.effis.emergency.copernicus.eu/effis"
BBOX       = "-9.5,35.9,4.5,44.0"   # Península Ibérica
WIDTH, HEIGHT = 560, 320
DATA_DIR   = "/data"

LAYERS = {
    "fwi":     "mf010.fwi",
    "ranking": "mf010.ranking",
    "anomaly": "mf010.anomaly",
}

def _raster_path(layer_key):
    return os.path.join(DATA_DIR, f"effis_{layer_key}.tif")

def _raster_date_path(layer_key, dt):
    """Caminho com data — para backup histórico se necessário."""
    return os.path.join(DATA_DIR, f"effis_{layer_key}_{dt}.tif")

async def fetch_effis(conn):
    """Descarrega os 3 rasters EFFIS e actualiza /data/effis_*.tif."""
    started = datetime.now(timezone.utc)
    today   = date.today().isoformat()
    ok_count = 0

    async with httpx.AsyncClient(timeout=60) as client:
        for key, layer in LAYERS.items():
            url = (
                f"{EFFIS_WMS}?LAYERS={layer}&FORMAT=image/tiff"
                f"&TRANSPARENT=true&SERVICE=WMS&VERSION=1.1.1"
                f"&REQUEST=GetMap&STYLES=&SRS=EPSG:4326"
                f"&BBOX={BBOX}&WIDTH={WIDTH}&HEIGHT={HEIGHT}"
                f"&TIME={today}"
            )
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                # Verificar que é mesmo um TIFF (começa com II ou MM)
                if resp.content[:2] not in (b'II', b'MM'):
                    log.warning(f"EFFIS {key}: resposta nao e TIFF — {resp.content[:100]}")
                    continue
                path = _raster_path(key)
                with open(path, 'wb') as f:
                    f.write(resp.content)
                size_kb = len(resp.content) // 1024
                log.info(f"EFFIS {key}: {size_kb}KB guardado em {path}")
                ok_count += 1
            except Exception as e:
                log.error(f"EFFIS {key}: erro — {e}")

    await _log_ingest(conn, started, ok_count)
    return ok_count

def get_effis_values(lat, lon):
    """
    Lê FWI, ranking e anomalia EFFIS para um ponto (lat, lon).
    Retorna dict ou None se os rasters nao estiverem disponiveis.
    """
    try:
        import rasterio
        from rasterio.windows import Window
        result = {}
        for key in LAYERS:
            path = _raster_path(key)
            if not os.path.exists(path):
                return None
            with rasterio.open(path) as src:
                row, col = src.index(lon, lat)
                if row < 0 or col < 0 or row >= src.height or col >= src.width:
                    return None
                w = Window(max(0, col-1), max(0, row-1), 3, 3)
                data = src.read(1, window=w)
                val = float(data[min(1, data.shape[0]-1), min(1, data.shape[1]-1)])
                result[key] = round(val, 1) if val > -9999 else None
        return result
    except Exception as e:
        log.warning(f"EFFIS lookup ({lat},{lon}): {e}")
        return None

async def _log_ingest(conn, started, ok_count):
    try:
        await conn.execute("""
            INSERT INTO ingest_log (source, started_at, ended_at, status, records_fetched, records_new)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, "EFFIS", started, datetime.now(timezone.utc),
            "ok" if ok_count == 3 else "partial", ok_count, ok_count)
    except Exception as e:
        log.warning(f"EFFIS ingest_log: {e}")
