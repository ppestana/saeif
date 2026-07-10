#!/usr/bin/env python3
"""
Gera o raster de distancia (em metros) ao quartel de bombeiros mais
proximo, a partir do CSV de quarteis do Wikidata, para a grelha oficial
do SAEIF (250m, EPSG:3763). Subdimensao Cobertura Operacional, Capacidade
de Resposta, Indice V.

Metodo:
    1. Le o CSV (formato Wikidata Query Service: coluna 'coord' no formato
       'Point(lon lat)'), deduplica por 'item' (URI unico).
    2. Transforma as coordenadas de EPSG:4326 para EPSG:3763.
    3. Rasteriza os pontos como mascara binaria (0 = celula com quartel,
       1 = resto) na grelha oficial.
    4. Calcula a distancia euclidiana (em metros) de cada celula ao
       quartel mais proximo via scipy.ndimage.distance_transform_edt,
       com sampling=(RESOLUCAO, RESOLUCAO) para obter metros directamente.

Uso:
    python3 gerar_distancia_bombeiros.py <csv_wikidata> <output.tif>
"""
import sys
import os
import re
import csv as csv_module
import numpy as np
from scipy.ndimage import distance_transform_edt
from osgeo import gdal, osr

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config"))
import grid_spec as gs

COORD_RE = re.compile(r"Point\(([-\d.]+)\s+([-\d.]+)\)")


def ler_pontos_csv(path):
    """Le o CSV do Wikidata, deduplica por item, extrai lon/lat."""
    vistos = set()
    pontos = []
    with open(path, encoding="utf-8") as f:
        for linha in csv_module.DictReader(f):
            item = linha["item"]
            if item in vistos:
                continue
            vistos.add(item)
            m = COORD_RE.match(linha["coord"])
            if not m:
                continue
            lon, lat = float(m.group(1)), float(m.group(2))
            pontos.append((lon, lat, linha.get("itemLabel", "")))
    return pontos


def transformar_pontos(pontos):
    """Transforma lon/lat (EPSG:4326) para x/y (EPSG:3763)."""
    source_srs = osr.SpatialReference()
    source_srs.ImportFromEPSG(4326)
    source_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(3763)
    target_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    transform = osr.CoordinateTransformation(source_srs, target_srs)

    resultado = []
    for lon, lat, nome in pontos:
        x, y, _ = transform.TransformPoint(lon, lat)
        resultado.append((x, y, nome))
    return resultado


def escrever_geotiff(array, path):
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(
        path, gs.GRID_NCOLS, gs.GRID_NROWS, 1, gdal.GDT_Float32,
        options=["COMPRESS=LZW", "TILED=YES"],
    )
    ds.SetGeoTransform(gs.GRID_GEOTRANSFORM)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3763)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    array_f32 = array.astype(np.float32)
    band.WriteRaster(0, 0, gs.GRID_NCOLS, gs.GRID_NROWS, array_f32.tobytes(), buf_type=gdal.GDT_Float32)
    band.FlushCache()
    ds = None


def main():
    if len(sys.argv) != 3:
        print("Uso: python3 gerar_distancia_bombeiros.py <csv_wikidata> <output.tif>")
        sys.exit(1)

    csv_path, output_path = sys.argv[1:3]

    gs.assert_grid_consistency()

    print(f"A ler {csv_path} ...")
    pontos_4326 = ler_pontos_csv(csv_path)
    print(f"{len(pontos_4326)} quarteis unicos lidos.")

    print("A transformar para EPSG:3763 ...")
    pontos_3763 = transformar_pontos(pontos_4326)

    print("A rasterizar mascara binaria de quarteis (0=quartel, 1=resto) ...")
    mascara = np.ones((gs.GRID_NROWS, gs.GRID_NCOLS), dtype=np.uint8)
    n_dentro_grelha = 0
    for x, y, nome in pontos_3763:
        col = int((x - gs.GRID_XMIN) / gs.GRID_RESOLUTION)
        row = int((gs.GRID_YMAX - y) / gs.GRID_RESOLUTION)
        if 0 <= col < gs.GRID_NCOLS and 0 <= row < gs.GRID_NROWS:
            mascara[row, col] = 0
            n_dentro_grelha += 1
    print(f"{n_dentro_grelha} quarteis dentro da grelha oficial.")

    print("A calcular distancia euclidiana (metros) via distance_transform_edt ...")
    distancia = distance_transform_edt(
        mascara, sampling=(gs.GRID_RESOLUTION, gs.GRID_RESOLUTION)
    )

    print(f"Distancia min/max/media: {distancia.min():.1f}m / {distancia.max():.1f}m / {distancia.mean():.1f}m")

    print(f"A escrever GeoTIFF em {output_path} ...")
    escrever_geotiff(distancia, output_path)
    print("Concluido.")


if __name__ == "__main__":
    main()
