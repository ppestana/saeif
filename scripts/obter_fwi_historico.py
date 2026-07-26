#!/usr/bin/env python3
"""
Obtem o Fire Weather Index (FWI) historico diario (2020-2025), via
Climate Data Store / CEMS Early Warning Data Store (Copernicus), para
construcao do conjunto de dados de validacao do modelo de integracao
Risco = f(I, P, V, M) (ver saeif_especificacao_cientifica.html Sec05).

Fonte: "Fire danger indices historical data from the Copernicus
Emergency Management Service" (cems-fire-historical-v1) -- reconstrucao
historica completa a partir da reanalise ERA5, resolucao nativa
0.25x0.25 graus, frequencia diaria. Requer conta ECMWF (distinta do
Copernicus Data Space Ecosystem/CDSE ja usado para NDVI/DEM).

IMPORTANTE (confirmado por erro real, 26 Jul 2026): este dataset esta
hospedado no EWDS (Early Warning Data Store, ewds.climate.copernicus.eu),
NAO no CDS principal (cds.climate.copernicus.eu) -- apesar de aparecer
listado la tambem. Um pedido ao endpoint do CDS devolve 404 "process
not found". A mesma chave de API funciona nos dois portais (mesma conta
ECMWF), so o URL muda -- por isso o script sobrescreve explicitamente o
URL do cliente, em vez de depender do ~/.cdsapirc por omissao (que
aponta para o CDS principal, util para outros datasets).

Nota de proveniencia: fonte DIFERENTE das que ja usamos para o resto do
SAEIF -- nao e o CDSE (Sentinel Hub Process API). Ver
data/fwi_historico.meta.yaml apos o download, para documentar como as
restantes fontes do projeto.

Uso:
    python3 obter_fwi_historico.py <output.grib>

Requisitos: cdsapi instalado (pip install cdsapi), ~/.cdsapirc configurado
com a chave pessoal (o URL nele e ignorado por este script -- ver acima),
termos de utilizacao do dataset aceites uma vez na interface web do EWDS
(https://ewds.climate.copernicus.eu/datasets/cems-fire-historical-v1).
"""
import sys
import os
import cdsapi

DATASET = "cems-fire-historical-v1"
EWDS_URL = "https://ewds.climate.copernicus.eu/api"

# Bbox: extensao iberica ja usada no resto do SAEIF, com pequena margem
# (North, West, South, East -- ordem exigida pela API do CDS)
AREA = [42.5, -9.6, 36.75, -6]

REQUEST = {
    "product_type": "reanalysis",
    "variable": ["fire_weather_index"],
    "dataset_type": "consolidated_dataset",
    "system_version": ["4_1"],
    "year": ["2020", "2021", "2022", "2023", "2024", "2025"],
    "month": [f"{m:02d}" for m in range(1, 13)],
    "day": [f"{d:02d}" for d in range(1, 32)],
    "grid": "original_grid",
    "data_format": "grib",
    "area": AREA,
}


def ler_chave_do_cdsapirc():
    """Le a chave do ~/.cdsapirc existente, ignorando o URL nele
    (que aponta para o CDS principal, nao o EWDS que este dataset exige)."""
    caminho = os.path.expanduser("~/.cdsapirc")
    if not os.path.exists(caminho):
        raise FileNotFoundError(f"{caminho} nao encontrado -- ver instrucoes no cabecalho do script.")
    with open(caminho) as f:
        for linha in f:
            if linha.strip().startswith("key:"):
                return linha.split(":", 1)[1].strip()
    raise ValueError(f"Nao encontrei uma linha 'key:' em {caminho}")


def main():
    if len(sys.argv) != 2:
        print("Uso: python3 obter_fwi_historico.py <output.grib>")
        sys.exit(1)

    output_path = sys.argv[1]

    print(f"Dataset: {DATASET}")
    print(f"URL (EWDS, nao o CDS principal): {EWDS_URL}")
    print(f"Area (N,W,S,E): {AREA}")
    print(f"Anos: {REQUEST['year']}")
    print("A submeter pedido ao EWDS -- pode demorar (fila de processamento "
          "do lado do ECMWF, nao e instantaneo como o Sentinel Hub) ...")

    chave = ler_chave_do_cdsapirc()
    client = cdsapi.Client(url=EWDS_URL, key=chave)
    resultado = client.retrieve(DATASET, REQUEST)
    resultado.download(output_path)

    if not os.path.exists(output_path):
        print("ERRO: ficheiro nao foi criado.")
        sys.exit(1)

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"FWI historico guardado em {output_path} ({size_mb:.1f}MB)")
    print("Concluido.")


if __name__ == "__main__":
    main()
