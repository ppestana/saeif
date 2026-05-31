import logging
import httpx

log = logging.getLogger("saeif.utils")

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_HEADERS = {"User-Agent": "SAEIF/1.0 (saeif.terradigital.net)"}

async def reverse_geocode(lat: float, lon: float) -> str | None:
    """
    Geocodificacao inversa via OSM Nominatim.
    Retorna string com nome do lugar ou None se falhar.
    Formato: "Freguesia, Concelho, Distrito"
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                NOMINATIM_URL,
                params={"lat": lat, "lon": lon, "format": "json", "addressdetails": 1},
                headers=NOMINATIM_HEADERS
            )
            resp.raise_for_status()
            data = resp.json()

        addr = data.get("address", {})

        # Construir string com os campos disponiveis
        parts = []
        # Nivel mais especifico primeiro
        for key in ["village", "town", "city", "municipality", "suburb", "hamlet"]:
            if addr.get(key):
                parts.append(addr[key])
                break
        # Concelho
        for key in ["county", "municipality"]:
            if addr.get(key) and addr[key] not in parts:
                parts.append(addr[key])
                break
        # Distrito
        if addr.get("state") and addr["state"] not in parts:
            parts.append(addr["state"])

        if parts:
            return ", ".join(parts)

        # Fallback: display_name truncado
        display = data.get("display_name", "")
        if display:
            return ", ".join(display.split(",")[:3]).strip()

        return None

    except Exception as e:
        log.warning(f"Nominatim falhou ({lat},{lon}): {e}")
        return None
