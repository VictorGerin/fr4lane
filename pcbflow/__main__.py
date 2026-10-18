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

from . import cache, cellcheck, check, drc, drive, floorplan, hier, kicad, netlist, place, progress, route, sizing, synth
from .layout import Rules
from .library import Library, LibraryError

ROOT = Path(__file__).resolve().parents[1]
# marcadores de falha usados pelos testbenches do projeto
FAIL_RE = re.compile(r"\[ERRO|(?<![A-Za-z])(ERROR|FAILED|FALHOU)(?![A-Za-z])")


def log(msg=""):
    progress.clear_line()
    print(msg, flush=True)


def _run_watched(cmd, pg, what, cwd=None):
    """Roda um processo externo mostrando a última linha que ele imprimiu."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cwd)
    out = []
    for raw in proc.stdout:
        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
        out.append(line)
        if line.strip():
            pg.update(info=f"{what}: {line.strip()[:80]}")
    return proc.wait(), "\n".join(out) + "\n"


def run_sim(tb, dut_files, outdir, name, label="simulação"):
    iverilog = shutil.which("iverilog") or "C:/msys64/ucrt64/bin/iverilog.exe"
    vvp = shutil.which("vvp") or "C:/msys64/ucrt64/bin/vvp.exe"
    out = (outdir / f"{name}.vvp").resolve()
    with progress.Progress(label, tick=True) as pg:
        pg.update(info="compilando (iverilog)")
        rc, text = _run_watched([iverilog, "-g2012", "-o", str(out), str(tb)] + [str(f) for f in dut_files],
                                pg, "compilando")
        if rc != 0:
            if not text.strip():
                text = f"iverilog terminou com código {rc} sem mensagem (ex.: travou na compilação)\n"
            return False, text
        pg.update(info="rodando o testbench")
        rc, text = _run_watched([vvp, "-n", str(out)], pg, "testbench", cwd=outdir)
    # o vvp não propaga o argumento de $finish como código de saída; procura os
    # marcadores de falha usados pelos testbenches do projeto
    ok = rc == 0 and not FAIL_RE.search(text)
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
    ap.add_argument("--max-parts", type=int, default=20000,
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
    ap.add_argument("--no-size", action="store_true",
                    help="não troca as células pelas variantes de fan-out (fica o que o Yosys escolheu)")
    ap.add_argument("--macro", action="append", default=[], metavar="TIPO",
                    help="tipo de módulo implementado como macro (posicionado e roteado uma vez por "
                         "estrutura e copiado em cada instância); repita para vários. Também pode vir "
                         "em \"macros\" no floorplan")
    ap.add_argument("--keep-placement", action="store_true",
                    help="reaproveita o placement salvo mesmo se o código do pcbflow mudou (ex.: um ajuste "
                         "no roteador); fontes, biblioteca, floorplan e opções ainda têm de ser os mesmos")
    ap.add_argument("--fresh", action="store_true",
                    help="ignora o placement e o roteamento salvos da rodada anterior (refaz tudo)")
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
    clock = _Clock()

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

    # placement salvo de uma rodada anterior com as mesmas entradas (cache.py)
    key = cache.fingerprint(args)
    saved, why = (None, None) if args.fresh or args.synth_only else \
        cache.load(out, key, ignore=("code",) if args.keep_placement else ())
    gates_v = out / f"{args.top}_gates.v"
    models = out / "cells_models.v"
    if saved and not gates_v.is_file():
        saved, why = None, f"falta {gates_v.name} da rodada anterior"
    if why:
        log(f"Placement salvo não reaproveitado ({why}): refazendo síntese e placement")

    if saved:
        when = time.strftime("%d/%m %H:%M", time.localtime(saved["time"]))
        clock.stage(f"[0-3/6] Biblioteca, síntese e placement: reaproveitados da rodada de {when} "
                    "(mesmas entradas; --fresh refaz)")
        design, board, fanout, sized = saved["design"], saved["board"], saved["fanout"], saved["sized"]
        stat_text, sims = saved["stat"], dict(saved.get("sims", {}))
        _summary(lib, design, sized, fanout, args)
        lib.write_verilog_models(models)
        _simulate(args, lib, design, out, gates_v, models, sims, clock)
        if sims != saved.get("sims", {}):
            cache.save(out, key, **{k: v for k, v in dict(saved, sims=sims).items() if k not in ("key", "version")})
    else:
        clock.stage(f"[0/6] Biblioteca '{lib.name}' ({len(lib.cells)} células): verificando montagem x Liberty")
        with progress.Progress("verificação das células (simulação de cada .sp)", tick=True):
            problems = cellcheck.check_cells(lib, out)
        if problems:
            log("ERRO: a montagem (.sp) de alguma célula não faz o que o .lib declara:")
            for p in problems:
                log("  " + p)
            return 3
        try:
            el, drives = drive.library_drive(lib)
            problems = drive.check_internal(lib, el, drives) if el else []
            drive.reference_loads(lib, el, drives)
        except ValueError as e:
            problems = [str(e)]
        if problems:
            log("ERRO: drive em pior caso:")
            for p in problems:
                log("  " + p)
            return 3
        liberty = out / "cells.lib"
        lib.write_liberty(liberty)
        lib.write_verilog_models(models)

        clock.stage(f"[1/6] Síntese Yosys de '{args.top}'")
        json_path, gates_v, stat, hier_json = synth.run_yosys(args.src, args.top, liberty, out, flatten=args.flatten,
                                                                latches=lib.latch_techmap())
        stat_text = stat.read_text()
        with progress.Progress("leitura do netlist e expansão em componentes", tick=True):
            design = netlist.load_yosys_json(json_path, args.top, lib, hier_json)
        sized = None
        if lib.variants and not args.no_size:
            with progress.Progress("sizing por fan-out", tick=True):
                sized = sizing.size_design(lib, design, el, drives)
            log(f"      sizing: {len(sized.changed)} instâncias trocadas por variantes de fan-out"
                + (f", {len(sized.unresolved)} sem variante que atenda" if sized.unresolved else ""))
        fanout = [n for n in sizing.check_nets(lib, design, el, drives) if not n.ok]
        _summary(lib, design, sized, fanout, args)
        sims = {}
        _simulate(args, lib, design, out, gates_v, models, sims, clock)

        if args.synth_only:
            clock.done()
            log(stat_text)
            info = place.measure(lib, design, _place_params(args), Rules())
            _write_placement(out / "placement.json", args, lib, design, info)
            log(f"Medidas para o editor de floorplan: {out / 'placement.json'}")
            return 0
        n_parts = len(design.parts)
        if n_parts > args.max_parts:
            log(f"ABORTADO: {n_parts} componentes > --max-parts {args.max_parts}. "
                "Divida o projeto ou aumente o limite.")
            return 2

        macros = sorted(set(args.macro) | set(fplan.macros if fplan else ()))
        clock.stage("[3/6] Placement" + (f" hierárquico (macros: {', '.join(macros)})" if macros else ""))
        rules = Rules()
        params = _place_params(args)
        try:
            if macros:
                board, summary = hier.place_hier(lib, design, params, rules, fplan, macros, args.route_iter, log)
                for typ, path, w, h, cells, n_copies, unrouted, secs in summary:
                    log(f"      macro {typ} (molde {path}): {w:g} x {h:g} mm, {cells} portas, "
                        f"{n_copies} cópia(s), {progress.fmt_time(secs)}"
                        + (f" — {len(unrouted)} ligação(ões) sem rotear por dentro: {', '.join(unrouted[:5])}"
                           if unrouted else ""))
            else:
                board = place.place(lib, design, params, rules, fplan)
        except (floorplan.FloorplanError, hier.HierError) as e:
            log(f"ERRO: {e}")
            return 3
        board.group_cells = {inst: cell for inst, (cell, _) in design.instances.items()}
        board.group_modules = {inst: m for inst, m in design.inst_module.items() if m}
        board.module_types = design.modules
        with progress.Progress("gravando o placement para reaproveitar", tick=True):
            cache.save(out, key, design=design, board=board, fanout=fanout, sized=sized,
                       stat=stat_text, sims=sims)

    by_cell = Counter(c for c, _ in design.instances.values())
    n_parts = len(design.parts)
    # com macros, o placement mede só a lógica solta: o editor precisa do projeto inteiro
    editor = (place.measure(lib, design, _place_params(args), Rules()) if getattr(board, "macro_info", None)
              else board.place_stats["editor"])
    _write_placement(out / "placement.json", args, lib, design, editor, board, fplan)
    reg = board.place_stats.get("regions")
    what = "áreas declaradas" if fplan else "regiões (uma por módulo)"
    log(f"      {f'{reg} {what}, ' if reg else ''}{board.place_stats['rows']} fileiras, HPWL {board.place_stats['hpwl_mm']} mm, "
        f"placa {board.width:.0f} x {board.height:.0f} mm")
    if args.place_only:
        clock.done()
        log(f"Placement para o editor de floorplan: {out / 'placement.json'}")
        log(f"Concluído em {progress.fmt_time(time.time() - t0)}")
        return 0

    clock.stage("[4/6] Roteamento")
    # ponto de controle: parar e rodar de novo retoma o roteamento desta mesma
    # placa da última iteração completa (--fresh começa do zero)
    ckpt = out / "route_state.pkl"
    if args.fresh and ckpt.exists():
        ckpt.unlink()
    route.route(board, args.route_iter, log=lambda m: log("    " + m), checkpoint=ckpt)

    clock.stage("[5/6] Verificação (folgas + conectividade)")
    with progress.Progress("verificação de folgas e conectividade", tick=True):
        errors, unconnected = check.check_board(board)
    log(f"      violações de folga: {len(errors)}")
    for e in errors[:10]:
        log("        " + e)
    log(f"      nets incompletas: {len(unconnected)}")
    for n, c in sorted(unconnected.items())[:10]:
        log(f"        {n}: {c} partes")

    clock.stage("[6/6] Projeto KiCad")
    name = tag
    with progress.Progress("gravando o projeto KiCad", tick=True):
        kicad.write_pcb(board, out / f"{name}.kicad_pcb", title=f"{name} — {lib.name}, {n_parts} componentes")
        kicad.write_project(board, out / f"{name}.kicad_pro")
        kicad.write_bom(board, out / f"{name}_bom.csv")
        netlist.write_switch_level_verilog(lib, design, out / f"{args.top}_switch.v")
    log(f"      {out / (name + '.kicad_pro')}")
    # DRC do KiCad: a referência, porque lê o arquivo escrito com a geometria real
    drc_res = None
    cli = None if args.no_drc else drc.find_cli()
    # o DRC também preenche e salva os planos de VDD/GND; sem ele, eles ficam vazios no arquivo
    unfilled = (" — planos de VDD/GND sem preenchimento: no KiCad, aperte B (preencher zonas)"
                if board.layers >= 4 else "")
    if args.no_drc:
        log("      DRC do KiCad: pulado (--no-drc)" + unfilled)
    elif not cli:
        log("      DRC do KiCad: kicad-cli não encontrado (instale o KiCad 8+ ou defina PCBFLOW_KICAD_CLI)"
            + unfilled)
    else:
        try:
            with progress.Progress("DRC do KiCad (kicad-cli)", tick=True):
                drc_res = drc.run(cli, out / f"{name}.kicad_pcb", out / "drc.json")
            for i, line in enumerate(drc.summary(drc_res)):
                log(("      DRC do KiCad: " if i == 0 else "        ") + line)
        except RuntimeError as e:
            log(f"      DRC do KiCad: {e}")
    _write_report(out / "report.md", args, design, board, by_cell, errors, unconnected, lib, fanout, drc_res,
                  sized)
    clock.done()
    log(f"Concluído em {progress.fmt_time(time.time() - t0)}")
    return 0 if not errors and not unconnected and (drc_res is None or drc.ok(drc_res)) else 1


class _Clock:
    """Tempo de cada etapa: impresso quando a próxima começa (ou no fim)."""

    def __init__(self):
        self.t = None

    def stage(self, title):
        self.done()
        log(title)
        self.t = time.time()

    def done(self):
        if self.t is not None and time.time() - self.t >= 1:
            log(f"      etapa: {progress.fmt_time(time.time() - self.t)}")
        self.t = None


def _summary(lib, design, sized, fanout, args):
    by_cell = Counter(c for c, _ in design.instances.values())
    kinds = Counter(lib.parts[p.model]["kind"] for p in design.parts)
    log("      células: " + ", ".join(f"{k}={v}" for k, v in sorted(by_cell.items())))
    log(f"      {len(design.blocks)} blocos, {len(design.parts)} componentes ("
        + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())) + ")")
    mods = sorted({m for m in design.inst_module.values() if m})
    if mods:
        log(f"      {len(mods)} módulos: " + ", ".join(mods[:12]) + (" ..." if len(mods) > 12 else ""))
    if not fanout:
        return
    # o report.md só sai no fluxo completo: sem ele, a lista vai para o log
    full = not (args.synth_only or args.place_only)
    log(f"      AVISO: {len(fanout)} nets com fan-out acima do que a saída aguenta"
        + (" (veja report.md)" if full else ":"))
    if not full:
        for n in fanout[:15]:
            why = [f"max_fanout {n.limit}"] if n.limit else []
            if n.margin is not None and n.margin != float("inf"):
                why.append(f"folga de Ib {n.margin:.2f}")
            log(f"        {n.net}: {n.inst} {n.cell}.{n.pin} → {n.sinks} entradas"
                + (f" ({', '.join(why)})" if why else ""))
        if len(fanout) > 15:
            log(f"        ... e mais {len(fanout) - 15}")


def _simulate(args, lib, design, out, gates_v, models, sims, clock):
    """Simulação com o testbench (gate-level e de componentes). sims guarda o
    resultado por testbench: com o placement reaproveitado, um testbench que já
    rodou nesta mesma entrada não roda de novo."""
    if not args.tb:
        clock.stage("[2/6] Simulação: pulada (use --tb)")
        return
    th = cache.file_hash(args.tb)
    if th in sims:
        ok, ok2 = sims[th]
        clock.stage("[2/6] Simulação: já feita com este testbench e estas mesmas entradas")
        log(f"      gate-level:       {'OK' if ok else 'FALHOU'}")
        log(f"      componentes:      {'OK' if ok2 else 'FALHOU'}")
        return
    clock.stage("[2/6] Simulação: netlist gate-level e de componentes")
    ok, text = run_sim(args.tb, [gates_v, models], out, "sim_gates", "simulação gate-level")
    log(f"      gate-level:       {'OK' if ok else 'FALHOU'}")
    (out / "sim_gates.log").write_text(text)
    sw = out / f"{args.top}_switch.v"
    netlist.write_switch_level_verilog(lib, design, sw)
    ok2, text2 = run_sim(args.tb, [sw], out, "sim_switch", "simulação de componentes")
    log(f"      componentes:      {'OK' if ok2 else 'FALHOU'}")
    (out / "sim_switch.log").write_text(text2)
    if not (ok and ok2):
        log("      veja sim_gates.log / sim_switch.log")
    sims[th] = (ok, ok2)


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
            "module_types": design.modules, "footprints": parts,
            "macros": getattr(board, "macro_info", None) if board is not None else None}
    Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _write_report(path, args, design, board, by_cell, errors, unconnected, lib, fanout, drc_res=None,
                  sized=None):
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
    blocked = set(getattr(board, "unrouted_blocked", ()))
    for n in board.unrouted:
        L.append(f"- não roteada: `{n}`" + (" (bloqueio físico: sem caminho nem com a placa vazia; "
                                             "veja os pads/pinos dela e o floorplan)" if n in blocked else ""))
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
    if sized:
        L += ["", "## Dimensionamento por fan-out", ""]
        if sized.changed:
            L += ["| Instância | Yosys escolheu | Variante | Entradas alimentadas |", "|---|---|---|---:|"]
            for inst, b, v, k in sized.changed:
                L.append(f"| {inst} | {b} | {v} | {k} |")
        else:
            L.append("Nenhuma troca: as células escolhidas pelo Yosys já atendem às cargas.")
        if sized.unresolved:
            L.append("")
            L.append("Sem variante que atenda (ficou a de maior folga): " + ", ".join(sized.unresolved))
    if fanout:
        L += ["", "## Fan-out acima do que a saída aguenta", "",
              "| Net | Instância | Saída | Entradas | max_fanout | VOH pior caso | Ib / Ib necessária |",
              "|---|---|---|---:|---:|---:|---:|"]
        for n in fanout:
            voh = f"{n.voh:.2f} V" if n.voh is not None else "—"
            mg = f"{n.margin:.2f}" if n.margin is not None and n.margin != float("inf") else "—"
            L.append(f"| `{n.net}` | {n.inst} | {n.cell}.{n.pin} | {n.sinks} | {n.limit or '—'} | {voh} | {mg} |")
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
