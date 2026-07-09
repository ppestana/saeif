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
SENSITIVITY_NORMALIZATION = "minmax"  # decidido com base na distribuicao real (assimetria moderada, 0.65,
                                        # apos ponderacao por confianca -- ver saeif_architecture.html)
SENSITIVITY_LOWER_BOUND = 0.0
SENSITIVITY_PERCENTILE = 99.0  # reservado para futuras variaveis da Sensibilidade que precisem de saturacao

SENSITIVITY_WEIGHT_ELDERLY = 0.65
SENSITIVITY_WEIGHT_CHILDREN = 0.35
SENSITIVITY_WEIGHT_METHOD = "literature-based (initial)"
# Os pesos NAO sao derivados matematicamente do risco relativo observado na
# literatura (ex. idosos 65+ com risco de mortalidade em incendio 2.2-2.9x
# superior a populacao geral, FEMA/USFA 2014-2023). Essa evidencia justifica
# QUE os idosos devem ter peso superior as criancas, nao O VALOR exato do
# peso -- o peso de uma variavel num indice multicriterio depende tambem de
# correlacao, redundancia, variabilidade espacial e calibracao do modelo,
# nao so do risco relativo individual. Os valores 0.65/0.35 sao uma decisao
# de modelacao informada pela evidencia disponivel para esta primeira
# versao operacional -- provisorios, sujeitos a recalibracao futura
# (regressao, Random Forest, SHAP, analise de sensibilidade) quando houver
# dados suficientes. Quando isso acontecer, actualizar tambem
# SENSITIVITY_WEIGHT_METHOD para "calibrated".

SENSITIVITY_CONFIDENCE_N0 = 50.0  # populacao de referencia (pessoas) para peso de confianca total

# Numero minimo de agregados domesticos para atingir confianca total na
# estimativa de proporcoes calculadas sobre agregados (nao pessoas) --
# ex. proporcao de agregados com 1-2 pessoas (isolamento). Nao reutiliza
# SENSITIVITY_CONFIDENCE_N0 porque agregados e pessoas sao universos
# estatisticos de escala diferente (um agregado tem em media 2-3 pessoas).
# Valor calibrado empiricamente a partir da distribuicao nacional da BGRI
# 2021 (mediana=11, p25=5, p75=22, p90=47, p99=178 agregados por
# subseccao): com N0=25, a mediana fica com peso ~0.44, o p75 com ~0.88,
# e o p90 ja atinge confianca total -- crescimento gradual, sem excesso
# de permissividade (N0=10 daria quase metade do pais em confianca alta)
# nem excesso de penalizacao (N0=50 deixaria so ~10% das subseccoes em
# confianca total).
SENSITIVITY_CONFIDENCE_HOUSEHOLDS_N0 = 25.0
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
