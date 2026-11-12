"""Valida os JSONs de cada campus gerados em site/data/ (publicação).

fetch_cardapio.py já escreve direto em site/data/cardapio-<campus>.json;
aqui apenas garantimos que cada arquivo existe, é válido e tem dias.

Um arquivo sem dias NÃO pode ir para o ar (o artefato do Pages é reconstruído
do zero a cada deploy e um JSON vazio substituiria a versão boa). Também não
pode ser apagado do repositório: o passo seguinte do workflow faz
`git add site/data/` e commitaria a exclusão, derrubando o campus até a
próxima coleta boa. Por isso a versão anterior (git HEAD) é restaurada.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CAMPUS = ["darcy", "executivo", "fcts", "fcte", "fup", "fal"]
SITE_DATA = ROOT / "site" / "data"


def restore_from_git(path):
    """Recupera a versão do arquivo no commit atual (HEAD).

    Retorna True se o arquivo foi restaurado. Se o JSON nem existe no git
    (primeira publicação), não há o que restaurar: aí sim ele é removido do
    deploy, porque apagar um arquivo não versionado não gera commit.
    """
    rel = path.relative_to(ROOT).as_posix()
    try:
        out = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=ROOT,
                             capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return False
    try:
        data = json.loads(out.decode("utf-8"))
    except ValueError:
        return False
    if not data.get("days"):
        return False
    # checkout (em vez de gravar o blob) respeita o core.autocrlf da máquina:
    # gravar os bytes crus deixaria o arquivo "modificado" no working tree
    try:
        subprocess.run(["git", "checkout", "HEAD", "--", rel], cwd=ROOT,
                       capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        path.write_bytes(out)
    return True


def usable_days(data):
    """Dias com pelo menos uma refeição com itens não vazios.

    O parser do Executivo pré-cria uma entrada para cada data do cabeçalho:
    se nenhum prato for extraído, o JSON tem 5 "dias" com listas vazias —
    que não podem contar como conteúdo válido.
    """
    n = 0
    for day in (data.get("days") or {}).values():
        if isinstance(day, dict) and any(
                isinstance(items, list) and items for items in day.values()):
            n += 1
    return n


ok = 0
for key in CAMPUS:
    path = SITE_DATA / f"cardapio-{key}.json"
    if not path.exists():
        print(f"AVISO: {path.name} não gerado (campus pulado)")
        continue
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"ERRO: {path.name} inválido: {e} — restaurando a versão anterior")
        data = {}
    n = usable_days(data)
    if not n:
        if restore_from_git(path):
            print(f"AVISO: {path.name} sem dias — restaurada a versão do commit; "
                  "o campus continua no ar com os dados anteriores")
        else:
            path.unlink()
            print(f"AVISO: {path.name} sem dias e sem versão anterior no git — "
                  "fora do deploy; o site usará o cache local")
        continue
    print(f"OK: {path.name} ({n} dias com itens)")
    ok += 1

if ok == 0:
    sys.exit("ERRO: nenhum campus gerado com dados — não publicar nada novo")
print(f"Publicado {ok}/{len(CAMPUS)} campi")
