#!/usr/bin/env python3
"""
Edicao segura de api/main.py: corrige um bug real encontrado ao testar
com QGIS -- pedidos HEAD a /layers/{nome}.png e /layers/{nome}.tif
devolviam 404 (a cair no handler de erro personalizado), apesar de GET
funcionar correctamente. O GDAL (por tras do QGIS /vsicurl/) faz sempre
um pedido HEAD primeiro para descobrir o tamanho do ficheiro antes de
pedir blocos via Range -- sem HEAD funcional, o COG nunca chega a
carregar, mesmo estando o ficheiro correcto e acessivel via GET.

Correccao: declarar explicitamente methods=["GET", "HEAD"] nas duas
rotas de camadas, em vez de depender do comportamento implicito
(que claramente nao estava a funcionar como esperado nesta app).

Backup + validacao ast.parse antes de escrever.
"""
import ast
import shutil
import sys

PATH = "api/main.py"

with open(PATH, encoding="utf-8") as f:
    content = f.read()

SUBSTITUICOES = [
    ('@app.get("/layers/{nome}.png")', '@app.api_route("/layers/{nome}.png", methods=["GET", "HEAD"])'),
    ('@app.get("/layers/{nome}.tif")', '@app.api_route("/layers/{nome}.tif", methods=["GET", "HEAD"])'),
]

novo_content = content
for antigo, novo in SUBSTITUICOES:
    n = novo_content.count(antigo)
    assert n == 1, f"'{antigo}' encontrado {n} vezes (esperado 1). Abortado sem alteracoes."
    novo_content = novo_content.replace(antigo, novo)

# Validar sintaxe antes de escrever
try:
    ast.parse(novo_content)
except SyntaxError as e:
    print(f"ERRO: sintaxe invalida apos edicao -- {e}")
    sys.exit(1)

shutil.copy(PATH, PATH + ".bak_head_fix")
with open(PATH, "w", encoding="utf-8") as f:
    f.write(novo_content)

print(f"OK: {PATH} editado com sucesso. Backup em {PATH}.bak_head_fix")
print("Rotas /layers/{nome}.png e /layers/{nome}.tif agora aceitam GET e HEAD explicitamente.")
