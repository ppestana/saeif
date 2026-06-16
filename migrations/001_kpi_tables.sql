-- Migration 001: Tabelas de KPIs (deteção precoce SAEIF vs PROCIV)
-- 12 Jun 2026. Aditiva. Idempotente (IF NOT EXISTS).

-- Agregados por período (semanal | anual | cumulativo_anual)
CREATE TABLE IF NOT EXISTS kpi_periodos (
    id                   SERIAL PRIMARY KEY,
    tipo                 VARCHAR(20) NOT NULL,          -- 'semanal' | 'anual' | 'cumulativo_anual'
    periodo_inicio       DATE NOT NULL,
    periodo_fim          DATE NOT NULL,
    ano                  INTEGER NOT NULL,
    total_pares          INTEGER NOT NULL DEFAULT 0,
    saeif_primeiro       INTEGER NOT NULL DEFAULT 0,
    simultaneo           INTEGER NOT NULL DEFAULT 0,
    prociv_primeiro      INTEGER NOT NULL DEFAULT 0,
    pct_saeif_primeiro   NUMERIC(5,2),
    antecedencia_media_h NUMERIC(6,2),
    calculado_em         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tipo, periodo_inicio, periodo_fim)
);

-- Detalhe auditável: um registo por par alerta↔PROCIV que entrou no cálculo
CREATE TABLE IF NOT EXISTS kpi_detalhe (
    id              SERIAL PRIMARY KEY,
    kpi_periodo_id  INTEGER NOT NULL REFERENCES kpi_periodos(id) ON DELETE CASCADE,
    alerta_id       INTEGER,
    hotspot_id      INTEGER,
    prociv_id       INTEGER,
    deteccao_sat    TIMESTAMPTZ,
    despacho_prociv TIMESTAMPTZ,
    horas_diff      NUMERIC(8,2),
    hotspot_lat     NUMERIC(9,6),
    hotspot_lon     NUMERIC(9,6),
    hotspot_frp     NUMERIC(8,2),
    prociv_lat      NUMERIC(9,6),
    prociv_lon      NUMERIC(9,6),
    distancia_m     NUMERIC(10,1),
    categoria       VARCHAR(12),                        -- 'saeif' | 'simultaneo' | 'prociv'
    localidade      VARCHAR(200)
);

CREATE INDEX IF NOT EXISTS idx_kpi_detalhe_periodo ON kpi_detalhe(kpi_periodo_id);
CREATE INDEX IF NOT EXISTS idx_kpi_periodos_tipo_ano ON kpi_periodos(tipo, ano);
