#!/usr/bin/env python3
"""
Gera o raster final do Indice P (Potencial de Propagacao), combinando as
quatro variaveis reconstruidas na grelha oficial (250m, EPSG:3763):

    Indice P = min(1.0, 0.5*WorldCover + 0.3*NDVI_factor + 0.2*Declive + Bonus_area_ardida)

Formula identica a score.py::get_structural_risk() + get_indice_p() --
so a resolucao/fonte mudou (250m offline, nao lookup pontual em tempo
real), nao a formula em si (decisao registada: mudar uma coisa de cada
vez, nao resolucao e pesos ao mesmo tempo).

Transformacoes aplicadas a cada variavel, confirmadas por inspeccao
directa do codigo de producao antes de implementar (nao assumidas):
    - WorldCover: usado directamente (ja normalizado 0-1 em fire_risk.tif)
    - NDVI: aplicada a MESMA normalizacao de get_ndvi_factor() --
      factor = 1 - clip((ndvi-0.2)/0.4, 0, 1) -- os ficheiros gerados por
      gerar_ndvi_indice_p.py guardam o NDVI em BRUTO (Principio da
      Separacao Analitica), a normalizacao e feita aqui, nao na fonte.
    - Declive: usado directamente (get_slope_factor() nao aplica nenhuma
      transformacao adicional ao slope_norm.tif ja normalizado -- o
      mesmo se aplica ao nosso declive_indice_p_250m.tif, gerado com
      gdaldem slope + clip(graus/45,0,1), identico).
    - Bonus de area ardida: somado directamente, sem transformacao.

Uso:
    python3 gerar_indice_p.py <mascara.tif> <worldcover.tif> <ndvi.tif> <declive.tif> <bonus.tif> <output.tif>
"""
import sys
import os
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config"))
import grid_spec as gs

DTYPE_MAP = {}


def ler_raster_bytes(path):
    from osgeo import gdal
    ds = gdal.Open(path)
    if ds is None:
        raise RuntimeError(f"Nao foi possivel abrir {path}")
    band = ds.GetRasterBand(1)
    ncols, nrows = ds.RasterXSize, ds.RasterYSize
    raw = band.ReadRaster(0, 0, ncols, nrows, buf_type=gdal.GDT_Float32)
    arr = np.frombuffer(raw, dtype=np.float32).reshape(nrows, ncols).astype(float)
    nodata = band.GetNoDataValue()
    return arr, nodata


def escrever_geotiff(array, path):
    from osgeo import gdal, osr
    driver = gdal.GetDriverByName("GTiff")
    ds = driver.Create(path, gs.GRID_NCOLS, gs.GRID_NROWS, 1, gdal.GDT_Float32,
                        options=["COMPRESS=LZW", "TILED=YES"])
    ds.SetGeoTransform(gs.GRID_GEOTRANSFORM)
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(3763)
    ds.SetProjection(srs.ExportToWkt())
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(gs.GRID_NODATA)
    band.WriteRaster(0, 0, gs.GRID_NCOLS, gs.GRID_NROWS,
                      array.astype("float32").tobytes(), buf_type=gdal.GDT_Float32)
    band.FlushCache()
    ds = None


def skewness(x):
    media = np.mean(x)
    desvio = np.std(x)
    if desvio == 0:
        return 0.0
    return float(np.mean(((x - media) / desvio) ** 3))


def normalizar_ndvi_factor(ndvi):
    """Replica exactamente api/ingest/ndvi.py::get_ndvi_factor()."""
    return 1.0 - np.clip((ndvi - 0.2) / 0.4, 0.0, 1.0)


def main():
    if len(sys.argv) != 7:
        print("Uso: python3 gerar_indice_p.py <mascara.tif> <worldcover.tif> <ndvi.tif> "
              "<declive.tif> <bonus.tif> <output.tif>")
        sys.exit(1)

    mascara_path, wc_path, ndvi_path, declive_path, bonus_path, output_path = sys.argv[1:7]
    gs.assert_grid_consistency()

    print(f"A ler mascara de {mascara_path} ...")
    mascara, _ = ler_raster_bytes(mascara_path)
    dentro_pt = mascara == 1
    print(f"Celulas dentro de Portugal Continental: {int(np.sum(dentro_pt))}")

    print(f"A ler WorldCover de {wc_path} ...")
    wc, wc_nodata = ler_raster_bytes(wc_path)

    print(f"A ler NDVI (bruto) de {ndvi_path} ...")
    ndvi_bruto, ndvi_nodata = ler_raster_bytes(ndvi_path)
    print("A aplicar a normalizacao de get_ndvi_factor() (1 - clip((ndvi-0.2)/0.4, 0, 1)) ...")
    ndvi_factor = normalizar_ndvi_factor(ndvi_bruto)

    print(f"A ler Declive de {declive_path} ...")
    declive, declive_nodata = ler_raster_bytes(declive_path)

    print(f"A ler Bonus de area ardida de {bonus_path} ...")
    bonus, bonus_nodata = ler_raster_bytes(bonus_path)

    # Celulas sem dados numa variavel qualquer: tratadas como 0 nessa
    # variavel (nao excluidas do calculo), replicando o comportamento de
    # score.py quando NDVI/declive nao estao disponiveis (usa so as
    # variaveis disponiveis, com pesos redistribuidos) -- simplificacao
    # aqui: assume-se 0 (sem contributo), documentado como limitacao.
    wc_valido = np.where((wc == wc_nodata) if wc_nodata is not None else False, 0.0, wc)
    ndvi_valido = np.where((ndvi_bruto == ndvi_nodata) if ndvi_nodata is not None else False, 0.0, ndvi_factor)
    declive_valido = np.where((declive == declive_nodata) if declive_nodata is not None else False, 0.0, declive)
    bonus_valido = np.where((bonus == bonus_nodata) if bonus_nodata is not None else False, 0.0, bonus)

    print("A combinar: 0.5*WorldCover + 0.3*NDVI_factor + 0.2*Declive + Bonus, limitado a 1.0 ...")
    indice_p = 0.5 * wc_valido + 0.3 * ndvi_valido + 0.2 * declive_valido + bonus_valido
    indice_p = np.clip(indice_p, 0.0, 1.0)

    indice_p_final = np.where(dentro_pt, indice_p, gs.GRID_NODATA)

    print("A validar o raster resultante ...")
    valores_validos = indice_p_final[dentro_pt]
    if np.any(np.isnan(valores_validos)) or np.any(np.isinf(valores_validos)):
        raise ValueError("VALIDACAO FALHOU: encontrados NaN/Inf no resultado.")
    vmin, vmax = valores_validos.min(), valores_validos.max()
    if vmin < -1e-6 or vmax > 1.0 + 1e-6:
        raise ValueError(f"VALIDACAO FALHOU: min={vmin}, max={vmax} fora do intervalo [0,1].")
    print(f"  OK: min={vmin:.6f}, max={vmax:.6f}, sem NaN/Inf.")

    print("=== Estatisticas do raster final (Indice P) ===")
    print(f"  Media: {np.mean(valores_validos):.4f}")
    print(f"  Mediana: {np.median(valores_validos):.4f}")
    print(f"  Desvio-padrao: {np.std(valores_validos):.4f}")
    print(f"  Assimetria: {skewness(valores_validos):.4f}")
    for p in [0, 25, 50, 75, 90, 95, 99, 100]:
        print(f"  p{p}: {np.percentile(valores_validos, p):.4f}")

    print(f"A escrever GeoTIFF em {output_path} ...")
    escrever_geotiff(indice_p_final, output_path)
    print("Concluido.")


if __name__ == "__main__":
    main()
