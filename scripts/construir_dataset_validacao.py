#!/usr/bin/env python3
"""
Constroi o conjunto de dados de validacao do modelo de integracao
Risco = f(I, P, V, M) (ver saeif_especificacao_cientifica.html Sec05).

Para cada incendio real em areas_ardidas (excluindo causas Natural/
Reacendimento, com data_inicio conhecida -- mesmo filtro ja usado para
o Indice I), extrai:
    - centroide (lat/lon)
    - data de inicio
    - area_ha (resultado real -- variavel de saida a explicar)
    - causa_tipo
    - I, P, V: valores dos rasters de producao na celula correspondente
      da grelha oficial (250m, EPSG:3763)
    - FWI: valor historico mais proximo (espacial, por vizinho mais
      proximo na grelha irregular do ECMWF) na data exacta da ignicao

Saida: CSV, uma linha por incendio, pronto para analise estatistica
(testar candidatas a funcao de integracao contra o resultado real).

Uso:
    python3 construir_dataset_validacao.py <output.csv>

Requisitos: ligacao a base de dados (DB_HOST=127.0.0.1 DB_PORT=5434 ...),
rasters de producao (data/indice_i/..., data/indice_p.tif, data/indice_v.tif),
FWI historico ja descarregado (data/fwi_historico_2020_2025.grib).
"""
import sys
import os
import csv
import numpy as np
from osgeo import gdal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config"))
import grid_spec as gs

FWI_GRIB_PATH = "data/fwi_historico_2020_2025.grib"
INDICE_I_PATH = "data/indice_i/indice_i_kde_producao_bw3500m.tif"
INDICE_P_PATH = "data/indice_p.tif"
INDICE_V_PATH = "data/indice_v.tif"


def obter_incendios_reais():
    """Consulta areas_ardidas (mesmo filtro do Indice I), devolve lista de dicts."""
    import asyncpg
    import asyncio

    async def _query():
        conn = await asyncpg.connect(
            host=os.getenv("DB_HOST", "127.0.0.1"),
            port=int(os.getenv("DB_PORT", "5434")),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASSWORD"),
            database=os.getenv("DB_NAME"),
        )
        try:
            rows = await conn.fetch("""
                SELECT
                    id,
                    ano,
                    area_ha,
                    causa_tipo,
                    data_inicio,
                    ST_Y(ST_Centroid(geom)) AS lat,
                    ST_X(ST_Centroid(geom)) AS lon
                FROM areas_ardidas
                WHERE data_inicio IS NOT NULL
                  AND causa_tipo NOT IN ('Natural', 'Reacendimento')
                ORDER BY id
            """)
            return [dict(r) for r in rows]
        finally:
            await conn.close()

    return asyncio.run(_query())


def ler_raster_indexavel(path):
    """Le um raster completo para memoria (bytes, convencao do projecto) e
    devolve tambem o inverso do GeoTransform, para lookup rapido lon/lat->celula."""
    from osgeo import gdal
    ds = gdal.Open(path)
    if ds is None:
        raise RuntimeError(f"Nao foi possivel abrir {path}")
    band = ds.GetRasterBand(1)
    ncols, nrows = ds.RasterXSize, ds.RasterYSize
    raw = band.ReadRaster(0, 0, ncols, nrows, buf_type=gdal.GDT_Float32)
    arr = np.frombuffer(raw, dtype=np.float32).reshape(nrows, ncols)
    nodata = band.GetNoDataValue()
    gt = ds.GetGeoTransform()
    inv_gt = gdal.InvGeoTransform(gt)
    proj = ds.GetProjection()
    return arr, nodata, inv_gt, proj


def lookup_raster(arr, nodata, inv_gt, x, y):
    """Devolve o valor do raster na coordenada (x,y), no CRS do proprio raster."""
    col, row = gdal.ApplyGeoTransform(inv_gt, x, y)
    col, row = int(col), int(row)
    if 0 <= row < arr.shape[0] and 0 <= col < arr.shape[1]:
        val = arr[row, col]
        if nodata is None or val != nodata:
            return float(val)
    return None


def transformar_4326_para_3763(lon, lat):
    from pyproj import Transformer
    transformer = Transformer.from_crs("EPSG:4326", "EPSG:3763", always_xy=True)
    x, y = transformer.transform(lon, lat)
    return x, y


def carregar_fwi():
    """Carrega o FWI historico e devolve (lats, lons, times, valores, mascara_valida)
    para lookup. Descoberta empirica (26 Jul 2026): o FWI so e calculado em areas
    vegetadas -- 12 dos 204 pontos da grelha ficam sempre a NaN (agua/urbano),
    mascara CONSTANTE ao longo dos 2192 dias (confirmado antes de aplicar a
    correcao). Por isso o vizinho mais proximo deve ser procurado so entre os
    pontos sempre validos, nao literalmente o mais proximo (que pode ser um dos
    12 sempre-NaN, fazendo falhar 73,7% dos incendios reais -- confirmado)."""
    import xarray as xr
    ds = xr.open_dataset(FWI_GRIB_PATH, engine="cfgrib")
    lats = ds["latitude"].values
    lons = ds["longitude"].values
    times = ds["time"].values
    valores = ds["fwinx"].values  # shape (time, values)

    nan_por_ponto = np.isnan(valores).sum(axis=0)
    mascara_valida = nan_por_ponto == 0
    n_validos = int(np.sum(mascara_valida))
    print(f"  Pontos da grelha FWI sempre validos: {n_validos} de {len(mascara_valida)}")

    return lats, lons, times, valores, mascara_valida


def lookup_fwi(lats, lons, times, valores, mascara_valida, lon, lat, data):
    """Vizinho mais proximo espacial, restrito aos pontos sempre validos
    (ver carregar_fwi), na data exacta (sem interpolacao temporal -- FWI ja e diario)."""
    dist2 = (lats - lat) ** 2 + (lons - lon) ** 2
    dist2_validos = np.where(mascara_valida, dist2, np.inf)
    idx_espacial = int(np.argmin(dist2_validos))

    data_np = np.datetime64(data.date().isoformat())
    idx_temporal = np.where(times == data_np)[0]
    if len(idx_temporal) == 0:
        return None
    idx_temporal = int(idx_temporal[0])

    val = valores[idx_temporal, idx_espacial]
    return float(val) if not np.isnan(val) else None


def main():
    if len(sys.argv) != 2:
        print("Uso: python3 construir_dataset_validacao.py <output.csv>")
        sys.exit(1)

    output_path = sys.argv[1]
    gs.assert_grid_consistency()

    print("A consultar incendios reais (areas_ardidas) ...")
    incendios = obter_incendios_reais()
    print(f"{len(incendios)} incendios encontrados (com data_inicio, causa != Natural/Reacendimento).")

    print(f"A carregar Indice I de {INDICE_I_PATH} ...")
    i_arr, i_nodata, i_inv_gt, _ = ler_raster_indexavel(INDICE_I_PATH)
    print(f"A carregar Indice P de {INDICE_P_PATH} ...")
    p_arr, p_nodata, p_inv_gt, _ = ler_raster_indexavel(INDICE_P_PATH)
    print(f"A carregar Indice V de {INDICE_V_PATH} ...")
    v_arr, v_nodata, v_inv_gt, _ = ler_raster_indexavel(INDICE_V_PATH)

    print(f"A carregar FWI historico de {FWI_GRIB_PATH} ...")
    fwi_lats, fwi_lons, fwi_times, fwi_valores, fwi_mascara_valida = carregar_fwi()

    print("A emparelhar cada incendio com I, P, V, FWI ...")
    linhas = []
    sem_fwi = 0
    sem_indices = 0
    for inc in incendios:
        lon, lat = inc["lon"], inc["lat"]
        x3763, y3763 = transformar_4326_para_3763(lon, lat)

        i_val = lookup_raster(i_arr, i_nodata, i_inv_gt, x3763, y3763)
        p_val = lookup_raster(p_arr, p_nodata, p_inv_gt, x3763, y3763)
        v_val = lookup_raster(v_arr, v_nodata, v_inv_gt, x3763, y3763)

        fwi_val = lookup_fwi(fwi_lats, fwi_lons, fwi_times, fwi_valores, fwi_mascara_valida,
                              lon, lat, inc["data_inicio"])

        if fwi_val is None:
            sem_fwi += 1
        if i_val is None or p_val is None or v_val is None:
            sem_indices += 1
            continue  # sem I/P/V nao e utilizavel para testar a integracao

        linhas.append({
            "id": inc["id"],
            "data_inicio": inc["data_inicio"].isoformat(),
            "ano": inc["ano"],
            "lat": lat,
            "lon": lon,
            "causa_tipo": inc["causa_tipo"],
            "area_ha": float(inc["area_ha"]) if inc["area_ha"] is not None else None,
            "indice_i": i_val,
            "indice_p": p_val,
            "indice_v": v_val,
            "fwi": fwi_val,
        })

    print(f"Incendios sem FWI correspondente (fora do periodo/area do ficheiro): {sem_fwi}")
    print(f"Incendios sem I/P/V (fora da mascara/grelha) -- excluidos: {sem_indices}")
    print(f"Total utilizavel no conjunto de dados de validacao: {len(linhas)}")

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
        writer.writeheader()
        writer.writerows(linhas)

    print(f"Concluido: {output_path}")


if __name__ == "__main__":
    main()
