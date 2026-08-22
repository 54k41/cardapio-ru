"""Valida os JSONs de cada campus gerados em site/data/ (publicação).

fetch_cardapio.py já escreve direto em site/data/cardapio-<campus>.json;
aqui apenas garantimos que cada arquivo existe, é válido e tem dias.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CAMPUS = ["darcy", "executivo", "fcts", "fcte", "fup", "fal"]
SITE_DATA = ROOT / "site" / "data"

ok = 0
for key in CAMPUS:
    path = SITE_DATA / f"cardapio-{key}.json"
    if not path.exists():
        print(f"AVISO: {path.name} não gerado (campus pulado)")
        continue
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        sys.exit(f"ERRO: {path.name} inválido: {e}")
    n = len(data.get("days", {}))
    if not n:
        print(f"AVISO: {path.name} sem dias — mantendo anterior se existir no Pages")
        continue
    print(f"OK: {path.name} ({n} dias)")
    ok += 1

if ok == 0:
    sys.exit("ERRO: nenhum campus gerado com dados — não publicar nada novo")
print(f"Publicado {ok}/{len(CAMPUS)} campi")
