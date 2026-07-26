#!/usr/bin/env python3
"""
Testa candidatas concretas a funcao de integracao Risco = f(I, P, V, M)
contra o conjunto de dados de validacao (data/dataset_validacao.csv --
4763 incendios reais, ver saeif_especificacao_cientifica.html Sec05).

RESSALVA CONCEPTUAL IMPORTANTE: todas as linhas deste conjunto de dados
sao incendios que JA OCORRERAM -- a ignicao esta condicionada (ja
aconteceu em todas as linhas). Nao testamos aqui o papel do Indice I
como "probabilidade de ignicao" -- testamos uma pergunta distinta:
dado que um fogo comecou, que combinacao de I/P/V/M explica melhor a
area que ardeu (area_ha, a variavel de resultado)?

Normalizacao do FWI (M): min-max, escolhido a partir da distribuicao
real observada (assimetria=1.046 -- moderada, muito abaixo da Exposicao
do Indice V que usou percentil 99 com assimetria 18.84; FWI e variavel
fisica continua onde o extremo e o proprio fenomeno, nao ruido de
amostra pequena -- mesmo criterio ja usado para a Sensibilidade,
assimetria 0.65, min-max).

Correlacao usada: Spearman (por postos), nao Pearson -- robusta a
relacoes nao-lineares e invariante a qualquer transformacao monotona da
variavel de resultado (nao e preciso decidir se transformar area_ha
por log antes de correlacionar). Mesma tecnica ja usada em
scripts/analisar_correlacao.py e scripts/gerar_declive_comparacao.py.

Uso:
    python3 testar_candidatas_integracao.py <dataset_validacao.csv>
"""
import sys
import csv
import numpy as np


def pearson(x, y):
    return float(np.corrcoef(x, y)[0, 1])


def spearman(x, y):
    """Correlacao de Spearman = Pearson sobre os postos (ranks)."""
    rank_x = np.argsort(np.argsort(x))
    rank_y = np.argsort(np.argsort(y))
    return pearson(rank_x.astype(np.float64), rank_y.astype(np.float64))


def normalizar_minmax(x):
    return (x - x.min()) / (x.max() - x.min())


def calcular_auc(scores, classe_binaria):
    """AUC via estatistica de Mann-Whitney (soma de postos), sem depender
    de sklearn -- mesma metrica ja usada na validacao holdout do Indice I
    (AUC 0.86). classe_binaria: array booleano (True = classe positiva,
    ex. 'fogo grande')."""
    n_pos = int(np.sum(classe_binaria))
    n_neg = len(classe_binaria) - n_pos
    if n_pos == 0 or n_neg == 0:
        return None
    postos = np.argsort(np.argsort(scores)) + 1  # postos de 1 a N
    soma_postos_positivos = np.sum(postos[classe_binaria])
    auc = (soma_postos_positivos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
    return float(auc)


def main():
    if len(sys.argv) != 2:
        print("Uso: python3 testar_candidatas_integracao.py <dataset_validacao.csv>")
        sys.exit(1)

    caminho = sys.argv[1]

    with open(caminho) as f:
        linhas = list(csv.DictReader(f))

    I = np.array([float(l["indice_i"]) for l in linhas])
    P = np.array([float(l["indice_p"]) for l in linhas])
    V = np.array([float(l["indice_v"]) for l in linhas])
    FWI = np.array([float(l["fwi"]) for l in linhas])
    area_ha = np.array([float(l["area_ha"]) for l in linhas])

    print(f"n = {len(linhas)} incendios reais")
    print()

    # I nao esta na escala 0-1 (KDE bruto, max~0.06) -- normalizar tambem,
    # min-max, para ser comparavel nas formulas com P/V/M (que ja estao 0-1)
    I_norm = normalizar_minmax(I)
    M_norm = normalizar_minmax(FWI)

    print("=== Correlacao individual de cada variavel com area_ha (Spearman) ===")
    for nome, arr in [("Indice I (normalizado)", I_norm), ("Indice P", P),
                      ("Indice V", V), ("FWI/M (normalizado)", M_norm)]:
        rho = spearman(arr, area_ha)
        print(f"  {nome:<24} rho={rho:+.4f}")
    print()

    # --- Candidatas a Hazard = f(I, P, M) ---
    candidatas_hazard = {
        "H_soma_IPM (media)":        (I_norm + P + M_norm) / 3,
        "H_produto_IPM":             I_norm * P * M_norm,
        "H_PM (P modulado por M, sem I)": P * M_norm,
        "H_soma_PM (media, sem I)":  (P + M_norm) / 2,
    }

    print("=== Candidatas a Hazard = f(I,P,M) -- correlacao com area_ha ===")
    resultados_hazard = {}
    for nome, h in candidatas_hazard.items():
        rho = spearman(h, area_ha)
        resultados_hazard[nome] = (h, rho)
        print(f"  {nome:<36} rho={rho:+.4f}")
    print()

    # --- Candidatas a Risco = f(Hazard, V), para cada Hazard testado ---
    print("=== Candidatas a Risco = f(Hazard,V) -- correlacao com area_ha ===")
    print(f"{'Hazard usado':<36} {'R=H*V':>10} {'R=H+V':>10} {'R=(H+V)/2':>10} {'R=H (sem V)':>12}")
    for nome_h, (h, _) in resultados_hazard.items():
        r_produto = spearman(h * V, area_ha)
        r_soma = spearman(h + V, area_ha)
        r_media = spearman((h + V) / 2, area_ha)
        r_sem_v = spearman(h, area_ha)
        print(f"{nome_h:<36} {r_produto:>+10.4f} {r_soma:>+10.4f} {r_media:>+10.4f} {r_sem_v:>+12.4f}")

    print()
    print("Nota: rho mais proximo de +1 = melhor concordancia com a area ardida real.")
    print("Ressalva: todas as linhas ja sao incendios ocorridos -- isto testa a relacao")
    print("com a GRAVIDADE (area ardida), nao com a probabilidade de ignicao em si.")

    # --- Analise binaria por limiar (recomendacao de consultoria externa, 26 Jul 2026) ---
    LIMIAR_HA = 100.0
    grande = area_ha > LIMIAR_HA
    n_grandes = int(np.sum(grande))
    n_pequenos = len(grande) - n_grandes

    print()
    print(f"=== ANALISE BINARIA: fogo grande (area_ha > {LIMIAR_HA}) vs. pequeno ===")
    print(f"Fogos grandes: {n_grandes} ({100*n_grandes/len(grande):.1f}%) | "
          f"Fogos pequenos: {n_pequenos} ({100*n_pequenos/len(grande):.1f}%)")
    print()
    print("AUC de cada candidata a discriminar fogo grande vs. pequeno "
          "(0.5=sem poder discriminativo, 1.0=perfeito, mesma metrica do holdout do Indice I):")
    print()

    print("--- Variaveis individuais ---")
    for nome, arr in [("Indice I (normalizado)", I_norm), ("Indice P", P),
                      ("Indice V", V), ("FWI/M (normalizado)", M_norm)]:
        auc = calcular_auc(arr, grande)
        print(f"  {nome:<24} AUC={auc:.4f}")

    print()
    print("--- Candidatas a Hazard ---")
    for nome, (h, _) in resultados_hazard.items():
        auc = calcular_auc(h, grande)
        print(f"  {nome:<36} AUC={auc:.4f}")

    print()
    print(f"{'Hazard usado':<36} {'R=H*V':>10} {'R=H+V':>10} {'R=(H+V)/2':>10} {'R=H (sem V)':>12}")
    for nome_h, (h, _) in resultados_hazard.items():
        auc_produto = calcular_auc(h * V, grande)
        auc_soma = calcular_auc(h + V, grande)
        auc_media = calcular_auc((h + V) / 2, grande)
        auc_sem_v = calcular_auc(h, grande)
        print(f"{nome_h:<36} {auc_produto:>10.4f} {auc_soma:>10.4f} {auc_media:>10.4f} {auc_sem_v:>12.4f}")


if __name__ == "__main__":
    main()
