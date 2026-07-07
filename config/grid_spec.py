"""
Referencial espacial oficial do SAEIF.

Todos os rasters do sistema (Indice I, Indice P, Indice V, meteorologia,
camadas derivadas) devem ser gerados ou reamostrados para obedecer
exatamente a esta grelha: mesmo CRS, mesma resolucao, mesma origem de
pixel, mesma extensao. Isto permite que operacoes como I + P + V sejam
soma direta de matrizes, sem warp/reprojecao/resampling intermedio.

Decisao tomada em: Julho 2026, durante a construcao do Indice I
(primeira camada a implementar esta grelha de facto).

Bbox herdado do artefacto legado slope_norm.tif (EPSG:4326, ~1.1km,
cobertura Iberia: lon -9.5 a -6.1, lat 36.9 a 42.2), reprojetado para
EPSG:3763 e arredondado para fora a multiplos exatos de GRID_RESOLUTION,
garantindo cobertura total sem cortar celulas a meio.

Nota: o bbox cobre toda a Peninsula Iberica por decisao deliberada —
os fogos florestais nao respeitam fronteiras administrativas, e um
incendio pode iniciar-se de um lado e propagar-se para o outro. A
cobertura espanhola do Indice I aparecera hoje como KDE ~0, nao porque
a grelha esteja mal desenhada, mas porque a unica fonte de dados atual
(areas_ardidas, ICNF, Portugal continental) nao tem cobertura do lado
espanhol. A grelha fica pronta para receber uma fonte de dados
adicional (ex. EFFIS/Copernicus, pan-europeia) sem qualquer alteracao
espacial, caso essa integracao venha a acontecer.
"""

# --- Sistema de referencia ---
GRID_CRS = "EPSG:3763"  # ETRS89 / Portugal TM06

# --- Resolucao ---
GRID_RESOLUTION = 250  # metros (principio da variavel limitante, ver saeif_visao_2.0.html)

# --- Extensao (em metros, EPSG:3763) ---
# Calculado a partir do bbox geografico do slope_norm.tif legado,
# reprojetado e arredondado para fora a multiplos de GRID_RESOLUTION.
GRID_XMIN = -122000.0
GRID_YMIN = -306500.0
GRID_XMAX = 181250.0
GRID_YMAX = 283250.0

# --- Dimensoes derivadas (nao editar manualmente) ---
GRID_NCOLS = int((GRID_XMAX - GRID_XMIN) / GRID_RESOLUTION)  # 1213
GRID_NROWS = int((GRID_YMAX - GRID_YMIN) / GRID_RESOLUTION)  # 2359

# --- Convencoes de raster ---
GRID_PIXEL_ORIGIN = "upper-left"
GRID_NODATA = -9999

# --- GeoTransform GDAL (upper-left origin, pixel size positivo em x, negativo em y) ---
# Formato: (xmin, pixel_width, 0, ymax, 0, -pixel_height)
GRID_GEOTRANSFORM = (
    GRID_XMIN,
    GRID_RESOLUTION,
    0,
    GRID_YMAX,
    0,
    -GRID_RESOLUTION,
)


def assert_grid_consistency():
    """Validacao de sanidade a correr no inicio de qualquer script que gere rasters da grelha SAEIF."""
    assert (GRID_XMAX - GRID_XMIN) % GRID_RESOLUTION == 0, "GRID_XMAX-GRID_XMIN nao e multiplo de GRID_RESOLUTION"
    assert (GRID_YMAX - GRID_YMIN) % GRID_RESOLUTION == 0, "GRID_YMAX-GRID_YMIN nao e multiplo de GRID_RESOLUTION"
    assert GRID_NCOLS == 1213, f"GRID_NCOLS inesperado: {GRID_NCOLS}"
    assert GRID_NROWS == 2359, f"GRID_NROWS inesperado: {GRID_NROWS}"


if __name__ == "__main__":
    assert_grid_consistency()
    print(f"Grelha SAEIF: {GRID_NCOLS} x {GRID_NROWS} celulas de {GRID_RESOLUTION}m em {GRID_CRS}")
    print(f"Extensao: ({GRID_XMIN}, {GRID_YMIN}) a ({GRID_XMAX}, {GRID_YMAX})")
