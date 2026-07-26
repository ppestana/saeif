#!/usr/bin/env python3
"""
Gera a componente ESTRUTURAL do Indice P (Potencial de Propagacao):

    P_estrutural = 0.5*WorldCover + 0.3*NDVI_factor + 0.2*Declive

Decisao arquitectural (26 Jul 2026, consultoria externa): decompor o
Indice P em duas subdimensoes semanticamente distintas -- estrutural
(propriedades fisicas do territorio: combustivel, vegetacao, relevo) e
historico (memoria de incendios recentes, ver
gerar_indice_p_historico.py / bonus_area_ardida_250m.tif) -- em vez de
uma soma monolitica sem distincao conceptual. Mesmo padrao ja usado no
Indice V (Exposicao/Sensibilidade/Resposta) e na propria Sensibilidade
(Demografica/Social).

Motivacao empirica: analise de contribuicoes reais revelou que o bonus
de area ardida contribui ~29% do Indice P observado, mais do que o
NDVI (24%) e 11x mais que o declive (2.5%) -- apesar de nao ter peso
formal na formula original. A decomposicao torna isto explicito e
visualizavel separadamente, sem alterar o resultado numerico final
(P_final = P_estrutural + P_historico, identico a soma anterior).

Uso:
    python3 gerar_indice_p_estrutural.py <mascara.tif> <worldcover.tif> <ndvi.tif> <declive.tif> <output.tif>
"""
import sys
import os
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config"))
import grid_spec as gs


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
    if len(sys.argv) != 6:
        print("Uso: python3 gerar_indice_p_estrutural.py <mascara.tif> <worldcover.tif> "
              "<ndvi.tif> <declive.tif> <output.tif>")
        sys.exit(1)

    mascara_path, wc_path, ndvi_path, declive_path, output_path = sys.argv[1:6]
    gs.assert_grid_consistency()

    print(f"A ler mascara de {mascara_path} ...")
    mascara, _ = ler_raster_bytes(mascara_path)
    dentro_pt = mascara == 1
    print(f"Celulas dentro de Portugal Continental: {int(np.sum(dentro_pt))}")

    print(f"A ler WorldCover de {wc_path} ...")
    wc, wc_nodata = ler_raster_bytes(wc_path)

    print(f"A ler NDVI (bruto) de {ndvi_path} ...")
    ndvi_bruto, ndvi_nodata = ler_raster_bytes(ndvi_path)
    ndvi_factor = normalizar_ndvi_factor(ndvi_bruto)

    print(f"A ler Declive de {declive_path} ...")
    declive, declive_nodata = ler_raster_bytes(declive_path)

    wc_valido = np.where((wc == wc_nodata) if wc_nodata is not None else False, 0.0, wc)
    ndvi_valido = np.where((ndvi_bruto == ndvi_nodata) if ndvi_nodata is not None else False, 0.0, ndvi_factor)
    declive_valido = np.where((declive == declive_nodata) if declive_nodata is not None else False, 0.0, declive)

    print("A combinar: 0.5*WorldCover + 0.3*NDVI_factor + 0.2*Declive (SEM bonus historico) ...")
    p_estrutural = 0.5 * wc_valido + 0.3 * ndvi_valido + 0.2 * declive_valido
    p_estrutural = np.clip(p_estrutural, 0.0, 1.0)

    p_estrutural_final = np.where(dentro_pt, p_estrutural, gs.GRID_NODATA)

    print("A validar o raster resultante ...")
    valores_validos = p_estrutural_final[dentro_pt]
    if np.any(np.isnan(valores_validos)) or np.any(np.isinf(valores_validos)):
        raise ValueError("VALIDACAO FALHOU: encontrados NaN/Inf no resultado.")
    vmin, vmax = valores_validos.min(), valores_validos.max()
    if vmin < -1e-6 or vmax > 1.0 + 1e-6:
        raise ValueError(f"VALIDACAO FALHOU: min={vmin}, max={vmax} fora do intervalo [0,1].")
    print(f"  OK: min={vmin:.6f}, max={vmax:.6f}, sem NaN/Inf.")

    print("=== Estatisticas do raster final (P_estrutural) ===")
    print(f"  Media: {np.mean(valores_validos):.4f}")
    print(f"  Mediana: {np.median(valores_validos):.4f}")
    print(f"  Desvio-padrao: {np.std(valores_validos):.4f}")
    print(f"  Assimetria: {skewness(valores_validos):.4f}")
    for p in [0, 25, 50, 75, 90, 95, 99, 100]:
        print(f"  p{p}: {np.percentile(valores_validos, p):.4f}")

    print(f"A escrever GeoTIFF em {output_path} ...")
    escrever_geotiff(p_estrutural_final, output_path)
    print("Concluido.")


if __name__ == "__main__":
    main()
