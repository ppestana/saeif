#!/usr/bin/env python3
"""
Publica um raster do SAEIF como camada visualizavel E como asset STAC:
gera um PNG colorido (visualizacao rapida, Leaflet), um COG (Cloud
Optimized GeoTIFF -- dados reais, para consumo por GeoLibre, QGIS, ou
qualquer cliente STAC), e um ficheiro JSON de metadados (bounds sempre
calculados automaticamente a partir do proprio GeoTIFF, nunca escritos
a mao).

Filosofia: infraestrutura generica de publicacao, nao um caso especial
por indice. Qualquer raster do SAEIF (Indice I, P, V, KDE por causa,
NDVI, declive, ...) publica-se da mesma forma, com o mesmo script.

Uso:
    python3 publicar_camada.py <raster.tif> <id> <titulo> <descricao> <rampa.txt> [opacidade]

Exemplo:
    python3 publicar_camada.py data/indice_i/indice_i_kde_producao_bw3500m.tif \\
        indice_i "Indice I - Suscetibilidade de Ignicao" \\
        "KDE sobre ignicoes 2020-2025, bandwidth 3500m, validado AUC 0.86" \\
        rampas/indice_i.txt 0.8

Saida (em data/layers/):
    {id}.png   -- imagem colorida, EPSG:4326 (visualizacao Leaflet)
    {id}.tif   -- Cloud Optimized GeoTIFF, EPSG:4326 (dados reais, asset STAC)
    {id}.json  -- metadados (bounds, bbox, geometry, min, max, resolucao, fonte, data)
"""
import json
import subprocess
import sys
import os
from datetime import date

from osgeo import gdal, osr

OUTPUT_DIR = "data/layers"


def obter_info_raster(path):
    ds = gdal.Open(path)
    if ds is None:
        raise RuntimeError(f"Nao foi possivel abrir {path}")
    gt = ds.GetGeoTransform()
    ncols, nrows = ds.RasterXSize, ds.RasterYSize
    xmin = gt[0]
    ymax = gt[3]
    xmax = xmin + ncols * gt[1]
    ymin = ymax + nrows * gt[5]  # gt[5] e negativo

    srs = osr.SpatialReference()
    srs.ImportFromWkt(ds.GetProjection())

    return {
        "xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax,
        "ncols": ncols, "nrows": nrows,
        "srs": srs,
        "pixel_size": abs(gt[1]),
    }


def calcular_bounds_4326(info):
    """Calcula os bounds em EPSG:4326. Devolve tanto o formato Leaflet
    ([[lat_min,lon_min],[lat_max,lon_max]]) como o bbox STAC
    ([lon_min,lat_min,lon_max,lat_max]) e a geometry GeoJSON (Polygon)."""
    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(4326)
    target_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    source_srs = info["srs"]
    source_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    transform = osr.CoordinateTransformation(source_srs, target_srs)

    # Transformar os 4 cantos (nao so 2, para CRS com rotacao/distorcao)
    cantos = [
        (info["xmin"], info["ymin"]), (info["xmax"], info["ymin"]),
        (info["xmin"], info["ymax"]), (info["xmax"], info["ymax"]),
    ]
    lons, lats = [], []
    for x, y in cantos:
        lon, lat, _ = transform.TransformPoint(x, y)
        lons.append(lon)
        lats.append(lat)

    lat_min, lat_max = min(lats), max(lats)
    lon_min, lon_max = min(lons), max(lons)

    bounds_leaflet = [[lat_min, lon_min], [lat_max, lon_max]]
    bbox_stac = [lon_min, lat_min, lon_max, lat_max]
    geometry_stac = {
        "type": "Polygon",
        "coordinates": [[
            [lon_min, lat_min], [lon_max, lat_min],
            [lon_max, lat_max], [lon_min, lat_max],
            [lon_min, lat_min],
        ]],
    }
    return bounds_leaflet, bbox_stac, geometry_stac


def obter_min_max(path):
    """Usa gdalinfo -stats para obter min/max reais (evita problemas de ABI numpy/gdal_array)."""
    resultado = subprocess.run(
        ["gdalinfo", "-stats", path], capture_output=True, text=True
    )
    vmin, vmax = None, None
    for linha in resultado.stdout.splitlines():
        if "Minimum=" in linha and "Maximum=" in linha:
            partes = linha.strip().split(",")
            for p in partes:
                if "Minimum=" in p:
                    vmin = float(p.split("=")[1])
                if "Maximum=" in p:
                    vmax = float(p.split("=")[1])
    return vmin, vmax


def gerar_reprojetado(raster_path, temp_path):
    """Reprojeta o raster original para EPSG:4326 (fonte comum ao PNG e ao COG)."""
    cmd_warp = ["gdalwarp", "-t_srs", "EPSG:4326", "-r", "near", "-overwrite",
                raster_path, temp_path]
    subprocess.run(cmd_warp, capture_output=True, text=True, check=True)


def gerar_png(reprojetado_path, rampa_path, output_png):
    """Aplica a rampa de cor ao raster ja reprojetado, gerando o PNG de visualizacao."""
    colorido = output_png + ".color.tif"

    cmd_color = ["gdaldem", "color-relief", reprojetado_path, rampa_path, colorido, "-alpha"]
    subprocess.run(cmd_color, capture_output=True, text=True, check=True)

    cmd_translate = ["gdal_translate", "-of", "PNG", colorido, output_png]
    subprocess.run(cmd_translate, capture_output=True, text=True, check=True)

    os.remove(colorido)
    aux_path = output_png + ".aux.xml"
    if os.path.exists(aux_path):
        os.remove(aux_path)


def gerar_cog(reprojetado_path, output_cog):
    """Converte o raster reprojetado (dados reais, sem cor) para Cloud
    Optimized GeoTIFF -- o asset recomendado pelo STAC para dados raster."""
    cmd_cog = [
        "gdal_translate", "-of", "COG",
        "-co", "COMPRESS=DEFLATE",
        "-co", "BLOCKSIZE=512",
        reprojetado_path, output_cog,
    ]
    subprocess.run(cmd_cog, capture_output=True, text=True, check=True)


def main():
    if len(sys.argv) not in (6, 7):
        print("Uso: python3 publicar_camada.py <raster.tif> <id> <titulo> <descricao> <rampa.txt> [opacidade]")
        sys.exit(1)

    raster_path, camada_id, titulo, descricao, rampa_path = sys.argv[1:6]
    opacidade = float(sys.argv[6]) if len(sys.argv) == 7 else 0.8

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    png_path = os.path.join(OUTPUT_DIR, f"{camada_id}.png")
    cog_path = os.path.join(OUTPUT_DIR, f"{camada_id}.tif")
    json_path = os.path.join(OUTPUT_DIR, f"{camada_id}.json")
    reprojetado_path = os.path.join(OUTPUT_DIR, f"{camada_id}.4326.tmp.tif")

    print(f"A ler informacao de {raster_path} ...")
    info = obter_info_raster(raster_path)

    print("A calcular bounds/bbox/geometry em EPSG:4326 (a partir do GeoTIFF, nao escritos a mao) ...")
    bounds, bbox, geometry = calcular_bounds_4326(info)
    print(f"  Bounds (Leaflet): {bounds}")
    print(f"  Bbox (STAC): {bbox}")

    print("A obter min/max reais ...")
    vmin, vmax = obter_min_max(raster_path)
    print(f"  Min={vmin}, Max={vmax}")

    print("A reprojetar para EPSG:4326 (fonte comum ao PNG e ao COG) ...")
    gerar_reprojetado(raster_path, reprojetado_path)

    print(f"A gerar PNG (visualizacao) em {png_path} ...")
    gerar_png(reprojetado_path, rampa_path, png_path)

    print(f"A gerar COG (dados reais, asset STAC) em {cog_path} ...")
    gerar_cog(reprojetado_path, cog_path)

    os.remove(reprojetado_path)

    metadados = {
        "id": camada_id,
        "title": titulo,
        "description": descricao,
        "bounds": bounds,
        "bbox": bbox,
        "geometry": geometry,
        "min": vmin,
        "max": vmax,
        "resolution_m": info["pixel_size"],
        "crs_original": info["srs"].GetAuthorityCode(None) or "desconhecido",
        "opacity": opacidade,
        "source_raster": os.path.basename(raster_path),
        "png": f"/layers/{camada_id}.png",
        "cog": f"/layers/{camada_id}.tif",
        "created": date.today().isoformat(),
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(metadados, f, indent=2, ensure_ascii=False)

    print(f"Metadados escritos em {json_path}")
    print(json.dumps(metadados, indent=2, ensure_ascii=False))
    print("Concluido.")


if __name__ == "__main__":
    main()
