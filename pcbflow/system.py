"""Sistema de várias placas (ex.: uma pilha ligada por um barramento).

Cada placa é um módulo top gerado à parte (pcbflow --top <placa>); o sistema é
um módulo Verilog que só liga as placas, como um backplane:

    module sap1 (...);
        sap1_ctrl_board u_ctrl (.bus, .ri, ...);
        sap1_ram_board  u_ram0 (.bus, .ri, .bank(2'd0), ...);
        ...
    endmodule

  pcbflow-system --top sap1 --boards sap1_ctrl_board sap1_ram_board ...

confere o sistema montado a partir das rodadas de cada placa (rode o pcbflow
de cada uma antes; --synth-only basta):

  - drive elétrico de cada ligação entre placas: o que uma placa dirige
    alimenta as cargas de TODAS as placas na mesma linha (cada placa só vê as
    suas). Num barramento, conta a terminação (de uma placa só) contra as
    cargas de todas;
  - corrente estimada de cada placa e da pilha (para dimensionar os pinos de
    alimentação do conector);
  - simulação do testbench do sistema contra os netlists de portas e de
    componentes das placas, ligados pelo módulo do sistema.

Cada rodada de placa grava ports.json (write_ports): as cargas e os drivers de
cada porta, já com o sizing e os buffers da placa.
"""

import argparse
import json
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from . import drive, project, synth
from .library import Library, LibraryError, resolve_family
from .netlist import drivers_by_net
from .sizing import _Model, _sinks_by_net

PORTS = "ports.json"


# ------------------------------------------------------- resumo de uma placa
def write_ports(path, lib, design):
    """Cargas e drivers de cada porta da placa (para o pcbflow-system)."""
    el, drives = drive.library_drive(lib)
    m = _Model(lib, el, drives)
    sinks = _sinks_by_net(lib, design)
    drv = drivers_by_net(lib, design)
    power = {design.vdd, design.gnd}
    ports = {}
    for p in design.ports:
        real = [s for s in sinks.get(p.net, []) if s[0]]
        loads = [ld for si, sp in real for ld in m.loads(design.instances[si][0], sp)]
        drivers = []
        if p.net in power:
            drivers.append({"kind": "const", "value": int(p.net == design.vdd)})
        for inst, pin in drv.get(p.net, []):
            cell = design.instances[inst][0]
            if lib.tristate and cell == lib.tristate["cell"]:
                drivers.append({"kind": "open", "inst": inst})
            elif lib.terminator and cell == lib.terminator["cell"]:
                drivers.append({"kind": "termination", "inst": inst,
                                "g_up": drives[cell].pins[pin].g_up if drives else 0.0})
            else:
                drivers.append({"kind": "cell", "inst": inst, "cell": cell, "pin": pin,
                                "g_up": drives[cell].pins[pin].g_up if drives else 0.0,
                                "max_fanout": lib.meta_of(cell).get("max_fanout")})
        ports[p.name] = {"dir": p.direction, "sinks": len(real),
                         "loads": [[ld.rb, ld.ic, ld.ve] for ld in loads], "drivers": drivers}
    static = sum(drives[c].static_ma for c, _ in design.instances.values()) if drives else None
    data = {"top": design.top, "family": lib.family, "library": lib.name, "parts": len(design.parts),
            # pior caso: todo pull-up conduzindo; típico: metade das saídas em 0
            "current_ma": {"max": static, "typ": static / 2} if static is not None else None,
            "ports": ports}
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


# ----------------------------------------------------- ligação entre placas
class SystemCheckError(Exception):
    pass


def connectivity(sources, top, boards, outdir):
    """Instâncias de placa no módulo do sistema e o que liga cada porta delas:
    ([(instância, placa)], {(instância, porta): net}, portas do sistema
    {nome: (direção, net)}). Nets são bits do Yosys; '0'/'1' são constantes."""
    js = Path(outdir) / "system_hier.json"
    reads = "\n".join(f"read_verilog -sv {Path(s).as_posix()}" for s in sources)
    script = f"{reads}\nhierarchy -check -top {top}\nproc\nwrite_json {js.as_posix()}\n"
    ys = Path(outdir) / "system.ys"
    ys.write_text(script)
    r = subprocess.run([synth.find_yosys(), "-q", "-s", str(ys)], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemCheckError("Yosys falhou ao ler o sistema:\n" + (r.stdout + r.stderr)[-2000:])
    mod = json.loads(js.read_text())["modules"][top]
    insts, conns = [], {}
    for name, c in mod["cells"].items():
        typ = c["type"].lstrip("\\")
        if typ not in boards:
            raise SystemCheckError(f"o módulo {top} deve só ligar placas, mas tem '{name}' ({typ}); "
                               f"placas: {', '.join(boards)}")
        inst = name.lstrip("\\")
        insts.append((inst, typ))
        for pin, bits in c["connections"].items():
            for i, b in enumerate(bits):
                conns[(inst, pin if len(bits) == 1 else f"{pin}[{i}]")] = str(b)
    ports = {}
    for pname, info in mod["ports"].items():
        for i, b in enumerate(info["bits"]):
            ports[pname if len(info["bits"]) == 1 else f"{pname}[{i}]"] = (info["direction"], str(b))
    return sorted(insts), conns, ports


def check_lines(lib, insts, conns, sys_ports, summaries):
    """Avalia cada ligação entre placas: [(net, rótulo, ok, texto)]."""
    el, drives = drive.library_drive(lib)
    from .buffering import buffer_cell
    buf = buffer_cell(lib, _Model(lib, el, drives))
    nets = {}
    for (inst, port), net in conns.items():
        nets.setdefault(net, []).append((inst, port))
    by_inst = dict(insts)
    ext = {net: (name, d) for name, (d, net) in sys_ports.items()}
    out = []
    for net, users in sorted(nets.items(), key=lambda kv: kv[1]):
        if net in ("0", "1", "x", "z"):
            continue                                  # placa com a porta presa (jumper)
        label = ext[net][0] if net in ext else f"{users[0][0]}.{users[0][1]}"
        loads, sinks, cells, opens, terms = [], 0, [], [], []
        for inst, port in users:
            info = summaries[by_inst[inst]]["ports"].get(port)
            if info is None:
                raise SystemCheckError(f"{inst} ({by_inst[inst]}) não tem a porta '{port}' na rodada da placa "
                                   "(rode o pcbflow dela de novo)")
            loads += [drive.Load(*ld) for ld in info["loads"]]
            sinks += info["sinks"]
            for d in info["drivers"]:
                d = dict(d, board=inst)
                if d["kind"] == "cell":
                    cells.append(d)
                elif d["kind"] == "open":
                    opens.append(d)
                elif d["kind"] == "termination":
                    terms.append(d)
        if net in ext and ext[net][1] == "input":
            # entrada do sistema: dirigida de fora, como por um buffer da família
            cells.append({"kind": "cell", "board": "(entrada)", "cell": buf, "pin": lib.cells[buf].outputs[0],
                          "g_up": drives[buf].pins[lib.cells[buf].outputs[0]].g_up if drives else 0.0,
                          "max_fanout": lib.meta_of(buf).get("max_fanout")})
        boards_ = sorted({d["board"] for d in cells + opens})
        if len(cells) > 1 or (cells and opens):
            out.append((net, label, False, "dirigida por várias placas: " + ", ".join(boards_)))
            continue
        if opens:
            term_boards = sorted({d["board"] for d in terms})
            if not terms:
                out.append((net, label, False, f"barramento sem terminação ({len(opens)} drivers em "
                                               f"{', '.join(boards_)}): uma placa deve tê-la"))
                continue
            if len(term_boards) > 1:
                out.append((net, label, False, f"terminação em {len(term_boards)} placas ({', '.join(term_boards)}): "
                                               "só uma deve tê-la (\"bus_termination\" no floorplan das placas)"))
                continue
            g, who = sum(d["g_up"] for d in terms), f"terminação ({term_boards[0]}), {len(opens)} drivers"
            limit = None
        elif cells:
            g, who, limit = cells[0]["g_up"], f"{cells[0]['board']} {cells[0]['cell']}.{cells[0]['pin']}", \
                cells[0]["max_fanout"]
        else:
            if sinks:
                out.append((net, label, False, "sem nenhuma placa dirigindo"))
            continue
        text = f"{who} → {sinks} entradas"
        ok = True
        if limit and sinks > limit:
            ok, text = False, text + f" (max_fanout {limit})"
        if el is not None and g:
            r = drive.evaluate(el, g, loads)
            text += f", VOH {r.voh:.2f} V, folga de Ib {r.margin:.2f}" if r.margin != float("inf") \
                else f", VOH {r.voh:.2f} V"
            ok = ok and r.ok
        out.append((net, label, ok, text))
    return out


# ----------------------------------------------------------------- comando
def main(argv=None):
    from .__main__ import _short, log, run_sim
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="pcbflow-system", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--top", required=True, help="módulo do sistema (só liga as placas)")
    ap.add_argument("--boards", nargs="+", required=True, help="módulos top das placas")
    ap.add_argument("--lib", default="cmos", help="família de células das placas")
    ap.add_argument("--layers", type=int, choices=(2, 4), default=4)
    ap.add_argument("--src", nargs="+", help="fontes (padrão: 'src' do pcbflow.json)")
    ap.add_argument("--tb", help="testbench do sistema (padrão: 'tb' do pcbflow.json para o --top)")
    ap.add_argument("--project", help="pasta do projeto")
    ap.add_argument("--out", help="pasta do relatório (padrão: <out do projeto>/<top>_<família>_sistema)")
    args = ap.parse_args(argv)
    t0 = time.time()
    try:
        proj = project.find(args.project)
        lib = Library(resolve_family(args.lib))
    except (project.ProjectError, LibraryError) as e:
        log(f"ERRO: {e}")
        return 3
    family = Path(lib.path).name
    sfx = "_2l" if args.layers == 2 else ""
    sources = [Path(s) for s in (args.src or proj.sources())]
    tb = args.tb or (proj.testbench(args.top) and str(proj.testbench(args.top)))
    out = Path(args.out) if args.out else proj.out_dir(f"{args.top}_{family}{sfx}_sistema")
    out.mkdir(parents=True, exist_ok=True)

    # rodada de cada placa
    runs, summaries = {}, {}
    for b in args.boards:
        d = proj.out_dir(f"{b}_{family}{sfx}")
        need = [d / PORTS, d / f"{b}_gates.v", d / f"{b}_switch.v"]
        missing = [p.name for p in need if not p.is_file()]
        if missing:
            log(f"ERRO: falta a rodada da placa {b} em {_short(d)} ({', '.join(missing)}): "
                f"rode antes 'pcbflow --top {b} --lib {args.lib}' (--synth-only basta)")
            return 3
        runs[b] = d
        summaries[b] = json.loads((d / PORTS).read_text(encoding="utf-8"))

    log(f"Sistema '{args.top}': {len(args.boards)} placa(s) — {', '.join(args.boards)}")
    try:
        insts, conns, sys_ports = connectivity(sources, args.top, set(args.boards), out)
        lines = check_lines(lib, insts, conns, sys_ports, summaries)
    except SystemCheckError as e:
        log(f"ERRO: {e}")
        return 3
    count = Counter(t for _, t in insts)
    log("  placas montadas: " + ", ".join(f"{t} ×{k}" if k > 1 else t for t, k in sorted(count.items())))

    # corrente
    cur = []
    for b in args.boards:
        c = summaries[b].get("current_ma")
        cur.append((b, count[b], summaries[b]["parts"], c))
    if all(c for *_, c in cur):
        typ = sum(k * c["typ"] for _, k, _, c in cur)
        mx = sum(k * c["max"] for _, k, _, c in cur)
        log(f"  corrente estimada da pilha: {typ / 1000:.1f} A típica, {mx / 1000:.1f} A no pior caso")

    bad = [l for l in lines if not l[2]]
    log(f"  ligações entre placas: {len(lines)}, com problema: {len(bad)}")
    for net, label, ok, text in bad[:20]:
        log(f"    {label}: {text}")

    # simulação do sistema: o módulo do sistema com os netlists das placas
    sims = {}
    if tb:
        top_file = [s for s in sources if re.search(rf"^\s*module\s+{re.escape(args.top)}\b",
                                                      s.read_text(encoding="utf-8", errors="replace"), re.M)]
        if len(top_file) != 1:
            log(f"ERRO: o módulo {args.top} deve estar em um arquivo (achei {len(top_file)})")
            return 3
        others = re.findall(r"^\s*module\s+(\w+)", top_file[0].read_text(encoding="utf-8"), re.M)
        if others != [args.top]:
            log(f"ERRO: {_short(top_file[0])} deve conter só o módulo {args.top} (tem {', '.join(others)}): "
                "na simulação do sistema, as placas vêm dos netlists delas")
            return 3
        pkgs = [s for s in sources if re.search(r"^\s*package\s+\w+", s.read_text(encoding="utf-8",
                                                                                   errors="replace"), re.M)]
        models = out / "cells_models.v"
        lib.write_verilog_models(models)
        log("  simulação do sistema (testbench contra os netlists das placas):")
        for kind, files in (("gate-level", [runs[b] / f"{b}_gates.v" for b in args.boards] + [models]),
                            ("componentes", [runs[b] / f"{b}_switch.v" for b in args.boards])):
            name = "sim_gates" if kind == "gate-level" else "sim_switch"
            ok, text = run_sim(tb, top_file + files, out, name, f"simulação do sistema ({kind})", pre_files=pkgs)
            (out / f"{name}.log").write_text(text)
            sims[kind] = ok
            log(f"    {kind + ':':<17} {'OK' if ok else 'FALHOU'}")
        if not all(sims.values()):
            log(f"    veja {_short(out / 'sim_gates.log')} / {_short(out / 'sim_switch.log')}")
    else:
        log("  simulação do sistema: pulada (sem testbench; use --tb ou 'tb' no pcbflow.json)")

    _report(out / "report.md", args, insts, cur, lines, sims)
    log(f"  relatório: {_short(out / 'report.md')}")
    log(f"Concluído em {time.time() - t0:.0f} s")
    return 0 if not bad and all(sims.values()) else 1


def _report(path, args, insts, cur, lines, sims):
    L = [f"# Sistema `{args.top}`", "", "## Placas", "",
         "| Placa | Cópias | Componentes | Corrente típica | Pior caso |", "|---|---:|---:|---:|---:|"]
    for b, k, parts, c in cur:
        L.append(f"| {b} | {k} | {parts} | " + (f"{c['typ']:.0f} mA | {c['max']:.0f} mA |" if c else "— | — |"))
    L += ["", "Instâncias: " + ", ".join(f"`{i}` ({t})" for i, t in insts), "",
          "## Ligações entre placas", "", "| Linha | Situação | Drive |", "|---|---|---|"]
    for net, label, ok, text in sorted(lines, key=lambda l: (l[2], l[1])):
        L.append(f"| `{label}` | {'OK' if ok else '**problema**'} | {text} |")
    if sims:
        L += ["", "## Simulação do sistema", ""] + [f"- {k}: {'OK' if v else 'FALHOU'}" for k, v in sims.items()]
    Path(path).write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
