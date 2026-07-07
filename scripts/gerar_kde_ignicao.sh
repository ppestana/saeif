#!/bin/bash
# scripts/gerar_kde_ignicao.sh
#
# Gera o Indice I (Suscetibilidade de Ignicao) - superficie KDE - em tres
# bandwidths (1000/2000/3000 m) para comparacao e validacao, a partir dos
# centroides de ignicao ja extraidos de areas_ardidas.
#
# Uso:
#   ./scripts/gerar_kde_ignicao.sh
#
# Pre-requisitos:
#   - venv_kde criado em /srv/saeif/venv_kde (numpy+scipy, --system-site-packages para gdal)
#   - data/ignicoes_centroides.geojson ja extraido (ver sessao de decisao do Indice I)
#   - config/grid_spec.py (especificacao oficial da grelha SAEIF)

set -e

cd "$(dirname "$0")/.."

source venv_kde/bin/activate

INPUT_GEOJSON="data/ignicoes_centroides.geojson"
OUTPUT_DIR="data/indice_i"

if [ ! -f "$INPUT_GEOJSON" ]; then
    echo "ERRO: $INPUT_GEOJSON nao encontrado. Corre primeiro a extracao dos centroides (ogr2ogr)."
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

for BW in 1000 2000 3000; do
    echo "=== Bandwidth ${BW}m ==="
    python3 scripts/gerar_kde_ignicao.py "$INPUT_GEOJSON" "$BW" "$OUTPUT_DIR/indice_i_kde_bw${BW}m.tif"
    echo
done

echo "Todos os rasters gerados em $OUTPUT_DIR/"
ls -la "$OUTPUT_DIR/"
