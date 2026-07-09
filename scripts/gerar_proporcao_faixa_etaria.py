#!/usr/bin/env python3
"""
Gera o raster de proporcao de uma faixa etaria (ponderada por confianca
estatistica) a partir da grelha de 1km do INE (Censos 2021,
GRID1K21_CONT.gpkg), para a grelha oficial do SAEIF (250m, EPSG:3763).

Generalizacao de gerar_proporcao_idosos.py: aceita o campo do numerador
como parametro, para reutilizar a mesma metodologia noutras faixas
etarias (crianças, N_INDIVIDUOS_0A14; jovens, N_INDIVIDUOS_15A24; etc.)
sem duplicar logica.

Metodo (identico ao de idosos):
    1. Reprojeta a grelha do INE (EPSG:3035) para EPSG:3763, calculando:
           proporcao = campo_numerador / N_INDIVIDUOS
           peso_confianca = MIN(N_INDIVIDUOS / SENSITIVITY_CONFIDENCE_N0, 1.0)
           valor = proporcao * peso_confianca
       Celulas com N_INDIVIDUOS=0 sao EXCLUIDAS da camada (nao computadas
       como NULL -- gdal_rasterize nao respeita NULL, trata como 0).
    2. Rasteriza para a grelha oficial de 250m (fonte vetorial, sem
       reamostragem raster).

Uso:
    python3 gerar_proporcao_faixa_etaria.py <grid_ine.gpkg> <camada> <campo_numerador> <output.tif>

Exemplo (criancas 0-14):
    python3 gerar_proporcao_faixa_etaria.py data/GRID1K21_CONT/GRID1K21_CONT.gpkg \\
        GRID1K21_CONT N_INDIVIDUOS_0A14 data/indice_v_sensibilidade_criancas.tif
"""
import subprocess
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config"))
import grid_spec as gs
import indice_v as cfg


def main():
    if len(sys.argv) != 5:
        print("Uso: python3 gerar_proporcao_faixa_etaria.py <grid_ine.gpkg> <camada> <campo_numerador> <output.tif>")
        sys.exit(1)

    gpkg_path, camada, campo_numerador, output_path = sys.argv[1:5]

    gs.assert_grid_consistency()

    reprojetado_path = output_path + ".reprojetado.gpkg"

    print(f"A reprojetar {camada} para {gs.GRID_CRS}, calcular proporcao de '{campo_numerador}' "
          f"e peso de confianca (N0={cfg.SENSITIVITY_CONFIDENCE_N0}) ...")
    sql = (
        f"SELECT *, "
        f"(CAST({campo_numerador} AS REAL) / CAST(N_INDIVIDUOS AS REAL)) "
        f"* MIN(CAST(N_INDIVIDUOS AS REAL) / {cfg.SENSITIVITY_CONFIDENCE_N0}, 1.0) "
        f"AS valor_ponderado "
        f"FROM {camada} WHERE N_INDIVIDUOS > 0"
    )
    cmd_reproj = [
        "ogr2ogr", "-f", "GPKG",
        "-t_srs", gs.GRID_CRS,
        "-dialect", "SQLite",
        "-sql", sql,
        "-nln", "grid_ine_faixa",
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

    print(f"A rasterizar valor_ponderado para a grelha oficial ({gs.GRID_NCOLS}x{gs.GRID_NROWS}) ...")
    cmd_rasterize = [
        "gdal_rasterize",
        "-a", "valor_ponderado",
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
