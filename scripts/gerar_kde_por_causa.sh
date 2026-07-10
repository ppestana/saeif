#!/bin/bash
# scripts/gerar_kde_por_causa.sh
#
# Gera as camadas analiticas do Indice I desagregadas por causa de ignicao
# (Negligente, Intencional, Desconhecida). Estas camadas NAO entram no
# calculo do Indice I oficial (que se mantem agregado, sem alteracao) --
# sao produtos analiticos complementares, preservando a estrutura espacial
# distinta que cada categoria de causa revelou ter (ver saeif_architecture.html,
# analise de correlacao Negligente/Intencional/Desconhecida, 10 Jul 2026).
#
# Uso:
#   ./scripts/gerar_kde_por_causa.sh
#
# Pre-requisitos: venv_kde activo, ligacao a BD (127.0.0.1:5434).

set -e

cd "$(dirname "$0")/.."

source venv_kde/bin/activate

mkdir -p data/indice_i

BANDWIDTH=3500  # mesmo bandwidth validado por LOO-CV do Indice I oficial

for CAUSA in Negligente Intencional Desconhecida; do
    echo "=== Causa: ${CAUSA} ==="

    GEOJSON="data/ignicoes_${CAUSA}.geojson"
    OUTPUT="data/indice_i/indice_i_${CAUSA,,}.tif"

    echo "A extrair centroides (causa_tipo = '${CAUSA}') ..."
    rm -f "$GEOJSON"
    ogr2ogr -f GeoJSON "$GEOJSON" \
        PG:"host=127.0.0.1 port=5434 dbname=saeif user=saeif password=saeif_db_2026" \
        -sql "SELECT id, ano, ST_Centroid(geom) AS geom FROM areas_ardidas WHERE causa_tipo = '${CAUSA}'" \
        -nln "ignicoes_${CAUSA}"

    echo "A gerar KDE (bandwidth=${BANDWIDTH}m) ..."
    python3 scripts/gerar_kde_ignicao.py "$GEOJSON" "$BANDWIDTH" "$OUTPUT"

    echo
done

echo "Concluido. Camadas geradas em data/indice_i/:"
ls -la data/indice_i/indice_i_negligente.tif data/indice_i/indice_i_intencional.tif data/indice_i/indice_i_desconhecida.tif
