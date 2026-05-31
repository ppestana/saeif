import os
import logging
from datetime import date, datetime, timezone
import httpx
import asyncpg

log = logging.getLogger("saeif.firms")
FIRMS_KEY = os.getenv("FIRMS_MAP_KEY", "")
FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
BBOX      = "-9.50,36.96,-6.19,42.15"
PRODUCT   = "VIIRS_SNPP_NRT"
DAYS      = 1

DEMO_HOTSPOTS = [
    {"lat": 39.60, "lon": -8.20, "brightness": 340.5, "frp": 12.3, "confidence": "nominal", "acq_time": "1300"},
    {"lat": 37.95, "lon": -8.10, "brightness": 355.2, "frp": 28.7, "confidence": "high",    "acq_time": "1312"},
    {"lat": 40.20, "lon": -7.80, "brightness": 320.1, "frp":  8.1, "confidence": "low",     "acq_time": "1318"},
    {"lat": 38.50, "lon": -8.50, "brightness": 362.8, "frp": 45.2, "confidence": "high",    "acq_time": "1324"},
    {"lat": 41.30, "lon": -7.40, "brightness": 331.0, "frp": 15.9, "confidence": "nominal", "acq_time": "1330"},
    {"lat": 39.10, "lon": -7.60, "brightness": 348.3, "frp": 21.4, "confidence": "nominal", "acq_time": "1336"},
]

async def fetch_firms(conn):
    started = datetime.now(timezone.utc)
    if not FIRMS_KEY or FIRMS_KEY in ("PLACEHOLDER", "your_firms_map_key_here"):
        log.warning("FIRMS_MAP_KEY nao configurada -- a usar focos de demonstracao.")
        return await _insert_demo(conn, started)
    url = f"{FIRMS_URL}/{FIRMS_KEY}/{PRODUCT}/{BBOX}/{DAYS}/"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            lines = resp.text.strip().splitlines()
        if len(lines) < 2:
            await _log_ingest(conn, "FIRMS", started, "ok", 0, 0)
            return 0
        header = [h.strip() for h in lines[0].split(",")]
        records = [dict(zip(header, l.split(","))) for l in lines[1:]]
        new_count = await _insert_hotspots(conn, records, "VIIRS")
        await _log_ingest(conn, "FIRMS", started, "ok", len(records), new_count)
        return new_count
    except Exception as e:
        log.error(f"Erro FIRMS: {e}")
        await _log_ingest(conn, "FIRMS", started, "error", 0, 0, str(e))
        return 0

async def _insert_hotspots(conn, records, source):
    new_count = 0
    today = str(date.today())
    for r in records:
        try:
            lat        = float(r.get("latitude", 0))
            lon        = float(r.get("longitude", 0))
            brightness = float(r.get("bright_ti4") or r.get("brightness") or 0) or None
            frp        = float(r.get("frp") or 0) or None
            confidence = str(r.get("confidence", "")).lower() or None
            acq_date   = date.fromisoformat(r.get("acq_date", today))
            t          = r.get("acq_time", "0000").zfill(4)
            from datetime import time as dtime; acq_time = dtime(int(t[:2]), int(t[2:4]))
            result = await conn.fetchval("""
                INSERT INTO hotspots (source, geom, brightness, frp, confidence, acq_date, acq_time)
                SELECT $1, ST_SetSRID(ST_MakePoint($2, $3), 4326), $4, $5, $6, $7, $8::time
                WHERE NOT EXISTS (
                    SELECT 1 FROM hotspots
                    WHERE source = $1::varchar AND acq_date = $7 AND acq_time = $8::time
                      AND ST_DWithin(geom::geography,
                                     ST_SetSRID(ST_MakePoint($2, $3), 4326)::geography, 500)
                )
                RETURNING id
            """, str(source), lon, lat, brightness, frp, confidence, acq_date, acq_time)
            if result:
                new_count += 1
        except Exception as e:
            log.warning(f"Erro a inserir hotspot: {e}")
    return new_count

async def _insert_demo(conn, started):
    today = str(date.today())
    fake = [{"latitude": str(h["lat"]), "longitude": str(h["lon"]),
             "bright_ti4": str(h["brightness"]), "frp": str(h["frp"]),
             "confidence": h["confidence"], "acq_date": today,
             "acq_time": h["acq_time"]} for h in DEMO_HOTSPOTS]
    new_count = await _insert_hotspots(conn, fake, "VIIRS_DEMO")
    await _log_ingest(conn, "FIRMS_DEMO", started, "ok", len(fake), new_count)
    return new_count

async def _log_ingest(conn, source, started, status, fetched, new, error=None):
    try:
        await conn.execute("""
            INSERT INTO ingest_log (source, started_at, ended_at, status, records_fetched, records_new, error_msg)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
        """, source, started, datetime.now(timezone.utc), status, fetched, new, error)
    except Exception as e:
        log.warning(f"Erro ingest_log: {e}")
