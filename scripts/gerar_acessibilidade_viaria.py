#!/usr/bin/env python3
"""
Gera a camada de Acessibilidade (Capacidade de Resposta, Indice V) a
partir da rede viaria OpenStreetMap (extrato Geofabrik, campo 'fclass'),
para a grelha oficial do SAEIF (250m, EPSG:3763).

Metodo:
    1. Atribui um peso de acessibilidade operacional a cada classe de via
       (fclass), reflectindo a utilidade real para veiculos de combate a
       incendio -- nao um valor cientifico, uma decisao de modelacao
       documentada (ver saeif_architecture.html). Vias exclusivamente
       pedonais/ciclaveis sao excluidas (footway, path, steps, pedestrian,
       cycleway, bridleway, unknown).
    2. Reprojeta para EPSG:3763, ORDENANDO por peso ASCENDENTE.
    3. Rasteriza para a grelha oficial (250m) numa unica passagem: como o
       gdal_rasterize desenha as features pela ordem em que aparecem na
       camada, sobrepondo a anterior, ordenar por peso ascendente faz com
       que a via de MAIOR peso "vença" em celulas onde varias vias se
       cruzam ou sao vizinhas dentro da mesma celula -- confirmado por
       teste deliberado antes de aplicar aos dados reais (uma celula com
       um cruzamento de vias de pesos 0.1 e 0.9 fica correctamente com
       0.9, o melhor acesso disponivel nessa celula).

Uso:
    python3 gerar_acessibilidade_viaria.py <osm.gpkg> <camada> <output.tif>
"""
import subprocess
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config"))
import grid_spec as gs

# Pesos de acessibilidade operacional por fclass (Geofabrik/OSM).
# Decisao de modelacao (nao medicao cientifica) -- ver saeif_architecture.html.
PESOS = {
    "track_grade1": 1.00,
    "track_grade2": 0.90,
    "track": 0.80,
    "track_grade3": 0.70,
    "service": 0.70,
    "unclassified": 0.65,
    "tertiary": 0.60,
    "tertiary_link": 0.55,
    "residential": 0.50,
    "track_grade4": 0.45,
    "secondary": 0.40,
    "secondary_link": 0.35,
    "living_street": 0.30,
    "track_grade5": 0.25,
    "primary": 0.20,
    "primary_link": 0.18,
    "trunk": 0.10,
    "trunk_link": 0.09,
    "motorway_link": 0.06,
    "motorway": 0.05,
    "busway": 0.10,
}
# Excluidas explicitamente: footway, path, steps, pedestrian, cycleway,
# bridleway, unknown -- sem acesso viavel para veiculos de combate.


def main():
    if len(sys.argv) != 4:
        print("Uso: python3 gerar_acessibilidade_viaria.py <osm.gpkg> <camada> <output.tif>")
        sys.exit(1)

    gpkg_path, camada, output_path = sys.argv[1:4]

    gs.assert_grid_consistency()

    reprojetado_path = output_path + ".reprojetado.gpkg"

    case_when = " ".join(
        f"WHEN '{fclass}' THEN {peso}" for fclass, peso in PESOS.items()
    )
    fclasses_incluidas = "', '".join(PESOS.keys())

    sql = (
        f"SELECT *, CASE fclass {case_when} END AS peso "
        f"FROM {camada} "
        f"WHERE fclass IN ('{fclasses_incluidas}') "
        f"ORDER BY peso ASC"
    )

    print(f"A reprojetar {camada} para {gs.GRID_CRS}, atribuir pesos, "
          f"ordenar por peso ascendente ...")
    cmd_reproj = [
        "ogr2ogr", "-f", "GPKG",
        "-t_srs", gs.GRID_CRS,
        "-dialect", "SQLite",
        "-sql", sql,
        "-nln", "vias_pesadas",
        "-overwrite",
        reprojetado_path, gpkg_path,
    ]
    resultado = subprocess.run(cmd_reproj, capture_output=True, text=True)
    if resultado.returncode != 0:
        print(f"ERRO no ogr2ogr (codigo {resultado.returncode}):")
        print(f"stdout: {resultado.stdout}")
        print(f"stderr: {resultado.stderr}")
        sys.exit(1)
    print("Reprojecao, pesos e ordenacao concluidos.")

    print(f"A rasterizar (max por celula, via da ordenacao) para a grelha oficial "
          f"({gs.GRID_NCOLS}x{gs.GRID_NROWS}) ...")
    cmd_rasterize = [
        "gdal_rasterize",
        "-a", "peso",
        "-a_nodata", str(gs.GRID_NODATA),
        "-init", str(gs.GRID_NODATA),
        "-ot", "Float32",
        "-te", str(gs.GRID_XMIN), str(gs.GRID_YMIN), str(gs.GRID_XMAX), str(gs.GRID_YMAX),
        "-tr", str(gs.GRID_RESOLUTION), str(gs.GRID_RESOLUTION),
        "-co", "COMPRESS=LZW",
        "-co", "TILED=YES",
        reprojetado_path, output_path,
    ]
    resultado = subprocess.run(cmd_rasterize, capture_output=True, text=True)
    if resultado.returncode != 0:
        print(f"ERRO no gdal_rasterize (codigo {resultado.returncode}):")
        print(f"stdout: {resultado.stdout}")
        print(f"stderr: {resultado.stderr}")
        sys.exit(1)
    print(resultado.stdout)

    os.remove(reprojetado_path)
    print(f"Concluido: {output_path}")


if __name__ == "__main__":
    main()
