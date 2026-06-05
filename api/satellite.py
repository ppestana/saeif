"""
Calculo de proximas passagens dos satelites VIIRS sobre Portugal Continental.
Usa skyfield + TLE da Celestrak (actualizados automaticamente).
Centro de Portugal Continental: 39.6°N, 8.0°W
"""
import os, logging, asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
import httpx

log = logging.getLogger('saeif.satellite')

# Centro de Portugal Continental
PT_LAT = 39.6
PT_LON = -8.0
PT_ELEVATION = 200  # metros (aproximado)

# Bbox Portugal Continental para calcular entrada/saida
PT_BBOX = (36.8, -9.5, 42.2, -6.1)  # lat_min, lon_min, lat_max, lon_max

TLE_DIR = "/data/tle"
TLE_SOURCES = {
    "NOAA-20":   "https://celestrak.org/SOCRATES/query.php?NAME=NOAA-20&TYPE=NAME&FORMAT=TLE",
    "Suomi-NPP": "https://celestrak.org/SOCRATES/query.php?NAME=SUOMI-NPP&TYPE=NAME&FORMAT=TLE",
    "NOAA-21":   "https://celestrak.org/SOCRATES/query.php?NAME=NOAA-21&TYPE=NAME&FORMAT=TLE",
}
# URL alternativo mais fiavel
TLE_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR={norad}&FORMAT=TLE"
NORAD_IDS = {
    "Suomi-NPP": "37849",
    "NOAA-20":   "43013",
    "NOAA-21":   "54234",
}

_tle_cache = {}
_passes_cache = {}
_passes_updated = None

async def fetch_tle():
    """Descarrega TLE dos 3 satelites VIIRS da Celestrak."""
    os.makedirs(TLE_DIR, exist_ok=True)
    results = {}
    async with httpx.AsyncClient(timeout=30) as c:
        for name, norad in NORAD_IDS.items():
            url = f"https://celestrak.org/NORAD/elements/gp.php?CATNR={norad}&FORMAT=TLE"
            try:
                r = await c.get(url)
                if r.status_code == 200 and r.text.strip():
                    lines = [l.strip() for l in r.text.strip().splitlines() if l.strip()]
                    if len(lines) >= 2:
                        tle_path = Path(TLE_DIR) / f"{name.replace(' ','-')}.tle"
                        tle_path.write_text('\n'.join(lines[-2:]))
                        results[name] = lines[-2:]
                        log.info(f"TLE {name}: actualizado")
            except Exception as e:
                log.warning(f"TLE {name}: {e}")
                # Tentar ler do cache em disco
                tle_path = Path(TLE_DIR) / f"{name.replace(' ','-')}.tle"
                if tle_path.exists():
                    lines = tle_path.read_text().strip().splitlines()
                    if len(lines) >= 2:
                        results[name] = lines[-2:]
    return results

def compute_next_passes(tle_data: dict, hours_ahead: int = 24) -> list:
    """
    Calcula proximas passagens sobre o centro de Portugal.
    Devolve lista de dicts ordenada por tempo.
    """
    from skyfield.api import EarthSatellite, load, wgs84
    from skyfield.api import N, W

    ts = load.timescale()
    portugal = wgs84.latlon(PT_LAT * N, abs(PT_LON) * W, elevation_m=PT_ELEVATION)

    now = datetime.now(timezone.utc)
    t0 = ts.from_datetime(now)
    t1 = ts.from_datetime(now + timedelta(hours=hours_ahead))

    passes = []
    for name, tle_lines in tle_data.items():
        try:
            sat = EarthSatellite(tle_lines[0], tle_lines[1], name, ts)
            times, events = sat.find_events(portugal, t0, t1, altitude_degrees=0.0)
            for ti, ev in zip(times, events):
                if ev == 1:  # culmination — ponto mais alto sobre Portugal
                    dt = ti.utc_datetime()
                    diff = sat - portugal
                    alt, az, dist = diff.at(ti).altaz()
                    passes.append({
                        "satellite": name,
                        "datetime_utc": dt.isoformat(),
                        "timestamp": dt.timestamp(),
                        "elevation_deg": round(alt.degrees, 1),
                        "azimuth_deg": round(az.degrees, 1),
                    })
        except Exception as e:
            log.warning(f"compute_passes {name}: {e}")

    passes.sort(key=lambda x: x["timestamp"])
    return passes

async def get_next_passes(force_refresh: bool = False) -> list:
    """
    Devolve lista de proximas passagens (cache de 6 horas).
    """
    global _tle_cache, _passes_cache, _passes_updated

    now = datetime.now(timezone.utc)
    cache_stale = (_passes_updated is None or
                   (now - _passes_updated).total_seconds() > 6 * 3600)

    if cache_stale or force_refresh:
        _tle_cache = await fetch_tle()
        if _tle_cache:
            _passes_cache = compute_next_passes(_tle_cache, hours_ahead=48)
            _passes_updated = now
            log.info(f"Passagens calculadas: {len(_passes_cache)} nas proximas 48h")

    # Filtrar passagens ja passadas
    now_ts = now.timestamp()
    future = [p for p in _passes_cache if p["timestamp"] > now_ts]
    return future
