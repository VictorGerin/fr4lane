"""Simulação analógica das células no ngspice (pcbflow-cellsim).

O cellcheck confere a lógica de cada montagem com chaves ideais; aqui cada
.sp é simulado como circuito de verdade, com o modelo SPICE de cada componente
("spice" no library.json), nos cantos de pior caso da família (VDD, tolerância
dos resistores, parâmetros do transistor e temperatura):

  - combinacionais: todas as combinações de entrada, com as entradas no nível
    de pior caso (alto = voh_min, baixo = 2 Vce(sat)) e cada saída carregada
    pelo fan-out máximo; confere o nível da saída e o que a carga (a porta de
    referência, ex.: INV) entende dele, e mede o atraso. Uma saída num nível
    intermediário que a carga ainda entende vira aviso de margem pequena;
  - flip-flops: sequência de dados nas bordas de clock (e o clear, se houver);
    mede clock -> Q, o menor período que funciona e o hold e o setup;
  - latches: transparente e travado; mede D -> Q e o hold depois do enable.

Um hold maior que o clock -> Q mínimo vira aviso: um flip-flop ligado direto
em outro capturaria o dado novo na mesma borda.

  pcbflow-cellsim --lib rtl [--cells DFF INV ...] [--out build/cellsim]
  pcbflow-cellsim --lib rtl --export docs/cellsim/rtl

--export grava, para cada célula, o teste funcional no primeiro canto como um
netlist do ngspice autocontido (<CÉLULA>.cir: modelo, subcircuitos, vetores de
teste e medidas, com o resultado esperado comentado), o gráfico das formas de
onda (<CÉLULA>.png) e um README.md com os resultados de todos os cantos: quem
quiser conferir uma célula roda "ngspice -b <CÉLULA>.cir" sem o pcbflow.

"spice" no library.json:
  "models":  {"NPN": "spice/BC548B.lib"}   chave do parts.json -> arquivo com o .model
  "corners": {"lento": {"vdd": 4.75, "temp": 0, "pull_up": 1.05, "base": 1.05,
                        "params": {"NPN": {"Bf": 110}}}, ...}
  pull_up escala os resistores ligados ao VDD; base, os outros.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from . import drive, liberty
from .library import Library, LibraryError, resolve_family

VTH = 1.0            # limiar para medir atrasos (entre o nível baixo e o alto)
STEP = 20e-6         # duração de cada combinação de entrada nas combinacionais
PERIOD = 20e-6       # período do clock no teste funcional dos flip-flops
PERIODS = (1e-5, 5e-6, 2e-6, 1e-6, 5e-7, 2e-7, 1e-7)
HOLDS = (1e-6, 5e-7, 3e-7, 2e-7, 1e-7, 5e-8, 2e-8, 1e-8)
SETUPS = (1e-6, 5e-7, 3e-7, 2e-7, 1e-7, 5e-8, 2e-8, 1e-8)
EDGE = 2e-9          # rampa das fontes ideais
VOL_MAX = 0.5        # nível baixo máximo: a próxima base fica cortada


class CellSimError(Exception):
    pass


def find_ngspice():
    exe = os.environ.get("PCBFLOW_NGSPICE")
    if exe and Path(exe).is_file():
        return exe
    for name in ("ngspice_con", "ngspice"):
        if shutil.which(name):
            return shutil.which(name)
    for cand in ("C:/msys64/ucrt64/bin/ngspice_con.exe", "C:/msys64/mingw64/bin/ngspice_con.exe"):
        if Path(cand).is_file():
            return cand
    return None


# ------------------------------------------------------------------ modelos
def _model_params(text, path):
    """'.model NOME TIPO(k=v ...)' -> (TIPO, {k: v}), juntando as linhas '+'."""
    body = " ".join(l.lstrip("+").strip() for l in text.splitlines()
                    if l.strip() and not l.lstrip().startswith("*"))
    m = re.search(r"\.model\s+\S+\s+(\w+)\s*\((.*)\)", body, re.I | re.S)
    if not m:
        raise CellSimError(f"{path}: esperado um '.model NOME TIPO(...)'")
    params = dict(re.findall(r"(\w+)\s*=\s*([^\s)]+)", m.group(2)))
    return m.group(1).upper(), params


@dataclass
class Corner:
    name: str
    vdd: float
    temp: float
    pull_up: float
    base: float
    params: dict = field(default_factory=dict)     # chave do parts.json -> {parâmetro: valor}


def spice_setup(lib):
    """(modelos {chave: (tipo, parâmetros)}, [Corner]) da família, ou erro."""
    cfg = lib.meta.get("spice")
    if not cfg:
        raise CellSimError(f"a família '{lib.name}' não declara \"spice\" no library.json "
                           "(modelos SPICE dos componentes e cantos)")
    models = {}
    for key, rel in cfg.get("models", {}).items():
        if key not in lib.parts:
            raise CellSimError(f"library.json: spice.models cita '{key}', que não está no parts.json")
        path = (lib.path / rel).resolve()
        if not path.is_file():
            raise CellSimError(f"library.json: modelo {rel} não encontrado")
        models[key] = _model_params(path.read_text(encoding="utf-8"), path)
    need = {p for s in lib.subckts.values() for e in s.devices if e.letter in "QMD" for p in [e.model]}
    missing = sorted(need - set(models))
    if missing:
        raise CellSimError(f"library.json: sem modelo SPICE para {', '.join(missing)} (spice.models)")
    corners = [Corner(n, float(c.get("vdd", 5.0)), float(c.get("temp", 27)), float(c.get("pull_up", 1.0)),
                      float(c.get("base", 1.0)), c.get("params", {}))
               for n, c in cfg.get("corners", {"típico": {}}).items()]
    return models, corners


# ---------------------------------------------------------------- netlists
def subckt_text(lib, names):
    """Os .subckt das células (e dos que elas instanciam), com os resistores
    escalados pelos parâmetros kup (ligados ao VDD) e kb (os outros)."""
    out, done = [], set()

    def emit(n):
        if n in done:
            return
        done.add(n)
        sub = lib.subckts[n]
        for x in sub.instances:
            emit(x.model)
        out.append(f".subckt {n} {' '.join(sub.pins)}")
        for e in sub.elements:
            if e.letter == "X":
                out.append(f"{e.name} {' '.join(e.nodes)} {e.model}")
            elif e.letter == "R":
                k = "kup" if lib.vdd in e.nodes else "kb"
                out.append(f"{e.name} {' '.join(e.nodes)} {{{drive.parse_value(e.value):g}*{k}}}")
            elif e.letter == "C":
                out.append(f"{e.name} {' '.join(e.nodes)} {drive.parse_value(e.value):g}")
            elif e.letter == "Q":
                out.append(f"{e.name} {' '.join(e.nodes)} {e.model}")
            elif e.letter == "M":
                out.append(f"{e.name} {' '.join(e.nodes)} {e.nodes[2]} {e.model}")
            elif e.letter == "D":
                out.append(f"{e.name} {' '.join(e.nodes)} {e.model}")
            else:
                raise CellSimError(f"{n}: elemento {e.name} ({e.letter}) sem equivalente no ngspice")
        out.append(f".ends {n}")
    for n in names:
        emit(n)
    return "\n".join(out)


def header(lib, models, corner, cells):
    lines = [f"* pcbflow-cellsim: canto {corner.name}", f".temp {corner.temp:g}",
             f".param kup={corner.pull_up:g} kb={corner.base:g}"]
    for key, (kind, params) in models.items():
        p = dict(params)
        p.update({k: str(v) for k, v in corner.params.get(key, {}).items()})
        lines.append(f".model {key} {kind}(" + " ".join(f"{k}={v}" for k, v in p.items()) + ")")
    lines.append(subckt_text(lib, cells))
    lines.append(f"VDD vdd 0 {corner.vdd:g}")
    return "\n".join(lines)


def instance(lib, cell, name, nets):
    """Linha X de uma célula: nets {pino: net}; VDD/GND da família -> vdd/0."""
    pins = lib.subckts[cell].pins
    nodes = ["vdd" if p == lib.vdd else "0" if p == lib.gnd else nets[p] for p in pins]
    return f"X{name} {' '.join(nodes)} {cell}"


def pwl(points):
    """[(t, v)] -> PWL com degraus de EDGE."""
    out, last = [], None
    for t, v in points:
        if last is None:
            out.append(f"0 {v:g}")
        elif v != last:
            out += [f"{t:.9g} {last:g}", f"{t + EDGE:.9g} {v:g}"]
        last = v
    return "PWL(" + " ".join(out) + ")"


def run_deck(ngspice, path, text):
    path.write_text(text, encoding="utf-8")
    r = subprocess.run([ngspice, "-b", path.name], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=path.parent)
    out = r.stdout + r.stderr
    (path.with_suffix(".log")).write_text(out, encoding="utf-8")
    vals = {m.group(1).lower(): float(m.group(2))
            for m in re.finditer(r"^(\w+)\s*=\s*([-+0-9.eE]+)", out, re.M)}
    if "error" in out.lower() and not vals:
        raise CellSimError(f"ngspice falhou em {path.name}:\n{out[-1500:]}")
    return vals


# ------------------------------------------------------------------ captura
def _capture(deck, name, signals, about):
    """Netlist para publicar: o comentário com os vetores e o esperado no topo e
    as formas de onda gravadas em <name>.dat (em passos uniformes)."""
    wr = ["linearize", "set wr_singlescale", "set wr_vecnames",
          f"wrdata {name}.dat " + " ".join(f"v({x})" for x in signals)]
    deck = deck.replace("\nrun\n", "\nrun\n" + "\n".join(wr) + "\n", 1)
    return "\n".join(("* " + l) if l else "*" for l in about) + "\n" + deck


def _about(lib, corner, cell, lv, loads, vectors):
    c = lib.cells[cell]
    desc = lib.meta_of(cell).get("description", "")
    models = ", ".join(f"{k}: {v}" for k, v in lib.meta.get("spice", {}).get("models", {}).items())
    return [f"{cell} — {desc}".rstrip(" —"),
            f"família {lib.name}, canto {corner.name} (VDD {corner.vdd:g} V, {corner.temp:g} °C; modelos {models})",
            "gerado por pcbflow-cellsim --export; rodar: ngspice -b " + f"{cell}.cir "
            f"(imprime as medidas e grava {cell}.dat)", "",
            f"entradas no nível de pior caso: alto = {lv.vih:g} V, baixo = {lv.vil:g} V; " + loads,
            f"saída: 1 se >= {lv.voh_min:g} V, 0 se <= {lv.vol_max:g} V", "",
            "vetores de teste (medida: valor esperado):"] + ["  " + v for v in vectors] + [""]


def _loads_note(lib, cell, outs):
    parts = []
    for o in outs:
        rcell, rpin, n = fanout_load(lib, cell, o)
        parts.append(f"{o} leva {n} carga(s) {rcell}.{rpin}")
    return "; ".join(parts)


# ------------------------------------------------------------------ níveis
@dataclass
class Levels:
    vih: float          # nível alto das entradas (pior caso)
    vil: float          # nível baixo das entradas (pior caso)
    voh_min: float      # nível alto mínimo aceito na saída
    vol_max: float      # nível baixo máximo aceito na saída


def levels(lib, corner):
    el = drive.electrical_of(lib)
    voh = el.voh_min if el else 0.7 * corner.vdd
    vol = (2 * el.vce_sat if el else 0.1 * corner.vdd)
    return Levels(vih=voh, vil=vol, voh_min=voh, vol_max=VOL_MAX if el else 0.3 * corner.vdd)


def logic(v, lv):
    return 1 if v >= lv.voh_min else 0 if v <= lv.vol_max else None


def fanout_load(lib, cell, pin):
    """Quantas cargas de referência (ex.: INV.A) penduradas na saída: o
    max_fanout da célula, limitado ao que o drive em pior caso aguenta."""
    el, drives = drive.library_drive(lib)
    ref = (el.reference_load if el else "") or "INV.A"
    rcell, _, rpin = ref.partition(".")
    n = lib.meta_of(cell).get("max_fanout")
    if el and drives:
        pd = drives[cell].pins[pin]
        cap = drive.capacity(el, pd.g_up, pd.loads, drive.reference_loads(lib, el, drives)) if pd.g_up else 0
        n = min(n, cap) if n else cap
    return rcell, rpin, max(1, n or 1)


def loads_text(lib, cell, outs):
    out = []
    for o, net in outs.items():
        rcell, rpin, n = fanout_load(lib, cell, o)
        others = [p for p in lib.subckts[rcell].pins if p not in (lib.vdd, lib.gnd, rpin)]
        for k in range(n):
            nets = {rpin: net, **{p: f"ld_{net}_{k}_{p}" for p in others}}
            out.append(instance(lib, rcell, f"ld_{net}_{k}", nets))
    return "\n".join(out)


# ---------------------------------------------------------- combinacionais
def sim_comb(lib, models, corner, cell, work, ngspice, capture=None):
    c = lib.cells[cell]
    lv = levels(lib, corner)
    ins, outs = c.inputs, c.outputs
    n = len(ins)
    combos = list(range(2 ** n)) + [0]                  # volta ao início: mede as duas transições
    src = []
    for i, p in enumerate(ins):
        pts = [(k * STEP, lv.vih if (combo >> (n - 1 - i)) & 1 else lv.vil) for k, combo in enumerate(combos)]
        src.append(f"V_{p} in_{p} 0 {pwl(pts)}")
    nets = {**{p: f"in_{p}" for p in ins}, **{o: f"out_{o}" for o in outs}}
    expect = [{o: _expected(lib, c, o, {p: (combo >> (n - 1 - i)) & 1 for i, p in enumerate(ins)}) for o in outs}
              for combo in combos]
    meas = []
    for k in range(len(combos)):
        for o in outs:
            at = (k + 1) * STEP - STEP / 20
            meas.append(f"meas tran s_{o}_{k} FIND v(out_{o}) AT={at:.9g}")
            lnet = _load_out(lib, cell, o)
            if lnet:
                meas.append(f"meas tran l_{o}_{k} FIND v({lnet}) AT={at:.9g}")
            if k and None not in (expect[k][o], expect[k - 1][o]) and expect[k][o] != expect[k - 1][o]:
                meas.append(f"meas tran d_{o}_{k} TRIG AT={k * STEP:.9g} TARG v(out_{o}) VAL={VTH} "
                            f"TD={k * STEP:.9g} CROSS=1")
    term = []
    for o in outs:                                      # drivers de coletor aberto: a terminação do barramento
        if c.pins[o].get("three_state") and lib.terminator:
            term.append(instance(lib, lib.terminator["cell"], f"term_{o}", {lib.terminator["pin"]: f"out_{o}"}))
    rcells = {fanout_load(lib, cell, o)[0] for o in outs}
    deck = "\n".join([header(lib, models, corner, [cell, *rcells] + ([lib.terminator["cell"]] if term else [])),
                      *src, instance(lib, cell, "dut", nets), *term,
                      loads_text(lib, cell, {o: f"out_{o}" for o in outs}),
                      f".tran {STEP / 500:.3g} {len(combos) * STEP:.9g}", ".control", "run", *meas, "quit",
                      ".endc", ".end"])
    path = work / f"{cell}_{corner.name}.cir"
    if capture:
        vectors = []
        for k, combo in enumerate(combos):
            env = {p: (combo >> (n - 1 - i)) & 1 for i, p in enumerate(ins)}
            want = ", ".join(f"s_{o}_{k}: {o}={expect[k][o]}" for o in outs)
            vectors.append(f"{k * STEP * 1e6:g}-{(k + 1) * STEP * 1e6:g} µs  {_env(env) or '(sem entradas)'}  ->  {want}")
        deck = _capture(deck, capture.name, [f"in_{p}" for p in ins] + [f"out_{o}" for o in outs],
                        _about(lib, corner, cell, lv, _loads_note(lib, cell, outs), vectors))
        path = capture.with_suffix(".cir")
    vals = run_deck(ngspice, path, deck)
    fails, warns = [], []
    for k, combo in enumerate(combos):
        env = {p: (combo >> (n - 1 - i)) & 1 for i, p in enumerate(ins)}
        for o in outs:
            want = expect[k][o]
            v = vals.get(f"s_{o}_{k}".lower())
            if v is None:
                fails.append(f"{o}: sem medida na combinação {env}")
                continue
            if want is None or logic(v, lv) == want:
                continue
            # nível fora da faixa: vale o que a porta seguinte entende dele
            lv_out = vals.get(f"l_{o}_{k}".lower())
            load_ok = lv_out is not None and logic(lv_out, lv) == 1 - want
            if logic(v, lv) is None and load_ok:
                warns.append(f"{o} = {v:.2f} V com {_env(env)}: fora da faixa (esperado {want}), "
                             f"mas a carga ainda entende {want}")
            else:
                fails.append(f"{o} = {v:.2f} V com {_env(env)} (esperado {want})"
                             + (f"; a carga ficou em {lv_out:.2f} V" if lv_out is not None else ""))
    delays = [v for k, v in vals.items() if k.startswith("d_") and v > 0]
    return {"ok": not fails, "fails": fails, "warns": warns, "tpd": max(delays) if delays else None}


def _load_out(lib, cell, o):
    """Net da saída da primeira carga de referência pendurada em o (None se a
    carga não for um inversor de uma entrada, que inverte o nível)."""
    rcell, rpin, _ = fanout_load(lib, cell, o)
    c = lib.cells[rcell]
    if len(c.inputs) != 1 or len(c.outputs) != 1:
        return None
    if liberty.parse_expr(c.pins[c.outputs[0]]["function"]) != ("not", ("var", rpin)):
        return None
    return f"ld_out_{o}_0_{c.outputs[0]}"


def _expected(lib, c, o, env):
    """Nível esperado na saída o; num driver de barramento desligado, o da terminação."""
    pin = c.pins[o]
    if pin.get("three_state") and liberty.eval_expr(liberty.parse_expr(pin["three_state"]), env):
        return lib.terminator["level"] if lib.terminator else None
    return liberty.eval_expr(liberty.parse_expr(pin["function"]), env)


def _env(env):
    return " ".join(f"{k}={v}" for k, v in env.items())


# -------------------------------------------------------------- flip-flops
def _ff_pins(c):
    ff = c.ff
    ck = liberty.parse_expr(ff["clocked_on"])
    rising = ck[0] == "var"
    clk = ck[1] if rising else ck[1][1]
    asyn = {}
    for key in ("clear", "preset"):
        if key in ff:
            e = liberty.parse_expr(ff[key])
            v = sorted(liberty.expr_vars(e))[0]
            asyn[v] = (key, next(x for x in (0, 1) if not liberty.eval_expr(e, {v: x})))
    data = [p for p in c.inputs if p != clk and p not in asyn]
    q = [o for o in c.outputs if c.pins[o]["function"].strip() == ff["iq"]]
    return clk, rising, data, asyn, q[0] if q else c.outputs[0]


def _ff_deck(lib, models, corner, cell, period, bits, change, extra_meas=(), clear_at=None, tstep=None):
    """Clock com bordas ativas em k*period (k >= 1); o dado muda 'change' antes
    de cada borda ativa (negativo: depois). Devolve (texto, instantes de medida)."""
    c = lib.cells[cell]
    lv = levels(lib, corner)
    clk, rising, data, asyn, q = _ff_pins(c)
    hi, lo = lv.vih, lv.vil
    a, b = (lo, hi) if rising else (hi, lo)
    n = len(bits)
    ck = f"V_{clk} in_{clk} 0 PULSE({a:g} {b:g} {period:.9g} {EDGE:g} {EDGE:g} {period / 2 - EDGE:.9g} {period:.9g})"
    d = data[0]
    pts, v = [(0.0, lo)], 0
    for i, bit in enumerate(bits):
        t = (i + 1) * period - change
        pts.append((t, hi if bit else lo))
    src = [ck, f"V_{d} in_{d} 0 {pwl(pts)}"]
    for p, (key, inactive) in asyn.items():
        pts = [(0.0, hi if inactive else lo)]
        if clear_at:
            t0, t1 = clear_at
            pts += [(t0, lo if inactive else hi), (t1, hi if inactive else lo)]
        src.append(f"V_{p} in_{p} 0 {pwl(pts)}")
    for p in data[1:]:
        src.append(f"V_{p} in_{p} 0 {lo:g}")
    nets = {**{p: f"in_{p}" for p in c.inputs}, **{o: f"out_{o}" for o in c.outputs}}
    rcell = fanout_load(lib, cell, q)[0]
    t_end = (n + 1) * period + (clear_at[1] - clear_at[0] + period if clear_at else 0)
    meas = [f"meas tran q_{k} FIND v(out_{q}) AT={(k + 1) * period + 0.45 * period:.9g}" for k in range(n)]
    deck = "\n".join([header(lib, models, corner, [cell, rcell]), *src, instance(lib, cell, "dut", nets),
                      loads_text(lib, cell, {q: f"out_{q}"}),
                      f".tran {tstep or min(period / 400, 5e-9):.3g} {t_end:.9g}", ".control", "run", *meas, *extra_meas,
                      "quit", ".endc", ".end"])
    return deck, q, clk


BITS = [1, 0, 1, 1, 0, 0, 1, 0, 1, 1, 1, 0]


def _sweep(grid, ok):
    """Varre a grade do maior para o menor: (último que passou, primeiro que
    falhou). (menor da grade, None) se tudo passa; (None, maior) se nada passa."""
    passed = None
    for t in grid:
        if not ok(t):
            return passed, t
        passed = t
    return passed, None


def _ff_ok(vals, bits, lv):
    got = [logic(vals.get(f"q_{k}", float("nan")), lv) for k in range(len(bits))]
    return got == bits


def sim_ff(lib, models, corner, cell, work, ngspice, capture=None):
    c = lib.cells[cell]
    lv = levels(lib, corner)
    out = {"fails": []}
    path = work / f"{cell}_{corner.name}"

    def run(tag, period, change, bits=BITS, extra=(), clear_at=None):
        deck, q, clk = _ff_deck(lib, models, corner, cell, period, bits, change, extra, clear_at)
        return run_deck(ngspice, Path(f"{path}_{tag}.cir"), deck), q, clk

    # funcional, com período folgado e o dado mudando longe das bordas
    clk_name, rising, data, asyn, qpin = _ff_pins(c)
    if capture:
        # para publicar: o funcional, com o clear (se houver) no fim
        bits = BITS
        clear = None
        tail = []
        if asyn:
            key, _ = next(iter(asyn.values()))
            t0 = (len(bits) + 0.5) * PERIOD
            clear = (t0, t0 + 0.4 * PERIOD)
            tail = [f"meas tran rst FIND v(out_{qpin}) AT={t0 + 0.3 * PERIOD:.9g}"]
        deck, *_ = _ff_deck(lib, models, corner, cell, PERIOD, bits, PERIOD / 4, tail, clear, tstep=PERIOD / 400)
        edge = "subida" if rising else "descida"
        vectors = [f"borda de {edge} {k + 1} em {(k + 1) * PERIOD * 1e6:g} µs: {data[0]}={b} "
                   f"(muda {PERIOD / 4 * 1e6:g} µs antes)  ->  q_{k}: {qpin}={b}" for k, b in enumerate(bits)]
        if asyn:
            p, (key, inactive) = next(iter(asyn.items()))
            vectors.append(f"{p} = {1 - inactive} de {clear[0] * 1e6:g} a {clear[1] * 1e6:g} µs ({key} assíncrono)"
                           f"  ->  rst: {qpin}={0 if key == 'clear' else 1}")
        sig = [f"in_{clk_name}", f"in_{data[0]}"] + [f"in_{p}" for p in asyn] + [f"out_{qpin}"]
        deck = _capture(deck, capture.name, sig, _about(lib, corner, cell, lv, _loads_note(lib, cell, [qpin]), vectors))
        vals = run_deck(ngspice, capture.with_suffix(".cir"), deck)
        ok = _ff_ok(vals, bits, lv) and (not asyn or logic(vals.get("rst", float("nan")), lv) ==
                                         (0 if next(iter(asyn.values()))[0] == "clear" else 1))
        return {"ok": ok, "fails": [] if ok else ["teste funcional exportado falhou"], "signals": sig}
    meas = []
    for k in range(1, len(BITS)):
        if BITS[k] != BITS[k - 1]:
            td = (k + 1) * PERIOD - PERIOD / 10
            e = "RISE" if BITS[k] else "FALL"
            meas.append(f"meas tran ckq_{k} TRIG v(in_{clk_name}) VAL={(lv.vih + lv.vil) / 2:g} TD={td:.9g} "
                        f"{'RISE' if rising else 'FALL'}=1 TARG v(out_{qpin}) VAL={VTH} TD={td:.9g} {e}=1")
    vals, q, clk = run("func", PERIOD, PERIOD / 4, extra=meas)
    if not _ff_ok(vals, BITS, lv):
        got = [round(vals.get(f"q_{k}", float("nan")), 2) for k in range(len(BITS))]
        out["fails"].append(f"captura errada com período de {PERIOD * 1e6:g} µs: Q = {got}, esperado {BITS}")
    ckq = [v for k, v in vals.items() if k.startswith("ckq_") and v > 0]
    out["ckq"] = (min(ckq), max(ckq)) if ckq else None
    # clear/preset assíncrono: no meio de um ciclo, Q vai ao valor e fica até soltar
    if asyn:
        key, inactive = next(iter(asyn.values()))
        level = 0 if key == "clear" else 1
        bits = [1 - level] * 4
        t0 = 4.5 * PERIOD
        extra = [f"meas tran rst FIND v(out_{qpin}) AT={t0 + 0.3 * PERIOD:.9g}"]
        vals, *_ = run("async", PERIOD, PERIOD / 4, bits=bits, extra=extra, clear_at=(t0, t0 + 0.4 * PERIOD))
        if logic(vals.get("rst", float("nan")), lv) != level:
            out["fails"].append(f"{key} assíncrono não levou Q a {level} (Q = {vals.get('rst', float('nan')):.2f} V)")
    # menor período que funciona
    out["period"] = None
    for p in PERIODS:
        vals, *_ = run(f"p{p:g}", p, p / 4)
        if not _ff_ok(vals, BITS, lv):
            break
        out["period"] = p
    # hold: o dado muda h DEPOIS da borda e o valor antigo tem de ficar. O hold
    # necessário fica entre o último h que passou e o primeiro que falhou.
    out["hold"] = _sweep(HOLDS, lambda h: _ff_ok(run(f"h{h:g}", PERIOD, -h)[0], [0] + BITS[:-1], lv))
    # setup: o dado muda s ANTES da borda e o valor novo tem de entrar
    out["setup"] = _sweep(SETUPS, lambda s: _ff_ok(run(f"s{s:g}", PERIOD, s)[0], BITS, lv))
    out["ok"] = not out["fails"]
    return out


# ----------------------------------------------------------------- latches
def sim_latch(lib, models, corner, cell, work, ngspice, capture=None):
    c = lib.cells[cell]
    lv = levels(lib, corner)
    lt = c.latch
    en_e = liberty.parse_expr(lt["enable"])
    high = en_e[0] == "var"
    en = en_e[1] if high else en_e[1][1]
    d = liberty.parse_expr(lt["data_in"])[1]
    q = next(o for o in c.outputs if c.pins[o]["function"].strip() == lt["iq"])
    on, off = (lv.vih, lv.vil) if high else (lv.vil, lv.vih)
    T = STEP
    # transparente: E ligado, D muda 3 vezes; travado: E desliga, D muda e Q fica
    en_pts = [(0.0, on), (4 * T, off)]
    d_pts = [(0.0, lv.vil), (T, lv.vih), (2 * T, lv.vil), (3 * T, lv.vih), (5 * T, lv.vil), (6 * T, lv.vih)]
    want = [(0.9 * T, 0), (1.9 * T, 1), (2.9 * T, 0), (3.9 * T, 1), (5.9 * T, 1), (6.9 * T, 1)]
    nets = {**{p: f"in_{p}" for p in c.inputs}, **{o: f"out_{o}" for o in c.outputs}}
    meas = [f"meas tran s_{k} FIND v(out_{q}) AT={t:.9g}" for k, (t, _) in enumerate(want)]
    meas += [f"meas tran dq_{k} TRIG AT={t:.9g} TARG v(out_{q}) VAL={VTH} TD={t:.9g} CROSS=1"
             for k, t in enumerate((T, 2 * T, 3 * T))]
    rcell = fanout_load(lib, cell, q)[0]
    deck = "\n".join([header(lib, models, corner, [cell, rcell]), f"V_{en} in_{en} 0 {pwl(en_pts)}",
                      f"V_{d} in_{d} 0 {pwl(d_pts)}", instance(lib, cell, "dut", nets),
                      loads_text(lib, cell, {q: f"out_{q}"}), f".tran {T / 500:.3g} {7 * T:.9g}",
                      ".control", "run", *meas, "quit", ".endc", ".end"])
    path = work / f"{cell}_{corner.name}.cir"
    if capture:
        vectors = [f"{t * 1e6:g} µs ({'transparente' if t < 4 * T else 'travado'})  ->  s_{k}: {q}={w}"
                   for k, (t, w) in enumerate(want)]
        vectors.insert(0, f"{en} ligado até {4 * T * 1e6:g} µs; {d} muda em 20, 40, 60, 100 e 120 µs")
        deck = _capture(deck, capture.name, [f"in_{en}", f"in_{d}", f"out_{q}"],
                        _about(lib, corner, cell, lv, _loads_note(lib, cell, [q]), vectors))
        path = capture.with_suffix(".cir")
    vals = run_deck(ngspice, path, deck)
    fails = []
    for k, (t, w) in enumerate(want):
        v = vals.get(f"s_{k}")
        if v is None or logic(v, lv) != w:
            fails.append(f"Q = {v if v is None else round(v, 2)} V em {t * 1e6:.1f} µs "
                         f"({'transparente' if t < 4 * T else 'travado'}; esperado {w})")
    dq = [v for k, v in vals.items() if k.startswith("dq_") and v > 0]
    return {"ok": not fails, "fails": fails, "tpd": max(dq) if dq else None}


# ----------------------------------------------------------------- comando
def check_family(lib, cells=None, work=None, log=print, jobs=None):
    """{célula: {canto: resultado}} e [avisos]."""
    ngspice = find_ngspice()
    if not ngspice:
        raise CellSimError("ngspice não encontrado (MSYS2: pacman -S mingw-w64-ucrt-x86_64-ngspice; "
                           "Debian: apt install ngspice; ou defina PCBFLOW_NGSPICE)")
    models, corners = spice_setup(lib)
    names = cells or list(lib.cells)
    unknown = [n for n in names if n not in lib.cells]
    if unknown:
        raise CellSimError(f"células inexistentes: {', '.join(unknown)}")
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)

    def one(job):
        cell, corner = job
        c = lib.cells[cell]
        fn = sim_ff if c.ff else sim_latch if c.latch else sim_comb
        try:
            return cell, corner.name, fn(lib, models, corner, cell, work, ngspice)
        except CellSimError as e:
            return cell, corner.name, {"ok": False, "fails": [str(e)]}

    jobs_list = [(n, c) for n in names for c in corners]
    res = {}
    with ThreadPoolExecutor(max_workers=jobs or min(8, os.cpu_count() or 2)) as ex:
        for cell, corner, r in ex.map(one, jobs_list):
            res.setdefault(cell, {})[corner] = r
            log(f"  {cell:<9} {corner:<7} {'OK' if r['ok'] else 'FALHOU'}")
    warns = [f"{cell} ({corner}): {w}" for cell, by in res.items() for corner, r in by.items()
             for w in r.get("warns", [])]
    for cell, by in res.items():
        ckqs = [r["ckq"][0] for r in by.values() if r.get("ckq")]
        # conservador: o lado de cima do intervalo do hold (o último que passou)
        holds = [r["hold"][0] or r["hold"][1] for r in by.values() if r.get("hold") and r["hold"][1]]
        if ckqs and holds and max(holds) >= min(ckqs):
            warns.append(f"{cell}: hold de até {max(holds) * 1e9:.0f} ns >= clock -> Q mínimo de "
                         f"{min(ckqs) * 1e9:.0f} ns: um {cell} ligado direto em outro capturaria o dado novo")
    return res, [c.name for c in corners], warns


def export(lib, cells, outdir, res, corners, warns, log=print):
    """Netlists autocontidos, gráficos e README.md para publicar (veja --export)."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        raise CellSimError("--export precisa do matplotlib (pip install matplotlib)") from None
    ngspice = find_ngspice()
    models, cs = spice_setup(lib)
    corner = cs[0]
    lv = levels(lib, corner)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    shown = {}
    for cell in cells:
        c = lib.cells[cell]
        fn = sim_ff if c.ff else sim_latch if c.latch else sim_comb
        r = fn(lib, models, corner, cell, outdir, ngspice, capture=outdir / cell)
        dat = outdir / f"{cell}.dat"
        names = dat.read_text(encoding="utf-8").splitlines()[0].split()
        data = np.loadtxt(dat, skiprows=1, ndmin=2)
        sig = names[1:]
        fig, axs = plt.subplots(len(sig), 1, sharex=True, figsize=(9, 0.95 * len(sig) + 1.1), squeeze=False)
        for i, name in enumerate(sig):
            ax = axs[i][0]
            label = re.sub(r"^v\((in|out)_(.*)\)$", r"\2", name)
            out = name.startswith("v(out_")
            ax.plot(data[:, 0] * 1e6, data[:, i + 1], lw=1.3, color="#c0392b" if out else "#2c3e50")
            if out:
                for y in (lv.voh_min, lv.vol_max):
                    ax.axhline(y, ls="--", lw=0.7, color="#7f8c8d")
            ax.set_ylim(-0.4, corner.vdd + 0.4)
            ax.set_ylabel(label, rotation=0, ha="right", va="center")
            ax.set_yticks([0, round(corner.vdd)])
            ax.grid(alpha=0.25)
        axs[-1][0].set_xlabel("tempo (µs)")
        fig.suptitle(f"{cell} — canto {corner.name} (VDD {corner.vdd:g} V, {corner.temp:g} °C)", fontsize=11)
        fig.tight_layout()
        fig.savefig(outdir / f"{cell}.png", dpi=110)
        plt.close(fig)
        dat.unlink()
        for f in outdir.glob(f"{cell}.log"):
            f.unlink()
        shown[cell] = r["ok"]
        log(f"  {cell:<9} exportado ({'OK' if r['ok'] else 'FALHOU'})")
    report(outdir / "resultados.md", lib, res, corners, warns)
    L = [f"# Células da família `{Path(lib.path).name}` no ngspice", "",
         "Cada célula da família é simulada como circuito de verdade, com o modelo SPICE dos componentes, "
         "e não só como chaves ideais. Os resultados de todos os cantos estão em [resultados.md](resultados.md).", "",
         "## Reproduzir", "",
         "Cada `<CÉLULA>.cir` é um netlist do ngspice completo: o modelo do transistor, os subcircuitos da "
         "célula e da carga, as fontes com os vetores de teste e as medidas. O cabeçalho explica os vetores "
         f"e o valor esperado de cada medida. É o teste funcional no canto {corner.name}.", "",
         "```sh", f"ngspice -b {cells[0]}.cir      # imprime as medidas e grava {cells[0]}.dat com as formas de onda",
         "```", "",
         f"Para rodar todos os cantos e refazer estes arquivos: `pcbflow-cellsim --lib {Path(lib.path).name} "
         f"--export {outdir.as_posix()}`.", "", "## Células", ""]
    for cell in cells:
        L += [f"### {cell}", "", lib.meta_of(cell).get("description", ""), "",
              f"[{cell}.cir]({cell}.cir) — {'passa' if shown[cell] else '**falha**'} no canto {corner.name}", "",
              f"![{cell}]({cell}.png)", ""]
    (outdir / "README.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def _ns(v):
    return "—" if v is None else f"{v * 1e9:.0f} ns" if v < 1e-6 else f"{v * 1e6:.2g} µs"


def _status(r):
    return "**falhou**" if not r["ok"] else "OK, com aviso" if r.get("warns") else "OK"


def _window(w):
    """Intervalo (passou, falhou) da varredura em texto."""
    if not w:
        return "—"
    passed, failed = w
    if failed is None:
        return f"< {_ns(passed)}"
    if passed is None:
        return f"> {_ns(failed)}"
    return f"{_ns(failed)} a {_ns(passed)}"


def report(path, lib, res, corners, warns):
    L = [f"# Simulação analógica das células — `{lib.name}`", "",
         "Gerado por `pcbflow-cellsim` (ngspice). Cantos: " + ", ".join(corners) + ".", "",
         "## Combinacionais e latches", "", "| Célula | " + " | ".join(corners) + " |",
         "|---|" + "---|" * len(corners)]
    for cell, by in res.items():
        if lib.cells[cell].ff:
            continue
        L.append(f"| {cell} | " + " | ".join(f"{_status(by[c])}, tpd {_ns(by[c].get('tpd'))}" for c in corners)
                 + " |")
    L += ["", "## Flip-flops", "", "| Célula | Canto | Função | clock → Q | Menor período | Hold | Setup |",
          "|---|---|---|---|---|---|---|"]
    for cell, by in res.items():
        if not lib.cells[cell].ff:
            continue
        for c in corners:
            r = by[c]
            ckq = f"{_ns(r['ckq'][0])} a {_ns(r['ckq'][1])}" if r.get("ckq") else "—"
            L.append(f"| {cell} | {c} | {_status(r)} | {ckq} | {_ns(r.get('period'))} "
                     f"| {_window(r.get('hold'))} | {_window(r.get('setup'))} |")
    L += ["", "Hold e setup saem de uma varredura em grade: o valor necessário fica no intervalo mostrado "
          "(\"< x\": passou em toda a grade, até x). Hold: quanto tempo depois da borda o dado ainda tem de "
          "ficar parado. Setup: quanto tempo antes da borda o dado já tem de estar pronto. As entradas usam o "
          "nível de pior caso, e a saída leva o fan-out máximo."]
    fails = [(cell, c, f) for cell, by in res.items() for c, r in by.items() for f in r["fails"]]
    if fails or warns:
        L += ["", "## Problemas e avisos", ""] + [f"- {cell} ({c}): {f}" for cell, c, f in fails] + [f"- {w}" for w in warns]
    Path(path).write_text("\n".join(L) + "\n", encoding="utf-8")


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="pcbflow-cellsim", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lib", default="rtl", help="família de células (padrão: rtl)")
    ap.add_argument("--cells", nargs="+", help="só estas células (padrão: todas)")
    ap.add_argument("--out", help="pasta dos netlists, logs e do relatório (padrão: build/cellsim/<família>)")
    ap.add_argument("--jobs", type=int, help="simulações em paralelo")
    ap.add_argument("--export", metavar="PASTA",
                    help="grava netlists autocontidos, gráficos e um README.md para publicar")
    args = ap.parse_args(argv)
    t0 = time.time()
    try:
        lib = Library(resolve_family(args.lib))
        out = Path(args.out or Path("build/cellsim") / Path(lib.path).name)
        print(f"Simulação analógica da família '{lib.name}' (ngspice)")
        res, corners, warns = check_family(lib, args.cells, out, jobs=args.jobs)
    except (LibraryError, CellSimError) as e:
        print(f"ERRO: {e}")
        return 3
    report(out / "report.md", lib, res, corners, warns)
    if args.export:
        try:
            export(lib, args.cells or list(lib.cells), args.export, res, corners, warns)
        except CellSimError as e:
            print(f"ERRO: {e}")
            return 3
    bad = [(cell, c) for cell, by in res.items() for c, r in by.items() if not r["ok"]]
    for cell, by in res.items():
        for c, r in by.items():
            for f in r["fails"]:
                print(f"  FALHA {cell} ({c}): {f}")
    for w in warns:
        print(f"  AVISO {w}")
    print(f"{len(res)} células x {len(corners)} cantos: {len(bad)} com falha. Relatório: {out / 'report.md'}")
    print(f"Concluído em {time.time() - t0:.0f} s")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
