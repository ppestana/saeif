#!/usr/bin/env python3
"""
Gera o raster oficial da componente Sensibilidade do Indice V (Vulnerabilidade).

Combina duas variaveis, cada uma normalizada independentemente (min-max
real, dentro da mascara de Portugal) antes de agregar com ponderacao:
    Sensibilidade = SENSITIVITY_WEIGHT_ELDERLY  * idosos_norm
                  + SENSITIVITY_WEIGHT_CHILDREN * criancas_norm

Metodo de normalizacao: min-max (nao percentil), decidido a partir da
distribuicao real dos dados para AMBAS as variaveis -- apos a ponderacao
de confianca (ver scripts/gerar_proporcao_idosos.py e
gerar_proporcao_faixa_etaria.py), as duas tem assimetria moderada
(idosos ~0.65, criancas ~0.58) e os maximos reais ja nao representam
ruido estatistico (confirmado por cruzamento com populacoes reais no
topo da distribuicao). Usar percentil aqui saturaria informacao real
sem ganho de robustez correspondente.

Pesos (ver config/indice_v.py): a literatura sobre mortalidade em
incendios documenta risco relativo consistentemente mais elevado para
idosos (65+) do que para criancas -- mas os valores exactos dos pesos
(0.65/0.35) sao uma decisao de modelacao informada por essa evidencia,
nao uma derivacao matematica do risco relativo (ver nota em
config/indice_v.py e saeif_architecture.html).

Uso:
    python3 gerar_indice_v_sensibilidade.py <mascara.tif> <idosos.tif> <criancas.tif> <output.tif>
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
    v_max = np.max(valores[dentro_mask])
    if v_max <= limite_inferior:
        raise ValueError(
            f"Maximo ({v_max}) <= limite inferior ({limite_inferior}) -- "
            "normalizacao invalida, verificar os dados de entrada."
        )
    norm = (valores - limite_inferior) / (v_max - limite_inferior)
    norm = np.clip(norm, 0.0, 1.0)
    return norm, v_max


def preparar_variavel(path, dentro_pt, nome):
    """Le, identifica celulas sem dados INE, normaliza (min-max), e trata
    explicitamente as celulas sem dados como 0 (ver nota em
    saeif_architecture.html sobre a decisao de cobertura incompleta)."""
    arr, nodata = ler_raster_completo(path)
    valido = dentro_pt & (arr != nodata if nodata is not None else dentro_pt)
    sem_dados = dentro_pt & ~valido

    norm, v_max = normalizar_minmax(arr, valido, cfg.SENSITIVITY_LOWER_BOUND)
    print(f"  [{nome}] Maximo real (dentro da mascara): {v_max:.4f}")
    norm[sem_dados] = 0.0
    print(f"  [{nome}] {int(np.sum(sem_dados))} celulas sem dados INE definidas explicitamente como 0.")
    return norm


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
    if len(sys.argv) != 5:
        print("Uso: python3 gerar_indice_v_sensibilidade.py <mascara.tif> <idosos.tif> <criancas.tif> <output.tif>")
        sys.exit(1)

    mascara_path, idosos_path, criancas_path, output_path = sys.argv[1:5]

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

    print("A normalizar (min-max) cada variavel ...")
    idosos_norm = preparar_variavel(idosos_path, dentro_pt, "idosos")
    criancas_norm = preparar_variavel(criancas_path, dentro_pt, "criancas")

    print(f"A combinar: {cfg.SENSITIVITY_WEIGHT_ELDERLY} x idosos + "
          f"{cfg.SENSITIVITY_WEIGHT_CHILDREN} x criancas "
          f"(pesos: {cfg.SENSITIVITY_WEIGHT_METHOD}) ...")
    sensibilidade = (
        cfg.SENSITIVITY_WEIGHT_ELDERLY * idosos_norm
        + cfg.SENSITIVITY_WEIGHT_CHILDREN * criancas_norm
    )

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
