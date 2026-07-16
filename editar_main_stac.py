#!/usr/bin/env python3
"""
Edicao segura de api/main.py: adiciona

    GET /layers/{nome}.tif   -> serve o COG (Cloud Optimized GeoTIFF) de uma camada
    GET /stac/*              -> monta data/stac/ como ficheiros estaticos
                                 (catalog.json, collections/.../collection.json,
                                 collections/.../items/{id}.json)

Aditivo, nao mexe em nada existente. Backup + validacao ast.parse antes de escrever.
"""
import ast
import shutil
import sys

PATH = "api/main.py"

with open(PATH, encoding="utf-8") as f:
    content = f.read()

ANCHOR = '''@app.get("/layers/{nome}.png")
async def get_layer_png(nome: str):
    """Serve a imagem PNG de uma camada publicada (ver /api/layers para o catalogo e bounds)."""
    from fastapi.responses import FileResponse
    # Seguranca: so nomes simples, so .png, sem travessia de diretorio
    if not nome.replace("_", "").replace("-", "").isalnum() or len(nome) > 60:
        raise HTTPException(status_code=400, detail="Nome invalido")
    caminho = f"/data/layers/{nome}.png"
    if not os.path.exists(caminho):
        raise HTTPException(status_code=404, detail="Camada nao encontrada")
    return FileResponse(caminho, media_type="image/png")'''

n = content.count(ANCHOR)
assert n == 1, f"Anchor encontrado {n} vezes (esperado 1) -- ficheiro pode ja ter sido editado ou diverge do esperado. Abortado sem alteracoes."

SUBSTITUICAO = ANCHOR + '''

@app.get("/layers/{nome}.tif")
async def get_layer_cog(nome: str):
    """Serve o COG (Cloud Optimized GeoTIFF) de uma camada publicada -- os
    dados reais (nao a visualizacao colorida), para consumo por GeoLibre,
    QGIS, ou qualquer cliente STAC (ver /stac/catalog.json)."""
    from fastapi.responses import FileResponse
    if not nome.replace("_", "").replace("-", "").isalnum() or len(nome) > 60:
        raise HTTPException(status_code=400, detail="Nome invalido")
    caminho = f"/data/layers/{nome}.tif"
    if not os.path.exists(caminho):
        raise HTTPException(status_code=404, detail="Camada nao encontrada")
    return FileResponse(caminho, media_type="image/tiff")'''

novo_content = content.replace(ANCHOR, SUBSTITUICAO)

# Adicionar o mount do catalogo STAC, ANTES do mount geral de "/" no fim do ficheiro
ANCHOR_MOUNT = 'app.mount("/", StaticFiles(directory="static", html=True), name="static")'
n_mount = novo_content.count(ANCHOR_MOUNT)
assert n_mount == 1, f"Anchor do mount encontrado {n_mount} vezes (esperado 1). Abortado sem alteracoes."

SUBSTITUICAO_MOUNT = (
    '# Catalogo STAC estatico (catalog.json, collections/.../collection.json, '
    'collections/.../items/{id}.json) -- gerado por scripts/gerar_stac.py\n'
    'os.makedirs("/data/stac", exist_ok=True)\n'
    'app.mount("/stac", StaticFiles(directory="/data/stac"), name="stac")\n\n'
    + ANCHOR_MOUNT
)
novo_content = novo_content.replace(ANCHOR_MOUNT, SUBSTITUICAO_MOUNT)

# Validar sintaxe antes de escrever
try:
    ast.parse(novo_content)
except SyntaxError as e:
    print(f"ERRO: sintaxe invalida apos edicao -- {e}")
    sys.exit(1)

shutil.copy(PATH, PATH + ".bak_stac")
with open(PATH, "w", encoding="utf-8") as f:
    f.write(novo_content)

print(f"OK: {PATH} editado com sucesso. Backup em {PATH}.bak_stac")
print("Novos endpoints: GET /layers/{nome}.tif (COG), GET /stac/* (catalogo STAC estatico).")
