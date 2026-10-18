"""DRC do KiCad sobre a placa gerada, pelo kicad-cli.

Uso:
  pcbflow-drc build/pcb/adder_cmos/adder_cmos.kicad_pcb
  python -m pcbflow.drc build/pcb/adder_cmos/adder_cmos.kicad_pcb

É a verificação de referência: lê o .kicad_pcb que foi escrito (não o modelo
interno do pcbflow) e usa a geometria real dos pads, então pega também erros
da exportação. Os planos internos são preenchidos antes (--refill-zones) e a
placa é salva já preenchida (--save-board): sem isso, ao abrir no KiCad, os
planos de VDD/GND aparecem vazios e todo pad de alimentação fica pendente até
alguém preencher as zonas (tecla B). Avisos esperados dos footprints aproximados (footprint
diferente da biblioteca, texto, serigrafia) são contados mas não reprovam a
placa; reprovam os itens desconectados e as violações de severidade erro.
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path


def find_cli():
    """kicad-cli: PCBFLOW_KICAD_CLI, o PATH ou a instalação mais nova do KiCad."""
    env = os.environ.get("PCBFLOW_KICAD_CLI")
    if env:
        return env if Path(env).is_file() else None
    hit = shutil.which("kicad-cli")
    if hit:
        return hit
    cands = glob.glob("C:/Program Files/KiCad/*/bin/kicad-cli.exe") + \
        glob.glob("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli")
    ver = lambda p: [int(x) for x in re.findall(r"\d+", Path(p).parts[-3])] if "Program Files" in p else [0]
    return max(cands, key=ver) if cands else None


def run(cli, board, out_json):
    """Roda o DRC e devolve o resumo:
    {"unconnected": [texto], "errors": [texto], "warnings": Counter(tipo)}."""
    out_json = Path(out_json)
    base = [cli, "pcb", "drc", "--format", "json", "--severity-all", "--refill-zones"]
    tail = ["-o", str(out_json), str(board)]
    r = subprocess.run(base + ["--save-board"] + tail, capture_output=True, text=True)
    if r.returncode != 0 and "save-board" in (r.stderr + r.stdout):
        # kicad-cli anterior ao --save-board (KiCad 8): o DRC roda, a placa fica sem preencher
        r = subprocess.run(base + tail, capture_output=True, text=True)
    if r.returncode != 0 or not out_json.is_file():
        raise RuntimeError(f"kicad-cli falhou ({r.returncode}): {(r.stderr or r.stdout).strip()[-500:]}")
    d = json.loads(out_json.read_text(encoding="utf-8"))

    def where(it):
        p = it.get("pos", {})
        return f"{it.get('description', '?')} em ({p.get('x', 0):.2f}, {p.get('y', 0):.2f})"

    res = {"unconnected": [], "errors": [], "warnings": Counter()}
    for u in d.get("unconnected_items", []):
        res["unconnected"].append(" <-> ".join(where(i) for i in u.get("items", [])))
    for v in d.get("violations", []):
        if v.get("severity") == "error":
            res["errors"].append(f"{v.get('type')}: " + " / ".join(where(i) for i in v.get("items", [])))
        else:
            res["warnings"][v.get("type", "?")] += 1
    return res


def ok(res):
    return not res["unconnected"] and not res["errors"]


def summary(res, limit=10):
    """Linhas para o log."""
    L = [f"desconectados: {len(res['unconnected'])}, erros: {len(res['errors'])}, "
         f"avisos: {sum(res['warnings'].values())}"
         + (f" ({', '.join(f'{k} {n}' for k, n in res['warnings'].most_common())})" if res["warnings"] else "")]
    for kind in ("unconnected", "errors"):
        for line in res[kind][:limit]:
            L.append(("desconectado: " if kind == "unconnected" else "erro: ") + line)
        if len(res[kind]) > limit:
            L.append(f"... e mais {len(res[kind]) - limit}")
    return L


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="python -m pcbflow.drc", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("board", help="arquivo .kicad_pcb")
    ap.add_argument("-o", "--out", help="relatório JSON do KiCad (padrão: drc.json ao lado da placa)")
    args = ap.parse_args(argv)
    board = Path(args.board)
    if not board.is_file():
        raise SystemExit(f"{board} não existe (gere a placa com o pcbflow antes)")
    cli = find_cli()
    if not cli:
        raise SystemExit("kicad-cli não encontrado: instale o KiCad 8+ ou defina PCBFLOW_KICAD_CLI")
    res = run(cli, board, args.out or board.with_name("drc.json"))
    for line in summary(res, limit=1000):
        print(line)
    print("OK" if ok(res) else "REPROVADA")
    return 0 if ok(res) else 1


if __name__ == "__main__":
    sys.exit(main())
