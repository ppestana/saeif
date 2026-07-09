# ------------------------------------------------------
# Indice V - Configuracao Geral
# ------------------------------------------------------
# Estrutura por dominio (config/indice_v.py), preparada para os tres
# subcomponentes do modelo PREFER (ver saeif_visao_2.0.html Sec06):
# Exposicao, Sensibilidade, Capacidade de Resposta. So Exposicao esta
# implementada por agora; os restantes ficam como parametros reservados.

# --- Exposicao ---
EXPOSURE_NORMALIZATION = "percentile"  # "percentile" | "minmax" | "robust" | "log" (so "percentile" implementado)
EXPOSURE_PERCENTILE = 99.0  # limite superior de saturacao (percentil, calculado dentro da mascara de Portugal)
EXPOSURE_LOWER_BOUND = 0.0  # limite inferior fixo (populacao/edificado sao fisicamente >= 0)

EXPOSURE_WEIGHT_POPULATION = 0.50
EXPOSURE_WEIGHT_BUILT_AREA = 0.50

# --- Sensibilidade ---
SENSITIVITY_PERCENTILE = 99.0
SENSITIVITY_CONFIDENCE_N0 = 50.0  # populacao de referencia para peso de confianca total
# Proporcoes calculadas sobre populacoes pequenas (denominador n) sao
# estatisticamente instaveis (variancia de uma proporcao cresce quando n
# diminui). Em vez de um limiar fixo (que criaria descontinuidades
# artificiais entre celulas vizinhas), pondera-se o valor pela confianca:
#   peso = min(N_INDIVIDUOS / SENSITIVITY_CONFIDENCE_N0, 1.0)
#   valor_final = proporcao * peso
# Uma celula com 100% idosos mas so 2 habitantes fica com peso ~0.04 (quase
# anulada); uma celula com 100% idosos e 50+ habitantes mantem peso 1.0.
# NOTA: isto amortece o CONTRIBUTO de proporcoes de baixa confianca para
# perto de zero -- nao e um shrinkage Bayesiano verdadeiro (nao aproxima a
# proporcao da media regional). Para uso num indice de sensibilidade a
# incendio, e uma escolha defensavel e simples: incerteza => sinal fraco,
# nao incerteza => valor "corrigido".

# --- Capacidade de resposta (reservado, nao implementado) ---
RESPONSE_PERCENTILE = 99.0

# --- Validacao automatica ---
VALIDATION_EXPORT_HISTOGRAM = True
VALIDATION_EXPORT_STATISTICS = True
VALIDATION_MIN_TOLERANCE = -1e-6   # minimo aceite (tolerancia numerica abaixo de 0)
VALIDATION_MAX_TOLERANCE = 1.0 + 1e-6  # maximo aceite (tolerancia numerica acima de 1)
