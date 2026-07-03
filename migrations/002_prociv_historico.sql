-- Migration 002: Histórico de transições de estado das ocorrências PROCIV
-- 3 Jul 2026. Aditiva. Idempotente.
-- Objetivo: guardar a trajetória de estados (Despacho -> Em Curso -> Conclusão...)
-- que o UPSERT em fogos.py sobrepõe. Permite derivar hora de dominado e duração.

CREATE TABLE IF NOT EXISTS prociv_estado_historico (
    id              SERIAL PRIMARY KEY,
    external_id     VARCHAR(50) NOT NULL,
    estado_anterior VARCHAR(50),
    estado_novo     VARCHAR(50) NOT NULL,
    momento         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Índice para consultar rapidamente a trajetória de uma ocorrência
CREATE INDEX IF NOT EXISTS idx_prociv_hist_extid ON prociv_estado_historico(external_id);
CREATE INDEX IF NOT EXISTS idx_prociv_hist_momento ON prociv_estado_historico(momento);
