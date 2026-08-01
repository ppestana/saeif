#!/usr/bin/env python3
"""
Gera a superficie continua do Indice I (Suscetibilidade de Ignicao) via KDE,
a partir dos centroides de ignicao extraidos de areas_ardidas.

Uso:
    python3 gerar_kde_ignicao.py <geojson_pontos> <bandwidth_m> <output_tif>

Metodo:
    1. Le pontos (EPSG:4326) do GeoJSON, reprojeta para EPSG:3763 (osgeo.osr).
    2. Constroi histograma 2D dos pontos na grelha oficial do SAEIF (config/grid_spec.py).
    3. Aplica filtro gaussiano (scipy.ndimage.gaussian_filter), sigma = bandwidth / GRID_RESOLUTION,
       equivalente matematicamente a uma convolucao com kernel gaussiano na grelha
       (mesmo resultado de um KDE gaussiano, muito mais rapido que somar 4747 gaussianas
       por celula).
    4. Escreve GeoTIFF georreferenciado (osgeo.gdal), CRS e geotransform da grelha oficial.

Nota: a soma total do raster apos o filtro gaussiano preserva a soma do histograma
original (a menos de perda residual nos bordos, mode="constant"). Isto e esperado
e serve como verificacao de sanidade (ver print no fim).
"""

import sys
import os
import numpy as np
from scipy.ndimage import gaussian_filter
import warnings
from osgeo import ogr, osr, gdal

# Silencia o FutureWarning inofensivo sobre ogr.UseExceptions() (GDAL 4.0).
# Nao chamamos UseExceptions()/DontUseExceptions() porque, neste ambiente,
# isso forca a importacao do modulo gdal_array (ponte com numpy), que colide
# com a versao do numpy instalada no venv (ver escrever_geotiff, que evita
# essa ponte deliberadamente via WriteRaster).
warnings.filterwarnings("ignore", category=FutureWarning, module="osgeo")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config"))
import grid_spec as gs


def ler_pontos_geojson(path):
    """Le pontos de um GeoJSON e reprojeta para EPSG:3763 (CRS da grelha oficial)."""
    ds = ogr.Open(path)
    if ds is None:
        raise RuntimeError(f"Nao foi possivel abrir {path}")
    layer = ds.GetLayer()
    layer_srs = layer.GetSpatialRef()

    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(3763)
    target_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    if layer_srs is None:
        # GeoJSON sem CRS explicito -> convencao GeoJSON e WGS84 (EPSG:4326)
        source_srs = osr.SpatialReference()
        source_srs.ImportFromEPSG(4326)
    else:
        source_srs = layer_srs
    source_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    transform = osr.CoordinateTransformation(source_srs, target_srs)

    xs, ys = [], []
    for feature in layer:
        geom = feature.GetGeometryRef()
        geom_clone = geom.Clone()
        geom_clone.Transform(transform)
        xs.append(geom_clone.GetX())
        ys.append(geom_clone.GetY())

    return np.array(xs), np.array(ys)


def construir_histograma(xs, ys):
    """Conta pontos por celula da grelha oficial (250m, EPSG:3763)."""
    ncols = gs.GRID_NCOLS
    nrows = gs.GRID_NROWS
    res = gs.GRID_RESOLUTION

    col = np.floor((xs - gs.GRID_XMIN) / res).astype(int)
    row = np.floor((gs.GRID_YMAX - ys) / res).astype(int)  # linha 0 = topo (upper-left)

    dentro = (col >= 0) & (col < ncols) & (row >= 0) & (row < nrows)
    n_fora = int(np.sum(~dentro))
    if n_fora > 0:
        print(f"AVISO: {n_fora} pontos fora da grelha oficial, ignorados.")

    hist = np.zeros((nrows, ncols), dtype=np.float64)
    np.add.at(hist, (row[dentro], col[dentro]), 1.0)
    return hist


def escrever_geotiff(array, path):
    """Escreve o raster resultante como GeoTIFF, com o CRS/geotransform da grelha oficial."""
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(
        path,
        gs.GRID_NCOLS,
        gs.GRID_NROWS,
        1,
        gdal.GDT_Float32,
        options=["COMPRESS=LZW", "TILED=YES"],
    )
    ds.SetGeoTransform(gs.GRID_GEOTRANSFORM)

    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3763)
    ds.SetProjection(srs.ExportToWkt())

    band = ds.GetRasterBand(1)
    band.SetNoDataValue(gs.GRID_NODATA)
    # WriteRaster (bytes brutos) em vez de WriteArray: evita depender do modulo
    # gdal_array, que e sensivel a incompatibilidades de ABI entre a versao do
    # numpy do sistema (usada para compilar os bindings gdal) e a versao do
    # numpy instalada no venv (mais recente, por causa do scipy).
    array_f32 = array.astype(np.float32)
    band.WriteRaster(
        0, 0, gs.GRID_NCOLS, gs.GRID_NROWS,
        array_f32.tobytes(),
        buf_type=gdal.GDT_Float32,
    )
    band.FlushCache()
    ds = None


def main():
    if len(sys.argv) != 4:
        print("Uso: python3 gerar_kde_ignicao.py <geojson_pontos> <bandwidth_m> <output_tif>")
        sys.exit(1)

    geojson_path = sys.argv[1]
    bandwidth_m = float(sys.argv[2])
    output_path = sys.argv[3]

    gs.assert_grid_consistency()

    print(f"A ler pontos de {geojson_path} ...")
    xs, ys = ler_pontos_geojson(geojson_path)
    print(f"{len(xs)} pontos lidos e reprojetados para EPSG:3763.")

    print("A construir histograma na grelha oficial (250 m) ...")
    hist = construir_histograma(xs, ys)
    print(f"Total de pontos dentro da grelha: {hist.sum():.0f}")

    sigma_celulas = bandwidth_m / gs.GRID_RESOLUTION
    print(f"A aplicar filtro gaussiano: bandwidth={bandwidth_m}m -> sigma={sigma_celulas:.2f} celulas ...")
    kde = gaussian_filter(hist, sigma=sigma_celulas, mode="constant", cval=0.0)

    print(f"Soma preservada apos filtro: {kde.sum():.2f} (deve ser proxima de {hist.sum():.0f})")
    print(f"Valor maximo na superficie: {kde.max():.4f}")

    print(f"A escrever GeoTIFF em {output_path} ...")
    escrever_geotiff(kde, output_path)
    print("Concluido.")


if __name__ == "__main__":
    main()
