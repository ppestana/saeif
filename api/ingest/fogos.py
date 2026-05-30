import logging
from datetime import datetime, timezone
import httpx

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
            if not isinstance(inc, dict):
                continue
            try:
                external_id = str(inc.get("id") or (inc.get("_id") or {}).get("$id") or "")
                if not external_id:
                    continue
                try:
                    lat = float(inc.get("lat") or 0)
                    lon = float(inc.get("lng") or 0)
                except (TypeError, ValueError):
                    lat = lon = 0
                localidade = str(inc.get("location") or inc.get("freguesia") or "")
                distrito   = str(inc.get("district") or "")
                concelho   = str(inc.get("concelho") or "")
                estado     = str(inc.get("natureza") or inc.get("status") or "")
                data_hora  = None
                sec = (inc.get("dateTime") or {}).get("sec")
                if sec:
                    try:
                        data_hora = datetime.fromtimestamp(int(sec), tz=timezone.utc)
                    except Exception:
                        pass
                exists = await conn.fetchval(
                    "SELECT id FROM ocorrencias_prociv WHERE external_id = $1::varchar",
                    external_id
                )
                if exists:
                    continue
                if lat and lon:
                    result = await conn.fetchval("""
                        INSERT INTO ocorrencias_prociv
                            (external_id, geom, localidade, distrito, concelho, estado, data_hora, source_tag)
                        VALUES ($1::varchar, ST_SetSRID(ST_MakePoint($2, $3), 4326),
                                $4::varchar, $5::varchar, $6::varchar, $7::varchar, $8, 'SYS')
                        RETURNING id
                    """, external_id, lon, lat, localidade, distrito, concelho, estado, data_hora)
                else:
                    result = await conn.fetchval("""
                        INSERT INTO ocorrencias_prociv
                            (external_id, localidade, distrito, concelho, estado, data_hora, source_tag)
                        VALUES ($1::varchar, $2::varchar, $3::varchar, $4::varchar, $5::varchar, $6, 'SYS')
                        RETURNING id
                    """, external_id, localidade, distrito, concelho, estado, data_hora)
                if result:
                    new_count += 1
            except Exception as e:
                log.warning(f"Erro PROCIV inc: {e}")
        await _log(conn, started, "ok", len(incidents), new_count)
        log.info(f"fogos.pt: {new_count} novas de {len(incidents)} ocorrencias")
        return new_count
    except Exception as e:
        log.error(f"Erro fogos.pt: {e}")
        await _log(conn, started, "error", 0, 0, str(e))
        return 0

async def _log(conn, started, status, fetched, new, error=None):
    try:
        await conn.execute("""
            INSERT INTO ingest_log
                (source, started_at, ended_at, status, records_fetched, records_new, error_msg)
            VALUES ('PROCIV', $1, $2, $3, $4, $5, $6)
        """, started, datetime.now(timezone.utc), status, fetched, new, error)
    except Exception as e:
        log.warning(f"Erro ingest_log: {e}")
