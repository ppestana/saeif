import logging
from datetime import datetime, timezone
import httpx
import asyncpg

log = logging.getLogger("saeif.fogos")
FOGOS_URL = "https://api.fogos.pt/v2/incidents/active"

async def fetch_fogos(conn):
    started = datetime.now(timezone.utc)
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(FOGOS_URL, headers={"Accept": "application/json"})
            resp.raise_for_status()
            data = resp.json()
        incidents = data.get("data", []) if isinstance(data, dict) else data
        if not incidents:
            await _log(conn, started, "ok", 0, 0)
            return 0
        new_count = 0
        for inc in incidents:
            try:
                external_id = str(inc.get("id") or inc.get("code") or "")
                if not external_id:
                    continue
                lat = float(inc.get("lat") or inc.get("latitude") or
                            (inc.get("location") or {}).get("lat") or 0)
                lon = float(inc.get("lng") or inc.get("longitude") or
                            (inc.get("location") or {}).get("lng") or 0)
                localidade = (inc.get("location") or {}).get("name") or inc.get("local") or ""
                distrito   = inc.get("district") or inc.get("distrito") or ""
                concelho   = inc.get("county") or inc.get("concelho") or ""
                estado     = inc.get("status") or inc.get("estado") or ""
                data_hora  = None
                dh_str = inc.get("date") or inc.get("data") or ""
                if dh_str:
                    try:
                        data_hora = datetime.fromisoformat(dh_str.replace("Z", "+00:00"))
                    except Exception:
                        pass
                if lat and lon:
                    result = await conn.fetchval("""
                        INSERT INTO ocorrencias_prociv
                            (external_id, geom, localidade, distrito, concelho, estado, data_hora, source_tag)
                        SELECT $1, ST_SetSRID(ST_MakePoint($7, $8), 4326), $2, $3, $4, $5, $6, 'SYS'
                        WHERE NOT EXISTS (
                            SELECT 1 FROM ocorrencias_prociv WHERE external_id = $1
                        )
                        RETURNING id
                    """, external_id, localidade, distrito, concelho, estado, data_hora, lon, lat)
                else:
                    result = await conn.fetchval("""
                        INSERT INTO ocorrencias_prociv
                            (external_id, localidade, distrito, concelho, estado, data_hora, source_tag)
                        SELECT $1, $2, $3, $4, $5, $6, 'SYS'
                        WHERE NOT EXISTS (
                            SELECT 1 FROM ocorrencias_prociv WHERE external_id = $1
                        )
                        RETURNING id
                    """, external_id, localidade, distrito, concelho, estado, data_hora)
                if result:
                    new_count += 1
            except Exception as e:
                log.warning(f"Erro PROCIV: {e}")
        await _log(conn, started, "ok", len(incidents), new_count)
        return new_count
    except Exception as e:
        log.error(f"Erro fogos.pt: {e}")
        await _log(conn, started, "error", 0, 0, str(e))
        return 0

async def _log(conn, started, status, fetched, new, error=None):
    try:
        await conn.execute("""
            INSERT INTO ingest_log (source, started_at, ended_at, status, records_fetched, records_new, error_msg)
            VALUES ('PROCIV', $1, $2, $3, $4, $5, $6)
        """, started, datetime.now(timezone.utc), status, fetched, new, error)
    except Exception as e:
        log.warning(f"Erro ingest_log: {e}")
