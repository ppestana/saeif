"""
Exportacao de alertas e hotspots para CSV.
"""
import csv, io, logging
from datetime import datetime, timezone

log = logging.getLogger('saeif.export')

RECOMENDACOES = {
    "CRITICO": "Mobilizacao imediata meios aereos + AGIF",
    "ALTO":    "Pre-alerta meios aereos + reforco terrestre",
    "MEDIO":   "Vigilancia activa + pre-posicionamento",
    "BAIXO":   "Monitorizacao regular",
}

def fmt_dt(val):
    """Converter timestamp ou string ISO para dd/mm/yyyy hh:mm."""
    if val is None: return ""
    try:
        if isinstance(val, (int, float)):
            dt = datetime.fromtimestamp(val, tz=timezone.utc)
        else:
            dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y %H:%M")
    except:
        return str(val)

def fmt_num(val, decimals=1):
    if val is None: return ""
    try: return f"{float(val):.{decimals}f}"
    except: return str(val)

def fmt_pct(val):
    if val is None: return ""
    try: return f"{float(val):.1f}%"
    except: return str(val)

async def export_alertas_csv(conn, date_from, date_to) -> str:
    """Exporta alertas para CSV."""
    rows = await conn.fetch("""
        SELECT
            id,
            criado_em,
            ST_Y(geom) AS lat,
            ST_X(geom) AS lon,
            localidade_estimada,
            score,
            categoria,
            satelite,
            prociv_confirmado,
            fwi,
            temp,
            humidade,
            vento_vel,
            vento_dir,
            effis_fwi,
            effis_ranking,
            effis_anomaly,
            risco_estrutural,
            vegetacao_tipo
        FROM alertas
        WHERE criado_em >= $1 AND criado_em <= $2
        ORDER BY criado_em DESC
    """, date_from, date_to)

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_MINIMAL)

    # Cabeçalho
    writer.writerow([
        "ID", "Data/Hora", "Latitude", "Longitude", "Localidade",
        "Score", "Categoria", "Satelite", "PROCIV",
        "FWI (IPMA)", "Temperatura (°C)", "Humidade (%)",
        "Vento (km/h)", "Direccao Vento",
        "FWI EFFIS previsto", "Ranking historico (%)", "Anomalia (sigma)",
        "Risco Estrutural (%)", "Vegetacao", "Recomendacao"
    ])

    dirs = {0:"N",45:"NE",90:"E",135:"SE",180:"S",225:"SO",270:"O",315:"NO"}
    def dir_card(graus):
        if graus is None: return ""
        g = float(graus) % 360
        closest = min(dirs.keys(), key=lambda x: abs(x - g))
        return dirs[closest]

    for r in rows:
        risco_pct = f"{int(float(r['risco_estrutural'])*100)}%" if r['risco_estrutural'] is not None else ""
        writer.writerow([
            r['id'],
            fmt_dt(r['criado_em']),
            fmt_num(r['lat'], 5),
            fmt_num(r['lon'], 5),
            r['localidade_estimada'] or "",
            fmt_num(r['score'], 1),
            r['categoria'] or "",
            r['satelite'] or "",
            "Sim" if r['prociv_confirmado'] else "Nao",
            fmt_num(r['fwi'], 1),
            fmt_num(r['temp'], 1),
            fmt_num(r['humidade'], 0),
            fmt_num(r['vento_vel'], 1),
            dir_card(r['vento_dir']),
            fmt_num(r['effis_fwi'], 1),
            fmt_pct(r['effis_ranking']),
            fmt_num(r['effis_anomaly'], 2),
            risco_pct,
            r['vegetacao_tipo'] or "",
            RECOMENDACOES.get(r['categoria'], ""),
        ])

    return output.getvalue()

async def export_hotspots_csv(conn, date_from, date_to) -> str:
    """Exporta hotspots FIRMS para CSV."""
    rows = await conn.fetch("""
        SELECT
            id, criado_em,
            ST_Y(geom) AS lat, ST_X(geom) AS lon,
            satelite, confianca, frp, temp_brilho
        FROM hotspots
        WHERE criado_em >= $1 AND criado_em <= $2
        ORDER BY criado_em DESC
    """, date_from, date_to)

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        "ID", "Data/Hora", "Latitude", "Longitude",
        "Satelite", "Confianca", "FRP (MW)", "Temp. Brilho (K)"
    ])
    for r in rows:
        writer.writerow([
            r['id'], fmt_dt(r['criado_em']),
            fmt_num(r['lat'], 5), fmt_num(r['lon'], 5),
            r['satelite'] or "", r['confianca'] or "",
            fmt_num(r['frp'], 1), fmt_num(r['temp_brilho'], 1),
        ])
    return output.getvalue()

async def export_prociv_csv(conn, date_from, date_to) -> str:
    """Exporta ocorrencias PROCIV para CSV."""
    rows = await conn.fetch("""
        SELECT
            id, criado_em,
            ST_Y(geom) AS lat, ST_X(geom) AS lon,
            localidade, natureza, estado
        FROM prociv_ocorrencias
        WHERE criado_em >= $1 AND criado_em <= $2
        ORDER BY criado_em DESC
    """, date_from, date_to)

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        "ID", "Data/Hora", "Latitude", "Longitude",
        "Localidade", "Natureza", "Estado"
    ])
    for r in rows:
        writer.writerow([
            r['id'], fmt_dt(r['criado_em']),
            fmt_num(r['lat'], 5), fmt_num(r['lon'], 5),
            r['localidade'] or "", r['natureza'] or "", r['estado'] or "",
        ])
    return output.getvalue()
