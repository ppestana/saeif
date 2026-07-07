#!/usr/bin/env python3
"""
Validacao cruzada leave-one-out (LOO) para escolher o bandwidth do KDE do Indice I.

Metodo:
    Para cada bandwidth h testado, e para cada ponto de ignicao i, calcula-se a
    densidade estimada em x_i usando um kernel gaussiano 2D, EXCLUINDO o proprio
    ponto i da soma (leave-one-out) - caso contrario cada ponto "prediria a si
    proprio" com peso total, inflacionando artificialmente a verosimilhanca de
    bandwidths pequenos.

    f_hat_{-i}(x_i) = 1/(n-1) * soma_{j != i} K_h(x_i - x_j)

    onde K_h e o kernel gaussiano 2D:
        K_h(d) = 1/(2*pi*h^2) * exp(-d^2 / (2*h^2))

    A log-verosimilhanca LOO total e:
        L(h) = soma_i log(f_hat_{-i}(x_i))

    O bandwidth que MAXIMIZA L(h) e o que melhor prediz cada ponto a partir de
    todos os outros - criterio objetivo, sem circularidade (nenhum ponto e
    usado para prever a si proprio).

Nota: este calculo e feito ponto-a-ponto (matriz de distancias completa,
O(n^2)), independente da grelha de 250m usada para o raster visual do Indice I.
Com ~4750 pontos, a matriz de distancias cabe confortavelmente em memoria.

Nota sobre valores -inf: se um bandwidth testado for muito pequeno face ao
espacamento real entre pontos vizinhos, um ponto isolado pode ficar com
densidade LOO praticamente nula, dando log(0) = -inf. Isto e matematicamente
correto (nao um erro do script) e e, por si so, um sinal de que esse
bandwidth e demasiado pequeno para os dados.

Uso:
    python3 validar_bandwidth_kde.py <geojson_pontos> <bw1> <bw2> <bw3> ...
"""

import sys
import os
import warnings
import numpy as np
from osgeo import ogr, osr

warnings.filterwarnings("ignore", category=FutureWarning, module="osgeo")


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


def log_verosimilhanca_loo(xs, ys, bandwidth_m, chunk_size=1000):
    """
    Calcula a log-verosimilhanca leave-one-out para um dado bandwidth.
    Processa por blocos (chunk_size) para limitar o uso de memoria com n grande.
    """
    n = len(xs)
    coords = np.column_stack([xs, ys])  # (n, 2)

    h2 = bandwidth_m ** 2
    log_norm = np.log(2 * np.pi * h2)  # log da constante de normalizacao do kernel

    log_lik_total = 0.0

    for start in range(0, n, chunk_size):
        end = min(start + chunk_size, n)
        bloco = coords[start:end]  # (b, 2)

        # distancias ao quadrado do bloco a todos os pontos: (b, n)
        d2 = (
            (bloco[:, 0:1] - coords[:, 0]) ** 2
            + (bloco[:, 1:2] - coords[:, 1]) ** 2
        )

        # log-kernel nao normalizado para cada par: -d2 / (2*h2)
        log_kernel = -d2 / (2 * h2)

        # soma das contribuicoes de todos os pontos (incluindo o proprio, d=0)
        # log-sum-exp para estabilidade numerica
        max_log = np.max(log_kernel, axis=1, keepdims=True)
        soma_exp = np.sum(np.exp(log_kernel - max_log), axis=1)
        log_soma_total = (max_log[:, 0] + np.log(soma_exp))  # log(soma incluindo self)

        # remover a contribuicao do proprio ponto (d=0 -> log_kernel=0 -> exp=1)
        # log(soma_total - 1) via expm1 no espaco original para precisao
        soma_total = np.exp(log_soma_total)
        soma_sem_self = soma_total - 1.0  # exp(0) = 1, contribuicao do proprio ponto

        # log f_hat_{-i}(x_i) = log(soma_sem_self) - log(n-1) - log_norm
        with np.errstate(divide="ignore"):
            log_f_hat = np.log(soma_sem_self) - np.log(n - 1) - log_norm

        log_lik_total += np.sum(log_f_hat)

    return log_lik_total


def main():
    if len(sys.argv) < 3:
        print("Uso: python3 validar_bandwidth_kde.py <geojson_pontos> <bw1> [bw2] [bw3] ...")
        sys.exit(1)

    geojson_path = sys.argv[1]
    bandwidths = [float(b) for b in sys.argv[2:]]

    print(f"A ler pontos de {geojson_path} ...")
    xs, ys = ler_pontos_geojson(geojson_path)
    n = len(xs)
    print(f"{n} pontos lidos e reprojetados para EPSG:3763.")
    print()

    resultados = []
    for bw in bandwidths:
        print(f"A calcular log-verosimilhanca LOO para bandwidth={bw:.0f}m ...")
        ll = log_verosimilhanca_loo(xs, ys, bw)
        ll_media = ll / n
        resultados.append((bw, ll, ll_media))
        print(f"  Log-verosimilhanca total: {ll:.2f}")
        print(f"  Log-verosimilhanca media por ponto: {ll_media:.4f}")
        print()

    print("=== Resumo ===")
    print(f"{'Bandwidth (m)':>15} | {'LL total':>15} | {'LL media/ponto':>15}")
    for bw, ll, ll_media in resultados:
        print(f"{bw:>15.0f} | {ll:>15.2f} | {ll_media:>15.4f}")

    melhor = max(resultados, key=lambda r: r[1])
    print()
    print(f"Bandwidth com maior log-verosimilhanca LOO (melhor previsao): {melhor[0]:.0f}m")


if __name__ == "__main__":
    main()
