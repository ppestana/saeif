import logging
from datetime import datetime, timezone
import httpx
import asyncpg

log = logging.getLogger("saeif.ipma")
IPMA_OBS_URL     = "https://api.ipma.pt/open-data/observation/meteorology/stations/observations.json"
IPMA_STATION_URL = "https://api.ipma.pt/open-data/observation/meteorology/stations/stations.json"

_stations_cache = {}

async def _load_stations():
    global _stations_cache
    if _stations_cache:
        return _stations_cache
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(IPMA_STATION_URL)
            resp.raise_for_status()
            stations = resp.json()
        _stations_cache = {
            str(s.get("idEstacao") or s.get("properties", {}).get("idEstacao", "")): {
                "lat": float(s.get("latitude") or s.get("geometry", {}).get("coordinates", [0,0])[1] or 0),
                "lon": float(s.get("longitude") or s.get("geometry", {}).get("coordinates", [0,0])[0] or 0),
                "name": s.get("localEstacao") or "",
            }
            for s in stations
        }
        log.info(f"IPMA: {len(_stations_cache)} estacoes carregadas.")
    except Exception as e:
        log.error(f"Erro estacoes IPMA: {e}")
    return _stations_cache

async def fetch_ipma_conditions(conn):
    stations = await _load_stations()
    meteo_data = []
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(IPMA_OBS_URL)
            resp.raise_for_status()
            obs_raw = resp.json()
        if not obs_raw:
            return []
        latest_ts = sorted(obs_raw.keys())[-1]
        obs = obs_raw[latest_ts]
        valido_em = datetime.now(timezone.utc)
        for station_id, data in obs.items():
            if data is None:
                continue
            station = stations.get(str(station_id), {})
            lat = station.get("lat", 0)
            lon = station.get("lon", 0)
            if not lat or not lon:
                continue
            temp      = _f(data.get("temperatura") or data.get("temp"))
            humidade  = _f(data.get("humidade") or data.get("humRelativa"))
            vento_vel = _f(data.get("intensidadeVento") or data.get("vento_int"))
            vento_dir = _f(data.get("direcaoVento") or data.get("vento_dir"))
            precip    = _f(data.get("precAcum") or data.get("precipitacao"))
            fwi       = _estimate_fwi(temp, humidade, vento_vel)
            meteo_data.append({
                "station_id": str(station_id),
                "lat": lat, "lon": lon,
                "temp": temp, "humidade": humidade,
                "vento_vel": vento_vel, "vento_dir": vento_dir,
                "precipitacao": precip, "fwi": fwi,
                "valido_em": valido_em,
            })
            try:
                await conn.execute("""
                    INSERT INTO meteo_log
                        (geom, station_id, temp, humidade, vento_vel, vento_dir, precipitacao, fwi, valido_em)
                    VALUES (ST_SetSRID(ST_MakePoint($1, $2), 4326), $3, $4, $5, $6, $7, $8, $9, $10)
                """, lon, lat, str(station_id), temp, humidade, vento_vel, vento_dir, precip, fwi, valido_em)
            except Exception as e:
                log.warning(f"Erro meteo estacao {station_id}: {e}")
        log.info(f"IPMA: {len(meteo_data)} estacoes processadas.")
        return meteo_data
    except Exception as e:
        log.error(f"Erro IPMA: {e}")
        return []

def get_nearest_meteo(lat, lon, meteo_data):
    if not meteo_data:
        return {}
    return min(meteo_data, key=lambda m: (m["lat"]-lat)**2 + (m["lon"]-lon)**2)

def _estimate_fwi(temp, humidade, vento_vel):
    if temp is None or humidade is None:
        return None
    mc = max(0, (100 - humidade) / 2)
    tc = max(0, (temp - 10) / 1.5) if temp and temp > 10 else 0
    wc = min(20, (vento_vel or 0) / 3)
    return round(min(100, mc + tc + wc), 1)

def _f(val):
    try:
        v = float(val)
        return v if v > -999 else None
    except (TypeError, ValueError):
        return None
