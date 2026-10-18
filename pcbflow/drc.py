"""DRC do KiCad sobre a placa gerada, pelo kicad-cli.

Uso:
  pcbflow-drc build/pcb/adder_cmos/adder_cmos.kicad_pcb
  python -m pcbflow.drc build/pcb/adder_cmos/adder_cmos.kicad_pcb

É a verificação de referência: lê o .kicad_pcb que foi escrito (não o modelo
interno do pcbflow) e usa a geometria real dos pads, então pega também erros
da exportação. Os planos internos são preenchidos antes e a placa é salva já
preenchida: sem isso, os planos de VDD/GND ficam vazios e todo pad de
alimentação aparece desconectado (no KiCad, até alguém apertar B).

Como preencher depende da versão do KiCad:
  - kicad-cli com --refill-zones/--save-board (KiCad 10): ele mesmo preenche;
  - sem eles (KiCad 8 e 9): a API Python do KiCad (pcbnew) preenche e salva
    a placa antes do DRC, pelo Python que vem com o KiCad (no Windows, o
    python.exe ao lado do kicad-cli; no Linux, o do sistema, com o pacote do
    KiCad) ou o de PCBFLOW_KICAD_PYTHON;
  - sem nenhum dos dois, o DRC roda com os planos vazios, e as desconexões das
    nets dos planos viram aviso ("plano sem preencher"), não erro.

Avisos esperados dos footprints aproximados (footprint diferente da
biblioteca, texto, serigrafia) são contados mas não reprovam a placa;
reprovam os itens desconectados e as violações de severidade erro.
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


def drc_options(cli):
    """Opções que o 'kicad-cli pcb drc' desta versão aceita."""
    r = subprocess.run([cli, "pcb", "drc", "--help"], capture_output=True, text=True)
    return set(re.findall(r"--[a-z][a-z-]+", r.stdout + r.stderr))


FILL_SCRIPT = """import sys, pcbnew
b = pcbnew.LoadBoard(sys.argv[1])
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
pcbnew.SaveBoard(sys.argv[1], b)
"""


def kicad_python(cli):
    """Um Python que importa o pcbnew (a API do KiCad), ou None."""
    env = os.environ.get("PCBFLOW_KICAD_PYTHON")
    cands = [env] if env else []
    here = Path(cli).resolve().parent
    cands += [str(here / "python.exe"), str(here / "python3"), "/usr/bin/python3", shutil.which("python3"),
              sys.executable]
    for py in dict.fromkeys(c for c in cands if c and Path(c).is_file()):
        r = subprocess.run([py, "-c", "import pcbnew"], capture_output=True, text=True)
        if r.returncode == 0:
            return py
    return None


def plane_nets(board):
    """Nets das zonas de cobre (os planos) escritas pelo pcbflow."""
    text = Path(board).read_text(encoding="utf-8", errors="replace")
    return set(re.findall(r'\(zone \(net \d+\) \(net_name "([^"]+)"\)', text))


def run(cli, board, out_json):
    """Preenche os planos, roda o DRC e devolve o resumo:
    {"unconnected": [texto], "errors": [texto], "warnings": Counter(tipo),
     "fill": como os planos foram preenchidos (None: não foram)}."""
    out_json = Path(out_json)
    opts = drc_options(cli)
    planes = plane_nets(board)
    cmd = [cli, "pcb", "drc", "--format", "json", "--severity-all"]
    fill = None
    if "--refill-zones" in opts and "--save-board" in opts:
        cmd += ["--refill-zones", "--save-board"]
        fill = "kicad-cli"
    elif planes:
        py = kicad_python(cli)
        if py:
            r = subprocess.run([py, "-c", FILL_SCRIPT, str(board)], capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"preenchimento dos planos (pcbnew) falhou: {(r.stderr or r.stdout).strip()[-500:]}")
            fill = "pcbnew"
        elif "--refill-zones" in opts:
            cmd.append("--refill-zones")              # preenche só para o DRC; a placa fica sem preencher
            fill = "kicad-cli (sem salvar)"
    r = subprocess.run(cmd + ["-o", str(out_json), str(board)], capture_output=True, text=True)
    if r.returncode != 0 or not out_json.is_file():
        raise RuntimeError(f"kicad-cli falhou ({r.returncode}): {(r.stderr or r.stdout).strip()[-500:]}")
    d = json.loads(out_json.read_text(encoding="utf-8"))

    def where(it):
        p = it.get("pos", {})
        return f"{it.get('description', '?')} em ({p.get('x', 0):.2f}, {p.get('y', 0):.2f})"

    res = {"unconnected": [], "errors": [], "warnings": Counter(), "fill": fill}
    for u in d.get("unconnected_items", []):
        items = u.get("items", [])
        if fill is None and planes and items and all(
                any(f"[{n}]" in i.get("description", "") for n in planes) for i in items):
            res["warnings"]["plano sem preencher"] += 1      # o plano liga, só não foi desenhado
            continue
        res["unconnected"].append(" <-> ".join(where(i) for i in items))
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
    if res.get("fill") is None and res["warnings"].get("plano sem preencher"):
        L.append("planos não preenchidos (kicad-cli sem --refill-zones e sem a API pcbnew): a ligação de "
                 "VDD/GND pelos planos não foi conferida pelo KiCad; no KiCad, aperte B e rode o DRC")
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
        raise SystemExit("kicad-cli não encontrado: instale o KiCad 8 ou mais novo ou defina PCBFLOW_KICAD_CLI")
    res = run(cli, board, args.out or board.with_name("drc.json"))
    for line in summary(res, limit=1000):
        print(line)
    print("OK" if ok(res) else "REPROVADA")
    return 0 if ok(res) else 1


if __name__ == "__main__":
    sys.exit(main())
