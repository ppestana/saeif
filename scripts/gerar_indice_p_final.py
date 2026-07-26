#!/usr/bin/env python3
"""
Combina as duas subdimensoes do Indice P (decisao arquitectural de 26 Jul
2026, ver saeif_especificacao_cientifica.html Sec02):

    P = min(1.0, P_estrutural + P_historico)

onde P_estrutural = 0.5*WorldCover + 0.3*NDVI_factor + 0.2*Declive
(scripts/gerar_indice_p_estrutural.py) e P_historico = bonus de area
ardida (scripts/gerar_bonus_area_ardida.py).

Substitui o antigo scripts/gerar_indice_p.py (que calculava as quatro
variaveis de uma vez, sem separacao conceptual) -- MESMO resultado
numerico esperado, so a arquitectura de scripts muda. Este script inclui
um teste de regressao: se um raster do Indice P anterior for fornecido,
compara celula a celula e reporta a diferenca maxima (deve ser ~0).

Uso:
    python3 gerar_indice_p_final.py <mascara.tif> <p_estrutural.tif> <p_historico.tif> <output.tif> [indice_p_anterior.tif]
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


def main():
    if len(sys.argv) not in (5, 6):
        print("Uso: python3 gerar_indice_p_final.py <mascara.tif> <p_estrutural.tif> "
              "<p_historico.tif> <output.tif> [indice_p_anterior.tif]")
        sys.exit(1)

    mascara_path, p_estrutural_path, p_historico_path, output_path = sys.argv[1:5]
    p_anterior_path = sys.argv[5] if len(sys.argv) == 6 else None

    gs.assert_grid_consistency()

    print(f"A ler mascara de {mascara_path} ...")
    mascara, _ = ler_raster_bytes(mascara_path)
    dentro_pt = mascara == 1
    print(f"Celulas dentro de Portugal Continental: {int(np.sum(dentro_pt))}")

    print(f"A ler P_estrutural de {p_estrutural_path} ...")
    p_estrutural, pe_nodata = ler_raster_bytes(p_estrutural_path)

    print(f"A ler P_historico de {p_historico_path} ...")
    p_historico, ph_nodata = ler_raster_bytes(p_historico_path)

    pe_valido = np.where((p_estrutural == pe_nodata) if pe_nodata is not None else False, 0.0, p_estrutural)
    ph_valido = np.where((p_historico == ph_nodata) if ph_nodata is not None else False, 0.0, p_historico)

    print("A combinar: P_estrutural + P_historico, limitado a 1.0 ...")
    p_final = np.clip(pe_valido + ph_valido, 0.0, 1.0)
    p_final_masked = np.where(dentro_pt, p_final, gs.GRID_NODATA)

    print("A validar o raster resultante ...")
    valores_validos = p_final_masked[dentro_pt]
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

    if p_anterior_path:
        print(f"\n=== TESTE DE REGRESSAO contra {p_anterior_path} ===")
        p_ant, pa_nodata = ler_raster_bytes(p_anterior_path)
        comparaveis = dentro_pt & (p_ant != pa_nodata if pa_nodata is not None else dentro_pt)
        diff = np.abs(p_final_masked[comparaveis] - p_ant[comparaveis])
        print(f"  Celulas comparadas: {int(np.sum(comparaveis))}")
        print(f"  Diferenca maxima: {diff.max():.8f}")
        print(f"  Diferenca media: {diff.mean():.8f}")
        print(f"  Celulas com diferenca > 0.0001: {int(np.sum(diff > 0.0001))}")
        if diff.max() < 0.0001:
            print("  RESULTADO: identico (dentro de precisao float32) -- decomposicao nao alterou o resultado.")
        else:
            print("  AVISO: ha diferencas nao triviais -- investigar antes de aceitar.")

    print(f"\nA escrever GeoTIFF em {output_path} ...")
    escrever_geotiff(p_final_masked, output_path)
    print("Concluido.")


if __name__ == "__main__":
    main()
