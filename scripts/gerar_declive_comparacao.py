#!/usr/bin/env python3
"""
Compara dois metodos de calculo do declive, a partir da mesma fonte DEM
(gerar_dem_indice_p.py, EPSG:3035), antes de decidir qual adoptar para
o Indice P (decisao registada em saeif_especificacao_cientifica.html Sec02).

Metodo ANTIGO (replica exactamente api/ingest/dem.py):
    DEM reprojectado para EPSG:4326 (graus) -> np.gradient com aproximacao
    graus->metros (x111320, sem correcao de latitude) -> declive em graus
    -> normalizado (clip(graus/45, 0, 1)) -> reprojectado para a grelha
    oficial (250m, EPSG:3763) para comparacao.

Metodo NOVO (proposta desta sessao):
    DEM reprojectado directamente para a grelha oficial (250m, EPSG:3763,
    metros reais) -> gdaldem slope -> normalizado da mesma forma.

Uso:
    python3 gerar_declive_comparacao.py <dem_3035.tif> <output_dir>

Saida (em <output_dir>/):
    declive_antigo.tif, declive_novo.tif -- os dois rasters, na grelha oficial
    Estatisticas de comparacao impressas no ecra (Pearson, Spearman, RMSE,
    diferenca media, % de celulas com diferenca > 0.05).
"""
import os
import sys
import subprocess
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config"))
import grid_spec as gs

DTYPE_MAP_GDAL = None  # preenchido apos import do gdal


def normalizar_declive(slope_deg, nodata_mask):
    """clip(graus/45, 0, 1) -- mesma normalizacao usada em api/ingest/dem.py."""
    norm = np.clip(slope_deg / 45.0, 0.0, 1.0).astype("float32")
    norm[nodata_mask] = gs.GRID_NODATA
    return norm


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


def ler_raster_bytes(path):
    """Le um raster via ReadRaster (bytes), nao ReadAsArray -- convencao do
    projeto desde o Indice I, evita incompatibilidade de ABI numpy/gdal_array."""
    from osgeo import gdal
    ds = gdal.Open(path)
    if ds is None:
        raise RuntimeError(f"Nao foi possivel abrir {path}")
    band = ds.GetRasterBand(1)
    ncols, nrows = ds.RasterXSize, ds.RasterYSize
    raw = band.ReadRaster(0, 0, ncols, nrows, buf_type=gdal.GDT_Float32)
    arr = np.frombuffer(raw, dtype=np.float32).reshape(nrows, ncols).astype(float)
    nodata = band.GetNoDataValue()
    gt = ds.GetGeoTransform()
    proj = ds.GetProjection()
    return arr, nodata, gt, proj, ncols, nrows


def gerar_declive_antigo(dem_3035_path, output_path, tmp_dir):
    """Replica api/ingest/dem.py: DEM em graus, np.gradient com aproximacao 111320."""
    dem_4326_path = os.path.join(tmp_dir, "dem_4326.tif")
    print("  [antigo] A reprojectar DEM para EPSG:4326 (graus, tal como o metodo original) ...")
    subprocess.run(["gdalwarp", "-t_srs", "EPSG:4326", "-r", "bilinear", "-overwrite",
                     dem_3035_path, dem_4326_path], capture_output=True, text=True, check=True)

    data, dem_nodata, gt, proj, ncols, nrows = ler_raster_bytes(dem_4326_path)
    res_x = abs(gt[1]) * 111320
    res_y = abs(gt[5]) * 111320
    print(f"  [antigo] Resolucao aproximada usada no gradiente: {res_x:.1f}m (x) / {res_y:.1f}m (y) "
          f"-- SEM correcao de latitude (mesmo comportamento do metodo original)")
    dy, dx = np.gradient(data, res_y, res_x)
    slope_deg = np.degrees(np.arctan(np.sqrt(dx**2 + dy**2)))
    print(f"  [antigo] Declive: max={slope_deg.max():.1f}graus medio={slope_deg.mean():.1f}graus")

    # Escrever o resultado no CRS/grelha do DEM 4326 temporario, depois reprojectar
    from osgeo import gdal, osr
    slope_4326_path = os.path.join(tmp_dir, "slope_4326.tif")
    driver = gdal.GetDriverByName("GTiff")
    out_ds = driver.Create(slope_4326_path, ncols, nrows, 1, gdal.GDT_Float32)
    out_ds.SetGeoTransform(gt)
    out_ds.SetProjection(proj)
    slope_norm = np.clip(slope_deg / 45.0, 0.0, 1.0).astype("float32")
    out_band = out_ds.GetRasterBand(1)
    out_band.WriteRaster(0, 0, ncols, nrows, slope_norm.tobytes(), buf_type=gdal.GDT_Float32)
    out_band.FlushCache()
    out_ds = None

    print("  [antigo] A reprojectar declive normalizado para a grelha oficial (para comparacao) ...")
    subprocess.run([
        "gdalwarp", "-t_srs", gs.GRID_CRS,
        "-te", str(gs.GRID_XMIN), str(gs.GRID_YMIN), str(gs.GRID_XMAX), str(gs.GRID_YMAX),
        "-tr", str(gs.GRID_RESOLUTION), str(gs.GRID_RESOLUTION),
        "-r", "bilinear", "-dstnodata", str(gs.GRID_NODATA), "-overwrite",
        slope_4326_path, output_path,
    ], capture_output=True, text=True, check=True)
    print(f"  [antigo] Guardado em {output_path}")


def gerar_declive_novo(dem_3035_path, output_path, tmp_dir):
    """gdaldem slope sobre o DEM reprojectado para a grelha oficial (metros reais)."""
    dem_3763_path = os.path.join(tmp_dir, "dem_3763.tif")
    print("  [novo] A reprojectar DEM para a grelha oficial (250m, EPSG:3763, metros) ...")
    subprocess.run([
        "gdalwarp", "-t_srs", gs.GRID_CRS,
        "-te", str(gs.GRID_XMIN), str(gs.GRID_YMIN), str(gs.GRID_XMAX), str(gs.GRID_YMAX),
        "-tr", str(gs.GRID_RESOLUTION), str(gs.GRID_RESOLUTION),
        "-r", "bilinear", "-overwrite",
        dem_3035_path, dem_3763_path,
    ], capture_output=True, text=True, check=True)

    slope_deg_path = os.path.join(tmp_dir, "slope_deg_3763.tif")
    print("  [novo] A calcular declive com gdaldem slope (unidades metricas reais) ...")
    subprocess.run(["gdaldem", "slope", dem_3763_path, slope_deg_path,
                     "-compute_edges"], capture_output=True, text=True, check=True)

    slope_deg, _, _, _, _, _ = ler_raster_bytes(slope_deg_path)
    print(f"  [novo] Declive: max={slope_deg.max():.1f}graus medio={slope_deg.mean():.1f}graus")

    dem_data, dem_nodata, _, _, _, _ = ler_raster_bytes(dem_3763_path)
    nodata_mask = (dem_data == dem_nodata) if dem_nodata is not None else np.zeros_like(dem_data, dtype=bool)

    final = normalizar_declive(slope_deg, nodata_mask)
    escrever_geotiff(final, output_path)
    print(f"  [novo] Guardado em {output_path}")


def pearson(x, y):
    return float(np.corrcoef(x, y)[0, 1])


def spearman(x, y):
    """Correlacao de Spearman = Pearson sobre os postos (ranks) -- mesma
    tecnica ja usada em scripts/analisar_correlacao.py, evita depender do
    scipy (conflito de versao numpy/scipy confirmado no servidor: scipy
    1.18 exige numpy>=2.0, servidor tem 1.26.4 gerido pelo sistema)."""
    rank_x = np.argsort(np.argsort(x))
    rank_y = np.argsort(np.argsort(y))
    return pearson(rank_x.astype(np.float64), rank_y.astype(np.float64))


def comparar(path_antigo, path_novo):
    a, nodata_a, _, _, _, _ = ler_raster_bytes(path_antigo)
    n, nodata_n, _, _, _, _ = ler_raster_bytes(path_novo)

    validos = (a != nodata_a) & (n != nodata_n) & ~np.isnan(a) & ~np.isnan(n)
    a_v = a[validos].astype(np.float64)
    n_v = n[validos].astype(np.float64)
    print(f"\nCelulas validas em ambos: {len(a_v)}")

    pearson_r = pearson(a_v, n_v)
    spearman_r = spearman(a_v, n_v)
    rmse = np.sqrt(np.mean((a_v - n_v) ** 2))
    diff_media = np.mean(n_v - a_v)
    pct_dif_grande = 100 * np.sum(np.abs(n_v - a_v) > 0.05) / len(a_v)

    print("\n=== COMPARACAO: metodo antigo (graus+np.gradient) vs. novo (gdaldem slope) ===")
    print(f"  Pearson r:                    {pearson_r:.4f}")
    print(f"  Spearman rho:                 {spearman_r:.4f}")
    print(f"  RMSE:                         {rmse:.4f}")
    print(f"  Diferenca media (novo-antigo): {diff_media:+.4f}")
    print(f"  % celulas com |diferenca| > 0.05: {pct_dif_grande:.2f}%")


def main():
    if len(sys.argv) != 3:
        print("Uso: python3 gerar_declive_comparacao.py <dem_3035.tif> <output_dir>")
        sys.exit(1)

    dem_path, output_dir = sys.argv[1:3]
    gs.assert_grid_consistency()
    os.makedirs(output_dir, exist_ok=True)
    tmp_dir = os.path.join(output_dir, "_tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    path_antigo = os.path.join(output_dir, "declive_antigo.tif")
    path_novo = os.path.join(output_dir, "declive_novo.tif")

    print("=== Metodo ANTIGO (graus + np.gradient, aproximacao 111320) ===")
    gerar_declive_antigo(dem_path, path_antigo, tmp_dir)

    print("\n=== Metodo NOVO (gdaldem slope, metros reais, EPSG:3763) ===")
    gerar_declive_novo(dem_path, path_novo, tmp_dir)

    comparar(path_antigo, path_novo)

    print("\nConcluido.")


if __name__ == "__main__":
    main()
