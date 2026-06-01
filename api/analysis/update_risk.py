#!/usr/bin/env python3
"""
Actualiza o mapa de risco estrutural por distrito.
Usa o raster WorldCover reamostrado (wc_2km.tif) e os polígonos
de distritos/províncias (concelhos.geojson) para calcular o risco
médio por unidade administrativa e gerar fire_risk.geojson.

Agendamento sugerido: mensal (1º dia do mês às 03:00 UTC)
Cron: 0 3 1 * * docker compose -f /srv/saeif/docker-compose.yml exec -T api python3 /app/analysis/update_risk.py
"""
import json, rasterio, numpy as np, os, shutil, logging
from datetime import datetime, timezone
from rasterio.mask import mask

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger('saeif.update_risk')

SRC_RASTER   = '/data/wc_2km.tif'
DISTRICTS    = '/data/concelhos.geojson'
OUT_GEOJSON  = '/data/fire_risk.geojson'
OUT_BACKUP   = '/data/fire_risk_backup.geojson'

FUEL_MAP = {
    10: 1.00,  # Floresta arborea
    20: 0.85,  # Arbustivo
    30: 0.30,  # Pastagem
    40: 0.15,  # Cultura
    50: 0.00,  # Urbano
    60: 0.05,  # Solo nu
    70: 0.00,  # Neve/Gelo
    80: 0.00,  # Agua
    90: 0.10,  # Zona humida
    95: 0.05,  # Mangal
   100: 0.20,  # Musgos/Liquenes
}

def classify(risk_mean):
    if risk_mean >= 0.7:   return 4
    elif risk_mean >= 0.5: return 3
    elif risk_mean >= 0.35:return 2
    elif risk_mean >= 0.2: return 1
    else:                  return 0

def main():
    log.info("Inicio da actualizacao do mapa de risco estrutural")
    start = datetime.now(timezone.utc)

    # Backup do GeoJSON actual
    if os.path.exists(OUT_GEOJSON):
        shutil.copy(OUT_GEOJSON, OUT_BACKUP)
        log.info(f"Backup: {OUT_BACKUP}")

    with open(DISTRICTS) as f:
        gj = json.load(f)

    features = gj.get('features', [])
    log.info(f"Distritos/provincias a processar: {len(features)}")

    results = []
    errors = 0

    with rasterio.open(SRC_RASTER) as src:
        for feat in features:
            name = (feat.get('properties') or {}).get('name', 'Unknown')
            try:
                out_image, _ = mask(src, [feat['geometry']], crop=True, nodata=0)
                data = out_image[0]
                valid = data[data > 0]
                if len(valid) == 0:
                    continue
                risk_vals = np.array([FUEL_MAP.get(int(v), 0.0) for v in valid])
                risk_mean = float(risk_vals.mean())
                cls = classify(risk_mean)
                results.append({
                    "type": "Feature",
                    "geometry": feat['geometry'],
                    "properties": {
                        "name": name,
                        "DN": cls,
                        "risk": round(risk_mean, 3),
                        "updated_at": start.isoformat()
                    }
                })
            except Exception as e:
                errors += 1
                log.debug(f"  SKIP {name}: {e}")

    out = {"type": "FeatureCollection", "features": results}
    with open(OUT_GEOJSON, 'w') as f:
        json.dump(out, f)

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    size_kb = os.path.getsize(OUT_GEOJSON) // 1024
    log.info(f"Concluido: {len(results)} features, {errors} erros, {size_kb}KB, {elapsed:.1f}s")
    return len(results)

if __name__ == '__main__':
    main()
