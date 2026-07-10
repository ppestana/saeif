#!/usr/bin/env python3
"""
Gera o raster de Deficit de Capacidade de Resposta (subdimensao
Acessibilidade) do Indice V, a partir da camada de acessibilidade viaria
(scripts/gerar_acessibilidade_viaria.py).

Metodo (decisao de 10 Jul 2026, ver saeif_architecture.html):
    deficit = 1 - acessibilidade

    Celulas SEM via mapeada nao sao NoData -- sao o valor extremo real da
    variavel (pior acesso possivel), pelo que ficam com deficit = 1.0
    directamente, nao herdam nenhum tratamento de "sem dados = 0" usado
    nas variaveis do INE (semantica INVERTIDA face as outras variaveis:
    la, "sem dados" = "sem populacao relevante" = 0; aqui, "sem via" =
    "pior acesso" = 1, o extremo OPOSTO).

    SEM saturacao por percentil: o extremo inferior de acessibilidade
    (= extremo superior de deficit) e o proprio fenomeno que a variavel
    pretende identificar, nao ruido estatistico a comprimir -- normalizacao
    linear directa.

Validado por cruzamento com a populacao GHSL antes de implementar: celulas
sem via mapeada tem populacao media 0.11 (~100x menos que celulas com
via, media 10.69) -- confirma zonas genuinamente remotas, nao vies de
extracao. Pequena cauda residual (2.3% das celulas sem via tem alguma
populacao, max ~168 habitantes) atribuida a cobertura incompleta do OSM
em caminhos rurais locais -- limitacao conhecida, documentada, nao
bloqueante.

Uso:
    python3 gerar_deficit_acessibilidade.py <mascara.tif> <acessibilidade.tif> <output.tif>
"""
import sys
import os
import json
from datetime import date
import numpy as np
from osgeo import gdal, osr

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config"))
import grid_spec as gs

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
        print("Uso: python3 gerar_deficit_acessibilidade.py <mascara.tif> <acessibilidade.tif> <output.tif>")
        sys.exit(1)

    mascara_path, acessibilidade_path, output_path = sys.argv[1:4]

    gs.assert_grid_consistency()

    print(f"A ler mascara de {mascara_path} ...")
    mascara, _ = ler_raster_completo(mascara_path)
    dentro_pt = mascara == 1
    n_pt = int(np.sum(dentro_pt))
    print(f"Celulas dentro de Portugal Continental: {n_pt}")

    print(f"A ler acessibilidade de {acessibilidade_path} ...")
    acess, acess_nodata = ler_raster_completo(acessibilidade_path)

    sem_via = dentro_pt & (acess == acess_nodata if acess_nodata is not None else False)
    com_via = dentro_pt & ~sem_via
    n_sem_via = int(np.sum(sem_via))

    print(f"Celulas sem via mapeada: {n_sem_via} ({100*n_sem_via/n_pt:.1f}% de Portugal) -> deficit = 1.0")

    # Deficit = 1 - acessibilidade. Sem via -> deficit maximo (1.0), directo.
    deficit = np.where(com_via, 1.0 - acess, 1.0)
    deficit_final = np.where(dentro_pt, deficit, gs.GRID_NODATA)

    print("A validar o raster resultante ...")
    valores_validos = deficit_final[dentro_pt]

    if np.any(np.isnan(valores_validos)) or np.any(np.isinf(valores_validos)):
        raise ValueError("VALIDACAO FALHOU: encontrados NaN/Inf no resultado.")

    vmin, vmax = valores_validos.min(), valores_validos.max()
    if vmin < -1e-6 or vmax > 1.0 + 1e-6:
        raise ValueError(f"VALIDACAO FALHOU: min={vmin}, max={vmax} fora do intervalo [0,1].")
    print(f"  OK: min={vmin:.6f}, max={vmax:.6f}, sem NaN/Inf.")

    print("=== Estatisticas do raster final (Deficit de Acessibilidade) ===")
    print(f"  Media: {np.mean(valores_validos):.4f}")
    print(f"  Mediana: {np.median(valores_validos):.4f}")
    print(f"  Desvio-padrao: {np.std(valores_validos):.4f}")
    print(f"  Assimetria: {skewness(valores_validos):.4f}")
    for p in [0, 25, 50, 75, 90, 95, 99, 100]:
        print(f"  p{p}: {np.percentile(valores_validos, p):.4f}")

    print(f"A escrever GeoTIFF em {output_path} ...")
    escrever_geotiff(deficit_final, output_path)

    # Indicador de qualidade do indice (sugestao de consultoria SIG externa)
    qualidade_path = output_path.replace(".tif", "_qualidade.json")
    qualidade = {
        "road_density_source": "OpenStreetMap (extrato Geofabrik, portugal.gpkg)",
        "road_types_included": [
            "track_grade1", "track_grade2", "track", "track_grade3", "service",
            "unclassified", "tertiary", "tertiary_link", "residential",
            "track_grade4", "secondary", "secondary_link", "living_street",
            "track_grade5", "primary", "primary_link", "trunk", "trunk_link",
            "motorway_link", "motorway", "busway",
        ],
        "road_types_excluded": [
            "footway", "path", "steps", "pedestrian", "cycleway", "bridleway", "unknown",
        ],
        "cells_without_roads_pct": round(100 * n_sem_via / n_pt, 2),
        "validation_note": (
            "Populacao media nas celulas sem via: 0.11 (GHSL); com via: 10.69. "
            "Confirma zonas genuinamente remotas, nao vies de extracao. "
            "Cauda residual: 2.3% das celulas sem via tem alguma populacao "
            "(max ~168 hab.), atribuida a cobertura incompleta do OSM em "
            "caminhos rurais locais -- limitacao conhecida."
        ),
        "created": date.today().isoformat(),
    }
    with open(qualidade_path, "w", encoding="utf-8") as f:
        json.dump(qualidade, f, indent=2, ensure_ascii=False)
    print(f"Indicador de qualidade escrito em {qualidade_path}")

    print("Concluido.")


if __name__ == "__main__":
    main()
