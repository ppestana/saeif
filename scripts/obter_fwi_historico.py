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
Copernicus Data Space Ecosystem/CDSE ja usado para NDVI/DEM) e ficheiro
~/.cdsapirc configurado com a chave pessoal do perfil CDS.

Nota de proveniencia: esta e uma fonte DIFERENTE das que ja usamos para
o resto do SAEIF -- nao e o CDSE (Sentinel Hub Process API), e o CDS/
EWDS (ECMWF), com sistema de autenticacao proprio. Ver
data/fwi_historico.meta.yaml apos o download, para documentar como as
restantes fontes do projeto.

Uso:
    python3 obter_fwi_historico.py <output.grib>

Requisitos: cdsapi instalado (pip install cdsapi), ~/.cdsapirc configurado,
termos de utilizacao do dataset aceites uma vez na interface web do EWDS
(https://ewds.climate.copernicus.eu/datasets/cems-fire-historical-v1).
"""
import sys
import os
import cdsapi

DATASET = "cems-fire-historical-v1"

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


def main():
    if len(sys.argv) != 2:
        print("Uso: python3 obter_fwi_historico.py <output.grib>")
        sys.exit(1)

    output_path = sys.argv[1]

    print(f"Dataset: {DATASET}")
    print(f"Area (N,W,S,E): {AREA}")
    print(f"Anos: {REQUEST['year']}")
    print("A submeter pedido ao CDS/EWDS -- pode demorar (fila de processamento "
          "do lado do ECMWF, nao e instantaneo como o Sentinel Hub) ...")

    client = cdsapi.Client()
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
