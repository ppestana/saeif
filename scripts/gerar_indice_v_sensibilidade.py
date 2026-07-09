#!/usr/bin/env python3
"""
Gera o raster oficial da componente Sensibilidade do Indice V (Vulnerabilidade).

Nesta versao, a Sensibilidade tem um unico componente implementado --
proporcao de populacao idosa (65+), ja ponderada por confianca estatistica
(ver scripts/gerar_proporcao_idosos.py). Estruturado para aceitar mais
componentes no futuro (crianças, isolamento, escolaridade, etc.), cada um
com o seu proprio peso em config/indice_v.py.

Metodo de normalizacao: min-max (nao percentil), decidido a partir da
distribuicao real dos dados -- ao contrario da Exposicao (assimetria ~19,
outliers extremos genuinos), a Sensibilidade por idosos, apos a ponderacao
de confianca, tem assimetria moderada (~0.65) e o maximo real ja nao
representa ruido estatistico (celulas no topo da distribuicao tem
populacoes de dezenas a centenas de habitantes, nao os "2 habitantes"
que geravam falsos 100% antes da ponderacao). Usar percentil aqui
saturaria informacao real sem ganho de robustez correspondente.

Uso:
    python3 gerar_indice_v_sensibilidade.py <mascara.tif> <idosos.tif> <output.tif>
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


def normalizar_minmax(valores, dentro_mask, limite_inferior):
    """Normaliza por min-max real (maximo calculado a partir dos dados dentro da mascara)."""
    v_max = np.max(valores[dentro_mask])
    if v_max <= limite_inferior:
        raise ValueError(
            f"Maximo ({v_max}) <= limite inferior ({limite_inferior}) -- "
            "normalizacao invalida, verificar os dados de entrada."
        )
    norm = (valores - limite_inferior) / (v_max - limite_inferior)
    norm = np.clip(norm, 0.0, 1.0)
    return norm, v_max


def exportar_histograma_texto(valores, path, n_bins=20):
    contagens, bordas = np.histogram(valores, bins=n_bins, range=(0.0, 1.0))
    max_contagem = contagens.max() if contagens.max() > 0 else 1
    largura_barra = 50
    with open(path, "w") as f:
        f.write("Histograma da Sensibilidade (Indice V) -- 0.0 a 1.0\n")
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
    if len(sys.argv) != 4:
        print("Uso: python3 gerar_indice_v_sensibilidade.py <mascara.tif> <idosos.tif> <output.tif>")
        sys.exit(1)

    mascara_path, idosos_path, output_path = sys.argv[1:4]

    gs.assert_grid_consistency()

    if cfg.SENSITIVITY_NORMALIZATION != "minmax":
        raise NotImplementedError(
            f"Metodo de normalizacao '{cfg.SENSITIVITY_NORMALIZATION}' ainda nao implementado "
            "(so 'minmax' disponivel nesta versao)."
        )

    print(f"A ler mascara de {mascara_path} ...")
    mascara, _ = ler_raster_completo(mascara_path)
    dentro_pt = mascara == 1
    print(f"Celulas dentro de Portugal Continental: {int(np.sum(dentro_pt))}")

    print(f"A ler sensibilidade de idosos de {idosos_path} ...")
    idosos, idosos_nodata = ler_raster_completo(idosos_path)
    idosos_valido = dentro_pt & (idosos != idosos_nodata if idosos_nodata is not None else dentro_pt)

    # Celulas dentro de Portugal sem dados do INE (idosos_nodata): o INE nao
    # publica dados de populacao para celulas de 1km essencialmente
    # desabitadas (confirmado por cruzamento com a populacao GHSL da
    # Exposicao: destas celulas, so 0.7% tem alguma populacao real, media
    # ~0.035 habitantes -- ver saeif_architecture.html). DECISAO EXPLICITA:
    # tratadas como sensibilidade=0 (nao ha populacao idosa a proteger onde
    # nao ha, na pratica, populacao nenhuma), nao como NoData. Isto e feito
    # de forma explicita aqui, nao como efeito colateral do clip da
    # normalizacao (fragil e nao documentado).
    sem_dados_ine = dentro_pt & ~idosos_valido

    print("A normalizar (min-max) ...")
    idosos_norm, v_max = normalizar_minmax(idosos, idosos_valido, cfg.SENSITIVITY_LOWER_BOUND)
    print(f"  Maximo real (dentro da mascara): {v_max:.4f}")
    idosos_norm[sem_dados_ine] = 0.0
    print(f"  {int(np.sum(sem_dados_ine))} celulas sem dados INE (essencialmente desabitadas, "
          f"confirmado por GHSL) definidas explicitamente como 0.")

    # Por agora, um so componente -- peso 1.0. Estrutura pronta para mais
    # variaveis no futuro (cada uma com o seu SENSITIVITY_WEIGHT_*).
    sensibilidade = cfg.SENSITIVITY_WEIGHT_ELDERLY * idosos_norm

    sensibilidade_final = np.where(dentro_pt, sensibilidade, gs.GRID_NODATA)

    print("A validar o raster resultante ...")
    valores_validos = sensibilidade_final[dentro_pt]

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
        print("=== Estatisticas do raster final (Sensibilidade, Indice V) ===")
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
    escrever_geotiff(sensibilidade_final, output_path)
    print("Concluido.")


if __name__ == "__main__":
    main()
