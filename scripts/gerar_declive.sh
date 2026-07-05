#!/bin/bash
# SAEIF 2.0 - Geracao da camada de declive (fator estrutural 1)
# Piloto Viseu (5 Jul 2026). Processa DEM no HOST com GDAL (BD intocada).
# Uso: ./gerar_declive.sh    (requer gdaldem, gdal_translate, wget no host)
set -e

TILE="Copernicus_DSM_COG_10_N40_00_W009_00_DEM"   # tile 1°x1° que cobre Viseu (40-41N, 8-9W)
LAT_SCALE=111320                                   # graus->metros na latitude ~40.7 (correcao gdaldem)
WORKDIR="/tmp/dem_piloto"
OUTDIR="/srv/saeif/data/layers"

mkdir -p "$WORKDIR" && cd "$WORKDIR"

# 1. Obter DEM do bucket publico AWS (Copernicus GLO-30, DSM 30m)
wget -q "https://copernicus-dem-30m.s3.amazonaws.com/${TILE}/${TILE}.tif" -O dem.tif

# 2. Calcular declive (graus), com correcao de escala graus->metros
gdaldem slope dem.tif slope.tif -s "$LAT_SCALE" -compute_edges

# 3. Aplicar simbologia discreta (4 classes, sem interpolacao)
cat > colors.txt << 'CEOF'
0    46 204 113 90
5    241 196 15 170
15   230 126 34 210
25   192 57 43 240
90   120 20 20 255
CEOF
gdaldem color-relief slope.tif colors.txt slope_rgba.tif -alpha -nearest_color_entry

# 4. PNG web otimizado (1200px, compressao maxima) -> pasta servida
mkdir -p "$OUTDIR"
gdal_translate -of PNG -outsize 1200 1200 -co ZLEVEL=9 slope_rgba.tif "$OUTDIR/viseu_slope_web.png"

echo "OK: $OUTDIR/viseu_slope_web.png (cantos geograficos: [[40,-9],[41,-8]])"
