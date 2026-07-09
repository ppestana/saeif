#!/usr/bin/env python3
"""
Gera o raster de uma proporcao ponderada por confianca estatistica, a
partir de qualquer camada vetorial do INE (grelha 1km ou BGRI), para a
grelha oficial do SAEIF (250m, EPSG:3763).

Generalizacao de gerar_proporcao_faixa_etaria.py: aceita tambem o campo
do DENOMINADOR e o N0 de confianca como parametros -- necessario porque
nem todas as proporcoes tem "pessoas" como denominador (ex. proporcao de
agregados domesticos com 1-2 pessoas usa "agregados domesticos" como
denominador, um universo estatistico de escala diferente, com o seu
proprio N0 -- ver config/indice_v.py).

Metodo (identico ao das faixas etarias, generalizado):
    1. Reprojeta a camada para EPSG:3763, calculando:
           proporcao = campo_numerador / campo_denominador
           peso_confianca = MIN(campo_denominador / N0, 1.0)
           valor = proporcao * peso_confianca
       Celulas com campo_denominador=0 sao EXCLUIDAS da camada (nao
       computadas como NULL -- gdal_rasterize nao respeita NULL, trata
       como 0, confirmado por teste deliberado).
    2. Rasteriza para a grelha oficial de 250m (fonte vetorial, sem
       reamostragem raster -- funciona tanto com grelha regular como
       com poligonos irregulares, ex. BGRI).

Uso:
    python3 gerar_proporcao_generica.py <gpkg> <camada> <campo_numerador> <campo_denominador> <n0> <output.tif>

Exemplo (isolamento, BGRI, N0=25):
    python3 gerar_proporcao_generica.py data/BGRI21_CONT/BGRI21_CONT.gpkg \\
        BGRI21_CONT N_ADP_1_OU_2_PESSOAS N_AGREGADOS_DOMESTICOS_PRIVADOS 25 \\
        data/indice_v_sensibilidade_isolamento.tif
"""
import subprocess
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config"))
import grid_spec as gs


def main():
    if len(sys.argv) != 7:
        print("Uso: python3 gerar_proporcao_generica.py <gpkg> <camada> <campo_numerador> "
              "<campo_denominador> <n0> <output.tif>")
        sys.exit(1)

    gpkg_path, camada, campo_numerador, campo_denominador, n0_str, output_path = sys.argv[1:7]
    n0 = float(n0_str)

    gs.assert_grid_consistency()

    reprojetado_path = output_path + ".reprojetado.gpkg"

    print(f"A reprojetar {camada} para {gs.GRID_CRS}, calcular proporcao "
          f"'{campo_numerador}/{campo_denominador}' e peso de confianca (N0={n0}) ...")
    sql = (
        f"SELECT *, "
        f"(CAST({campo_numerador} AS REAL) / CAST({campo_denominador} AS REAL)) "
        f"* MIN(CAST({campo_denominador} AS REAL) / {n0}, 1.0) "
        f"AS valor_ponderado "
        f"FROM {camada} WHERE {campo_denominador} > 0"
    )
    cmd_reproj = [
        "ogr2ogr", "-f", "GPKG",
        "-t_srs", gs.GRID_CRS,
        "-dialect", "SQLite",
        "-sql", sql,
        "-nln", "camada_proporcao",
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
