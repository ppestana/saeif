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
directamente a resolucao oficial (250m), nao 2km nem 10m.

Mesmo evalscript do api/ingest/ndvi.py (formula NDVI identica, mascara de
nuvens identica) -- so a grelha de saida muda. Guarda o NDVI em BRUTO
(nao a "factor de risco" normalizado que o score.py calcula em
get_ndvi_factor) -- Principio da Separacao Analitica: a normalizacao
para o Indice P e feita ao combinar, nao aqui.

Uso:
    python3 gerar_ndvi_indice_p.py <output.tif>

Requisitos: CDSE_USER e CDSE_PASSWORD no ambiente (.env), grelha oficial
dentro do limite de pedido sincrono da Process API (max. 2500x2500px --
a nossa grelha, 1213x2359, cabe).
"""
import os
import sys
import httpx
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config"))
import grid_spec as gs

load_dotenv()

CDSE_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
SH_PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"

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


def main():
    if len(sys.argv) != 2:
        print("Uso: python3 gerar_ndvi_indice_p.py <output.tif>")
        sys.exit(1)

    output_path = sys.argv[1]

    gs.assert_grid_consistency()

    from datetime import date, timedelta
    date_to = date.today().isoformat() + "T23:59:59Z"
    date_from = (date.today() - timedelta(days=20)).isoformat() + "T00:00:00Z"

    print("A obter token Copernicus ...")
    token = get_token()
    print("Token obtido.")

    payload = {
        "input": {
            "bounds": {
                "bbox": [gs.GRID_XMIN, gs.GRID_YMIN, gs.GRID_XMAX, gs.GRID_YMAX],
                "properties": {"crs": f"http://www.opengis.net/def/crs/EPSG/0/{gs.GRID_CRS.split(':')[1]}"},
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
            "width": gs.GRID_NCOLS,
            "height": gs.GRID_NROWS,
            "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}],
        },
        "evalscript": EVALSCRIPT,
    }

    print(f"A pedir NDVI na grelha oficial ({gs.GRID_NCOLS}x{gs.GRID_NROWS}px, "
          f"{gs.GRID_CRS}, janela {date_from[:10]} a {date_to[:10]}) ...")
    with httpx.Client(timeout=180) as c:
        r = c.post(SH_PROCESS_URL, json=payload, headers={"Authorization": f"Bearer {token}"})
        r.raise_for_status()

        if r.content[:2] not in (b"II", b"MM"):
            print(f"ERRO: resposta nao e TIFF -- {r.content[:200]}")
            sys.exit(1)

        with open(output_path, "wb") as f:
            f.write(r.content)

    size_kb = len(r.content) // 1024
    print(f"NDVI guardado em {output_path} ({size_kb}KB)")

    # Confirmar georreferenciacao real do ficheiro devolvido, nao assumir
    from osgeo import gdal
    ds = gdal.Open(output_path)
    print(f"Confirmacao: {ds.RasterXSize}x{ds.RasterYSize}px, "
          f"GeoTransform={ds.GetGeoTransform()}")
    esperado = (gs.GRID_NCOLS, gs.GRID_NROWS)
    obtido = (ds.RasterXSize, ds.RasterYSize)
    if obtido != esperado:
        print(f"AVISO: dimensoes devolvidas ({obtido}) != esperadas ({esperado})")
    print("Concluido.")


if __name__ == "__main__":
    main()
