#!/usr/bin/env python3
"""
Gera o raster oficial da componente Exposicao do Indice V (Vulnerabilidade).

Pipeline:
    Populacao  -> normalizacao (percentil, dentro da mascara PT) -> Pop_norm
    Edificado  -> normalizacao (percentil, dentro da mascara PT) -> Built_norm
    Exposicao  = EXPOSURE_WEIGHT_POPULATION * Pop_norm + EXPOSURE_WEIGHT_BUILT_AREA * Built_norm

Fora da mascara de Portugal Continental, o resultado fica NoData -- o
Indice V so faz sentido dentro do dominio real do modelo.

Validacao automatica antes de gravar: minimo >= 0, maximo <= 1 (com
tolerancia numerica), sem NaN/Inf. Se VALIDATION_EXPORT_STATISTICS,
imprime percentis/media/skewness do resultado final.

Uso:
    python3 gerar_indice_v_exposicao.py <mascara.tif> <pop.tif> <built.tif> <output.tif>
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


def normalizar_percentil(valores, dentro_mask, percentil_superior, limite_inferior):
    """
    Normaliza valores para 0-1 por saturacao no percentil superior (calculado
    so dentro da mascara), com limite inferior fixo. Valores acima do
    percentil saturam em 1.0.
    """
    p_sup = np.percentile(valores[dentro_mask], percentil_superior)
    if p_sup <= limite_inferior:
        raise ValueError(
            f"Percentil superior ({p_sup}) <= limite inferior ({limite_inferior}) -- "
            "normalizacao invalida, verificar os dados de entrada."
        )
    norm = (valores - limite_inferior) / (p_sup - limite_inferior)
    norm = np.clip(norm, 0.0, 1.0)
    return norm, p_sup


def exportar_histograma_texto(valores, path, n_bins=20):
    """Histograma ASCII simples, sem dependencias externas (sem matplotlib)."""
    contagens, bordas = np.histogram(valores, bins=n_bins, range=(0.0, 1.0))
    max_contagem = contagens.max() if contagens.max() > 0 else 1
    largura_barra = 50
    with open(path, "w") as f:
        f.write("Histograma da Exposicao (Indice V) -- 0.0 a 1.0\n")
        f.write("=" * 70 + "\n")
        for i in range(n_bins):
            barra = "#" * int(largura_barra * contagens[i] / max_contagem)
            f.write(f"[{bordas[i]:.2f}-{bordas[i+1]:.2f}] {contagens[i]:>8d} {barra}\n")
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
    if len(sys.argv) != 5:
        print("Uso: python3 gerar_indice_v_exposicao.py <mascara.tif> <pop.tif> <built.tif> <output.tif>")
        sys.exit(1)

    mascara_path, pop_path, built_path, output_path = sys.argv[1:5]

    gs.assert_grid_consistency()

    if cfg.EXPOSURE_NORMALIZATION != "percentile":
        raise NotImplementedError(
            f"Metodo de normalizacao '{cfg.EXPOSURE_NORMALIZATION}' ainda nao implementado "
            "(so 'percentile' disponivel nesta versao)."
        )

    print(f"A ler mascara de {mascara_path} ...")
    mascara, _ = ler_raster_completo(mascara_path)
    dentro_pt = mascara == 1
    print(f"Celulas dentro de Portugal Continental: {int(np.sum(dentro_pt))}")

    print(f"A ler populacao de {pop_path} ...")
    pop, pop_nodata = ler_raster_completo(pop_path)
    pop_valido = dentro_pt & (pop != pop_nodata if pop_nodata is not None else dentro_pt)

    print(f"A ler edificado de {built_path} ...")
    built, built_nodata = ler_raster_completo(built_path)
    built_valido = dentro_pt & (built != built_nodata if built_nodata is not None else dentro_pt)

    print(f"A normalizar populacao (percentil {cfg.EXPOSURE_PERCENTILE}) ...")
    pop_norm, pop_p_sup = normalizar_percentil(
        pop, pop_valido, cfg.EXPOSURE_PERCENTILE, cfg.EXPOSURE_LOWER_BOUND
    )
    print(f"  p{cfg.EXPOSURE_PERCENTILE}: {pop_p_sup:.4f}")

    print(f"A normalizar edificado (percentil {cfg.EXPOSURE_PERCENTILE}) ...")
    built_norm, built_p_sup = normalizar_percentil(
        built, built_valido, cfg.EXPOSURE_PERCENTILE, cfg.EXPOSURE_LOWER_BOUND
    )
    print(f"  p{cfg.EXPOSURE_PERCENTILE}: {built_p_sup:.4f}")

    print(f"A combinar: {cfg.EXPOSURE_WEIGHT_POPULATION} x Pop_norm + "
          f"{cfg.EXPOSURE_WEIGHT_BUILT_AREA} x Built_norm ...")
    exposicao = (
        cfg.EXPOSURE_WEIGHT_POPULATION * pop_norm
        + cfg.EXPOSURE_WEIGHT_BUILT_AREA * built_norm
    )

    # Fora da mascara de Portugal, o Indice V nao tem significado -- NoData
    exposicao_final = np.where(dentro_pt, exposicao, gs.GRID_NODATA)

    # --- Validacao automatica ---
    print("A validar o raster resultante ...")
    valores_validos = exposicao_final[dentro_pt]

    if np.any(np.isnan(valores_validos)) or np.any(np.isinf(valores_validos)):
        raise ValueError("VALIDACAO FALHOU: encontrados NaN/Inf no resultado.")

    vmin, vmax = valores_validos.min(), valores_validos.max()
    if vmin < cfg.VALIDATION_MIN_TOLERANCE:
        raise ValueError(f"VALIDACAO FALHOU: minimo {vmin} abaixo da tolerancia "
                          f"({cfg.VALIDATION_MIN_TOLERANCE}).")
    if vmax > cfg.VALIDATION_MAX_TOLERANCE:
        raise ValueError(f"VALIDACAO FALHOU: maximo {vmax} acima da tolerancia "
                          f"({cfg.VALIDATION_MAX_TOLERANCE}).")
    print(f"  OK: min={vmin:.6f}, max={vmax:.6f}, sem NaN/Inf.")

    if cfg.VALIDATION_EXPORT_STATISTICS:
        print("=== Estatisticas do raster final (Exposicao, Indice V) ===")
        print(f"  Media: {np.mean(valores_validos):.4f}")
        print(f"  Mediana: {np.median(valores_validos):.4f}")
        print(f"  Desvio-padrao: {np.std(valores_validos):.4f}")
        print(f"  Assimetria: {skewness(valores_validos):.4f}")
        for p in [0, 25, 50, 75, 90, 95, 99, 100]:
            print(f"  p{p}: {np.percentile(valores_validos, p):.4f}")

    if cfg.VALIDATION_EXPORT_HISTOGRAM:
        hist_path = output_path.replace(".tif", "_histograma.txt")
        exportar_histograma_texto(valores_validos, hist_path)

    print(f"A escrever GeoTIFF em {output_path} ...")
    escrever_geotiff(exposicao_final, output_path)
    print("Concluido.")


if __name__ == "__main__":
    main()
