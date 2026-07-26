#!/usr/bin/env python3
"""
Emparelha os incendios do conjunto de dados de validacao (dentro da
janela temporal do PROCIV, >= 2025-08-12) com ocorrencias reais de
ocorrencias_prociv, extraindo os recursos operacionais alocados
(man, terrain, aerial) como proxy de GRAVIDADE OPERACIONAL -- o
"Produto 3" (consequencias potenciais) do SAEIF nunca foi validado
correctamente por falta de um alvo adequado (ver
saeif_especificacao_cientifica.html Sec05).

Emparelhamento: espacial (raio configuravel) + temporal (janela de dias
a volta de data_inicio) -- ao contrario do FWI (grelha regular, um valor
por dia), aqui pode haver zero, uma, ou multiplas ocorrencias PROCIV
proximas de um dado incendio; escolhe-se a mais proxima no tempo (menor
diferenca absoluta face a data_inicio).

Uso:
    python3 construir_dataset_consequencia.py <dataset_validacao.csv> <output.csv>
"""
import sys
import os
import csv
from datetime import datetime, timedelta, timezone

RAIO_M = 5000  # mesmo raio ja usado no bonus de area ardida
JANELA_DIAS = 2
DATA_MIN_PROCIV_STR = "2025-08-12"  # para comparar com as strings ISO do CSV
DATA_MIN_PROCIV = datetime(2025, 8, 12, tzinfo=timezone.utc)  # asyncpg exige datetime real, nao string

NATUREZAS_FLORESTAIS = ["%mato%", "%florest%", "%rural%", "%povoamento%"]


def obter_ocorrencias_prociv():
    import asyncpg
    import asyncio

    async def _query():
        conn = await asyncpg.connect(
            host=os.getenv("DB_HOST", "127.0.0.1"),
            port=int(os.getenv("DB_PORT", "5434")),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
        )
        try:
            condicoes = " OR ".join(f"natureza ILIKE ${i+2}" for i in range(len(NATUREZAS_FLORESTAIS)))
            sql = f"""
                SELECT
                    id, data_hora, natureza, man, terrain, aerial,
                    ST_Y(geom) AS lat, ST_X(geom) AS lon
                FROM ocorrencias_prociv
                WHERE data_hora >= $1 AND ({condicoes})
            """
            rows = await conn.fetch(sql, DATA_MIN_PROCIV, *NATUREZAS_FLORESTAIS)
            return [dict(r) for r in rows]
        finally:
            await conn.close()

    return asyncio.run(_query())


def distancia_metros_aprox(lat1, lon1, lat2, lon2):
    """Distancia aproximada em metros (formula equirectangular, suficiente
    para distancias curtas ~poucos km -- nao precisa da precisao de uma
    projeccao completa para este proposito de match, so de ordenacao)."""
    import math
    lat_media = math.radians((lat1 + lat2) / 2)
    dx = math.radians(lon2 - lon1) * math.cos(lat_media) * 6371000
    dy = math.radians(lat2 - lat1) * 6371000
    return math.sqrt(dx**2 + dy**2)


def main():
    if len(sys.argv) != 3:
        print("Uso: python3 construir_dataset_consequencia.py <dataset_validacao.csv> <output.csv>")
        sys.exit(1)

    caminho_entrada, caminho_saida = sys.argv[1:3]

    print("A consultar ocorrencias PROCIV (natureza florestal, >= "
          f"{DATA_MIN_PROCIV_STR}) ...")
    ocorrencias = obter_ocorrencias_prociv()
    print(f"{len(ocorrencias)} ocorrencias PROCIV candidatas.")

    with open(caminho_entrada) as f:
        incendios = list(csv.DictReader(f))

    incendios_na_janela = [
        i for i in incendios if i["data_inicio"] >= DATA_MIN_PROCIV_STR
    ]
    print(f"{len(incendios_na_janela)} incendios do conjunto de validacao dentro da janela PROCIV.")

    linhas_saida = []
    n_emparelhados = 0
    for inc in incendios_na_janela:
        lat_inc = float(inc["lat"])
        lon_inc = float(inc["lon"])
        data_inc = datetime.fromisoformat(inc["data_inicio"])

        melhor = None
        melhor_diff_tempo = None
        for oc in ocorrencias:
            if oc["lat"] is None or oc["lon"] is None:
                continue
            dist = distancia_metros_aprox(lat_inc, lon_inc, oc["lat"], oc["lon"])
            if dist > RAIO_M:
                continue
            diff_dias = abs((oc["data_hora"] - data_inc).total_seconds()) / 86400
            if diff_dias > JANELA_DIAS:
                continue
            if melhor is None or diff_dias < melhor_diff_tempo:
                melhor = oc
                melhor_diff_tempo = diff_dias

        linha = dict(inc)
        if melhor is not None:
            linha["prociv_man"] = melhor["man"]
            linha["prociv_terrain"] = melhor["terrain"]
            linha["prociv_aerial"] = melhor["aerial"]
            n_emparelhados += 1
        else:
            linha["prociv_man"] = ""
            linha["prociv_terrain"] = ""
            linha["prociv_aerial"] = ""
        linhas_saida.append(linha)

    print(f"Incendios emparelhados com sucesso a uma ocorrencia PROCIV: {n_emparelhados} "
          f"de {len(incendios_na_janela)} ({100*n_emparelhados/len(incendios_na_janela):.1f}%)")

    with open(caminho_saida, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(linhas_saida[0].keys()))
        writer.writeheader()
        writer.writerows(linhas_saida)

    print(f"Concluido: {caminho_saida}")


if __name__ == "__main__":
    main()
