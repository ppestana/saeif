#!/usr/bin/env python3
"""
Gera o raster de sensibilidade por proporcao de populacao idosa (65+),
ponderada pela confianca estatistica, a partir da grelha de 1km do INE
(Censos 2021, GRID1K21_CONT.gpkg), para a grelha oficial do SAEIF (250m,
EPSG:3763).

Metodo:
    1. Reprojeta a grelha do INE (EPSG:3035, ETRS89-LAEA) para EPSG:3763,
       calculando por celula de 1km:
           proporcao = N_INDIVIDUOS_65_OU_MAIS / N_INDIVIDUOS
           peso_confianca = MIN(N_INDIVIDUOS / SENSITIVITY_CONFIDENCE_N0, 1.0)
           sensibilidade = proporcao * peso_confianca
       Celulas com N_INDIVIDUOS=0 sao EXCLUIDAS da camada (nao computadas
       como NULL/0 -- ver nota abaixo sobre limitacao do gdal_rasterize).
    2. Rasteriza o atributo 'sensibilidade' para a grelha oficial de 250m:
       cada celula de destino herda o valor do poligono de 1km que a
       contem (fonte vetorial, sem reamostragem raster).

Justificacao da ponderacao por confianca: uma proporcao calculada sobre
um denominador pequeno (ex. 2 habitantes) e estatisticamente instavel --
"100% idosos" em 2 pessoas nao tem a mesma fiabilidade que "100% idosos"
em 200 pessoas, mesmo sendo o mesmo valor bruto. Em vez de um limiar fixo
(que criaria descontinuidades artificiais entre celulas vizinhas com
populacoes proximas do limiar), o peso de confianca amortece
continuamente o contributo de proporcoes de baixa confianca para perto de
zero, sem descartar nenhuma celula.

NOTA sobre o gdal_rasterize: nao respeita valores NULL de atributo (trata-
os como 0, confirmado por teste deliberado durante o desenvolvimento) --
por isso celulas sem populacao sao excluidas da camada via WHERE, nao
computadas como NULL.

Uso:
    python3 gerar_proporcao_idosos.py <grid_ine.gpkg> <camada> <output.tif>
"""
import subprocess
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config"))
import grid_spec as gs
import indice_v as cfg


def main():
    if len(sys.argv) != 4:
        print("Uso: python3 gerar_proporcao_idosos.py <grid_ine.gpkg> <camada> <output.tif>")
        sys.exit(1)

    gpkg_path, camada, output_path = sys.argv[1:4]

    gs.assert_grid_consistency()

    reprojetado_path = output_path + ".reprojetado.gpkg"

    print(f"A reprojetar {camada} para {gs.GRID_CRS}, calcular proporcao e peso de confianca "
          f"(N0={cfg.SENSITIVITY_CONFIDENCE_N0}) ...")
    sql = (
        f"SELECT *, "
        f"(CAST(N_INDIVIDUOS_65_OU_MAIS AS REAL) / CAST(N_INDIVIDUOS AS REAL)) "
        f"* MIN(CAST(N_INDIVIDUOS AS REAL) / {cfg.SENSITIVITY_CONFIDENCE_N0}, 1.0) "
        f"AS sensibilidade_idosos "
        f"FROM {camada} WHERE N_INDIVIDUOS > 0"
    )
    cmd_reproj = [
        "ogr2ogr", "-f", "GPKG",
        "-t_srs", gs.GRID_CRS,
        "-dialect", "SQLite",
        "-sql", sql,
        "-nln", "grid_ine_sensibilidade",
        "-overwrite",
        reprojetado_path, gpkg_path,
    ]
    resultado = subprocess.run(cmd_reproj, capture_output=True, text=True)
    if resultado.returncode != 0:
        print(f"ERRO no ogr2ogr (codigo {resultado.returncode}):")
        print(f"stdout: {resultado.stdout}")
        print(f"stderr: {resultado.stderr}")
        sys.exit(1)
    print("Reprojecao, proporcao e ponderacao de confianca concluidas.")

    print(f"A rasterizar sensibilidade_idosos para a grelha oficial ({gs.GRID_NCOLS}x{gs.GRID_NROWS}) ...")
    cmd_rasterize = [
        "gdal_rasterize",
        "-a", "sensibilidade_idosos",
        "-a_nodata", str(gs.GRID_NODATA),
        "-init", str(gs.GRID_NODATA),
        "-ot", "Float32",
        "-te", str(gs.GRID_XMIN), str(gs.GRID_YMIN), str(gs.GRID_XMAX), str(gs.GRID_YMAX),
        "-tr", str(gs.GRID_RESOLUTION), str(gs.GRID_RESOLUTION),
        "-co", "COMPRESS=LZW",
        "-co", "TILED=YES",
        reprojetado_path, output_path,
    ]
    resultado = subprocess.run(cmd_rasterize, capture_output=True, text=True)
    if resultado.returncode != 0:
        print(f"ERRO no gdal_rasterize (codigo {resultado.returncode}):")
        print(f"stdout: {resultado.stdout}")
        print(f"stderr: {resultado.stderr}")
        sys.exit(1)
    print(resultado.stdout)

    os.remove(reprojetado_path)
    print(f"Concluido: {output_path}")


if __name__ == "__main__":
    main()
