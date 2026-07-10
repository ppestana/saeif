#!/usr/bin/env python3
"""
Gera o raster de Deficit de Cobertura Operacional (subdimensao da
Capacidade de Resposta, Indice V), a partir da distancia ao quartel de
bombeiros mais proximo (scripts/gerar_distancia_bombeiros.py).

Metodo (decisao de 10 Jul 2026, ver saeif_architecture.html e
config/indice_v.py):
    deficit = min(distancia_km / RESPONSE_MAX_DISTANCE_KM, 1.0)

Normalizacao linear (nao percentil): a distancia e uma variavel fisica
continua sem outliers de amostragem -- 2km e objectivamente melhor que
10km, sem ambiguidade estatistica a resolver. RESPONSE_MAX_DISTANCE_KM e
um parametro FIXO e configuravel (nao o maximo observado em cada
execucao), para o indice nao "flutuar" sempre que a base de dados de
quarteis for actualizada.

Uso:
    python3 gerar_deficit_bombeiros.py <mascara.tif> <distancia.tif> <output.tif>
"""
import sys
import os
import numpy as np
from osgeo import gdal, osr

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config"))
import grid_spec as gs
import indice_v as cfg

DTYPE_MAP = {
    gdal.GDT_Byte: np.uint8, gdal.GDT_UInt16: np.uint16,
    gdal.GDT_Int16: np.int16, gdal.GDT_UInt32: np.uint32,
    gdal.GDT_Int32: np.int32, gdal.GDT_Float32: np.float32,
    gdal.GDT_Float64: np.float64,
}


def ler_raster_completo(path):
    ds = gdal.Open(path)
    if ds is None:
        raise RuntimeError(f"Nao foi possivel abrir {path}")
    band = ds.GetRasterBand(1)
    ncols, nrows = ds.RasterXSize, ds.RasterYSize
    dtype = band.DataType
    raw = band.ReadRaster(0, 0, ncols, nrows, buf_type=dtype)
    np_dtype = DTYPE_MAP.get(dtype, np.float32)
    arr = np.frombuffer(raw, dtype=np_dtype).reshape(nrows, ncols)
    nodata = band.GetNoDataValue()
    return arr, nodata


def skewness(x):
    media = np.mean(x)
    desvio = np.std(x)
    if desvio == 0:
        return 0.0
    return float(np.mean(((x - media) / desvio) ** 3))


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
    band.SetNoDataValue(gs.GRID_NODATA)
    array_f32 = array.astype(np.float32)
    band.WriteRaster(0, 0, gs.GRID_NCOLS, gs.GRID_NROWS, array_f32.tobytes(), buf_type=gdal.GDT_Float32)
    band.FlushCache()
    ds = None


def main():
    if len(sys.argv) != 4:
        print("Uso: python3 gerar_deficit_bombeiros.py <mascara.tif> <distancia.tif> <output.tif>")
        sys.exit(1)

    mascara_path, distancia_path, output_path = sys.argv[1:4]

    gs.assert_grid_consistency()

    print(f"A ler mascara de {mascara_path} ...")
    mascara, _ = ler_raster_completo(mascara_path)
    dentro_pt = mascara == 1
    print(f"Celulas dentro de Portugal Continental: {int(np.sum(dentro_pt))}")

    print(f"A ler distancia de {distancia_path} ...")
    distancia_m, _ = ler_raster_completo(distancia_path)
    distancia_km = distancia_m / 1000.0

    print(f"A normalizar (linear, RESPONSE_MAX_DISTANCE_KM={cfg.RESPONSE_MAX_DISTANCE_KM}) ...")
    deficit = np.clip(distancia_km / cfg.RESPONSE_MAX_DISTANCE_KM, 0.0, 1.0)

    n_saturado = int(np.sum((deficit >= 1.0) & dentro_pt))
    if n_saturado > 0:
        print(f"  AVISO: {n_saturado} celulas com distancia >= {cfg.RESPONSE_MAX_DISTANCE_KM}km "
              f"(saturadas em deficit=1.0).")

    deficit_final = np.where(dentro_pt, deficit, gs.GRID_NODATA)

    print("A validar o raster resultante ...")
    valores_validos = deficit_final[dentro_pt]

    if np.any(np.isnan(valores_validos)) or np.any(np.isinf(valores_validos)):
        raise ValueError("VALIDACAO FALHOU: encontrados NaN/Inf no resultado.")

    vmin, vmax = valores_validos.min(), valores_validos.max()
    if vmin < -1e-6 or vmax > 1.0 + 1e-6:
        raise ValueError(f"VALIDACAO FALHOU: min={vmin}, max={vmax} fora do intervalo [0,1].")
    print(f"  OK: min={vmin:.6f}, max={vmax:.6f}, sem NaN/Inf.")

    print("=== Estatisticas do raster final (Deficit de Cobertura Operacional) ===")
    print(f"  Media: {np.mean(valores_validos):.4f}")
    print(f"  Mediana: {np.median(valores_validos):.4f}")
    print(f"  Desvio-padrao: {np.std(valores_validos):.4f}")
    print(f"  Assimetria: {skewness(valores_validos):.4f}")
    for p in [0, 25, 50, 75, 90, 95, 99, 100]:
        print(f"  p{p}: {np.percentile(valores_validos, p):.4f}")

    print(f"A escrever GeoTIFF em {output_path} ...")
    escrever_geotiff(deficit_final, output_path)
    print("Concluido.")


if __name__ == "__main__":
    main()
