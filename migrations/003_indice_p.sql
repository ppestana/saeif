-- Migration 003: Índice P explícito na tabela alertas
-- 7 Jul 2026. Aditiva. Idempotente.
-- Objetivo: destilar o Índice P (Potencial de Propagação) como campo explícito
-- e nomeado, em vez de ficar implícito dentro do score. Corrige também uma
-- inconsistência de sincronização identificada em alerts.py: o campo
-- risco_estrutural era calculado sem o bónus de área ardida (get_structural_risk
-- sozinho), enquanto o score já incluía esse bónus desde a introdução de
-- area_ardida_factor — as duas chamadas divergiram ao longo do desenvolvimento
-- incremental, sem ser uma decisão deliberada (confirmado via git log).
--
-- indice_p = get_structural_risk() + area_ardida_factor, capado a 1.0
-- (o Índice P completo tal como documentado em saeif_visao_2.0.html §06).
--
-- risco_estrutural mantém-se como está (combustível/vegetação puro, sem
-- histórico de fogo) para não quebrar a continuidade do histórico já
-- gravado; indice_p é o novo campo canónico, sem ambiguidade de nome.

ALTER TABLE alertas ADD COLUMN IF NOT EXISTS indice_p NUMERIC(4,3);

COMMENT ON COLUMN alertas.indice_p IS
    'Índice P (Potencial de Propagação) explícito: get_structural_risk() + area_ardida_factor, capado a 1.0. Ver saeif_visao_2.0.html §06 e saeif_architecture.html §07.';

COMMENT ON COLUMN alertas.risco_estrutural IS
    'Componente de combustível/vegetação (WorldCover+NDVI+declive), SEM o bónus de área ardida. Sub-componente do Índice P, não o valor completo. Ver indice_p para o valor completo usado no score.';
