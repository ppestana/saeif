"""
Ingest NDVI via Sentinel Hub Process API (Copernicus Data Space Ecosystem).
Calcula NDVI = (B08 - B04) / (B08 + B04) para a Península Ibérica.
Resolução: ~2km (340x532 px para bbox ibérica)
Frequência: a cada 10 dias (agendado no main.py)
"""
import os, logging, asyncio
from datetime import datetime, timezone, timedelta, date
import httpx

log = logging.getLogger('saeif.ndvi')

CDSE_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
SH_PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"

BBOX      = [-9.5, 36.9, -6.1, 42.2]   # Península Ibérica
WIDTH     = 340
HEIGHT    = 532
DATA_DIR  = "/data"
NDVI_PATH = os.path.join(DATA_DIR, "ndvi_latest.tif")

EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{bands: ["B04", "B08", "SCL"]}],
    output: {bands: 1, sampleType: "FLOAT32"}
  }
}
function evaluatePixel(s) {
  // Mascarar nuvens (SCL: 8=nuvem media, 9=nuvem alta, 10=cirrus)
  if ([8,9,10].includes(s.SCL)) return [-9999];
  var ndvi = (s.B08 - s.B04) / (s.B08 + s.B04 + 0.0001);
  return [ndvi];
}
"""

async def _get_token():
    """Obter token OAuth2 do Copernicus Data Space."""
    user = os.getenv("CDSE_USER")
    pwd  = os.getenv("CDSE_PASSWORD")
    if not user or not pwd:
        raise ValueError("CDSE_USER e CDSE_PASSWORD nao definidos no .env")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(CDSE_TOKEN_URL, data={
            "grant_type": "password",
            "username": user,
            "password": pwd,
            "client_id": "cdse-public"
        })
        r.raise_for_status()
        return r.json()["access_token"]

async def fetch_ndvi(conn):
    """Descarrega raster NDVI via Sentinel Hub e guarda em /data/ndvi_latest.tif."""
    started = datetime.now(timezone.utc)
    try:
        token = await _get_token()
        log.info("Token Copernicus obtido")

        # Janela temporal: ultimos 20 dias (para garantir imagem sem nuvens)
        date_to   = date.today().isoformat() + "T23:59:59Z"
        date_from = (date.today() - timedelta(days=20)).isoformat() + "T00:00:00Z"

        payload = {
            "input": {
                "bounds": {
                    "bbox": BBOX,
                    "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}
                },
                "data": [{
                    "type": "sentinel-2-l2a",
                    "dataFilter": {
                        "maxCloudCoverage": 30,
                        "timeRange": {"from": date_from, "to": date_to}
                    },
                    "processing": {"mosaickingOrder": "leastCC"}
                }]
            },
            "output": {
                "width": WIDTH,
                "height": HEIGHT,
                "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}]
            },
            "evalscript": EVALSCRIPT
        }

        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(SH_PROCESS_URL,
                json=payload,
                headers={"Authorization": f"Bearer {token}"}
            )
            r.raise_for_status()

            if r.content[:2] not in (b'II', b'MM'):
                log.error(f"NDVI: resposta nao e TIFF — {r.content[:100]}")
                return False

            with open(NDVI_PATH, 'wb') as f:
                f.write(r.content)

        size_kb = len(r.content) // 1024
        log.info(f"NDVI: {size_kb}KB guardado em {NDVI_PATH}")
        await _log_ingest(conn, started, True)
        return True

    except Exception as e:
        log.error(f"NDVI fetch erro: {e}")
        await _log_ingest(conn, started, False)
        return False

def get_ndvi_factor(lat, lon):
    """
    Lê o NDVI para um ponto e devolve factor de risco normalizado (0.0-1.0).
    NDVI alto (vegetacao verde) = risco baixo agora mas alto em seca.
    NDVI baixo (vegetacao seca) = risco alto.
    Retorna None se raster nao disponivel.
    """
    if not os.path.exists(NDVI_PATH):
        return None
    try:
        import rasterio
        from rasterio.windows import Window
        with rasterio.open(NDVI_PATH) as src:
            row, col = src.index(lon, lat)
            if row < 0 or col < 0 or row >= src.height or col >= src.width:
                return None
            w = Window(max(0, col-1), max(0, row-1), 3, 3)
            data = src.read(1, window=w)
            valid = data[(data > -1) & (data < 1)]
            if len(valid) == 0:
                return None
            ndvi = float(valid.mean())
            # Normalizar: NDVI baixo (<0.2) = risco alto; NDVI alto (>0.6) = risco baixo
            # Factor de risco = 1 - ((ndvi - 0.2) / 0.4) clamped 0-1
            factor = 1.0 - max(0.0, min(1.0, (ndvi - 0.2) / 0.4))
            return round(factor, 3)
    except Exception as e:
        log.warning(f"NDVI lookup ({lat},{lon}): {e}")
        return None

async def _log_ingest(conn, started, ok):
    try:
        await conn.execute("""
            INSERT INTO ingest_log (source, started_at, ended_at, status, records_fetched, records_new)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, "NDVI", started, datetime.now(timezone.utc),
            "ok" if ok else "error", 1 if ok else 0, 1 if ok else 0)
    except Exception as e:
        log.warning(f"NDVI ingest_log: {e}")
