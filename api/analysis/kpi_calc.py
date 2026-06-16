"""
Cálculo de KPIs de deteção precoce: SAEIF vs PROCIV.
Métrica: de cada par alerta↔ocorrência PROCIV, qual fonte detetou primeiro.
Grava agregado (kpi_periodos) + detalhe auditável (kpi_detalhe) por período.
"""
import logging
import asyncpg
from datetime import date, timedelta, datetime, timezone

log = logging.getLogger("saeif.kpi")

# Query base: empareha alertas com PROCIV, traz timestamps, geometrias e distância.
_SQL_PARES = """
    SELECT
        a.id AS alerta_id,
        h.id AS hotspot_id,
        p.id AS prociv_id,
        (h.acq_date + h.acq_time)::timestamptz AS deteccao_sat,
        p.data_hora AS despacho_prociv,
        EXTRACT(EPOCH FROM (p.data_hora - (h.acq_date + h.acq_time)::timestamptz))/3600.0 AS horas_diff,
        ST_Y(h.geom) AS hotspot_lat, ST_X(h.geom) AS hotspot_lon, h.frp AS hotspot_frp,
        ST_Y(p.geom) AS prociv_lat, ST_X(p.geom) AS prociv_lon,
        ST_Distance(h.geom::geography, p.geom::geography) AS distancia_m,
        a.localidade_estimada AS localidade
    FROM alertas a
    JOIN hotspots h ON h.id = a.hotspot_id
    JOIN ocorrencias_prociv p ON p.id = a.prociv_id
    WHERE a.prociv_id IS NOT NULL
      AND h.acq_date IS NOT NULL
      AND p.data_hora IS NOT NULL
      AND h.acq_date >= $1 AND h.acq_date < $2
      AND ST_Distance(h.geom::geography, p.geom::geography) <= 2000  -- limiar 2km (coerente com dedup)
"""

def _categoria(horas_diff):
    if horas_diff is None:
        return None
    if horas_diff > 0:
        return "saeif"
    if horas_diff < 0:
        return "prociv"
    return "simultaneo"

async def calcular_periodo(conn, tipo, inicio, fim, ano):
    """Calcula um período [inicio, fim) e grava agregado + detalhe (snapshot)."""
    # Janela por DATA DE DETECAO (acq_date), o evento real — nao a data de processamento.
    # acq_date e' DATE; filtro [inicio, fim+1dia) para incluir todo o dia 'fim'.
    d_from = inicio
    d_to   = fim + timedelta(days=1)

    pares = await conn.fetch(_SQL_PARES, d_from, d_to)

    total = len(pares)
    saeif = sum(1 for r in pares if _categoria(r["horas_diff"]) == "saeif")
    simult = sum(1 for r in pares if _categoria(r["horas_diff"]) == "simultaneo")
    prociv = sum(1 for r in pares if _categoria(r["horas_diff"]) == "prociv")
    pct = round(100.0 * saeif / total, 2) if total else None
    antec = [r["horas_diff"] for r in pares if _categoria(r["horas_diff"]) == "saeif"]
    antec_media = round(sum(antec) / len(antec), 2) if antec else None

    # UPSERT do agregado (UNIQUE tipo+inicio+fim) — recalcular sobrepõe
    periodo_id = await conn.fetchval("""
        INSERT INTO kpi_periodos
            (tipo, periodo_inicio, periodo_fim, ano, total_pares,
             saeif_primeiro, simultaneo, prociv_primeiro, pct_saeif_primeiro,
             antecedencia_media_h, calculado_em)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10, NOW())
        ON CONFLICT (tipo, periodo_inicio, periodo_fim) DO UPDATE SET
            ano=EXCLUDED.ano, total_pares=EXCLUDED.total_pares,
            saeif_primeiro=EXCLUDED.saeif_primeiro, simultaneo=EXCLUDED.simultaneo,
            prociv_primeiro=EXCLUDED.prociv_primeiro,
            pct_saeif_primeiro=EXCLUDED.pct_saeif_primeiro,
            antecedencia_media_h=EXCLUDED.antecedencia_media_h,
            calculado_em=NOW()
        RETURNING id
    """, tipo, inicio, fim, ano, total, saeif, simult, prociv, pct, antec_media)

    # Snapshot do detalhe: apaga o antigo deste período, insere o fresco
    await conn.execute("DELETE FROM kpi_detalhe WHERE kpi_periodo_id = $1", periodo_id)
    for r in pares:
        await conn.execute("""
            INSERT INTO kpi_detalhe
                (kpi_periodo_id, alerta_id, hotspot_id, prociv_id,
                 deteccao_sat, despacho_prociv, horas_diff,
                 hotspot_lat, hotspot_lon, hotspot_frp,
                 prociv_lat, prociv_lon, distancia_m, categoria, localidade)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
        """, periodo_id, r["alerta_id"], r["hotspot_id"], r["prociv_id"],
            r["deteccao_sat"], r["despacho_prociv"],
            round(r["horas_diff"], 2) if r["horas_diff"] is not None else None,
            r["hotspot_lat"], r["hotspot_lon"], r["hotspot_frp"],
            r["prociv_lat"], r["prociv_lon"],
            round(r["distancia_m"], 1) if r["distancia_m"] is not None else None,
            _categoria(r["horas_diff"]), r["localidade"])

    log.info(f"KPI {tipo} [{inicio}..{fim}]: {total} pares, "
             f"{saeif} SAEIF, {simult} simult, {prociv} PROCIV ({pct}%)")
    return periodo_id

async def calcular_semana_terminada(conn, hoje=None):
    """A semana ISO (segunda-domingo) que terminou antes de hoje."""
    hoje = hoje or date.today()
    # Domingo passado = fim; segunda anterior = inicio
    dias_desde_segunda = hoje.weekday()  # 0=segunda
    segunda_desta = hoje - timedelta(days=dias_desde_segunda)
    fim = segunda_desta - timedelta(days=1)        # domingo passado
    inicio = fim - timedelta(days=6)               # segunda dessa semana
    return await calcular_periodo(conn, "semanal", inicio, fim, fim.year)

async def calcular_cumulativo_anual(conn, ano=None):
    """Acumulado do ano corrente (1 Jan até hoje)."""
    ano = ano or date.today().year
    inicio = date(ano, 1, 1)
    fim = date.today()
    return await calcular_periodo(conn, "cumulativo_anual", inicio, fim, ano)

async def calcular_anual(conn, ano):
    """Ano completo (1 Jan a 31 Dez) — para a vista interanual."""
    inicio = date(ano, 1, 1)
    fim = date(ano, 12, 31)
    return await calcular_periodo(conn, "anual", inicio, fim, ano)

async def main():
    """Ponto de entrada do cron: semana terminada + cumulativo anual + anual."""
    import os
    dsn = (f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
           f"@{os.getenv('DB_HOST','db')}:{os.getenv('DB_PORT','5432')}/{os.getenv('DB_NAME')}")
    conn = await asyncpg.connect(dsn)
    try:
        await calcular_semana_terminada(conn)
        await calcular_cumulativo_anual(conn)
        await calcular_anual(conn, date.today().year)
        log.info("KPI: cálculo semanal concluído.")
    finally:
        await conn.close()

if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
