#!/usr/bin/env python3
"""
Obtem o DEM (Copernicus DEM GLO-30, via Sentinel Hub Process API) para
uso no Indice P -- fonte comum para as duas variantes de calculo do
declive comparadas em gerar_declive_comparacao.py (metodo antigo,
graus+np.gradient, vs. metodo novo, gdaldem slope em metros).

Mesma tecnica de duas etapas ja usada em gerar_ndvi_indice_p.py: a API
do Sentinel Hub nao suporta EPSG:3763 como CRS de saida -- pedido feito
em EPSG:3035 (ETRS89/LAEA Europe, suportado), resolucao 300m (250m
excede o limite sincrono de 2500px dado a distorcao real entre TM06 e
LAEA nesta extensao -- ver gerar_ndvi_indice_p.py para o calculo).

Uso:
    python3 gerar_dem_indice_p.py <output.tif>

Requisitos: CDSE_USER e CDSE_PASSWORD no ambiente (.env).
"""
import os
import sys
import httpx
from dotenv import load_dotenv
from pyproj import Transformer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config"))
import grid_spec as gs

load_dotenv()

CDSE_TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
SH_PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"

REQUEST_CRS_EPSG = 3035
REQUEST_RESOLUTION_M = 300
REQUEST_BUFFER_M = 5000

EVALSCRIPT = (
    '//VERSION=3\n'
    'function setup(){return{input:[{bands:["DEM"]}],output:{bands:1,sampleType:"FLOAT32"}}}\n'
    'function evaluatePixel(s){return[s.DEM]}'
)


def get_token():
    user = os.getenv("CDSE_USER")
    pwd = os.getenv("CDSE_PASSWORD")
    if not user or not pwd:
        raise ValueError("CDSE_USER e CDSE_PASSWORD nao definidos no .env")
    with httpx.Client(timeout=30) as c:
        r = c.post(CDSE_TOKEN_URL, data={
            "grant_type": "password", "username": user,
            "password": pwd, "client_id": "cdse-public",
        })
        r.raise_for_status()
        return r.json()["access_token"]


def calcular_bbox_3035():
    """Identico ao de gerar_ndvi_indice_p.py -- mesma grelha oficial, mesma margem."""
    transformer = Transformer.from_crs("EPSG:3763", f"EPSG:{REQUEST_CRS_EPSG}", always_xy=True)
    cantos = [
        (gs.GRID_XMIN, gs.GRID_YMIN), (gs.GRID_XMAX, gs.GRID_YMIN),
        (gs.GRID_XMIN, gs.GRID_YMAX), (gs.GRID_XMAX, gs.GRID_YMAX),
    ]
    xs, ys = [], []
    for x, y in cantos:
        tx, ty = transformer.transform(x, y)
        xs.append(tx)
        ys.append(ty)
    return (min(xs) - REQUEST_BUFFER_M, min(ys) - REQUEST_BUFFER_M,
            max(xs) + REQUEST_BUFFER_M, max(ys) + REQUEST_BUFFER_M)


def main():
    if len(sys.argv) != 2:
        print("Uso: python3 gerar_dem_indice_p.py <output.tif>")
        sys.exit(1)

    output_path = sys.argv[1]

    gs.assert_grid_consistency()

    print(f"A calcular bbox em EPSG:{REQUEST_CRS_EPSG} ...")
    xmin, ymin, xmax, ymax = calcular_bbox_3035()
    width = int((xmax - xmin) / REQUEST_RESOLUTION_M) + 1
    height = int((ymax - ymin) / REQUEST_RESOLUTION_M) + 1
    print(f"  Bbox: [{xmin:.1f}, {ymin:.1f}, {xmax:.1f}, {ymax:.1f}]")
    print(f"  Dimensoes: {width}x{height}px a {REQUEST_RESOLUTION_M}m")
    if width > 2500 or height > 2500:
        print(f"ERRO: dimensoes excedem o limite sincrono da API (2500x2500).")
        sys.exit(1)

    print("A obter token Copernicus ...")
    token = get_token()
    print("Token obtido.")

    payload = {
        "input": {
            "bounds": {
                "bbox": [xmin, ymin, xmax, ymax],
                "properties": {"crs": f"http://www.opengis.net/def/crs/EPSG/0/{REQUEST_CRS_EPSG}"},
            },
            "data": [{"type": "dem", "dataFilter": {"demInstance": "COPERNICUS_30"}}],
        },
        "output": {
            "width": width, "height": height,
            "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}],
        },
        "evalscript": EVALSCRIPT,
    }

    print(f"A pedir DEM (Copernicus GLO-30) em EPSG:{REQUEST_CRS_EPSG} ...")
    with httpx.Client(timeout=180) as c:
        r = c.post(SH_PROCESS_URL, json=payload, headers={"Authorization": f"Bearer {token}"})
        if r.status_code != 200:
            print(f"ERRO: status {r.status_code} -- corpo: {r.text[:1000]}")
            sys.exit(1)
        if r.content[:2] not in (b"II", b"MM"):
            print(f"ERRO: resposta nao e TIFF -- {r.content[:200]}")
            sys.exit(1)
        with open(output_path, "wb") as f:
            f.write(r.content)

    print(f"DEM guardado em {output_path} ({len(r.content)//1024}KB, EPSG:{REQUEST_CRS_EPSG})")
    print("NOTA: este ficheiro fica em EPSG:3035, NAO reprojectado -- e a fonte comum")
    print("para os dois metodos de calculo do declive comparados a seguir.")
    print("Concluido.")


if __name__ == "__main__":
    main()
