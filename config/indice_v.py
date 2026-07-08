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

# --- Sensibilidade (reservado, nao implementado) ---
SENSITIVITY_PERCENTILE = 99.0

# --- Capacidade de resposta (reservado, nao implementado) ---
RESPONSE_PERCENTILE = 99.0

# --- Validacao automatica ---
VALIDATION_EXPORT_HISTOGRAM = True
VALIDATION_EXPORT_STATISTICS = True
VALIDATION_MIN_TOLERANCE = -1e-6   # minimo aceite (tolerancia numerica abaixo de 0)
VALIDATION_MAX_TOLERANCE = 1.0 + 1e-6  # maximo aceite (tolerancia numerica acima de 1)
