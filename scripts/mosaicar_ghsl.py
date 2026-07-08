#!/usr/bin/env python3
"""
Mosaico e reprojecao dos tiles GHSL (GHS-POP / GHS-BUILT-S) para a grelha
oficial do SAEIF (250m, EPSG:3763 -- ver config/grid_spec.py).

Os tiles GHSL vem em Mollweide (ESRI:54009), 100m de resolucao, em ficheiros
separados por tile (ex. R4_C18, R5_C18). Este script:
    1. Constroi um mosaico VRT a partir de 2+ tiles contiguos.
    2. Reprojeta e reamostra para a grelha oficial (gdalwarp, metodo 'sum').

O metodo de reamostragem 'sum' (nao 'average'/'bilinear') e essencial aqui:
ao AGREGAR celulas de 100m para 250m (6.25x mais area por celula), queremos
que o total (populacao, m2 de area edificada) se mantenha -- nao a media.
gdalwarp com -r sum soma os valores de origem que caem dentro de cada celula
de destino, preservando o total.

Uso:
    python3 mosaicar_ghsl.py <tile1.tif> <tile2.tif> [...] <output.tif>
"""
import subprocess
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config"))
import grid_spec as gs


def main():
    if len(sys.argv) < 3:
        print("Uso: python3 mosaicar_ghsl.py <tile1.tif> <tile2.tif> [...] <output.tif>")
        sys.exit(1)

    tiles_entrada = sys.argv[1:-1]
    output_path = sys.argv[-1]

    gs.assert_grid_consistency()

    vrt_path = output_path + ".mosaico.vrt"

    print(f"A construir mosaico VRT de {len(tiles_entrada)} tile(s) ...")
    cmd_vrt = ["gdalbuildvrt", vrt_path] + tiles_entrada
    resultado = subprocess.run(cmd_vrt, capture_output=True, text=True)
    if resultado.returncode != 0:
        print(f"ERRO no gdalbuildvrt:\n{resultado.stderr}")
        sys.exit(1)
    print(resultado.stdout)

    print(f"A reprojetar para a grelha oficial do SAEIF "
          f"({gs.GRID_CRS}, {gs.GRID_RESOLUTION}m, sum) ...")
    cmd_warp = [
        "gdalwarp",
        "-t_srs", gs.GRID_CRS,
        "-te", str(gs.GRID_XMIN), str(gs.GRID_YMIN), str(gs.GRID_XMAX), str(gs.GRID_YMAX),
        "-tr", str(gs.GRID_RESOLUTION), str(gs.GRID_RESOLUTION),
        "-r", "sum",
        "-dstnodata", str(gs.GRID_NODATA),
        "-co", "COMPRESS=LZW",
        "-co", "TILED=YES",
        "-overwrite",
        vrt_path, output_path,
    ]
    resultado = subprocess.run(cmd_warp, capture_output=True, text=True)
    if resultado.returncode != 0:
        print(f"ERRO no gdalwarp:\n{resultado.stderr}")
        sys.exit(1)
    print(resultado.stdout)

    os.remove(vrt_path)
    print(f"Concluido: {output_path}")


if __name__ == "__main__":
    main()
