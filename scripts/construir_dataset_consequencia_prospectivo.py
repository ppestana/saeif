#!/usr/bin/env python3
"""
Constroi um conjunto de dados de validacao PROSPECTIVO, alternativo ao
principal (data/dataset_validacao.csv, 2020-2025, area_ha como
resultado). Motivacao: nao ha sobreposicao temporal entre
areas_ardidas/ICNF (atraso de publicacao, sem registos apos Mai 2026) e
ocorrencias_prociv com cobertura densa (so a partir de Jun 2026) -- ver
saeif_architecture.html Sec15.29 para o diagnostico completo.

Aqui, a propria ocorrencia PROCIV serve de EVENTO e de RESULTADO ao
mesmo tempo -- os campos man/terrain/aerial (recursos operacionais
alocados) sao usados como proxy de GRAVIDADE OPERACIONAL, mais proximo
do "Produto 3" (consequencias) do que area_ha alguma vez foi (ver
saeif_especificacao_cientifica.html Sec05, reinterpretacao dos tres
produtos). Amostra pequena mas prospectiva e genuina (Jun-Jul 2026).

Uso:
    python3 construir_dataset_consequencia_prospectivo.py <fwi_2026.grib> <output.csv>

Requisitos: FWI intermediate_dataset para o periodo desejado (ver
scripts/obter_fwi_historico.py -- adaptar dataset_type para
'intermediate_dataset', dado que o consolidated tem atraso de
publicacao de meses, nao disponivel para dados tao recentes).
"""
import sys
import os
import csv
import numpy as np
from osgeo import gdal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config"))
import grid_spec as gs

INDICE_I_PATH = "data/indice_i/indice_i_kde_producao_bw3500m.tif"
INDICE_P_PATH = "data/indice_p.tif"
INDICE_V_PATH = "data/indice_v.tif"

NATUREZAS_FLORESTAIS = ["%mato%", "%florest%", "%rural%", "%povoamento%"]


def obter_ocorrencias_prociv(data_min, data_max):
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
            condicoes = " OR ".join(f"natureza ILIKE ${i+3}" for i in range(len(NATUREZAS_FLORESTAIS)))
            sql = f"""
                SELECT id, data_hora, natureza, man, terrain, aerial,
                       ST_Y(geom) AS lat, ST_X(geom) AS lon
                FROM ocorrencias_prociv
                WHERE data_hora >= $1 AND data_hora <= $2 AND ({condicoes})
                  AND man IS NOT NULL
            """
            rows = await conn.fetch(sql, data_min, data_max, *NATUREZAS_FLORESTAIS)
            return [dict(r) for r in rows]
        finally:
            await conn.close()

    return asyncio.run(_query())


def ler_raster_indexavel(path):
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
    return arr, nodata, inv_gt


def lookup_raster(arr, nodata, inv_gt, x, y):
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


def carregar_fwi(caminho_grib):
    import xarray as xr
    ds = xr.open_dataset(caminho_grib, engine="cfgrib")
    lats = ds["latitude"].values
    lons = ds["longitude"].values
    times = ds["time"].values
    valores = ds["fwinx"].values
    nan_por_ponto = np.isnan(valores).sum(axis=0)
    mascara_valida = nan_por_ponto == 0
    print(f"  Pontos da grelha FWI sempre validos: {int(np.sum(mascara_valida))} de {len(mascara_valida)}")
    return lats, lons, times, valores, mascara_valida


def lookup_fwi(lats, lons, times, valores, mascara_valida, lon, lat, data):
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
    if len(sys.argv) != 3:
        print("Uso: python3 construir_dataset_consequencia_prospectivo.py <fwi_2026.grib> <output.csv>")
        sys.exit(1)

    fwi_path, output_path = sys.argv[1:3]
    gs.assert_grid_consistency()

    print(f"A carregar FWI de {fwi_path} ...")
    fwi_lats, fwi_lons, fwi_times, fwi_valores, fwi_mascara = carregar_fwi(fwi_path)
    data_min_fwi = fwi_times.min()
    data_max_fwi = fwi_times.max()
    print(f"  Cobertura FWI: {data_min_fwi} a {data_max_fwi}")

    from datetime import datetime, timezone
    data_min_dt = datetime.fromtimestamp(int(data_min_fwi.astype("datetime64[s]").astype(int)), tz=timezone.utc)
    data_max_dt = datetime.fromtimestamp(int(data_max_fwi.astype("datetime64[s]").astype(int)), tz=timezone.utc)

    print("A consultar ocorrencias PROCIV (natureza florestal, dentro da cobertura FWI, com 'man' preenchido) ...")
    ocorrencias = obter_ocorrencias_prociv(data_min_dt, data_max_dt)
    print(f"{len(ocorrencias)} ocorrencias PROCIV candidatas.")

    print(f"A carregar Indice I de {INDICE_I_PATH} ...")
    i_arr, i_nodata, i_inv_gt = ler_raster_indexavel(INDICE_I_PATH)
    print(f"A carregar Indice P de {INDICE_P_PATH} ...")
    p_arr, p_nodata, p_inv_gt = ler_raster_indexavel(INDICE_P_PATH)
    print(f"A carregar Indice V de {INDICE_V_PATH} ...")
    v_arr, v_nodata, v_inv_gt = ler_raster_indexavel(INDICE_V_PATH)

    print("A emparelhar cada ocorrencia com I, P, V, FWI ...")
    linhas = []
    sem_fwi = 0
    sem_indices = 0
    for oc in ocorrencias:
        lon, lat = oc["lon"], oc["lat"]
        x3763, y3763 = transformar_4326_para_3763(lon, lat)

        i_val = lookup_raster(i_arr, i_nodata, i_inv_gt, x3763, y3763)
        p_val = lookup_raster(p_arr, p_nodata, p_inv_gt, x3763, y3763)
        v_val = lookup_raster(v_arr, v_nodata, v_inv_gt, x3763, y3763)
        fwi_val = lookup_fwi(fwi_lats, fwi_lons, fwi_times, fwi_valores, fwi_mascara,
                              lon, lat, oc["data_hora"])

        if fwi_val is None:
            sem_fwi += 1
        if i_val is None or p_val is None or v_val is None:
            sem_indices += 1
            continue

        linhas.append({
            "id": oc["id"],
            "data_hora": oc["data_hora"].isoformat(),
            "lat": lat,
            "lon": lon,
            "natureza": oc["natureza"],
            "man": oc["man"],
            "terrain": oc["terrain"],
            "aerial": oc["aerial"],
            "indice_i": i_val,
            "indice_p": p_val,
            "indice_v": v_val,
            "fwi": fwi_val,
        })

    print(f"Ocorrencias sem FWI correspondente: {sem_fwi}")
    print(f"Ocorrencias sem I/P/V (fora da mascara/grelha) -- excluidas: {sem_indices}")
    print(f"Total utilizavel: {len(linhas)}")

    if not linhas:
        print("AVISO: nenhuma linha utilizavel -- ficheiro nao escrito.")
        sys.exit(1)

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(linhas[0].keys()))
        writer.writeheader()
        writer.writerows(linhas)

    print(f"Concluido: {output_path}")


if __name__ == "__main__":
    main()
