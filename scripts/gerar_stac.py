#!/usr/bin/env python3
"""
Gera um catalogo STAC (SpatioTemporal Asset Catalog, v1.0.0) estatico a
partir dos metadados das camadas ja publicadas em data/layers/*.json
(por scripts/publicar_camada.py).

Filosofia: catalogo ESTATICO (so ficheiros JSON, servidos por HTTP) --
o barreira de entrada mais baixa possivel para expor dados como STAC,
conforme a propria especificacao recomenda. Nao requer uma API STAC
dinamica; qualquer cliente STAC (GeoLibre, QGIS, pystac, etc.) consegue
navegar catalog -> collection -> items so seguindo os links.

Estrutura gerada (em BASE_URL/stac/):
    catalog.json                              -- raiz
    collections/saeif-indices/collection.json -- colecao unica (por agora)
    collections/saeif-indices/items/{id}.json -- um Item por camada publicada

Uso:
    python3 gerar_stac.py <base_url>

Exemplo:
    python3 gerar_stac.py https://saeif.terradigital.net
"""
import json
import os
import sys
import glob

LAYERS_DIR = "data/layers"
STAC_DIR = "data/stac"
COLLECTION_ID = "saeif-indices"
STAC_VERSION = "1.0.0"


def ler_camadas_publicadas():
    """Le todos os {id}.json em data/layers/ (metadados gerados por publicar_camada.py)."""
    camadas = []
    for path in sorted(glob.glob(os.path.join(LAYERS_DIR, "*.json"))):
        with open(path, encoding="utf-8") as f:
            camadas.append(json.load(f))
    return camadas


def gerar_item(camada, base_url):
    """Constroi um STAC Item (GeoJSON Feature) a partir dos metadados de uma camada."""
    item_id = camada["id"]
    item_self = f"{base_url}/stac/collections/{COLLECTION_ID}/items/{item_id}.json"

    assets = {
        "thumbnail": {
            "href": f"{base_url}{camada['png']}",
            "type": "image/png",
            "title": "Visualizacao colorida (PNG)",
            "roles": ["thumbnail"],
        },
    }
    if "cog" in camada:
        assets["data"] = {
            "href": f"{base_url}{camada['cog']}",
            "type": "image/tiff; application=geotiff; profile=cloud-optimized",
            "title": "Dados reais (Cloud Optimized GeoTIFF)",
            "roles": ["data"],
        }

    return {
        "stac_version": STAC_VERSION,
        "type": "Feature",
        "id": item_id,
        "bbox": camada.get("bbox"),
        "geometry": camada.get("geometry"),
        "properties": {
            "datetime": f"{camada['created']}T00:00:00Z",
            "title": camada["title"],
            "description": camada["description"],
            "saeif:min": camada.get("min"),
            "saeif:max": camada.get("max"),
            "saeif:resolution_m": camada.get("resolution_m"),
            "saeif:source_raster": camada.get("source_raster"),
        },
        "collection": COLLECTION_ID,
        "links": [
            {"rel": "self", "href": item_self, "type": "application/geo+json"},
            {"rel": "root", "href": f"{base_url}/stac/catalog.json", "type": "application/json"},
            {"rel": "collection", "href": f"{base_url}/stac/collections/{COLLECTION_ID}/collection.json",
             "type": "application/json"},
            {"rel": "parent", "href": f"{base_url}/stac/collections/{COLLECTION_ID}/collection.json",
             "type": "application/json"},
        ],
        "assets": assets,
    }


def gerar_collection(camadas, base_url):
    """Constroi a STAC Collection, com extensao espacial/temporal derivada das camadas reais."""
    if not camadas:
        raise ValueError("Nenhuma camada publicada em data/layers/ -- nada para catalogar.")

    todos_bbox = [c["bbox"] for c in camadas if "bbox" in c]
    lon_min = min(b[0] for b in todos_bbox)
    lat_min = min(b[1] for b in todos_bbox)
    lon_max = max(b[2] for b in todos_bbox)
    lat_max = max(b[3] for b in todos_bbox)

    datas = sorted(c["created"] for c in camadas)
    data_min, data_max = datas[0], datas[-1]

    collection_self = f"{base_url}/stac/collections/{COLLECTION_ID}/collection.json"

    return {
        "stac_version": STAC_VERSION,
        "type": "Collection",
        "id": COLLECTION_ID,
        "title": "SAEIF -- Indices de Risco de Incendio Florestal",
        "description": (
            "Indices geoespaciais do Sistema de Alerta e Encaminhamento Imediato "
            "em Incendios Florestais (SAEIF), TerraDigital -- Suscetibilidade de "
            "Ignicao (Indice I), Potencial de Propagacao (Indice P), e "
            "Vulnerabilidade (Indice V), grelha oficial 250m/EPSG:3763, "
            "Portugal Continental."
        ),
        "license": "proprietary",
        "providers": [
            {
                "name": "TerraDigital",
                "roles": ["producer", "processor", "host"],
                "url": "https://terradigital.net",
            }
        ],
        "extent": {
            "spatial": {"bbox": [[lon_min, lat_min, lon_max, lat_max]]},
            "temporal": {"interval": [[f"{data_min}T00:00:00Z", f"{data_max}T00:00:00Z"]]},
        },
        "summaries": {
            "saeif:source_raster": sorted(set(c.get("source_raster", "") for c in camadas)),
        },
        "links": [
            {"rel": "self", "href": collection_self, "type": "application/json"},
            {"rel": "root", "href": f"{base_url}/stac/catalog.json", "type": "application/json"},
            {"rel": "parent", "href": f"{base_url}/stac/catalog.json", "type": "application/json"},
        ] + [
            {
                "rel": "item",
                "href": f"{base_url}/stac/collections/{COLLECTION_ID}/items/{c['id']}.json",
                "type": "application/geo+json",
            }
            for c in camadas
        ],
    }


def gerar_catalog(base_url):
    """Constroi o STAC Catalog raiz."""
    return {
        "stac_version": STAC_VERSION,
        "type": "Catalog",
        "id": "saeif-catalog",
        "title": "SAEIF -- Catalogo STAC",
        "description": (
            "Catalogo de dados geoespaciais do SAEIF (Sistema de Alerta e "
            "Encaminhamento Imediato em Incendios Florestais), TerraDigital. "
            "Catalogo estatico STAC v1.0.0 -- explorabel por qualquer cliente "
            "STAC (GeoLibre, QGIS, pystac, etc.)."
        ),
        "links": [
            {"rel": "self", "href": f"{base_url}/stac/catalog.json", "type": "application/json"},
            {"rel": "root", "href": f"{base_url}/stac/catalog.json", "type": "application/json"},
            {
                "rel": "child",
                "href": f"{base_url}/stac/collections/{COLLECTION_ID}/collection.json",
                "type": "application/json",
            },
        ],
    }


def main():
    if len(sys.argv) != 2:
        print("Uso: python3 gerar_stac.py <base_url>")
        print("Exemplo: python3 gerar_stac.py https://saeif.terradigital.net")
        sys.exit(1)

    base_url = sys.argv[1].rstrip("/")

    print(f"A ler camadas publicadas de {LAYERS_DIR}/ ...")
    camadas = ler_camadas_publicadas()
    print(f"{len(camadas)} camada(s) encontrada(s): {[c['id'] for c in camadas]}")

    items_dir = os.path.join(STAC_DIR, "collections", COLLECTION_ID, "items")
    os.makedirs(items_dir, exist_ok=True)

    print("A gerar Items STAC ...")
    for camada in camadas:
        item = gerar_item(camada, base_url)
        item_path = os.path.join(items_dir, f"{camada['id']}.json")
        with open(item_path, "w", encoding="utf-8") as f:
            json.dump(item, f, indent=2, ensure_ascii=False)
        print(f"  {item_path}")

    print("A gerar Collection STAC ...")
    collection = gerar_collection(camadas, base_url)
    collection_path = os.path.join(STAC_DIR, "collections", COLLECTION_ID, "collection.json")
    with open(collection_path, "w", encoding="utf-8") as f:
        json.dump(collection, f, indent=2, ensure_ascii=False)
    print(f"  {collection_path}")

    print("A gerar Catalog STAC (raiz) ...")
    catalog = gerar_catalog(base_url)
    catalog_path = os.path.join(STAC_DIR, "catalog.json")
    with open(catalog_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
    print(f"  {catalog_path}")

    print("Concluido.")


if __name__ == "__main__":
    main()
