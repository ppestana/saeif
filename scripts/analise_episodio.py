#!/usr/bin/env python3
"""
SAEIF — Análise do episódio de incêndios (Fase A).
Extrai ocorrências PROCIV de um período + dados SAEIF quando há alerta.
Produz CSV (Excel) + relatório de cobertura das lacunas.
Independente do Docker: TCP 127.0.0.1:5434. Lê /srv/saeif/.env.
Uso: python3 analise_episodio.py [data_inicio]   (default 2026-07-01)
"""
import csv, os, sys
import psycopg2, psycopg2.extras

ENV_PATH = "/srv/saeif/.env"
DB_HOST, DB_PORT = "127.0.0.1", 5434
OUTPUT_CSV = "/tmp/saeif_episodio.csv"
DATA_INICIO_DEFAULT = "2026-07-01"

def carregar_env(path):
    cfg = {}
    with open(path, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha or linha.startswith("#") or "=" not in linha:
                continue
            k, _, v = linha.partition("=")
            cfg[k.strip()] = v.strip()
    return cfg

COLUNAS = [
    ("data_hora_inicio","prociv"),("hora_inicio","prociv"),("concelho","prociv"),
    ("freguesia","prociv"),("distrito","prociv"),("natureza","prociv"),
    ("estado_atual","prociv"),("operacionais","prociv"),("meios_terrestres","prociv"),
    ("meios_aereos","prociv"),("fonte_alerta","prociv"),("latitude","prociv"),
    ("longitude","prociv"),("saeif_alerta_id","saeif"),("saeif_score","saeif"),
    ("saeif_risco_estrutural","saeif"),("saeif_categoria","saeif"),("saeif_frp","saeif"),
    ("hora_dominado","lacuna"),("duracao_h","lacuna"),("causa","lacuna"),
    ("area_ardida_ha","lacuna"),("observacoes","manual"),
]

QUERY = """
    SELECT p.data_hora, p.concelho, p.freguesia, p.distrito, p.natureza,
        p.status AS estado_atual, p.man AS operacionais,
        p.terrain AS meios_terrestres, p.aerial AS meios_aereos, p.fonte_alerta,
        ST_Y(p.geom) AS latitude, ST_X(p.geom) AS longitude,
        a.id AS saeif_alerta_id, a.score AS saeif_score,
        ROUND(a.risco_estrutural::numeric,2) AS saeif_risco_estrutural,
        a.categoria AS saeif_categoria, h.frp AS saeif_frp
    FROM ocorrencias_prociv p
    LEFT JOIN alertas a ON a.prociv_id = p.id
    LEFT JOIN hotspots h ON h.id = a.hotspot_id
    WHERE p.data_hora >= %s
    ORDER BY p.data_hora DESC
"""

def main():
    data_inicio = sys.argv[1] if len(sys.argv) > 1 else DATA_INICIO_DEFAULT
    cfg = carregar_env(ENV_PATH)
    conn = psycopg2.connect(host=DB_HOST, port=DB_PORT, user=cfg["DB_USER"],
                            password=cfg["DB_PASSWORD"], dbname=cfg["DB_NAME"])
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(QUERY, (data_inicio,))
    linhas = cur.fetchall()
    cur.close(); conn.close()

    cabecalhos = [c[0] for c in COLUNAS]
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f); w.writerow(cabecalhos)
        for r in linhas:
            dh = r["data_hora"]
            reg = {
                "data_hora_inicio": dh.strftime("%Y-%m-%d %H:%M") if dh else "",
                "hora_inicio": dh.strftime("%H:%M") if dh else "",
                "concelho": r["concelho"] or "", "freguesia": r["freguesia"] or "",
                "distrito": r["distrito"] or "", "natureza": r["natureza"] or "",
                "estado_atual": r["estado_atual"] or "",
                "operacionais": r["operacionais"] if r["operacionais"] is not None else "",
                "meios_terrestres": r["meios_terrestres"] if r["meios_terrestres"] is not None else "",
                "meios_aereos": r["meios_aereos"] if r["meios_aereos"] is not None else "",
                "fonte_alerta": r["fonte_alerta"] or "",
                "latitude": round(r["latitude"],6) if r["latitude"] is not None else "",
                "longitude": round(r["longitude"],6) if r["longitude"] is not None else "",
                "saeif_alerta_id": r["saeif_alerta_id"] if r["saeif_alerta_id"] is not None else "",
                "saeif_score": r["saeif_score"] if r["saeif_score"] is not None else "",
                "saeif_risco_estrutural": r["saeif_risco_estrutural"] if r["saeif_risco_estrutural"] is not None else "",
                "saeif_categoria": r["saeif_categoria"] or "",
                "saeif_frp": r["saeif_frp"] if r["saeif_frp"] is not None else "",
                "hora_dominado": "", "duracao_h": "", "causa": "",
                "area_ardida_ha": "", "observacoes": "",
            }
            w.writerow([reg[c] for c in cabecalhos])

    total = len(linhas)
    print(f"\n{'='*66}")
    print(f"  SAEIF — Análise do episódio desde {data_inicio}")
    print(f"  {total} ocorrências · CSV: {OUTPUT_CSV}")
    print(f"{'='*66}")
    print(f"  {'COLUNA':<26}{'PREENCHIDAS':>12}{'VAZIAS':>9}{'ORIGEM':>9}")
    print(f"  {'-'*26}{'-'*12}{'-'*9}{'-'*9}")
    def cheio(r, col):
        m = {"data_hora_inicio":r["data_hora"],"hora_inicio":r["data_hora"],
            "concelho":r["concelho"],"freguesia":r["freguesia"],"distrito":r["distrito"],
            "natureza":r["natureza"],"estado_atual":r["estado_atual"],
            "operacionais":r["operacionais"],"meios_terrestres":r["meios_terrestres"],
            "meios_aereos":r["meios_aereos"],"fonte_alerta":r["fonte_alerta"],
            "latitude":r["latitude"],"longitude":r["longitude"],
            "saeif_alerta_id":r["saeif_alerta_id"],"saeif_score":r["saeif_score"],
            "saeif_risco_estrutural":r["saeif_risco_estrutural"],
            "saeif_categoria":r["saeif_categoria"],"saeif_frp":r["saeif_frp"]}
        return m.get(col) is not None and m.get(col) != ""
    for col, origem in COLUNAS:
        n_ok = 0 if origem in ("lacuna","manual") else sum(1 for r in linhas if cheio(r,col))
        n_vazio = total - n_ok
        marca = "  <-- LACUNA" if origem=="lacuna" else (
                "  <-- baixa cobertura" if origem=="saeif" and total and n_ok/total<0.5 else "")
        print(f"  {col:<26}{n_ok:>12}{n_vazio:>9}{origem:>9}{marca}")
    print(f"{'='*66}")
    n_alerta = sum(1 for r in linhas if r["saeif_alerta_id"] is not None)
    if total:
        print(f"  Cobertura SAEIF: {n_alerta}/{total} ocorrências com alerta ({100.0*n_alerta/total:.1f}%).")
    print(f"{'='*66}\n")

if __name__ == "__main__":
    main()
