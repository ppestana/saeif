"""
Sistema de notificações SAEIF via Resend.
Gestão de subscritores e envio de alertas por email.
"""
import os, logging, secrets, hashlib
from datetime import datetime, timezone
import httpx

log = logging.getLogger('saeif.notifications')

RESEND_API   = "https://api.resend.com/emails"
RESEND_KEY   = os.getenv("RESEND_API_KEY")
FROM_EMAIL   = os.getenv("RESEND_FROM", "alertas@terradigital.net")
BASE_URL     = "https://saeif.terradigital.net"

CATEGORIAS = {"CRITICO": 4, "ALTO": 3, "MEDIO": 2, "BAIXO": 1}

def _gen_token():
    return secrets.token_urlsafe(32)

async def registar_subscritor(conn, email, lat, lon, raio_km, categoria_min):
    """Regista subscritor e envia email de confirmação."""
    token_confirmar = _gen_token()
    token_cancelar  = _gen_token()
    try:
        await conn.execute("""
            INSERT INTO subscritores (email, geom, raio_km, categoria_min, token_confirmar, token_cancelar)
            VALUES ($1, ST_SetSRID(ST_MakePoint($2,$3),4326), $4, $5, $6, $7)
            ON CONFLICT (email) DO UPDATE SET
                geom=ST_SetSRID(ST_MakePoint($2,$3),4326),
                raio_km=$4, categoria_min=$5,
                token_confirmar=$6, token_cancelar=$7,
                confirmado=FALSE, cancelado_em=NULL
        """, email, lon, lat, raio_km, categoria_min, token_confirmar, token_cancelar)
    except Exception as e:
        log.error(f"Erro ao registar subscritor {email}: {e}")
        raise

    await _enviar_confirmacao(email, token_confirmar, token_cancelar, raio_km, categoria_min)
    log.info(f"Subscritor registado: {email} raio={raio_km}km cat={categoria_min}")

async def confirmar_subscritor(conn, token):
    """Activa subscrição via token de confirmação."""
    row = await conn.fetchrow(
        "SELECT id, email FROM subscritores WHERE token_confirmar=$1 AND confirmado=FALSE AND cancelado_em IS NULL",
        token
    )
    if not row:
        return False
    await conn.execute(
        "UPDATE subscritores SET confirmado=TRUE, confirmado_em=$1 WHERE id=$2",
        datetime.now(timezone.utc), row['id']
    )
    log.info(f"Subscrição confirmada: {row['email']}")
    return True

async def cancelar_subscritor(conn, token):
    """Cancela subscrição via token de cancelamento."""
    row = await conn.fetchrow(
        "SELECT id, email FROM subscritores WHERE token_cancelar=$1 AND cancelado_em IS NULL",
        token
    )
    if not row:
        return False
    await conn.execute(
        "UPDATE subscritores SET cancelado_em=$1 WHERE id=$2",
        datetime.now(timezone.utc), row['id']
    )
    log.info(f"Subscrição cancelada: {row['email']}")
    return True

async def notificar_alerta(conn, alerta):
    """Envia notificação a subscritores no raio do alerta."""
    if not RESEND_KEY:
        log.warning("RESEND_API_KEY nao definida")
        return 0

    lat = alerta.get("lat")
    lon = alerta.get("lon")
    categoria = alerta.get("categoria")
    nivel_alerta = CATEGORIAS.get(categoria, 0)

    # Buscar subscritores no raio com categoria_min <= categoria do alerta
    subscritores = await conn.fetch("""
        SELECT email, raio_km, categoria_min, token_cancelar
        FROM subscritores
        WHERE confirmado = TRUE
          AND cancelado_em IS NULL
          AND ST_DWithin(
              geom::geography,
              ST_SetSRID(ST_MakePoint($1,$2),4326)::geography,
              raio_km * 1000
          )
        ORDER BY ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint($1,$2),4326)::geography)
    """, lon, lat)

    enviados = 0
    for s in subscritores:
        nivel_min = CATEGORIAS.get(s['categoria_min'], 0)
        if nivel_alerta < nivel_min:
            continue
        try:
            await _enviar_alerta(s['email'], s['token_cancelar'], alerta)
            enviados += 1
        except Exception as e:
            log.error(f"Erro ao enviar alerta para {s['email']}: {e}")

    if enviados:
        log.info(f"Alerta #{alerta.get('id')} notificado a {enviados} subscritores")
    return enviados

async def _enviar_email(to, subject, html):
    """Envia email via Resend API."""
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(RESEND_API,
            headers={"Authorization": f"Bearer {RESEND_KEY}", "Content-Type": "application/json"},
            json={"from": f"SAEIF Alertas <{FROM_EMAIL}>", "to": [to], "subject": subject, "html": html}
        )
        r.raise_for_status()
        return r.json()

async def _enviar_confirmacao(email, token_confirmar, token_cancelar, raio_km, categoria_min):
    url_confirmar = f"{BASE_URL}/api/subscricoes/confirmar?token={token_confirmar}"
    url_cancelar  = f"{BASE_URL}/api/subscricoes/cancelar?token={token_cancelar}"
    html = f"""
    <div style="font-family:monospace;max-width:560px;margin:0 auto;background:#0d1117;color:#c9d1d9;padding:2rem;border-radius:4px">
      <h2 style="color:#f85149;margin-top:0">🔥 SAEIF — Confirme a sua subscrição</h2>
      <p>Recebemos o seu pedido de subscrição de alertas de incêndio florestal.</p>
      <p><strong>Configuração:</strong><br>
      Raio: {raio_km} km &nbsp;|&nbsp; Categoria mínima: {categoria_min}</p>
      <p>Para activar a sua subscrição, clique no botão abaixo:</p>
      <a href="{url_confirmar}" style="display:inline-block;background:#f85149;color:#fff;padding:.7rem 1.4rem;border-radius:3px;text-decoration:none;font-weight:bold;margin:1rem 0">
        Confirmar subscrição →
      </a>
      <p style="font-size:0.8rem;color:#8b949e;margin-top:2rem">
        Se não pediu esta subscrição, ignore este email.<br>
        Para cancelar: <a href="{url_cancelar}" style="color:#8b949e">{url_cancelar}</a>
      </p>
      <hr style="border-color:#30363d;margin:1.5rem 0">
      <p style="font-size:0.75rem;color:#8b949e">SAEIF · TerraDigital · Torres Vedras, Portugal</p>
    </div>
    """
    await _enviar_email(email, "SAEIF — Confirme a sua subscrição de alertas", html)

async def _enviar_alerta(email, token_cancelar, alerta):
    url_cancelar = f"{BASE_URL}/api/subscricoes/cancelar?token={token_cancelar}"
    url_saeif    = BASE_URL
    categoria    = alerta.get("categoria","--")
    score        = alerta.get("score","--")
    localidade   = alerta.get("localidade_estimada","--")
    lat          = alerta.get("lat","--")
    lon          = alerta.get("lon","--")
    fwi          = (alerta.get("meteo") or {}).get("fwi","--")
    ranking      = ((alerta.get("effis") or {}).get("ranking") or "--")
    cor = {"CRITICO":"#b22020","ALTO":"#f85149","MEDIO":"#e3b341","BAIXO":"#3fb950"}.get(categoria,"#f85149")
    html = f"""
    <div style="font-family:monospace;max-width:560px;margin:0 auto;background:#0d1117;color:#c9d1d9;padding:2rem;border-radius:4px">
      <h2 style="color:{cor};margin-top:0">🔥 Alerta de Incêndio — {categoria}</h2>
      <table style="width:100%;border-collapse:collapse;font-size:0.85rem">
        <tr><td style="color:#8b949e;padding:.3rem 0">Score</td><td style="text-align:right;color:{cor};font-weight:bold">{score}</td></tr>
        <tr><td style="color:#8b949e;padding:.3rem 0">Localidade</td><td style="text-align:right">{localidade}</td></tr>
        <tr><td style="color:#8b949e;padding:.3rem 0">Coordenadas</td><td style="text-align:right">{lat}, {lon}</td></tr>
        <tr><td style="color:#8b949e;padding:.3rem 0">FWI (IPMA)</td><td style="text-align:right">{fwi}</td></tr>
        <tr><td style="color:#8b949e;padding:.3rem 0">Ranking EFFIS</td><td style="text-align:right">{ranking}%</td></tr>
      </table>
      <a href="{url_saeif}" style="display:inline-block;background:{cor};color:#fff;padding:.7rem 1.4rem;border-radius:3px;text-decoration:none;font-weight:bold;margin:1.5rem 0">
        Ver no mapa →
      </a>
      <hr style="border-color:#30363d;margin:1.5rem 0">
      <p style="font-size:0.75rem;color:#8b949e">
        Recebe este email porque subscreveu alertas SAEIF.<br>
        <a href="{url_cancelar}" style="color:#8b949e">Cancelar subscrição</a>
        &nbsp;|&nbsp; SAEIF · TerraDigital · Torres Vedras, Portugal
      </p>
    </div>
    """
    await _enviar_email(email, f"🔥 SAEIF — Alerta {categoria}: {localidade}", html)
