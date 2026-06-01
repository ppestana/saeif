"""
SAEIF — Sistema de Alerta e Encaminhamento Imediato em Incêndios Florestais
TerraDigital · Pedro Pestana · saeif.terradigital.net
"""
import os
import json
import asyncio
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from typing import Optional

import asyncpg
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv

from ingest.firms import fetch_firms
from ingest.fogos import fetch_fogos
from ingest.ipma import fetch_ipma_conditions
from analysis.dedup import dedup_hotspots
from analysis.score import calcular_score
from analysis.alerts import gerar_alertas

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("saeif")

DB_DSN = (
    f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
    f"@{os.getenv('DB_HOST', 'db')}:{os.getenv('DB_PORT', 5432)}/{os.getenv('DB_NAME')}"
)

async def get_db():
    return await asyncpg.connect(DB_DSN)

async def init_db():
    conn = await get_db()
    try:
        await conn.execute("""
            CREATE EXTENSION IF NOT EXISTS postgis;
            CREATE TABLE IF NOT EXISTS hotspots (
                id          SERIAL PRIMARY KEY,
                source      VARCHAR(20) NOT NULL,
                geom        GEOMETRY(POINT, 4326) NOT NULL,
                brightness  NUMERIC(6,2),
                frp         NUMERIC(8,2),
                confidence  VARCHAR(10),
                acq_date    DATE NOT NULL,
                acq_time    TIME NOT NULL,
                fetched_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                processed   BOOLEAN NOT NULL DEFAULT FALSE
            );
            CREATE INDEX IF NOT EXISTS idx_hotspots_geom ON hotspots USING GIST (geom);
            CREATE INDEX IF NOT EXISTS idx_hotspots_date ON hotspots (acq_date, processed);
            CREATE TABLE IF NOT EXISTS ocorrencias_prociv (
                id          SERIAL PRIMARY KEY,
                external_id VARCHAR(50) UNIQUE,
                geom        GEOMETRY(POINT, 4326),
                localidade  VARCHAR(200),
                distrito    VARCHAR(100),
                concelho    VARCHAR(100),
                estado      VARCHAR(50),
                data_hora   TIMESTAMPTZ,
                source_tag  VARCHAR(10) NOT NULL DEFAULT 'SYS',
                fetched_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE INDEX IF NOT EXISTS idx_prociv_geom ON ocorrencias_prociv USING GIST (geom);
            CREATE TABLE IF NOT EXISTS alertas (
                id                  SERIAL PRIMARY KEY,
                geom                GEOMETRY(POINT, 4326) NOT NULL,
                hotspot_id          INTEGER REFERENCES hotspots(id),
                prociv_id           INTEGER REFERENCES ocorrencias_prociv(id),
                score               NUMERIC(5,2) NOT NULL,
                categoria           VARCHAR(10) NOT NULL,
                source_tag          VARCHAR(10) NOT NULL DEFAULT 'SYS',
                temp                NUMERIC(5,1),
                humidade            NUMERIC(5,1),
                vento_vel           NUMERIC(5,1),
                vento_dir           NUMERIC(5,1),
                fwi                 NUMERIC(6,2),
                risco_estrutural    NUMERIC(5,2),
                criado_em           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                notificado          BOOLEAN NOT NULL DEFAULT FALSE
            );
            CREATE INDEX IF NOT EXISTS idx_alertas_geom ON alertas USING GIST (geom);
            CREATE INDEX IF NOT EXISTS idx_alertas_data ON alertas (criado_em, categoria);
            CREATE TABLE IF NOT EXISTS meteo_log (
                id          SERIAL PRIMARY KEY,
                geom        GEOMETRY(POINT, 4326) NOT NULL,
                station_id  VARCHAR(20),
                temp        NUMERIC(5,1),
                humidade    NUMERIC(5,1),
                vento_vel   NUMERIC(5,1),
                vento_dir   NUMERIC(5,1),
                precipitacao NUMERIC(6,2),
                fwi         NUMERIC(6,2),
                valido_em   TIMESTAMPTZ NOT NULL,
                fetched_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS ingest_log (
                id              SERIAL PRIMARY KEY,
                source          VARCHAR(30) NOT NULL,
                started_at      TIMESTAMPTZ NOT NULL,
                ended_at        TIMESTAMPTZ,
                status          VARCHAR(20),
                records_fetched INTEGER,
                records_new     INTEGER,
                error_msg       TEXT
            );
        """)
        log.info("Base de dados inicializada.")
    finally:
        await conn.close()

class WSManager:
    def __init__(self):
        self.connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)
        log.info(f"WebSocket conectado. Total: {len(self.connections)}")

    def disconnect(self, ws: WebSocket):
        self.connections.remove(ws)
        log.info(f"WebSocket desconectado. Total: {len(self.connections)}")

    async def broadcast(self, data: dict):
        msg = json.dumps(data)
        dead = []
        for ws in self.connections:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections.remove(ws)

ws_manager = WSManager()
scheduler = AsyncIOScheduler(timezone="UTC")

async def run_ingest_cycle():
    log.info("── Ciclo de ingest iniciado ──")
    started = datetime.now(timezone.utc)
    conn = await get_db()
    try:
        hotspots_novos = await fetch_firms(conn)
        log.info(f"FIRMS: {hotspots_novos} hotspots novos")
        prociv_novos = await fetch_fogos(conn)
        log.info(f"fogos.pt: {prociv_novos} ocorrencias novas")
        meteo = await fetch_ipma_conditions(conn)
        log.info(f"IPMA: {len(meteo)} estacoes actualizadas")
        pares = await dedup_hotspots(conn)
        log.info(f"Dedup: {len(pares)} pares FIRMS x PROCIV")
        alertas_novos = await gerar_alertas(conn, pares, meteo)
        log.info(f"Alertas gerados: {len(alertas_novos)}")
        if alertas_novos:
            await ws_manager.broadcast({
                "type": "alertas_update",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "count": len(alertas_novos),
                "alertas": alertas_novos
            })
        await conn.execute("""
            INSERT INTO ingest_log (source, started_at, ended_at, status, records_new)
            VALUES ('CYCLE', $1, $2, 'ok', $3)
        """, started, datetime.now(timezone.utc), len(alertas_novos))
    except Exception as e:
        log.error(f"Erro no ciclo de ingest: {e}")
        await conn.execute("""
            INSERT INTO ingest_log (source, started_at, ended_at, status, error_msg)
            VALUES ('CYCLE', $1, $2, 'error', $3)
        """, started, datetime.now(timezone.utc), str(e))
    finally:
        await conn.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("SAEIF a arrancar...")
    await asyncio.sleep(3)
    await init_db()
    scheduler.add_job(run_ingest_cycle, "interval", minutes=15, id="ingest_cycle")
    scheduler.start()
    log.info("Scheduler iniciado.")
    asyncio.create_task(run_ingest_cycle())
    yield
    scheduler.shutdown()
    log.info("SAEIF encerrado.")

app = FastAPI(title="SAEIF API", version="1.0.0", lifespan=lifespan)

@app.get("/api/health")
async def health():
    conn = await get_db()
    try:
        last = await conn.fetchrow(
            "SELECT source, started_at, status, records_new FROM ingest_log ORDER BY id DESC LIMIT 1"
        )
        firms_key = bool(os.getenv("FIRMS_MAP_KEY") and os.getenv("FIRMS_MAP_KEY") != "PLACEHOLDER")
        return {
            "status": "ok",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "firms_configured": firms_key,
            "last_ingest": dict(last) if last else None,
            "ws_connections": len(ws_manager.connections)
        }
    finally:
        await conn.close()

@app.get("/api/alertas")
async def get_alertas(categoria: Optional[str] = None, limit: int = 50):
    conn = await get_db()
    try:
        where = "WHERE criado_em > NOW() - INTERVAL '24 hours'"
        params = []
        if categoria:
            where += " AND categoria = $1"
            params.append(categoria.upper())
        rows = await conn.fetch(f"""
            SELECT a.id, ST_X(a.geom) AS lon, ST_Y(a.geom) AS lat,
                   a.score, a.categoria, a.source_tag,
                   a.temp, a.humidade, a.vento_vel, a.vento_dir, a.fwi,
                   a.risco_estrutural, a.criado_em,
                   h.source AS hotspot_source,
                   p.id IS NOT NULL AS prociv_confirmado,
                   p.localidade AS prociv_localidade,
                   a.localidade_estimada
            FROM alertas a
            LEFT JOIN hotspots h ON h.id = a.hotspot_id
            LEFT JOIN ocorrencias_prociv p ON p.id = a.prociv_id
            {where}
            ORDER BY a.score DESC, a.criado_em DESC LIMIT {limit}
        """, *params)
        features = []
        for r in rows:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                "properties": {
                    "id": r["id"], "score": float(r["score"]),
                    "categoria": r["categoria"], "source_tag": r["source_tag"],
                    "hotspot_source": r["hotspot_source"],
                    "prociv_confirmado": bool(r["prociv_confirmado"]),
                    "localidade_estimada": r["localidade_estimada"] if r.get("localidade_estimada") else None,
                    "meteo": {
                        "temp": float(r["temp"]) if r["temp"] else None,
                        "humidade": float(r["humidade"]) if r["humidade"] else None,
                        "vento_vel": float(r["vento_vel"]) if r["vento_vel"] else None,
                        "vento_dir": float(r["vento_dir"]) if r["vento_dir"] else None,
                        "fwi": float(r["fwi"]) if r["fwi"] else None,
                    },
                    "risco_estrutural": float(r["risco_estrutural"]) if r["risco_estrutural"] else None,
                    "criado_em": r["criado_em"].isoformat(),
                }
            })
        return {"type": "FeatureCollection", "features": features, "count": len(features)}
    finally:
        await conn.close()

@app.get("/api/alertas/{alerta_id}")
async def get_alerta(alerta_id: int):
    conn = await get_db()
    try:
        r = await conn.fetchrow("""
            SELECT a.*, ST_X(a.geom) AS lon, ST_Y(a.geom) AS lat,
                   h.confidence AS hotspot_confidence, h.frp,
                   p.localidade, p.distrito, p.estado AS prociv_estado
            FROM alertas a
            LEFT JOIN hotspots h ON h.id = a.hotspot_id
            LEFT JOIN ocorrencias_prociv p ON p.id = a.prociv_id
            WHERE a.id = $1
        """, alerta_id)
        if not r:
            raise HTTPException(status_code=404, detail="Alerta nao encontrado")
        return dict(r)
    finally:
        await conn.close()

@app.get("/api/hotspots")
async def get_hotspots(limit: int = 100):
    conn = await get_db()
    try:
        rows = await conn.fetch("""
            SELECT id, source, ST_X(geom) AS lon, ST_Y(geom) AS lat,
                   brightness, frp, confidence, acq_date, acq_time
            FROM hotspots
            WHERE fetched_at > NOW() - INTERVAL '24 hours'
            ORDER BY fetched_at DESC LIMIT $1
        """, limit)
        features = []
        for r in rows:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
                "properties": {
                    "id": r["id"], "source": r["source"],
                    "brightness": float(r["brightness"]) if r["brightness"] else None,
                    "frp": float(r["frp"]) if r["frp"] else None,
                    "confidence": r["confidence"],
                    "acq_date": str(r["acq_date"]), "acq_time": str(r["acq_time"]),
                }
            })
        return {"type": "FeatureCollection", "features": features, "count": len(features)}
    finally:
        await conn.close()

@app.get("/api/status")
async def get_status():
    conn = await get_db()
    try:
        rows = await conn.fetch("""
            SELECT DISTINCT ON (source) source, started_at, status, records_fetched, records_new, error_msg
            FROM ingest_log ORDER BY source, started_at DESC
        """)
        total_alertas = await conn.fetchval(
            "SELECT COUNT(*) FROM alertas WHERE criado_em > NOW() - INTERVAL '24 hours'"
        )
        total_hotspots = await conn.fetchval(
            "SELECT COUNT(*) FROM hotspots WHERE fetched_at > NOW() - INTERVAL '24 hours'"
        )
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "alertas_24h": total_alertas,
            "hotspots_24h": total_hotspots,
            "ws_connections": len(ws_manager.connections),
            "last_ingest_by_source": [dict(r) for r in rows]
        }
    finally:
        await conn.close()

@app.get("/favicon.svg", include_in_schema=False)
async def favicon():
    from fastapi.responses import FileResponse
    return FileResponse("/app/static/favicon.svg", media_type="image/svg+xml")

@app.exception_handler(404)
async def not_found_handler(request, exc):
    from fastapi.responses import FileResponse
    return FileResponse("/app/static/404.html", status_code=404)

@app.get("/api/risk/map")
async def get_risk_map():
    """GeoJSON de risco estrutural para overlay no Leaflet."""
    import json
    risk_path = "/data/fire_risk.geojson"
    if not os.path.exists(risk_path):
        raise HTTPException(status_code=404, detail="Mapa de risco nao disponivel")
    with open(risk_path) as f:
        data = json.load(f)
    return data

@app.post("/api/ingest/trigger")
async def trigger_ingest():
    asyncio.create_task(run_ingest_cycle())
    return {"status": "triggered", "timestamp": datetime.now(timezone.utc).isoformat()}

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        conn = await get_db()
        try:
            rows = await conn.fetch("""
                SELECT id, ST_X(geom) AS lon, ST_Y(geom) AS lat,
                       score, categoria, criado_em
                FROM alertas
                WHERE criado_em > NOW() - INTERVAL '24 hours'
                ORDER BY score DESC LIMIT 20
            """)
            await ws.send_text(json.dumps({
                "type": "initial_state",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "alertas": [
                    {"id": r["id"], "lon": r["lon"], "lat": r["lat"],
                     "score": float(r["score"]), "categoria": r["categoria"],
                     "criado_em": r["criado_em"].isoformat()}
                    for r in rows
                ]
            }))
        finally:
            conn.close()
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)

app.mount("/", StaticFiles(directory="static", html=True), name="static")
