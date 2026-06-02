"""
Ingest DEM (Copernicus DEM GLO-30) via Sentinel Hub Process API.
Calcula declive normalizado (0.0-1.0) para a Peninsula Iberica.
O declive e estatico — actualizado apenas quando necessario.
"""
import os, logging, numpy as np
from datetime import datetime, timezone

log = logging.getLogger('saeif.dem')

DATA_DIR   = "/data"
DEM_PATH   = os.path.join(DATA_DIR, "dem_iberia.tif")
SLOPE_PATH = os.path.join(DATA_DIR, "slope_norm.tif")

def get_slope_factor(lat, lon):
    if not os.path.exists(SLOPE_PATH):
        return None
    try:
        import rasterio
        from rasterio.windows import Window
        with rasterio.open(SLOPE_PATH) as src:
            row, col = src.index(lon, lat)
            if row < 0 or col < 0 or row >= src.height or col >= src.width:
                return None
            w = Window(max(0, col-1), max(0, row-1), 3, 3)
            data = src.read(1, window=w)
            valid = data[data >= 0]
            if len(valid) == 0:
                return None
            return round(float(valid.mean()), 3)
    except Exception as e:
        log.warning(f"Slope lookup ({lat},{lon}): {e}")
        return None

async def fetch_dem(conn):
    import httpx, rasterio
    started = datetime.now(timezone.utc)
    CDSE_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
    SH_PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"
    BBOX = [-9.5, 36.9, -6.1, 42.2]
    try:
        user = os.getenv("CDSE_USER")
        pwd  = os.getenv("CDSE_PASSWORD")
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(CDSE_TOKEN_URL, data={
                "grant_type": "password", "username": user,
                "password": pwd, "client_id": "cdse-public"
            })
            token = r.json()["access_token"]
        payload = {
            "input": {
                "bounds": {"bbox": BBOX, "properties": {"crs": "http://www.opengis.net/def/crs/EPSG/0/4326"}},
                "data": [{"type": "dem", "dataFilter": {"demInstance": "COPERNICUS_30"}}]
            },
            "output": {"width": 340, "height": 532,
                       "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}]},
            "evalscript": "//VERSION=3\nfunction setup(){return{input:[{bands:[\"DEM\"]}],output:{bands:1,sampleType:\"FLOAT32\"}}}\nfunction evaluatePixel(s){return[s.DEM]}"
        }
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.post(SH_PROCESS_URL, json=payload,
                             headers={"Authorization": f"Bearer {token}"})
            r.raise_for_status()
            with open(DEM_PATH, 'wb') as f:
                f.write(r.content)
        log.info(f"DEM: {len(r.content)//1024}KB guardado")
        with rasterio.open(DEM_PATH) as src:
            data = src.read(1).astype(float)
            res_x = abs(src.transform.a) * 111320
            res_y = abs(src.transform.e) * 111320
            dy, dx = np.gradient(data, res_y, res_x)
            slope_deg = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))
            slope_norm = np.clip(slope_deg / 45.0, 0.0, 1.0).astype('float32')
            profile = src.profile.copy()
            profile.update(dtype='float32', nodata=-9999)
            with rasterio.open(SLOPE_PATH, 'w', **profile) as dst:
                dst.write(slope_norm, 1)
        log.info(f"Slope: max={slope_deg.max():.1f}° medio={slope_deg.mean():.1f}°")
        return True
    except Exception as e:
        log.error(f"DEM fetch erro: {e}")
        return False
