#!/usr/bin/env python3
"""
Calcula a correlacao (Pearson e Spearman) entre duas variaveis raster,
restrita as celulas dentro da mascara de Portugal Continental.

Motivacao: verificar se os pesos 0.5/0.5 da Exposicao (populacao +
edificado) estao a introduzir redundancia -- se as duas variaveis forem
altamente correlacionadas (ex. >0.9), estao a representar quase a mesma
informacao, o que poderia justificar rever os pesos ou reduzir a
dimensionalidade (sugestao de consultoria SIG externa, saeif_architecture.html).

Pearson mede correlacao LINEAR; Spearman mede correlacao MONOTONA (mais
robusta a relacoes nao-lineares e a outliers, mais apropriada para
variaveis com distribuicao muito assimetrica como populacao/edificado).

Uso:
    python3 analisar_correlacao.py <mascara.tif> <variavel1.tif> <variavel2.tif>
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


def pearson(x, y):
    return float(np.corrcoef(x, y)[0, 1])


def spearman(x, y):
    """Correlacao de Spearman = Pearson sobre os postos (ranks) dos dados."""
    rank_x = np.argsort(np.argsort(x))
    rank_y = np.argsort(np.argsort(y))
    return pearson(rank_x.astype(np.float64), rank_y.astype(np.float64))


def main():
    if len(sys.argv) != 4:
        print("Uso: python3 analisar_correlacao.py <mascara.tif> <variavel1.tif> <variavel2.tif>")
        sys.exit(1)

    mascara_path, var1_path, var2_path = sys.argv[1:4]

    print(f"A ler mascara de {mascara_path} ...")
    mascara, _ = ler_raster_completo(mascara_path)
    dentro_pt = mascara == 1

    print(f"A ler {var1_path} ...")
    var1, nodata1 = ler_raster_completo(var1_path)
    print(f"A ler {var2_path} ...")
    var2, nodata2 = ler_raster_completo(var2_path)

    valido = dentro_pt.copy()
    if nodata1 is not None:
        valido &= (var1 != nodata1)
    if nodata2 is not None:
        valido &= (var2 != nodata2)

    x = var1[valido].astype(np.float64)
    y = var2[valido].astype(np.float64)
    print(f"\nCelulas validas para a analise: {len(x)}")

    r_pearson = pearson(x, y)
    r_spearman = spearman(x, y)

    print(f"\n=== Correlacao entre {var1_path} e {var2_path} ===")
    print(f"Pearson (linear):        r = {r_pearson:.4f}  (r^2 = {r_pearson**2:.4f})")
    print(f"Spearman (monotona):     rho = {r_spearman:.4f}")

    print("\n=== Interpretacao ===")
    for nome, r in [("Pearson", r_pearson), ("Spearman", r_spearman)]:
        abs_r = abs(r)
        if abs_r >= 0.9:
            nivel = "MUITO ALTA -- forte indicio de redundancia"
        elif abs_r >= 0.7:
            nivel = "alta -- alguma sobreposicao de informacao"
        elif abs_r >= 0.4:
            nivel = "moderada -- as variaveis trazem informacao distinta, com alguma sobreposicao"
        else:
            nivel = "baixa -- as variaveis sao largamente independentes"
        print(f"  {nome}: {nivel}")


if __name__ == "__main__":
    main()
