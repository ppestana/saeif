#!/usr/bin/env python3
"""
Gera o raster de proporcao de populacao idosa (65+) a partir da grelha de
1km do INE (Censos 2021, GRID1K21_CONT.gpkg), para a grelha oficial do
SAEIF (250m, EPSG:3763).

Metodo:
    1. Reprojeta a grelha do INE (EPSG:3035, ETRS89-LAEA) para EPSG:3763,
       calculando a proporcao pct_65 = N_INDIVIDUOS_65_OU_MAIS / N_INDIVIDUOS
       por celula de 1km. Celulas com N_INDIVIDUOS=0 ficam com pct_65=NULL
       (nao 0 -- "sem populacao" e "0% idosos" sao coisas diferentes).
    2. Rasteriza o atributo pct_65 para a grelha oficial de 250m: cada
       celula de destino herda o valor do poligono de 1km que a contem
       (nearest neighbour "natural" de uma fonte vetorial -- nao ha
       reamostragem raster envolvida, e por isso nao ha risco de bilinear/
       cubica/media criarem valores inexistentes numa variavel censitaria).
       Celulas sem poligono correspondente (NULL) ou fora da grelha do INE
       ficam com o NoData oficial do SAEIF.

Uso:
    python3 gerar_proporcao_idosos.py <grid_ine.gpkg> <camada> <output.tif>
"""
import subprocess
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config"))
import grid_spec as gs


def main():
    if len(sys.argv) != 4:
        print("Uso: python3 gerar_proporcao_idosos.py <grid_ine.gpkg> <camada> <output.tif>")
        sys.exit(1)

    gpkg_path, camada, output_path = sys.argv[1:4]

    gs.assert_grid_consistency()

    reprojetado_path = output_path + ".reprojetado.gpkg"

    print(f"A reprojetar {camada} para {gs.GRID_CRS} e a calcular a proporcao de idosos ...")
    # NOTA IMPORTANTE: o gdal_rasterize NAO respeita valores NULL de atributo
    # (trata-os como 0, confirmado por teste deliberado) -- por isso as
    # celulas sem populacao sao EXCLUIDAS da camada (WHERE N_INDIVIDUOS > 0),
    # em vez de computadas como NULL. Onde nao ha poligono, o gdal_rasterize
    # deixa corretamente o valor de -init/-a_nodata (NoData oficial do SAEIF).
    sql = (
        f"SELECT *, "
        f"CAST(N_INDIVIDUOS_65_OU_MAIS AS REAL) / CAST(N_INDIVIDUOS AS REAL) AS pct_65 "
        f"FROM {camada} WHERE N_INDIVIDUOS > 0"
    )
    cmd_reproj = [
        "ogr2ogr", "-f", "GPKG",
        "-t_srs", gs.GRID_CRS,
        "-dialect", "SQLite",
        "-sql", sql,
        "-nln", "grid_ine_pct65",
        "-overwrite",
        reprojetado_path, gpkg_path,
    ]
    resultado = subprocess.run(cmd_reproj, capture_output=True, text=True)
    if resultado.returncode != 0:
        print(f"ERRO no ogr2ogr (codigo {resultado.returncode}):")
        print(f"stdout: {resultado.stdout}")
        print(f"stderr: {resultado.stderr}")
        sys.exit(1)
    print("Reprojecao e calculo da proporcao concluidos.")

    print(f"A rasterizar pct_65 para a grelha oficial ({gs.GRID_NCOLS}x{gs.GRID_NROWS}) ...")
    cmd_rasterize = [
        "gdal_rasterize",
        "-a", "pct_65",
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
