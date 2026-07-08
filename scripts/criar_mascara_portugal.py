#!/usr/bin/env python3
"""
Rasteriza a fronteira de Portugal Continental (CAOP2025) para a grelha
oficial do SAEIF (250m, EPSG:3763), criando uma mascara binaria:
    1 = dentro de Portugal Continental
    0 = fora (mar, Espanha, ou qualquer area fora da fronteira oficial)

Esta mascara e usada para calcular estatisticas/percentis apenas sobre o
territorio real, evitando que a metade iberica vazia da grelha (Espanha,
oceano) distorca calculos como percentis de normalizacao.

Uso:
    python3 criar_mascara_portugal.py <fronteira.gpkg> <output_mask.tif>
"""
import subprocess
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config"))
import grid_spec as gs


def main():
    if len(sys.argv) != 3:
        print("Uso: python3 criar_mascara_portugal.py <fronteira.gpkg> <output_mask.tif>")
        sys.exit(1)

    fronteira_path = sys.argv[1]
    output_path = sys.argv[2]

    gs.assert_grid_consistency()

    cmd = [
        "gdal_rasterize",
        "-burn", "1",
        "-a_nodata", "0",
        "-init", "0",
        "-ot", "Byte",
        "-te", str(gs.GRID_XMIN), str(gs.GRID_YMIN), str(gs.GRID_XMAX), str(gs.GRID_YMAX),
        "-tr", str(gs.GRID_RESOLUTION), str(gs.GRID_RESOLUTION),
        "-co", "COMPRESS=LZW",
        "-co", "TILED=YES",
        fronteira_path, output_path,
    ]
    print(f"A rasterizar {fronteira_path} para a grelha oficial ({gs.GRID_NCOLS}x{gs.GRID_NROWS}) ...")
    resultado = subprocess.run(cmd, capture_output=True, text=True)
    if resultado.returncode != 0:
        print(f"ERRO no gdal_rasterize (codigo {resultado.returncode}):")
        print(f"stdout: {resultado.stdout}")
        print(f"stderr: {resultado.stderr}")
        sys.exit(1)
    print(resultado.stdout)
    print(f"Concluido: {output_path}")


if __name__ == "__main__":
    main()
