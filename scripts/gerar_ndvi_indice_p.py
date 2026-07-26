#!/usr/bin/env python3
"""
Gera o NDVI (Sentinel-2, via Sentinel Hub Process API) directamente na
grelha oficial do SAEIF (250m, EPSG:3763) -- para uso no Indice P como
raster de superficie (nao o lookup pontual em tempo real de
api/ingest/ndvi.py, que continua a servir o score.py a ~2km).

Decisao (17 Jul 2026, ver parecer registado em saeif_especificacao_cientifica.html
Sec02): o pipeline em tempo real do score.py estava limitado a 340x532px
por ter de ser rapido (consulta a cada alerta). Este script e offline,
reprocessado periodicamente -- sem essa restricao, pelo que se pede
directamente perto da resolucao oficial (250m), nao 2km nem 10m.

CORRECCAO IMPORTANTE (17 Jul 2026): a API do Sentinel Hub NAO suporta
EPSG:3763 como CRS de saida (confirmado por erro 400 "Unsupported CRS
value" e pela lista oficial em
https://documentation.dataspace.copernicus.eu/APIs/SentinelHub/Process/Crs.html).
Pedido feito em EPSG:3035 (ETRS89/LAEA Europe, suportado -- o mesmo CRS
ja usado para a grelha INE), reprojectado depois para a grelha oficial
via gdalwarp -- mesmo padrao de duas etapas ja usado para GHSL/CAOP/INE.

Mesmo evalscript do api/ingest/ndvi.py (formula NDVI identica, mascara de
nuvens identica) -- so a grelha de saida muda. Guarda o NDVI em BRUTO
(nao a "factor de risco" normalizado que o score.py calcula em
get_ndvi_factor) -- Principio da Separacao Analitica: a normalizacao
para o Indice P e feita ao combinar, nao aqui.

Uso:
    python3 gerar_ndvi_indice_p.py <output.tif>

Requisitos: CDSE_USER e CDSE_PASSWORD no ambiente (.env), grelha oficial
dentro do limite de pedido sincrono da Process API (max. 2500x2500px).
"""
import os
import sys
import subprocess
import httpx
from dotenv import load_dotenv
from pyproj import Transformer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config"))
import grid_spec as gs

load_dotenv()

CDSE_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
SH_PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"

REQUEST_CRS_EPSG = 3035  # ETRS89 / LAEA Europe -- suportado pela API (3763 nao e)
REQUEST_RESOLUTION_M = 300  # 250m excede o limite de 2500px (distorcao real entre TM06 e LAEA aumenta o bbox); 300m confirma-se dentro do limite (1440x2189px)
REQUEST_BUFFER_M = 5000  # margem de seguranca para nao cortar bordas apos reprojeccao

# Mesmo evalscript de api/ingest/ndvi.py -- formula NDVI e mascara de
# nuvens identicas, so a grelha de saida muda.
EVALSCRIPT = """//VERSION=3
function setup() {
  return {
    input: [{bands: ["B04", "B08", "SCL"]}],
    output: {bands: 1, sampleType: "FLOAT32"}
  }
}
function evaluatePixel(s) {
  if ([8,9,10].includes(s.SCL)) return [-9999];
  var ndvi = (s.B08 - s.B04) / (s.B08 + s.B04 + 0.0001);
  return [ndvi];
}
"""


def get_token():
    user = os.getenv("CDSE_USER")
    pwd = os.getenv("CDSE_PASSWORD")
    if not user or not pwd:
        raise ValueError("CDSE_USER e CDSE_PASSWORD nao definidos no .env")
    with httpx.Client(timeout=30) as c:
        r = c.post(CDSE_TOKEN_URL, data={
            "grant_type": "password",
            "username": user,
            "password": pwd,
            "client_id": "cdse-public",
        })
        r.raise_for_status()
        return r.json()["access_token"]


def calcular_bbox_3035():
    """Calcula o bbox da grelha oficial (EPSG:3763) reprojectado para
    EPSG:3035, com margem de seguranca, a partir dos 4 cantos (nao so 2,
    por causa de possivel rotacao entre CRS)."""
    transformer = Transformer.from_crs(
        f"EPSG:3763", f"EPSG:{REQUEST_CRS_EPSG}", always_xy=True
    )

    cantos = [
        (gs.GRID_XMIN, gs.GRID_YMIN), (gs.GRID_XMAX, gs.GRID_YMIN),
        (gs.GRID_XMIN, gs.GRID_YMAX), (gs.GRID_XMAX, gs.GRID_YMAX),
    ]
    xs, ys = [], []
    for x, y in cantos:
        tx, ty = transformer.transform(x, y)
        xs.append(tx)
        ys.append(ty)

    xmin = min(xs) - REQUEST_BUFFER_M
    xmax = max(xs) + REQUEST_BUFFER_M
    ymin = min(ys) - REQUEST_BUFFER_M
    ymax = max(ys) + REQUEST_BUFFER_M
    return xmin, ymin, xmax, ymax


def main():
    if len(sys.argv) != 2:
        print("Uso: python3 gerar_ndvi_indice_p.py <output.tif>")
        sys.exit(1)

    output_path = sys.argv[1]
    temp_3035_path = output_path + ".3035.tmp.tif"

    gs.assert_grid_consistency()

    print(f"A calcular bbox em EPSG:{REQUEST_CRS_EPSG} (a partir da grelha oficial, com margem "
          f"de {REQUEST_BUFFER_M}m) ...")
    xmin, ymin, xmax, ymax = calcular_bbox_3035()
    largura_m = xmax - xmin
    altura_m = ymax - ymin
    width = int(largura_m / REQUEST_RESOLUTION_M) + 1
    height = int(altura_m / REQUEST_RESOLUTION_M) + 1
    print(f"  Bbox: [{xmin:.1f}, {ymin:.1f}, {xmax:.1f}, {ymax:.1f}]")
    print(f"  Dimensoes pedidas: {width}x{height}px a {REQUEST_RESOLUTION_M}m")
    if width > 2500 or height > 2500:
        print(f"ERRO: dimensoes ({width}x{height}) excedem o limite sincrono da API (2500x2500). "
              f"Aumentar REQUEST_RESOLUTION_M ou dividir o pedido em blocos.")
        sys.exit(1)

    from datetime import date, timedelta
    date_to = date.today().isoformat() + "T23:59:59Z"
    date_from = (date.today() - timedelta(days=20)).isoformat() + "T00:00:00Z"

    print("A obter token Copernicus ...")
    token = get_token()
    print("Token obtido.")

    payload = {
        "input": {
            "bounds": {
                "bbox": [xmin, ymin, xmax, ymax],
                "properties": {"crs": f"http://www.opengis.net/def/crs/EPSG/0/{REQUEST_CRS_EPSG}"},
            },
            "data": [{
                "type": "sentinel-2-l2a",
                "dataFilter": {
                    "maxCloudCoverage": 30,
                    "timeRange": {"from": date_from, "to": date_to},
                },
                "processing": {"mosaickingOrder": "leastCC"},
            }],
        },
        "output": {
            "width": width,
            "height": height,
            "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}],
        },
        "evalscript": EVALSCRIPT,
    }

    print(f"A pedir NDVI em EPSG:{REQUEST_CRS_EPSG} (janela {date_from[:10]} a {date_to[:10]}) ...")
    with httpx.Client(timeout=180) as c:
        r = c.post(SH_PROCESS_URL, json=payload, headers={"Authorization": f"Bearer {token}"})
        if r.status_code != 200:
            print(f"ERRO: status {r.status_code} -- corpo: {r.text[:1000]}")
            sys.exit(1)

        if r.content[:2] not in (b"II", b"MM"):
            print(f"ERRO: resposta nao e TIFF -- {r.content[:200]}")
            sys.exit(1)

        with open(temp_3035_path, "wb") as f:
            f.write(r.content)

    size_kb = len(r.content) // 1024
    print(f"NDVI (EPSG:{REQUEST_CRS_EPSG}) guardado em {temp_3035_path} ({size_kb}KB)")

    print(f"A reprojectar para a grelha oficial ({gs.GRID_NCOLS}x{gs.GRID_NROWS}px, "
          f"{gs.GRID_CRS}, {gs.GRID_RESOLUTION}m) ...")
    cmd_warp = [
        "gdalwarp",
        "-t_srs", gs.GRID_CRS,
        "-te", str(gs.GRID_XMIN), str(gs.GRID_YMIN), str(gs.GRID_XMAX), str(gs.GRID_YMAX),
        "-tr", str(gs.GRID_RESOLUTION), str(gs.GRID_RESOLUTION),
        "-r", "bilinear",
        "-srcnodata", "-9999", "-dstnodata", "-9999",
        "-overwrite",
        temp_3035_path, output_path,
    ]
    resultado = subprocess.run(cmd_warp, capture_output=True, text=True)
    if resultado.returncode != 0:
        print(f"ERRO no gdalwarp: {resultado.stderr}")
        sys.exit(1)

    os.remove(temp_3035_path)

    # Confirmar georreferenciacao real do ficheiro final, nao assumir
    from osgeo import gdal
    ds = gdal.Open(output_path)
    print(f"Confirmacao final: {ds.RasterXSize}x{ds.RasterYSize}px, "
          f"GeoTransform={ds.GetGeoTransform()}")
    esperado = (gs.GRID_NCOLS, gs.GRID_NROWS)
    obtido = (ds.RasterXSize, ds.RasterYSize)
    if obtido != esperado:
        print(f"AVISO: dimensoes finais ({obtido}) != esperadas ({esperado})")
    print(f"Concluido: {output_path}")


if __name__ == "__main__":
    main()
