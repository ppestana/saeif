#!/usr/bin/env python3
"""
Validacao holdout temporal do Indice I: treina o KDE so com ignicoes ate um
ano de corte, testa contra ignicoes reais de anos posteriores (nunca vistas
pelo modelo), e calcula a curva de concentracao ("Prediction Rate Curve" na
literatura de suscetibilidade a incendios, ex. Jaafari et al. 2019): que
fracao das ignicoes de teste cai dentro da fracao mais suscetivel da area,
segundo o modelo treinado so com o passado.

Sem isto, comparar o KDE contra os mesmos pontos que o geraram seria
circular (o modelo estaria a "prever" os pontos que ja conhece). Aqui as
ignicoes de teste nunca entram na construcao da superficie.

Nota sobre a area de referencia: a grelha oficial do SAEIF cobre toda a
Peninsula Iberica (ver config/grid_spec.py), mas a maior parte dessa area
(Espanha, oceano) nunca podera conter uma ignicao dos dados ICNF usados
aqui. Se a curva usasse a grelha inteira como universo de area, o modelo
pareceria artificialmente melhor (grande parte da "area facil de
descartar" nunca teve sequer a possibilidade de conter um ponto). Por isso
a curva restringe-se a uma caixa delimitadora (bounding box) em torno de
TODOS os pontos (treino + teste), com um buffer, garantindo uma
comparacao justa contra um modelo aleatorio.

Interpretacao do resultado (AUC da curva de concentracao):
    ~0.5  -> sem poder preditivo (equivalente a acaso)
    ~0.7+ -> poder preditivo razoavel
    ~0.9+ -> poder preditivo forte
(mesma escala de leitura que uma AUC de curva ROC, ainda que o metodo de
calculo aqui seja o de curva de concentracao area-vs-ocorrencias, nao TPR-vs-FPR)

Uso:
    python3 validar_holdout_temporal.py <geojson_treino> <geojson_teste> <bandwidth_m> [buffer_m]
"""

import sys
import os
import warnings
import numpy as np
from scipy.ndimage import gaussian_filter
from osgeo import ogr, osr

warnings.filterwarnings("ignore", category=FutureWarning, module="osgeo")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config"))
import grid_spec as gs


def ler_pontos_geojson(path):
    """Le pontos de um GeoJSON e reprojeta para EPSG:3763."""
    ds = ogr.Open(path)
    if ds is None:
        raise RuntimeError(f"Nao foi possivel abrir {path}")
    layer = ds.GetLayer()
    layer_srs = layer.GetSpatialRef()

    target_srs = osr.SpatialReference()
    target_srs.ImportFromEPSG(3763)
    target_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    if layer_srs is None:
        source_srs = osr.SpatialReference()
        source_srs.ImportFromEPSG(4326)
    else:
        source_srs = layer_srs
    source_srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)

    transform = osr.CoordinateTransformation(source_srs, target_srs)

    xs, ys = [], []
    for feature in layer:
        geom = feature.GetGeometryRef()
        geom_clone = geom.Clone()
        geom_clone.Transform(transform)
        xs.append(geom_clone.GetX())
        ys.append(geom_clone.GetY())

    return np.array(xs), np.array(ys)


def construir_histograma(xs, ys):
    """Conta pontos por celula da grelha oficial (250m, EPSG:3763)."""
    ncols = gs.GRID_NCOLS
    nrows = gs.GRID_NROWS
    res = gs.GRID_RESOLUTION

    col = np.floor((xs - gs.GRID_XMIN) / res).astype(int)
    row = np.floor((gs.GRID_YMAX - ys) / res).astype(int)

    dentro = (col >= 0) & (col < ncols) & (row >= 0) & (row < nrows)
    n_fora = int(np.sum(~dentro))
    if n_fora > 0:
        print(f"AVISO: {n_fora} pontos fora da grelha oficial, ignorados.")

    hist = np.zeros((nrows, ncols), dtype=np.float64)
    np.add.at(hist, (row[dentro], col[dentro]), 1.0)
    return hist


def main():
    if len(sys.argv) < 4:
        print("Uso: python3 validar_holdout_temporal.py <geojson_treino> <geojson_teste> <bandwidth_m> [buffer_m]")
        sys.exit(1)

    treino_path = sys.argv[1]
    teste_path = sys.argv[2]
    bandwidth_m = float(sys.argv[3])
    buffer_m = float(sys.argv[4]) if len(sys.argv) > 4 else 20000.0

    gs.assert_grid_consistency()

    print(f"A ler pontos de treino de {treino_path} ...")
    xs_tr, ys_tr = ler_pontos_geojson(treino_path)
    print(f"{len(xs_tr)} pontos de treino.")

    print(f"A ler pontos de teste de {teste_path} ...")
    xs_te, ys_te = ler_pontos_geojson(teste_path)
    print(f"{len(xs_te)} pontos de teste.")
    print()

    print(f"A construir a superficie KDE so com os pontos de treino (bandwidth={bandwidth_m:.0f}m) ...")
    hist = construir_histograma(xs_tr, ys_tr)
    sigma = bandwidth_m / gs.GRID_RESOLUTION
    kde = gaussian_filter(hist, sigma=sigma, mode="constant", cval=0.0)

    # Area de referencia: bbox de treino+teste, com buffer -- evita que a
    # grelha iberica inteira (Espanha/oceano, sempre ~0) infle o resultado.
    all_x = np.concatenate([xs_tr, xs_te])
    all_y = np.concatenate([ys_tr, ys_te])
    bbox_xmin = all_x.min() - buffer_m
    bbox_xmax = all_x.max() + buffer_m
    bbox_ymin = all_y.min() - buffer_m
    bbox_ymax = all_y.max() + buffer_m

    col_min = max(0, int((bbox_xmin - gs.GRID_XMIN) / gs.GRID_RESOLUTION))
    col_max = min(gs.GRID_NCOLS, int((bbox_xmax - gs.GRID_XMIN) / gs.GRID_RESOLUTION) + 1)
    row_min = max(0, int((gs.GRID_YMAX - bbox_ymax) / gs.GRID_RESOLUTION))
    row_max = min(gs.GRID_NROWS, int((gs.GRID_YMAX - bbox_ymin) / gs.GRID_RESOLUTION) + 1)

    n_celulas_area = (row_max - row_min) * (col_max - col_min)
    print(f"Area de referencia (bbox treino+teste + buffer {buffer_m:.0f}m): "
          f"{n_celulas_area} celulas ({row_max-row_min} x {col_max-col_min}).")

    kde_area = kde[row_min:row_max, col_min:col_max]
    flat = kde_area.flatten()
    n_celulas = len(flat)

    # Ranking por posicao (nao por valor): evita que empates em celulas de
    # densidade exactamente zero (fora do alcance do kernel) inflacionem
    # artificialmente a captura quando o limiar de valor cai em zero.
    ordem = np.argsort(-flat, kind="stable")  # indices ordenados por densidade decrescente
    rank = np.empty(n_celulas, dtype=np.int64)
    rank[ordem] = np.arange(n_celulas)  # rank 0 = celula mais suscetivel
    rank_area = rank.reshape(kde_area.shape)

    col_te = np.floor((xs_te - gs.GRID_XMIN) / gs.GRID_RESOLUTION).astype(int) - col_min
    row_te = np.floor((gs.GRID_YMAX - ys_te) / gs.GRID_RESOLUTION).astype(int) - row_min

    dentro = (
        (col_te >= 0) & (col_te < (col_max - col_min))
        & (row_te >= 0) & (row_te < (row_max - row_min))
    )
    n_fora = int(np.sum(~dentro))
    if n_fora > 0:
        print(f"AVISO: {n_fora} pontos de teste fora da area de referencia, ignorados.")

    rank_teste = rank_area[row_te[dentro], col_te[dentro]]
    n_teste_validos = len(rank_teste)
    print(f"{n_teste_validos} pontos de teste dentro da area de referencia.")
    print()

    fracoes_area = [0.01, 0.02, 0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0]

    print(f"{'% area (mais suscetivel)':>28} | {'% ignicoes capturadas':>24}")
    resultados = []
    for p in fracoes_area:
        limiar_rank = int(p * n_celulas) - 1
        limiar_rank = max(0, min(limiar_rank, n_celulas - 1))
        capturados = int(np.sum(rank_teste <= limiar_rank))
        pct_capturados = 100.0 * capturados / n_teste_validos if n_teste_validos > 0 else 0.0
        resultados.append((p * 100, pct_capturados))
        print(f"{p * 100:>26.0f}% | {pct_capturados:>22.1f}%")

    xs_curve = [0.0] + [r[0] / 100.0 for r in resultados]
    ys_curve = [0.0] + [r[1] / 100.0 for r in resultados]

    # Integracao trapezoidal manual (evita depender de np.trapz/np.trapezoid,
    # cujo nome mudou entre versoes do numpy).
    auc = 0.0
    for i in range(1, len(xs_curve)):
        largura = xs_curve[i] - xs_curve[i - 1]
        altura_media = (ys_curve[i] + ys_curve[i - 1]) / 2.0
        auc += largura * altura_media

    print()
    print(f"AUC da curva de concentracao: {auc:.4f} (0.5 = aleatorio, 1.0 = perfeito)")


if __name__ == "__main__":
    main()
