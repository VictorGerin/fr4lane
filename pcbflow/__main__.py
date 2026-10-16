"""pcbflow: Verilog -> Yosys -> células de componentes discretos -> placement -> roteamento -> KiCad.

Uso:
  python -m pcbflow --top adder --src rtl/RISC_V/ALU/adder.v --tb sim/testbenches/tb_adder.v
  python -m pcbflow --lib pcbflow/lib/rtl --top adder --src ...      (família RTL com BC548)
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from . import cellcheck, check, drc, floorplan, kicad, netlist, place, route, synth
from .layout import Rules
from .library import Library, LibraryError

ROOT = Path(__file__).resolve().parents[1]
# marcadores de falha usados pelos testbenches do projeto
FAIL_RE = re.compile(r"\[ERRO|(?<![A-Za-z])(ERROR|FAILED|FALHOU)(?![A-Za-z])")


def log(msg=""):
    print(msg, flush=True)


def run_sim(tb, dut_files, outdir, name):
    iverilog = shutil.which("iverilog") or "C:/msys64/ucrt64/bin/iverilog.exe"
    vvp = shutil.which("vvp") or "C:/msys64/ucrt64/bin/vvp.exe"
    out = (outdir / f"{name}.vvp").resolve()
    r = subprocess.run([iverilog, "-g2012", "-o", str(out), str(tb)] + [str(f) for f in dut_files],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return False, r.stdout + r.stderr
    r = subprocess.run([vvp, "-n", str(out)], capture_output=True, text=True, cwd=outdir)
    text = r.stdout + r.stderr
    # o vvp não propaga o argumento de $finish como código de saída; procura os
    # marcadores de falha usados pelos testbenches do projeto
    ok = r.returncode == 0 and not FAIL_RE.search(text)
    return ok, text


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="pcbflow", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--top", required=True, help="módulo topo")
    ap.add_argument("--src", nargs="+", required=True, help="arquivos Verilog")
    ap.add_argument("--lib", default=str(ROOT / "lib" / "cmos"), help="pasta da família de células")
    ap.add_argument("--out", help="diretório de saída (padrão: build/pcb/<top>)")
    ap.add_argument("--tb", help="testbench para simular gate-level e switch-level")
    ap.add_argument("--effort", type=float, default=1.0, help="esforço do placement")
    ap.add_argument("--density", type=float, default=None,
                    help="ocupação-alvo das fileiras fora das fences/regions, de 0 a 1 (padrão 0.8; "
                         "1 = compacto); as fences/regions espalham o módulo pela área toda")
    ap.add_argument("--row-gap", type=float, help="canal entre fileiras de blocos (mm)")
    ap.add_argument("--part-gap", type=float, help="folga entre componentes no bloco (mm)")
    ap.add_argument("--module-weight", type=float, default=None,
                    help="força que mantém cada módulo agrupado no placement (0 = desliga)")
    ap.add_argument("--route-iter", type=int, default=40)
    ap.add_argument("--max-parts", type=int, default=8000,
                    help="aborta antes do P&R se o projeto for maior que isso")
    ap.add_argument("--layers", type=int, choices=(2, 4), default=4,
                    help="4: VDD/GND em planos internos (padrão); 2: trilhos de alimentação")
    ap.add_argument("--floorplan", help="arquivo JSON com a posição (mm) dos módulos e keepouts")
    ap.add_argument("--flatten", action="store_true",
                    help="achata antes do mapeamento: o ABC otimiza entre módulos, "
                         "mas a placa perde o agrupamento por módulo")
    ap.add_argument("--synth-only", action="store_true", help="para após síntese/estatísticas")
    ap.add_argument("--place-only", action="store_true",
                    help="para após o placement (grava o placement.json, sem rotear nem gerar o KiCad)")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--no-drc", action="store_true",
                    help="não roda o DRC do KiCad (kicad-cli) sobre a placa gerada")
    args = ap.parse_args(argv)

    # o nome da família (pasta da biblioteca) vai na pasta e nos arquivos do KiCad,
    # para as versões cmos/rtl do mesmo módulo não se confundirem
    family = Path(args.lib).resolve().name
    tag = f"{args.top}_{family}" + ("_2l" if args.layers == 2 else "")
    out = Path(args.out or f"build/pcb/{tag}")
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    try:
        lib = Library(args.lib)
    except LibraryError as e:
        log(f"ERRO: {e}")
        return 3
    fplan = None
    if args.floorplan:
        if args.flatten:
            log("ERRO: --floorplan precisa da hierarquia dos módulos; não use --flatten")
            return 3
        try:
            fplan = floorplan.load(args.floorplan)
        except floorplan.FloorplanError as e:
            log(f"ERRO: {e}")
            return 3
    log(f"[0/6] Biblioteca '{lib.name}' ({len(lib.cells)} células): verificando montagem x Liberty")
    problems = cellcheck.check_cells(lib, out)
    if problems:
        log("ERRO: a montagem (.sp) de alguma célula não faz o que o .lib declara:")
        for p in problems:
            log("  " + p)
        return 3
    liberty = out / "cells.lib"
    models = out / "cells_models.v"
    lib.write_liberty(liberty)
    lib.write_verilog_models(models)

    log(f"[1/6] Síntese Yosys de '{args.top}'")
    json_path, gates_v, stat, hier = synth.run_yosys(args.src, args.top, liberty, out, flatten=args.flatten)
    design = netlist.load_yosys_json(json_path, args.top, lib, hier)
    by_cell = Counter(c for c, _ in design.instances.values())
    kinds = Counter(lib.parts[p.model]["kind"] for p in design.parts)
    n_parts = len(design.parts)
    log("      células: " + ", ".join(f"{k}={v}" for k, v in sorted(by_cell.items())))
    log(f"      {len(design.blocks)} blocos, {n_parts} componentes ("
        + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())) + ")")
    mods = sorted({m for m in design.inst_module.values() if m})
    if mods:
        log(f"      {len(mods)} módulos: " + ", ".join(mods[:12]) + (" ..." if len(mods) > 12 else ""))
    fanout = netlist.fanout_violations(lib, design)
    if fanout:
        log(f"      AVISO: {len(fanout)} nets acima do max_fanout (veja report.md)")
    if args.tb:
        log("[2/6] Simulação: netlist gate-level e de componentes")
        ok, text = run_sim(args.tb, [gates_v, models], out, "sim_gates")
        log(f"      gate-level:       {'OK' if ok else 'FALHOU'}")
        (out / "sim_gates.log").write_text(text)
        sw = out / f"{args.top}_switch.v"
        netlist.write_switch_level_verilog(lib, design, sw)
        ok2, text2 = run_sim(args.tb, [sw], out, "sim_switch")
        log(f"      componentes:      {'OK' if ok2 else 'FALHOU'}")
        (out / "sim_switch.log").write_text(text2)
        if not (ok and ok2):
            log("      veja sim_gates.log / sim_switch.log")
    else:
        log("[2/6] Simulação: pulada (use --tb)")

    if args.synth_only:
        log(stat.read_text())
        info = place.measure(lib, design, _place_params(args), Rules())
        _write_placement(out / "placement.json", args, lib, design, info)
        log(f"Medidas para o editor de floorplan: {out / 'placement.json'}")
        return 0
    if n_parts > args.max_parts:
        log(f"ABORTADO: {n_parts} componentes > --max-parts {args.max_parts}. "
            "Divida o projeto ou aumente o limite.")
        return 2

    log("[3/6] Placement")
    rules = Rules()
    params = _place_params(args)
    try:
        board = place.place(lib, design, params, rules, fplan)
    except floorplan.FloorplanError as e:
        log(f"ERRO: {e}")
        return 3
    board.group_cells = {inst: cell for inst, (cell, _) in design.instances.items()}
    board.group_modules = {inst: m for inst, m in design.inst_module.items() if m}
    board.module_types = design.modules
    _write_placement(out / "placement.json", args, lib, design, board.place_stats["editor"], board, fplan)
    reg = board.place_stats.get("regions")
    what = "áreas declaradas" if fplan else "regiões (uma por módulo)"
    log(f"      {f'{reg} {what}, ' if reg else ''}{board.place_stats['rows']} fileiras, HPWL {board.place_stats['hpwl_mm']} mm, "
        f"placa {board.width:.0f} x {board.height:.0f} mm")
    if args.place_only:
        log(f"Placement para o editor de floorplan: {out / 'placement.json'}")
        log(f"Concluído em {time.time() - t0:.1f} s")
        return 0

    log("[4/6] Roteamento")
    route.route(board, args.route_iter, log=lambda m: log("    " + m))

    log("[5/6] Verificação (folgas + conectividade)")
    errors, unconnected = check.check_board(board)
    log(f"      violações de folga: {len(errors)}")
    for e in errors[:10]:
        log("        " + e)
    log(f"      nets incompletas: {len(unconnected)}")
    for n, c in sorted(unconnected.items())[:10]:
        log(f"        {n}: {c} partes")

    log("[6/6] Projeto KiCad")
    name = tag
    kicad.write_pcb(board, out / f"{name}.kicad_pcb", title=f"{name} — {lib.name}, {n_parts} componentes")
    kicad.write_project(board, out / f"{name}.kicad_pro")
    kicad.write_bom(board, out / f"{name}_bom.csv")
    netlist.write_switch_level_verilog(lib, design, out / f"{args.top}_switch.v")
    log(f"      {out / (name + '.kicad_pro')}")
    # DRC do KiCad: a referência, porque lê o arquivo escrito com a geometria real
    drc_res = None
    cli = None if args.no_drc else drc.find_cli()
    if args.no_drc:
        log("      DRC do KiCad: pulado (--no-drc)")
    elif not cli:
        log("      DRC do KiCad: kicad-cli não encontrado (instale o KiCad 8+ ou defina PCBFLOW_KICAD_CLI)")
    else:
        try:
            drc_res = drc.run(cli, out / f"{name}.kicad_pcb", out / "drc.json")
            for i, line in enumerate(drc.summary(drc_res)):
                log(("      DRC do KiCad: " if i == 0 else "        ") + line)
        except RuntimeError as e:
            log(f"      DRC do KiCad: {e}")
    _write_report(out / "report.md", args, design, board, by_cell, errors, unconnected, lib, fanout, drc_res)
    log(f"Concluído em {time.time() - t0:.1f} s")
    return 0 if not errors and not unconnected and (drc_res is None or drc.ok(drc_res)) else 1


def _place_params(args):
    params = place.PlaceParams(part_gap=args.part_gap, row_gap=args.row_gap,
                               effort=args.effort, seed=args.seed, layers=args.layers)
    if args.module_weight is not None:
        params.module_weight = args.module_weight
    if args.density is not None:
        if not 0 < args.density <= 1:
            raise SystemExit("--density deve ser de 0 (exclusive) a 1")
        params.density = args.density
    return params


def _write_placement(path, args, lib, design, info, board=None, fplan=None):
    """Resumo para o editor de floorplan (python -m pcbflow.fpedit): grade de
    fileiras e largura que cada módulo ocupa; depois do placement, também onde
    ficou cada componente (com --synth-only, a lista fica vazia)."""
    parts = []
    if board is not None:
        gmod = board.group_modules
        for f in board.footprints:
            x0, y0, x1, y1 = f.courtyard
            parts.append({"ref": f.ref, "module": gmod.get(f.group, "") if f.group else None,
                          "box": [round(f.x + x0, 3), round(f.y + y0, 3), round(f.x + x1, 3), round(f.y + y1, 3)]})
    data = {"top": args.top, "family": Path(args.lib).resolve().name, "library": lib.name,
            "sources": [str(Path(f).resolve()) for f in args.src],
            "layers": args.layers, "placed": board is not None,
            "board": [board.width, board.height] if board is not None else info["board"],
            "floorplan": str(fplan.source) if fplan else None,
            "geo": info["geo"], "min_width": info["min_width"], "module_width": info["module_width"],
            "module_types": design.modules, "footprints": parts}
    Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _write_report(path, args, design, board, by_cell, errors, unconnected, lib, fanout, drc_res=None):
    parts = Counter(fp.value for fp in board.footprints)
    L = [f"# Relatório pcbflow — `{design.top}`", "",
         f"- Fontes: {', '.join(args.src)}",
         f"- Biblioteca: `{lib.name}` ({lib.family}, VDD = {lib.supply_voltage})",
         f"- Placa: {board.width:.0f} x {board.height:.0f} mm, "
         + ("4 camadas (F.Cu sinais H, In1.Cu GND, In2.Cu VDD, B.Cu sinais V)" if board.layers >= 4 else
            "2 camadas (F.Cu sinais H + trilhos de VDD/GND, B.Cu sinais V + troncos de VDD/GND)"),
         f"- Trilhas: {len(board.tracks)}, vias: {len(board.vias)}", "",
         "## Células lógicas", "", "| Célula | Qtd | Componentes |", "|---|---:|---:|"]
    for c, k in sorted(by_cell.items()):
        L.append(f"| {c} | {k} | {k * lib.count_parts(c)} |")
    L += ["", "## Componentes", "", "| Valor | Qtd |", "|---|---:|"]
    for v, k in sorted(parts.items()):
        L.append(f"| {v} | {k} |")
    by_mod = {}
    for inst, m in design.inst_module.items():
        by_mod.setdefault(m, []).append(inst)
    if len(by_mod) > 1 or "" not in by_mod:
        refs = {}
        for fp in board.footprints:
            if fp.group:
                refs.setdefault(design.inst_module.get(fp.group, ""), []).append(fp.ref)
        L += ["", "## Módulos", "", "| Módulo | Tipo | Células | Componentes |", "|---|---|---|---|"]
        for m, insts in sorted(by_mod.items()):
            cells = Counter(design.instances[i][0] for i in insts)
            L.append(f"| {m or '(topo)'} | {design.modules.get(m, '')} | "
                     + ", ".join(f"{c}×{k}" for c, k in sorted(cells.items()))
                     + f" | {_ref_ranges(refs.get(m, []))} |")
    if board.floorplan:
        fp = board.floorplan
        y_top, pitch, bh, n_rows = board.place_stats["grid"]
        lx0, lx1 = board.place_stats["logic_x"]
        bands = ", ".join(f"{y_top + k * pitch:.1f}–{y_top + k * pitch + bh:.1f}" for k in range(n_rows))
        L += ["", "## Floorplan", "", f"Arquivo: `{fp.source}`", "",
              f"Área de lógica: x de {lx0:g} a {lx1:g} mm. Fileiras (passo {pitch:.2f} mm, y em mm): {bands}. "
              "Uma área de fence/region só usa as fileiras que cabem inteiras dentro dela.", "",
              "| Área | Tipo | Fileira usada (mm) | Fileira disponível (mm) |", "|---|---|---:|---:|"]
        for area, typ, need, have in board.place_stats.get("usage", []):
            L.append(f"| {area} | {typ} | {need:.0f} | {have:.0f} |")
        for r in fp.modules.values():
            if r.type == "guide":
                L.append(f"| {r.path} | guide | — | — |")
        for k in fp.keepouts:
            what = " + ".join(w for w, on in (("posicionamento", k.place), ("roteamento", k.route)) if on)
            L.append(f"| keepout `{k.name}` | {what} ({', '.join(k.layers)}) | — | — |")
    L += ["", "## Pendências", ""]
    if not errors and not unconnected and not board.unrouted:
        L.append("Nenhuma: todas as nets roteadas e sem violações de folga.")
    for n in board.unrouted:
        L.append(f"- não roteada: `{n}`")
    for n, c in sorted(unconnected.items()):
        L.append(f"- net `{n}` em {c} partes")
    for e in errors[:50]:
        L.append(f"- {e}")
    L += ["", "## DRC do KiCad", ""]
    if drc_res is None:
        L.append("Não rodou (kicad-cli não encontrado ou --no-drc).")
    else:
        L.append(("Aprovada: " if drc.ok(drc_res) else "**Reprovada**: ") + drc.summary(drc_res)[0]
                 + ". Relatório completo em `drc.json`.")
        for line in drc.summary(drc_res, limit=50)[1:]:
            L.append(f"- {line}")
    if fanout:
        L += ["", "## Fan-out acima do limite", "", "| Net | Bloco que dirige | Célula | Cargas | Limite |",
              "|---|---|---|---:|---:|"]
        for net, blk, cell, k, lim in fanout:
            L.append(f"| `{net}` | {blk} | {cell} | {k} | {lim} |")
    L += ["", "## Mapa de instâncias (Yosys -> placa)", "",
          "| Instância | Célula | Módulo | Nome no Yosys |", "|---|---|---|---|"]
    for inst, (cell, yname) in design.instances.items():
        L.append(f"| {inst} | {cell} | {design.inst_module.get(inst) or '—'} | `{yname}` |")
    Path(path).write_text("\n".join(L) + "\n", encoding="utf-8")


def _ref_ranges(refs):
    """['Q1','Q2','Q3','R5','R6'] -> 'Q1–Q3, R5–R6'"""
    nums = {}
    for r in refs:
        m = re.match(r"([A-Z]+)(\d+)$", r)
        if m:
            nums.setdefault(m.group(1), []).append(int(m.group(2)))
    out = []
    for pre, ns in sorted(nums.items()):
        ns.sort()
        start = prev = ns[0]
        for n in ns[1:] + [None]:
            if n is not None and n == prev + 1:
                prev = n
                continue
            out.append(f"{pre}{start}" if start == prev else f"{pre}{start}–{pre}{prev}")
            if n is not None:
                start = prev = n
    return ", ".join(out)


if __name__ == "__main__":
    sys.exit(main())
