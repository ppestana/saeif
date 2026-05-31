import logging
import asyncpg
from ingest.ipma import get_nearest_meteo
from analysis.score import calcular_score, get_structural_risk

log = logging.getLogger("saeif.alerts")

async def gerar_alertas(conn, pares, meteo_data):
    alertas_gerados = []
    for par in pares:
        hotspot_id = par.get("hotspot_id")
        lat = par.get("lat")
        lon = par.get("lon")
        existing = await conn.fetchval(
            "SELECT id FROM alertas WHERE hotspot_id = $1", hotspot_id
        )
        if existing:
            continue
        # Deduplicacao entre satélites: nao gerar alerta se ja existe um
        # para o mesmo foco (raio 2km) nas ultimas 2 horas
        nearby = await conn.fetchval("""
            SELECT id FROM alertas
            WHERE criado_em > NOW() - INTERVAL '2 hours'
              AND ST_DWithin(geom::geography,
                             ST_SetSRID(ST_MakePoint($1, $2), 4326)::geography, 2000)
        """, lon, lat)
        if nearby:
            log.info(f"Alerta duplicado ignorado (raio 2km): lat={lat:.3f} lon={lon:.3f}")
            continue
        meteo = get_nearest_meteo(lat, lon, meteo_data) if meteo_data else {}
        score, categoria = calcular_score(par, meteo)
        risco_estrutural = get_structural_risk(lat, lon)
        try:
            alerta_id = await conn.fetchval("""
                INSERT INTO alertas (
                    geom, hotspot_id, prociv_id, score, categoria, source_tag,
                    temp, humidade, vento_vel, vento_dir, fwi, risco_estrutural
                )
                VALUES (
                    ST_SetSRID(ST_MakePoint($1, $2), 4326),
                    $3, $4, $5, $6, 'SYS', $7, $8, $9, $10, $11, $12
                )
                RETURNING id
            """, lon, lat, hotspot_id, par.get("prociv_id"),
                score, categoria,
                meteo.get("temp"), meteo.get("humidade"),
                meteo.get("vento_vel"), meteo.get("vento_dir"),
                meteo.get("fwi"), risco_estrutural)
            alertas_gerados.append({
                "id": alerta_id, "lat": lat, "lon": lon,
                "score": score, "categoria": categoria, "source_tag": "SYS",
                "prociv_confirmado": par.get("prociv_confirmado"),
                "prociv_localidade": par.get("prociv_localidade"),
                "meteo": {"temp": meteo.get("temp"), "humidade": meteo.get("humidade"),
                          "vento_vel": meteo.get("vento_vel"), "fwi": meteo.get("fwi")},
                "risco_estrutural": risco_estrutural,
            })
            log.info(f"Alerta {alerta_id}: score={score} cat={categoria} lat={lat:.3f} lon={lon:.3f}")
        except Exception as e:
            log.error(f"Erro a inserir alerta hotspot {hotspot_id}: {e}")
    return alertas_gerados
