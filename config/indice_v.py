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

SENSITIVITY_WEIGHT_METHOD = "literature-based (initial), hierarchical by sub-dimension"

# --- Subdimensao: Vulnerabilidade Demografica (estrutura etaria) ---
# A literatura sobre mortalidade em incendios documenta risco relativo
# consistentemente mais elevado para idosos (65+) do que para criancas --
# mas os valores exactos dos pesos (0.65/0.35) sao uma decisao de
# modelacao informada por essa evidencia, nao uma derivacao matematica
# do risco relativo (ex. idosos 65+ com risco de mortalidade em incendio
# 2.2-2.9x superior a populacao geral, FEMA/USFA 2014-2023). Idosos e
# criancas medem a MESMA dimensao (estrutura etaria), por isso competem
# entre si por 100% do peso desta subdimensao.
SENSITIVITY_DEMOGRAPHIC_WEIGHT_ELDERLY = 0.65
SENSITIVITY_DEMOGRAPHIC_WEIGHT_CHILDREN = 0.35

# --- Subdimensao: Vulnerabilidade Social (dimensao independente da demografica) ---
# Isolamento (proporcao de agregados domesticos com 1-2 pessoas) e, por
# agora, o unico componente desta subdimensao -- peso 1.0. Quando outras
# variaveis sociais forem adicionadas (escolaridade, rendimento,
# deficiencia, acesso a transportes), os pesos redistribuem-se DENTRO
# desta subdimensao, sem afectar a subdimensao demografica nem os pesos
# de combinacao final (ver abaixo).
SENSITIVITY_SOCIAL_WEIGHT_ISOLATION = 1.00

# --- Combinacao das subdimensoes na Sensibilidade final ---
# Peso igual entre as duas grandes dimensoes -- nao ha evidencia
# cientifica forte o suficiente para justificar um desequilibrio entre
# vulnerabilidade demografica e vulnerabilidade social, por isso
# privilegia-se o principio simples de peso identico. Esta e a decisao
# que fica estavel a longo prazo, mesmo que os pesos DENTRO de cada
# subdimensao mudem com novas variaveis.
SENSITIVITY_WEIGHT_DEMOGRAPHIC = 0.50
SENSITIVITY_WEIGHT_SOCIAL = 0.50

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
