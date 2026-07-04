import logging
import asyncpg

log = logging.getLogger("saeif.dedup")
PROXIMITY_M = 5000  # Frente B (4 Jul 2026): 40km->5km. Raio de 40km gerava 71% de
                    # emparelhamentos falsos (pares a dezenas de km). 5km e' defensavel
                    # para fogos portugueses. Bug de escolha (PROCIV<2km nao escolhido)
                    # fica para correcao separada (Correcao B).

async def dedup_hotspots(conn):
    pares = []
    hotspots = await conn.fetch("""
        SELECT id, ST_X(geom) AS lon, ST_Y(geom) AS lat,
               brightness, frp, confidence, acq_date, source
        FROM hotspots
        WHERE processed = FALSE
        ORDER BY fetched_at DESC
    """)
    if not hotspots:
        return []
    for h in hotspots:
        prociv = await conn.fetchrow("""
            SELECT id, localidade, distrito,
                   ST_Distance(geom::geography,
                               ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography) AS dist_m
            FROM ocorrencias_prociv
            WHERE geom IS NOT NULL
              AND fetched_at > NOW() - INTERVAL '24 hours'
              AND ST_DWithin(geom::geography,
                             ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography, $3)
            ORDER BY dist_m ASC LIMIT 1
        """, h["lon"], h["lat"], PROXIMITY_M)
        pares.append({
            "hotspot_id": h["id"],
            "prociv_id": prociv["id"] if prociv else None,
            "lat": h["lat"], "lon": h["lon"],
            "frp": float(h["frp"]) if h["frp"] else None,
            "confidence": h["confidence"],
            "source": h["source"],
            "prociv_confirmado": prociv is not None,
            "prociv_localidade": prociv["localidade"] if prociv else None,
            "prociv_distrito": prociv["distrito"] if prociv else None,
            "dist_prociv_m": float(prociv["dist_m"]) if prociv else None,
        })
        # NOTA: processed=TRUE passou para gerar_alertas (apos sucesso).
        # Marcar aqui causava perda permanente de hotspots se o INSERT falhasse.
    log.info(f"Dedup: {len(pares)} hotspots, {sum(1 for p in pares if p['prociv_confirmado'])} confirmados PROCIV")
    return pares
