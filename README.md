# saeif
Sistema de Alerta e Encaminhamento Imediato em Incêndios Florestais "Forest fire alerts, before the smoke clears"

## Decisões de arquitectura

### Geração de alertas — confirmação dupla
O SAEIF gera alertas apenas quando existe confirmação cruzada entre uma ocorrência PROCIV (fogos.pt) e um hotspot satelitário FIRMS (VIIRS/MODIS) num raio de 40 km. Ocorrências PROCIV sem hotspot correspondente são registadas na base de dados mas não geram alerta. Esta decisão visa minimizar falsos positivos no PoC.
