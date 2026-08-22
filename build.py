"""Copia data/cardapio.json para site/data/ (publicação)."""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
src = ROOT / "data" / "cardapio.json"
dst = ROOT / "site" / "data" / "cardapio.json"

data = json.loads(src.read_text(encoding="utf-8"))
if not data.get("days"):
    raise SystemExit("ERRO: cardapio.json vazio — não publicado")

dst.parent.mkdir(exist_ok=True)
shutil.copy2(src, dst)
print(f"Publicado: {dst} ({len(data['days'])} dias)")
