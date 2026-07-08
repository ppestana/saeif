#!/usr/bin/env python3
"""
Calcula estatisticas descritivas (percentis, media, mediana, desvio-padrao,
assimetria) de uma variavel raster, restritas as celulas dentro da mascara
de Portugal Continental -- incluindo celulas de valor zero (uma celula sem
populacao/edificado faz parte da distribuicao real do fenomeno), excluindo
apenas mar/Espanha (fora da mascara) e NoData genuino da variavel.

Uso:
    python3 percentis_exposicao_mascarados.py <mascara.tif> <variavel1.tif> [variavel2.tif ...]
"""
import sys
import numpy as np
from osgeo import gdal


def ler_raster_completo(path):
    ds = gdal.Open(path)
    if ds is None:
        raise RuntimeError(f"Nao foi possivel abrir {path}")
    band = ds.GetRasterBand(1)
    ncols, nrows = ds.RasterXSize, ds.RasterYSize
    dtype = band.DataType
    raw = band.ReadRaster(0, 0, ncols, nrows, buf_type=dtype)

    dtype_map = {
        gdal.GDT_Byte: np.uint8, gdal.GDT_UInt16: np.uint16,
        gdal.GDT_Int16: np.int16, gdal.GDT_UInt32: np.uint32,
        gdal.GDT_Int32: np.int32, gdal.GDT_Float32: np.float32,
        gdal.GDT_Float64: np.float64,
    }
    np_dtype = dtype_map.get(dtype, np.float32)
    arr = np.frombuffer(raw, dtype=np_dtype).reshape(nrows, ncols)
    nodata = band.GetNoDataValue()
    return arr, nodata


def skewness(x):
    """Coeficiente de assimetria (Fisher-Pearson, sem correcao de vies)."""
    media = np.mean(x)
    desvio = np.std(x)
    if desvio == 0:
        return 0.0
    return float(np.mean(((x - media) / desvio) ** 3))


def main():
    if len(sys.argv) < 3:
        print("Uso: python3 percentis_exposicao_mascarados.py <mascara.tif> <variavel1.tif> [variavel2.tif ...]")
        sys.exit(1)

    mascara_path = sys.argv[1]
    variaveis = sys.argv[2:]

    print(f"A ler mascara de {mascara_path} ...")
    mascara, mascara_nodata = ler_raster_completo(mascara_path)
    dentro_pt = mascara == 1
    n_celulas_pt = int(np.sum(dentro_pt))
    print(f"Celulas dentro de Portugal Continental: {n_celulas_pt}")
    print()

    percentis = [0, 1, 25, 50, 75, 90, 95, 99, 99.5, 99.9, 100]

    for var_path in variaveis:
        print(f"=== {var_path} ===")
        arr, nodata = ler_raster_completo(var_path)

        if arr.shape != mascara.shape:
            print(f"  AVISO: dimensoes nao coincidem com a mascara ({arr.shape} vs {mascara.shape}), a saltar.")
            continue

        valido = dentro_pt & (arr != nodata if nodata is not None else np.ones_like(arr, dtype=bool))
        valores = arr[valido].astype(np.float64)

        n_zero = int(np.sum(valores == 0))
        n_total = len(valores)
        print(f"  N celulas validas (dentro de PT, excluindo NoData): {n_total}")
        print(f"  Das quais com valor exactamente 0: {n_zero} ({100*n_zero/n_total:.1f}%)")
        print(f"  Media: {np.mean(valores):.4f}")
        print(f"  Mediana: {np.median(valores):.4f}")
        print(f"  Desvio-padrao: {np.std(valores):.4f}")
        print(f"  Assimetria (skewness): {skewness(valores):.4f}")
        print(f"  Soma total: {np.sum(valores):.2f}")
        print("  Percentis:")
        for p in percentis:
            print(f"    p{p}: {np.percentile(valores, p):.4f}")
        print()


if __name__ == "__main__":
    main()
