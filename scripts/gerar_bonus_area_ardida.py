#!/usr/bin/env python3
"""
Gera o bonus de area ardida do Indice P como superficie raster (250m,
grelha oficial) -- substitui a consulta pontual em tempo real de
score.py::get_area_ardida_factor() por um raster pre-calculado.

Replica exactamente a mesma logica da consulta SQL original:
    - Para cada celula, considera todos os poligonos de areas_ardidas
      a menos de 5km (buffer).
    - De entre esses, usa o ANO MAIS RECENTE (nao o poligono mais
      proximo -- pode ser um fogo mais antigo mas mais perto; a logica
      original prioriza recencia, nao distancia).
    - Bonus por antiguidade: <=2 anos = +0.25, 2-4 anos = +0.15,
      4-6 anos = +0.05, sem limite superior = +0.05 (replica o "else"
      da funcao original, sem tecto -- um fogo de ha 20 anos a 5km
      ainda da +0.05 para sempre, tal como no codigo actual).

Tecnica: buffer em metros reais (EPSG:3763, Principio da Consistencia
Projectiva -- nao graus/geography como a consulta SQL original, que usa
::geography para o ST_DWithin) -- fisicamente equivalente, mais correcto.
Poligonos ordenados por ano ASCENDENTE, rasterizados numa unica passagem
(gdal_rasterize desenha por ordem, o valor mais recente "vence" em
celulas cobertas por multiplos buffers de anos diferentes) -- mesma
tecnica ja validada para o Deficit de Acessibilidade (Indice V).

Uso:
    python3 gerar_bonus_area_ardida.py <output.tif>

Requisitos: acesso a base de dados PostgreSQL (mesmas variaveis de
ambiente que o resto do SAEIF: DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME).
"""
import os
import sys
import subprocess
from datetime import date

import numpy as np
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config"))
import grid_spec as gs

load_dotenv()

BUFFER_M = 5000  # mesmo raio da consulta original (ST_DWithin 5000m)


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


def bonus_por_ano(anos_desde):
    """Replica exactamente os escaloes de score.py::get_area_ardida_factor."""
    bonus = np.zeros_like(anos_desde, dtype=np.float32)
    bonus[anos_desde <= 2] = 0.25
    bonus[(anos_desde > 2) & (anos_desde <= 4)] = 0.15
    bonus[anos_desde > 4] = 0.05  # sem tecto superior -- replica o "else" original
    return bonus


def main():
    if len(sys.argv) != 2:
        print("Uso: python3 gerar_bonus_area_ardida.py <output.tif>")
        sys.exit(1)

    output_path = sys.argv[1]
    gs.assert_grid_consistency()

    db_host = os.getenv("DB_HOST", "127.0.0.1")
    db_port = os.getenv("DB_PORT", "5434")
    db_user = os.getenv("DB_USER")
    db_pass = os.getenv("DB_PASSWORD")
    db_name = os.getenv("DB_NAME")

    pg_conn = f"PG:host={db_host} port={db_port} user={db_user} password={db_pass} dbname={db_name}"

    reprojetado_path = output_path + ".buffers.tmp.gpkg"
    ano_raster_path = output_path + ".ano.tmp.tif"

    print("A extrair areas_ardidas, reprojectar para EPSG:3763 (metros reais), "
          f"aplicar buffer de {BUFFER_M}m, ordenar por ano ascendente ...")
    sql = (
        f"SELECT ano, ST_Buffer(geom, {BUFFER_M}) AS geom "
        f"FROM areas_ardidas WHERE ano IS NOT NULL ORDER BY ano ASC"
    )
    cmd_reproj = [
        "ogr2ogr", "-f", "GPKG",
        "-t_srs", gs.GRID_CRS,
        "-sql", sql,
        "-nln", "buffers_ano",
        "-overwrite",
        reprojetado_path, pg_conn,
    ]
    resultado = subprocess.run(cmd_reproj, capture_output=True, text=True)
    if resultado.returncode != 0:
        print(f"ERRO no ogr2ogr (codigo {resultado.returncode}):")
        print(f"stdout: {resultado.stdout}")
        print(f"stderr: {resultado.stderr}")
        sys.exit(1)
    print("Extraccao, reprojeccao e buffer concluidos.")

    print(f"A rasterizar (ano mais recente por celula, via ordenacao) para a grelha oficial "
          f"({gs.GRID_NCOLS}x{gs.GRID_NROWS}) ...")
    cmd_rasterize = [
        "gdal_rasterize",
        "-a", "ano",
        "-a_nodata", str(gs.GRID_NODATA),
        "-init", str(gs.GRID_NODATA),
        "-ot", "Float32",
        "-te", str(gs.GRID_XMIN), str(gs.GRID_YMIN), str(gs.GRID_XMAX), str(gs.GRID_YMAX),
        "-tr", str(gs.GRID_RESOLUTION), str(gs.GRID_RESOLUTION),
        reprojetado_path, ano_raster_path,
    ]
    resultado = subprocess.run(cmd_rasterize, capture_output=True, text=True)
    if resultado.returncode != 0:
        print(f"ERRO no gdal_rasterize (codigo {resultado.returncode}):")
        print(f"stdout: {resultado.stdout}")
        print(f"stderr: {resultado.stderr}")
        sys.exit(1)
    print(resultado.stdout)

    print("A calcular bonus por antiguidade (mesmos escaloes de score.py) ...")
    ano_arr, ano_nodata = ler_raster_bytes(ano_raster_path)
    ano_atual = date.today().year
    tem_fogo = ano_arr != ano_nodata
    anos_desde = np.where(tem_fogo, ano_atual - ano_arr, np.nan)

    bonus = np.where(tem_fogo, bonus_por_ano(anos_desde), 0.0)
    bonus_final = np.where(np.ones_like(bonus, dtype=bool), bonus, gs.GRID_NODATA)
    # Nota: ao contrario de outras variaveis do Indice V, aqui NAO ha
    # mascara de Portugal Continental a aplicar -- o bonus e 0.0 (nao
    # NoData) em qualquer celula sem fogo proximo, replicando a funcao
    # original (devolve 0.0, nunca None, quando nao ha area ardida perto).

    n_com_fogo = int(np.sum(tem_fogo))
    print(f"Celulas com bonus > 0 (fogo a {BUFFER_M}m nos ultimos anos): {n_com_fogo}")
    for escalao, desc in [(0.25, "<=2 anos"), (0.15, "2-4 anos"), (0.05, ">4 anos")]:
        n = int(np.sum(bonus == escalao))
        print(f"  Bonus {escalao} ({desc}): {n} celulas")

    escrever_geotiff(bonus_final, output_path)

    os.remove(reprojetado_path)
    os.remove(ano_raster_path)
    print(f"Concluido: {output_path}")


if __name__ == "__main__":
    main()
