#!/usr/bin/env python3
"""
Gera o raster final do Indice V (Vulnerabilidade), combinando as tres
componentes do modelo PREFER (Bento-Goncalves et al. 2014):

    V = INDICE_V_WEIGHT_EXPOSURE     * Exposicao
      + INDICE_V_WEIGHT_SENSITIVITY  * Sensibilidade
      + INDICE_V_WEIGHT_RESPONSE     * Deficit_Capacidade_Resposta

Todas as tres componentes ja estao na mesma semantica (valor alto =
maior vulnerabilidade), pelo que a combinacao e simplesmente aditiva.

Principio da Separacao Analitica (saeif_architecture.html Sec16): o
resultado NAO e reescalado para 0-1 -- o maximo real fica abaixo de 1.0
porque as componentes tem dominios diferentes e raramente atingem os
seus maximos individuais na mesma celula. Isto e esperado, nao um erro.

Uso:
    python3 gerar_indice_v.py <mascara.tif> <exposicao.tif> <sensibilidade.tif> <deficit_resposta.tif> <output.tif>
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


def exportar_histograma_texto(valores, path, n_bins=20, escala_max=1.0):
    contagens, bordas = np.histogram(valores, bins=n_bins, range=(0.0, escala_max))
    max_contagem = contagens.max() if contagens.max() > 0 else 1
    largura_barra = 50
    with open(path, "w") as f:
        f.write(f"Histograma do Indice V (Vulnerabilidade) -- 0.0 a {escala_max:.4f}\n")
        f.write("=" * 70 + "\n")
        for i in range(n_bins):
            barra = "#" * int(largura_barra * contagens[i] / max_contagem)
            f.write(f"[{bordas[i]:.3f}-{bordas[i+1]:.3f}] {contagens[i]:>8d} {barra}\n")
    print(f"Histograma exportado para {path}")


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
    if len(sys.argv) != 6:
        print("Uso: python3 gerar_indice_v.py <mascara.tif> <exposicao.tif> <sensibilidade.tif> "
              "<deficit_resposta.tif> <output.tif>")
        sys.exit(1)

    mascara_path, exposicao_path, sensibilidade_path, resposta_path, output_path = sys.argv[1:6]

    gs.assert_grid_consistency()

    print(f"A ler mascara de {mascara_path} ...")
    mascara, _ = ler_raster_completo(mascara_path)
    dentro_pt = mascara == 1
    print(f"Celulas dentro de Portugal Continental: {int(np.sum(dentro_pt))}")

    print(f"A ler Exposicao de {exposicao_path} ...")
    exposicao, _ = ler_raster_completo(exposicao_path)

    print(f"A ler Sensibilidade de {sensibilidade_path} ...")
    sensibilidade, _ = ler_raster_completo(sensibilidade_path)

    print(f"A ler Deficit de Capacidade de Resposta de {resposta_path} ...")
    resposta, _ = ler_raster_completo(resposta_path)

    print(f"A combinar: {cfg.INDICE_V_WEIGHT_EXPOSURE:.4f} x Exposicao + "
          f"{cfg.INDICE_V_WEIGHT_SENSITIVITY:.4f} x Sensibilidade + "
          f"{cfg.INDICE_V_WEIGHT_RESPONSE:.4f} x Deficit_Resposta ...")
    indice_v = (
        cfg.INDICE_V_WEIGHT_EXPOSURE * exposicao
        + cfg.INDICE_V_WEIGHT_SENSITIVITY * sensibilidade
        + cfg.INDICE_V_WEIGHT_RESPONSE * resposta
    )

    indice_v_final = np.where(dentro_pt, indice_v, gs.GRID_NODATA)

    print("A validar o raster resultante ...")
    valores_validos = indice_v_final[dentro_pt]

    if np.any(np.isnan(valores_validos)) or np.any(np.isinf(valores_validos)):
        raise ValueError("VALIDACAO FALHOU: encontrados NaN/Inf no resultado.")

    vmin, vmax = valores_validos.min(), valores_validos.max()
    if vmin < -1e-6 or vmax > 1.0 + 1e-6:
        raise ValueError(f"VALIDACAO FALHOU: min={vmin}, max={vmax} fora do intervalo [0,1] esperado.")
    print(f"  OK: min={vmin:.6f}, max={vmax:.6f}, sem NaN/Inf.")
    print(f"  (Principio da Separacao Analitica: max real pode ficar abaixo de 1.0 -- esperado.)")

    print("=== Estatisticas do raster final (Indice V - Vulnerabilidade) ===")
    print(f"  Media: {np.mean(valores_validos):.4f}")
    print(f"  Mediana: {np.median(valores_validos):.4f}")
    print(f"  Desvio-padrao: {np.std(valores_validos):.4f}")
    print(f"  Assimetria: {skewness(valores_validos):.4f}")
    for p in [0, 25, 50, 75, 90, 95, 99, 100]:
        print(f"  p{p}: {np.percentile(valores_validos, p):.4f}")

    hist_path = output_path.replace(".tif", "_histograma.txt")
    exportar_histograma_texto(valores_validos, hist_path, escala_max=float(vmax))

    print(f"A escrever GeoTIFF em {output_path} ...")
    escrever_geotiff(indice_v_final, output_path)
    print("Concluido.")


if __name__ == "__main__":
    main()
