import logging
import asyncpg
from ingest.ipma import get_nearest_meteo
from analysis.score import calcular_score, get_structural_risk, get_area_ardida_factor, get_vegetacao_tipo, get_indice_p
from ingest.effis import get_effis_values
from utils import reverse_geocode

log = logging.getLogger("saeif.alerts")

async def gerar_alertas(conn, pares, meteo_data):
    alertas_gerados = []

    async def _marcar_processed(hid):
        if hid is not None:
            await conn.execute(
                "UPDATE hotspots SET processed = TRUE WHERE id = $1", hid
            )
    for par in pares:
        hotspot_id = par.get("hotspot_id")
        lat = par.get("lat")
        lon = par.get("lon")
        existing = await conn.fetchval(
            "SELECT id FROM alertas WHERE hotspot_id = $1", hotspot_id
        )
        if existing:
            await _marcar_processed(hotspot_id)
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
            await _marcar_processed(hotspot_id)
            continue
        meteo = get_nearest_meteo(lat, lon, meteo_data) if meteo_data else {}
        area_factor = await get_area_ardida_factor(conn, lat, lon)
        vegetacao_tipo = get_vegetacao_tipo(lat, lon)
        score, categoria = calcular_score(par, meteo, area_ardida_factor=area_factor)
        risco_estrutural = get_structural_risk(lat, lon)  # combustivel puro, sem bonus (ver migration 003)
        indice_p = get_indice_p(lat, lon, area_factor)     # Indice P completo (= o que entrou no score)
        effis = get_effis_values(lat, lon)

        # Geocodificacao inversa sempre via Nominatim
        # (nao usamos prociv_localidade para evitar erros de associacao por proximidade)
        localidade_estimada = await reverse_geocode(lat, lon)
        if localidade_estimada:
            log.info(f"Nominatim: {localidade_estimada} ({lat:.3f},{lon:.3f})")

        try:
            alerta_id = await conn.fetchval("""
                INSERT INTO alertas (
                    geom, hotspot_id, prociv_id, score, categoria, source_tag,
                    temp, humidade, vento_vel, vento_dir, fwi, risco_estrutural, vegetacao_tipo,
                    localidade_estimada, effis_fwi, effis_ranking, effis_anomaly, indice_p
                )
                VALUES (
                    ST_SetSRID(ST_MakePoint($1, $2), 4326),
                    $3, $4, $5, $6, 'SYS', $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18
                )
                RETURNING id
            """, lon, lat, hotspot_id, par.get("prociv_id"),
                score, categoria,
                meteo.get("temp"), meteo.get("humidade"),
                meteo.get("vento_vel"), meteo.get("vento_dir"),
meteo.get("fwi"), risco_estrutural, vegetacao_tipo, localidade_estimada,
                (effis or {}).get("fwi"), (effis or {}).get("ranking"), (effis or {}).get("anomaly"), indice_p)
            alertas_gerados.append({
                "id": alerta_id, "lat": lat, "lon": lon,
                "score": score, "categoria": categoria, "source_tag": "SYS",
                "prociv_confirmado": par.get("prociv_confirmado"),
                "prociv_localidade": par.get("prociv_localidade"),
                "localidade_estimada": localidade_estimada,
                "meteo": {"temp": meteo.get("temp"), "humidade": meteo.get("humidade"),
                          "vento_vel": meteo.get("vento_vel"), "fwi": meteo.get("fwi")},
                "risco_estrutural": risco_estrutural,
                "indice_p": indice_p,
            })
            log.info(f"Alerta {alerta_id}: score={score} cat={categoria} lat={lat:.3f} lon={lon:.3f}")
            await _marcar_processed(hotspot_id)
        except Exception as e:
            log.error(f"Erro a inserir alerta hotspot {hotspot_id}: {e}")
    return alertas_gerados
