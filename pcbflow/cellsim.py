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
  pcbflow-cellsim --lib rtl --design add4 --src examples/demo/demo_top.v

--design simula um circuito combinacional inteiro, do jeito que vai para a
placa: o pcbflow sintetiza o Verilog (com o sizing e os buffers), cada célula
vira uma instância no ngspice e as entradas recebem todas as combinações (ou
--vectors sorteadas). Cada vetor é conferido contra a lógica do netlist, e o
último cruzamento de cada saída dá o atraso do caminho crítico, com as cargas
reais entre as portas.

--export grava, para cada célula, o teste funcional no primeiro canto como um
netlist do ngspice autocontido (<CÉLULA>.cir: modelo, subcircuitos, vetores de
teste e medidas, com o resultado esperado comentado), o gráfico das formas de
onda (<CÉLULA>.png) e um README.md com os resultados de todos os cantos: quem
quiser conferir uma célula roda "ngspice -b <CÉLULA>.cir" sem o pcbflow.

"spice" no library.json:
  "models":  {"NPN": "spice/BC548B.lib"}   chave do parts.json -> arquivo com o
             .model, ou {"file": ..., "instance": "L=100u W=100u"} (parâmetros
             da instância). Um arquivo com .subckt (ex.: o relé) vira uma
             instância X dele, com os nós na ordem do elemento do .sp.
  "corners": {"lento": {"vdd": 4.75, "temp": 0, "pull_up": 1.05, "base": 1.05,
                        "params": {"NPN": {"Bf": 110}}}, ...}
             pull_up escala os resistores ligados ao VDD; base, os outros;
             params troca parâmetros do .model ou, num .subckt, define os
             .param que ele usa (ex.: {"RELAY": {"kcoil": 1.2}}).
  "levels":  {"vih": 1.0, "vil": 0.0, "voh_min": 0.9, "vol_max": 0.1, "vth": 0.5}
             (opcional) níveis em fração do VDD; sem ele, os da família RTL
             (voh_min do "electrical", 2 Vce(sat) e 0,5 V);
  "timing":  {"step": 20e-6, "period": 20e-6, "periods": [...], "holds": [...],
              "setups": [...], "resolution": 5e-9} (opcional) a escala de tempo
             dos testes: passo das combinacionais, período do teste funcional,
             grades de período, hold e setup, e o passo da simulação.
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

# escala de tempo padrão (a da família RTL); "timing" no library.json troca
TIMING = {"step": 20e-6,          # duração de cada combinação de entrada nas combinacionais
          "period": 20e-6,        # período do clock no teste funcional dos flip-flops
          "periods": [1e-5, 5e-6, 2e-6, 1e-6, 5e-7, 2e-7, 1e-7],
          "holds": [1e-6, 5e-7, 3e-7, 2e-7, 1e-7, 5e-8, 2e-8, 1e-8],
          "setups": [1e-6, 5e-7, 3e-7, 2e-7, 1e-7, 5e-8, 2e-8, 1e-8],
          "resolution": 5e-9,     # passo da simulação nas varreduras dos flip-flops
          "edge": 2e-9,           # rampa das fontes de entrada
          "batch": 64}            # vetores por netlist no --design
VTH = 1.0            # limiar para medir atrasos na RTL (entre o nível baixo e o alto)
VOL_MAX = 0.5        # nível baixo máximo na RTL: a próxima base fica cortada


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
class Model:
    kind: str                   # NPN, NMOS, D... ou SUBCKT
    params: dict                # parâmetros do .model ({} num .subckt)
    instance: str = ""          # parâmetros da instância (ex.: L=100u W=100u)
    text: str = ""              # o .subckt inteiro, quando o modelo é um subcircuito
    subckt: str = ""            # nome do .subckt


@dataclass
class Corner:
    name: str
    vdd: float
    temp: float
    pull_up: float
    base: float
    params: dict = field(default_factory=dict)     # chave do parts.json -> {parâmetro: valor}
    levels: dict = None                            # frações do VDD ("levels"), ou None (RTL)
    timing: dict = field(default_factory=lambda: dict(TIMING))

    def __getattr__(self, name):                   # corner.step, corner.periods... vêm de timing
        t = self.__dict__.get("timing") or {}
        if name in t:
            return t[name]
        raise AttributeError(name)

    @property
    def vth(self):
        return self.levels["vth"] * self.vdd if self.levels else VTH


def spice_setup(lib):
    """(modelos {chave: (tipo, parâmetros)}, [Corner]) da família, ou erro."""
    cfg = lib.meta.get("spice")
    if not cfg:
        raise CellSimError(f"a família '{lib.name}' não declara \"spice\" no library.json "
                           "(modelos SPICE dos componentes e cantos)")
    models = {}
    for key, spec in cfg.get("models", {}).items():
        if key not in lib.parts:
            raise CellSimError(f"library.json: spice.models cita '{key}', que não está no parts.json")
        spec = spec if isinstance(spec, dict) else {"file": spec}
        path = (lib.path / spec["file"]).resolve()
        if not path.is_file():
            raise CellSimError(f"library.json: modelo {spec['file']} não encontrado")
        text = path.read_text(encoding="utf-8")
        m = re.search(r"^\s*\.subckt\s+(\S+)", text, re.I | re.M)
        if m:
            models[key] = Model("SUBCKT", {}, spec.get("instance", ""), text, m.group(1))
        else:
            kind, params = _model_params(text, path)
            models[key] = Model(kind, params, spec.get("instance", ""))
    need = {p for s in lib.subckts.values() for e in s.devices if e.letter in "QMDKT" for p in [e.model]}
    missing = sorted(need - set(models))
    if missing:
        raise CellSimError(f"library.json: sem modelo SPICE para {', '.join(missing)} (spice.models)")
    levels = cfg.get("levels")
    timing = dict(TIMING, **cfg.get("timing", {}))
    corners = [Corner(n, float(c.get("vdd", 5.0)), float(c.get("temp", 27)), float(c.get("pull_up", 1.0)),
                      float(c.get("base", 1.0)), c.get("params", {}), levels, timing)
               for n, c in cfg.get("corners", {"típico": {}}).items()]
    return models, corners


# ---------------------------------------------------------------- netlists
def subckt_text(lib, names, models=None):
    """Os .subckt das células (e dos que elas instanciam), com os resistores
    escalados pelos parâmetros kup (ligados ao VDD) e kb (os outros)."""
    models = models or {}

    def inst(e):
        m = models.get(e.model)
        return f" {m.instance}" if m and m.instance else ""
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
                out.append(f"{e.name} {' '.join(e.nodes)} {e.model}{inst(e)}")
            elif e.letter == "M":                  # corpo no fonte: componente discreto
                out.append(f"{e.name} {' '.join(e.nodes)} {e.nodes[2]} {e.model}{inst(e)}")
            elif e.letter == "D":
                out.append(f"{e.name} {' '.join(e.nodes)} {e.model}{inst(e)}")
            elif e.letter in ("K", "T", "V"):      # relé, núcleo de ferrite ou válvula: instância do subcircuito do modelo
                m = models.get(e.model)
                if not m or m.kind != "SUBCKT":
                    raise CellSimError(f"{n}: o componente {e.name} precisa de um modelo .subckt em spice.models")
                out.append(f"X{e.name} {' '.join(e.nodes)} {m.subckt}")
            else:
                raise CellSimError(f"{n}: elemento {e.name} ({e.letter}) sem equivalente no ngspice")
        out.append(f".ends {n}")
    for n in names:
        emit(n)
    return "\n".join(out)


def header(lib, models, corner, cells):
    lines = [f"* pcbflow-cellsim: canto {corner.name}", f".temp {corner.temp:g}",
             f".param kup={corner.pull_up:g} kb={corner.base:g}"]
    for key, m in models.items():
        over = corner.params.get(key, {})
        if m.kind == "SUBCKT":
            if over:
                lines.append(".param " + " ".join(f"{k}={v}" for k, v in over.items()))
            lines.append(m.text.strip())
            continue
        p = dict(m.params)
        p.update({k: str(v) for k, v in over.items()})
        lines.append(f".model {key} {m.kind}(" + " ".join(f"{k}={v}" for k, v in p.items()) + ")")
    lines.append(subckt_text(lib, cells, models))
    lines.append(f"VDD vdd 0 {corner.vdd:g}")
    return "\n".join(lines)


def instance(lib, cell, name, nets):
    """Linha X de uma célula: nets {pino: net}; VDD/GND da família -> vdd/0."""
    pins = lib.subckts[cell].pins
    nodes = ["vdd" if p == lib.vdd else "0" if p == lib.gnd else nets[p] for p in pins]
    return f"X{name} {' '.join(nodes)} {cell}"


def pwl(points, edge):
    """[(t, v)] -> PWL com rampas de 'edge' (tempos com precisão total: em 1 s,
    uma rampa de µs some se o instante for escrito com poucos algarismos)."""
    out, last = [], None
    for t, v in points:
        if last is None:
            out.append(f"0 {v:g}")
        elif v != last:
            out += [f"{t:.15g} {last:g}", f"{t + edge:.15g} {v:g}"]
        last = v
    return "PWL(" + " ".join(out) + ")"


TIMEOUT = 180       # segundos por netlist: além disso, o ponto do teste conta como falha


def run_deck(ngspice, path, text):
    """Roda o netlist e devolve as medidas {nome: valor}. Um netlist que não
    termina em TIMEOUT (o ngspice não converge, ex.: um flip-flop de relés com
    o dado mudando no meio da troca dos contatos) devolve {}: o ponto falha."""
    path.write_text(text, encoding="utf-8")
    try:
        r = subprocess.run([ngspice, "-b", path.name], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", cwd=path.parent, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        (path.with_suffix(".log")).write_text(f"ngspice não terminou em {TIMEOUT} s (não convergiu)\n",
                                               encoding="utf-8")
        return {}
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
    if corner.levels:
        f = corner.levels
        return Levels(vih=f["vih"] * corner.vdd, vil=f["vil"] * corner.vdd,
                      voh_min=f["voh_min"] * corner.vdd, vol_max=f["vol_max"] * corner.vdd)
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
        pts = [(k * corner.step, lv.vih if (combo >> (n - 1 - i)) & 1 else lv.vil) for k, combo in enumerate(combos)]
        src.append(f"V_{p} in_{p} 0 {pwl(pts, corner.edge)}")
    nets = {**{p: f"in_{p}" for p in ins}, **{o: f"out_{o}" for o in outs}}
    expect = [{o: _expected(lib, c, o, {p: (combo >> (n - 1 - i)) & 1 for i, p in enumerate(ins)}) for o in outs}
              for combo in combos]
    meas = []
    for k in range(len(combos)):
        for o in outs:
            at = (k + 1) * corner.step - corner.step / 20
            meas.append(f"meas tran s_{o}_{k} FIND v(out_{o}) AT={at:.9g}")
            lnet = _load_out(lib, cell, o)
            if lnet:
                meas.append(f"meas tran l_{o}_{k} FIND v({lnet}) AT={at:.9g}")
            if k and None not in (expect[k][o], expect[k - 1][o]) and expect[k][o] != expect[k - 1][o]:
                meas.append(f"meas tran d_{o}_{k} TRIG AT={k * corner.step:.9g} TARG v(out_{o}) VAL={corner.vth} "
                            f"TD={k * corner.step:.9g} CROSS=1")
    term = []
    for o in outs:                                      # drivers de coletor aberto: a terminação do barramento
        if c.pins[o].get("three_state") and lib.terminator:
            term.append(instance(lib, lib.terminator["cell"], f"term_{o}", {lib.terminator["pin"]: f"out_{o}"}))
    rcells = {fanout_load(lib, cell, o)[0] for o in outs}
    deck = "\n".join([header(lib, models, corner, [cell, *rcells] + ([lib.terminator["cell"]] if term else [])),
                      *src, instance(lib, cell, "dut", nets), *term,
                      loads_text(lib, cell, {o: f"out_{o}" for o in outs}),
                      f".tran {corner.step / 500:.3g} {len(combos) * corner.step:.9g}", ".control", "run", *meas, "quit",
                      ".endc", ".end"])
    path = work / f"{cell}_{corner.name}.cir"
    if capture:
        vectors = []
        for k, combo in enumerate(combos):
            env = {p: (combo >> (n - 1 - i)) & 1 for i, p in enumerate(ins)}
            want = ", ".join(f"s_{o}_{k}: {o}={expect[k][o]}" for o in outs)
            vectors.append(f"{k * corner.step * 1e6:g}-{(k + 1) * corner.step * 1e6:g} µs  {_env(env) or '(sem entradas)'}  ->  {want}")
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
    ck = f"V_{clk} in_{clk} 0 PULSE({a:g} {b:g} {period:.9g} {corner.edge:g} {corner.edge:g} {period / 2 - corner.edge:.15g} {period:.9g})"
    d = data[0]
    pts, v = [(0.0, lo)], 0
    for i, bit in enumerate(bits):
        t = (i + 1) * period - change
        pts.append((t, hi if bit else lo))
    src = [ck, f"V_{d} in_{d} 0 {pwl(pts, corner.edge)}"]
    for p, (key, inactive) in asyn.items():
        pts = [(0.0, hi if inactive else lo)]
        if clear_at:
            t0, t1 = clear_at
            pts += [(t0, lo if inactive else hi), (t1, hi if inactive else lo)]
        src.append(f"V_{p} in_{p} 0 {pwl(pts, corner.edge)}")
    for p in data[1:]:
        src.append(f"V_{p} in_{p} 0 {lo:g}")
    nets = {**{p: f"in_{p}" for p in c.inputs}, **{o: f"out_{o}" for o in c.outputs}}
    rcell = fanout_load(lib, cell, q)[0]
    t_end = (n + 1) * period + (clear_at[1] - clear_at[0] + period if clear_at else 0)
    meas = [f"meas tran q_{k} FIND v(out_{q}) AT={(k + 1) * period + 0.45 * period:.9g}" for k in range(n)]
    deck = "\n".join([header(lib, models, corner, [cell, rcell]), *src, instance(lib, cell, "dut", nets),
                      loads_text(lib, cell, {q: f"out_{q}"}),
                      f".tran {tstep or min(period / 400, corner.resolution):.3g} {t_end:.9g}", ".control", "run", *meas, *extra_meas,
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
        # Para publicar: o funcional e, se houver clear/preset, a prova de que ele é
        # assíncrono e manda mais que o clock e o dado: com Q no valor oposto, ele
        # chega no meio de um ciclo (Q muda na hora), atravessa uma borda ativa com
        # o dado contrário (Q não muda) e solta (Q volta na borda seguinte).
        P = corner.period
        bits = list(BITS)
        want = list(BITS)
        tail, clear, extra_vec = [], None, []
        if asyn:
            pin, (key, inactive) = next(iter(asyn.items()))
            level = 0 if key == "clear" else 1
            n0 = len(bits)
            bits += [1 - level] * 4                    # Q fica no valor oposto ao do clear/preset
            want += [1 - level] * 4
            t0, t1 = (n0 + 1.5) * P, (n0 + 2.8) * P     # do meio de um ciclo até depois da borda seguinte
            clear = (t0, t1)
            want[n0 + 1] = level                       # amostrado em (n0 + 2,45) P: ainda com o clear
            tail = [f"meas tran rst_a FIND v(out_{qpin}) AT={t0 + 0.25 * P:.15g}",
                    f"meas tran rst_b FIND v(out_{qpin}) AT={(n0 + 2) * P + 0.3 * P:.15g}"]
            extra_vec = [f"{pin} = {1 - inactive} de {_ns(t0)} a {_ns(t1)} ({key} assíncrono, com Q = {1 - level} "
                         f"e {data[0]} = {1 - level})",
                         f"  {_ns(t0 + 0.25 * P)}, no meio do ciclo  ->  rst_a: {qpin}={level} (muda sem esperar o clock)",
                         f"  {_ns((n0 + 2) * P + 0.3 * P)}, depois da borda {n0 + 2}  ->  rst_b: {qpin}={level} "
                         f"(o {key} vence o clock e o dado)",
                         f"  borda {n0 + 3}, depois de soltar  ->  q_{n0 + 2}: {qpin}={1 - level} (volta a obedecer o dado)"]
        deck, *_ = _ff_deck(lib, models, corner, cell, P, bits, P / 4, tail, clear, tstep=P / 400)
        edge = "subida" if rising else "descida"
        vectors = [f"borda de {edge} {k + 1} em {_ns((k + 1) * P)}: {data[0]}={b} (muda {_ns(P / 4)} antes)"
                   f"  ->  q_{k}: {qpin}={w}" for k, (b, w) in enumerate(zip(bits, want))] + extra_vec
        sig = [f"in_{clk_name}", f"in_{data[0]}"] + [f"in_{p}" for p in asyn] + [f"out_{qpin}"]
        deck = _capture(deck, capture.name, sig, _about(lib, corner, cell, lv, _loads_note(lib, cell, [qpin]), vectors))
        vals = run_deck(ngspice, capture.with_suffix(".cir"), deck)
        ok = _ff_ok(vals, want, lv)
        if asyn:
            ok = ok and all(logic(vals.get(m, float("nan")), lv) == level for m in ("rst_a", "rst_b"))
        return {"ok": ok, "fails": [] if ok else ["teste funcional exportado falhou"], "signals": sig}
    meas = []
    for k in range(1, len(BITS)):
        if BITS[k] != BITS[k - 1]:
            td = (k + 1) * corner.period - corner.period / 10
            e = "RISE" if BITS[k] else "FALL"
            meas.append(f"meas tran ckq_{k} TRIG v(in_{clk_name}) VAL={(lv.vih + lv.vil) / 2:g} TD={td:.9g} "
                        f"{'RISE' if rising else 'FALL'}=1 TARG v(out_{qpin}) VAL={corner.vth} TD={td:.9g} {e}=1")
    vals, q, clk = run("func", corner.period, corner.period / 4, extra=meas)
    if not _ff_ok(vals, BITS, lv):
        got = [round(vals.get(f"q_{k}", float("nan")), 2) for k in range(len(BITS))]
        out["fails"].append(f"captura errada com período de {corner.period * 1e6:g} µs: Q = {got}, esperado {BITS}")
    ckq = [v for k, v in vals.items() if k.startswith("ckq_") and v > 0]
    out["ckq"] = (min(ckq), max(ckq)) if ckq else None
    # clear/preset assíncrono: no meio de um ciclo, Q vai ao valor e fica até soltar
    if asyn:
        key, inactive = next(iter(asyn.values()))
        level = 0 if key == "clear" else 1
        bits = [1 - level] * 4
        t0 = 4.5 * corner.period
        extra = [f"meas tran rst FIND v(out_{qpin}) AT={t0 + 0.3 * corner.period:.9g}"]
        vals, *_ = run("async", corner.period, corner.period / 4, bits=bits, extra=extra, clear_at=(t0, t0 + 0.4 * corner.period))
        if logic(vals.get("rst", float("nan")), lv) != level:
            out["fails"].append(f"{key} assíncrono não levou Q a {level} (Q = {vals.get('rst', float('nan')):.2f} V)")
    # menor período que funciona
    out["period"] = None
    for p in corner.periods:
        vals, *_ = run(f"p{p:g}", p, p / 4)
        if not _ff_ok(vals, BITS, lv):
            break
        out["period"] = p
    # hold: o dado muda h DEPOIS da borda e o valor antigo tem de ficar. O hold
    # necessário fica entre o último h que passou e o primeiro que falhou.
    out["hold"] = _sweep(corner.holds, lambda h: _ff_ok(run(f"h{h:g}", corner.period, -h)[0], [0] + BITS[:-1], lv))
    # setup: o dado muda s ANTES da borda e o valor novo tem de entrar
    out["setup"] = _sweep(corner.setups, lambda s: _ff_ok(run(f"s{s:g}", corner.period, s)[0], BITS, lv))
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
    T = corner.step
    # transparente: E ligado, D muda 3 vezes; travado: E desliga, D muda e Q fica
    en_pts = [(0.0, on), (4 * T, off)]
    d_pts = [(0.0, lv.vil), (T, lv.vih), (2 * T, lv.vil), (3 * T, lv.vih), (5 * T, lv.vil), (6 * T, lv.vih)]
    want = [(0.9 * T, 0), (1.9 * T, 1), (2.9 * T, 0), (3.9 * T, 1), (5.9 * T, 1), (6.9 * T, 1)]
    nets = {**{p: f"in_{p}" for p in c.inputs}, **{o: f"out_{o}" for o in c.outputs}}
    meas = [f"meas tran s_{k} FIND v(out_{q}) AT={t:.9g}" for k, (t, _) in enumerate(want)]
    meas += [f"meas tran dq_{k} TRIG AT={t:.9g} TARG v(out_{q}) VAL={corner.vth} TD={t:.9g} CROSS=1"
             for k, t in enumerate((T, 2 * T, 3 * T))]
    rcell = fanout_load(lib, cell, q)[0]
    deck = "\n".join([header(lib, models, corner, [cell, rcell]), f"V_{en} in_{en} 0 {pwl(en_pts, corner.edge)}",
                      f"V_{d} in_{d} 0 {pwl(d_pts, corner.edge)}", instance(lib, cell, "dut", nets),
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


# ---------------------------------------------------------------- circuitos
def build_design(lib, sources, top, outdir):
    """O netlist de células do circuito, como o fluxo o monta (síntese, sizing e buffers)."""
    from . import buffering, netlist, sizing, synth
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    liberty_file = outdir / "cells.lib"
    lib.write_liberty(liberty_file)
    json_path, _, _, hier = synth.run_yosys(sources, top, liberty_file, outdir, latches=lib.latch_techmap())
    design = netlist.load_yosys_json(json_path, top, lib, hier)
    el, drives = drive.library_drive(lib)
    if lib.variants:
        sizing.size_design(lib, design, el, drives)
    buffering.buffer_design(lib, design, el, drives)
    return design


def _eval_comb(lib, design, env, state=None):
    """Propaga a lógica combinacional dado o estado {inst: 0/1} dos flip-flops/latches."""
    val = dict(env)
    val[design.vdd], val[design.gnd] = 1, 0
    pending = {}
    for inst, (cell, _) in design.instances.items():
        c = lib.cells[cell]
        if c.seq:
            q = 0 if state is None else state.get(inst, 0)
            s = c.seq
            iq = {s["iq"]: q, s["iqn"]: 1 - q}
            for o in c.outputs:
                if o in design.conns[inst]:
                    val[design.conns[inst][o]] = liberty.eval_expr(liberty.parse_expr(c.pins[o]["function"]), iq)
        else:
            pending[inst] = (cell, _)
    while pending:
        progress_ = False
        for inst, (cell, _) in list(pending.items()):
            c = lib.cells[cell]
            conns = design.conns[inst]
            ins = {p: val.get(conns.get(p)) for p in c.inputs}
            if None in ins.values():
                continue
            for o in c.outputs:
                if o in conns:
                    if lib.is_bus_cell(cell):
                        raise CellSimError("--design não simula barramentos tri-state")
                    val[conns[o]] = liberty.eval_expr(liberty.parse_expr(c.pins[o]["function"]), ins)
            del pending[inst]
            progress_ = True
        if not progress_:
            raise CellSimError("o circuito tem um laço combinacional (ou uma net sem driver)")
    return val


def _evaluate(lib, design, env, state=None, prev_val=None):
    """Valor lógico de cada net para as entradas env {net: 0/1}, atualizando state (se houver células sequenciais)."""
    if state is None:
        return _eval_comb(lib, design, env)
    for inst, (cell, _) in design.instances.items():
        state.setdefault(inst, 0)
    val = _eval_comb(lib, design, env, state)
    # 1) borda de clock dos flip-flops (usa o D do ciclo anterior antes da borda e o clear atual)
    changed = False
    for inst, (cell, _) in design.instances.items():
        c = lib.cells[cell]
        if not c.ff:
            continue
        conns = design.conns[inst]
        ins_now = {p: val.get(conns.get(p)) for p in c.inputs}
        q = state[inst]
        if "clear" in c.ff and liberty.eval_expr(liberty.parse_expr(c.ff["clear"]), ins_now):
            q = 0
        elif "preset" in c.ff and liberty.eval_expr(liberty.parse_expr(c.ff["preset"]), ins_now):
            q = 1
        elif prev_val is not None:
            ins_prev = {p: prev_val.get(conns.get(p)) for p in c.inputs}
            ck_prev = liberty.eval_expr(liberty.parse_expr(c.ff["clocked_on"]), ins_prev)
            ck_now = liberty.eval_expr(liberty.parse_expr(c.ff["clocked_on"]), ins_now)
            if not ck_prev and ck_now:
                q = liberty.eval_expr(liberty.parse_expr(c.ff["next_state"]), ins_prev)
        if q != state[inst]:
            state[inst] = q
            changed = True
    if changed:
        val = _eval_comb(lib, design, env, state)
    # 2) latches transparentes (e clear/preset assíncronos que cascateiem)
    for _ in range(len(design.instances) + 1):
        lat_changed = False
        for inst, (cell, _) in design.instances.items():
            c = lib.cells[cell]
            conns = design.conns[inst]
            ins_now = {p: val.get(conns.get(p)) for p in c.inputs}
            q = state[inst]
            if c.ff:
                if "clear" in c.ff and liberty.eval_expr(liberty.parse_expr(c.ff["clear"]), ins_now):
                    q = 0
                elif "preset" in c.ff and liberty.eval_expr(liberty.parse_expr(c.ff["preset"]), ins_now):
                    q = 1
            elif c.latch:
                if "clear" in c.latch and liberty.eval_expr(liberty.parse_expr(c.latch["clear"]), ins_now):
                    q = 0
                elif "preset" in c.latch and liberty.eval_expr(liberty.parse_expr(c.latch["preset"]), ins_now):
                    q = 1
                elif liberty.eval_expr(liberty.parse_expr(c.latch["enable"]), ins_now):
                    q = liberty.eval_expr(liberty.parse_expr(c.latch["data_in"]), ins_now)
            if q != state[inst]:
                state[inst] = q
                lat_changed = True
        if not lat_changed:
            break
        val = _eval_comb(lib, design, env, state)
    return val


def sim_design(lib, models, corner, design, vectors, work, ngspice, capture=None):
    """Simula o circuito com os vetores [{entrada: 0/1}], em lotes (timing.batch no library.json); cada
    lote começa repetindo o último vetor do anterior, para medir a transição."""
    has_seq = any(lib.cells[c].seq for c, _ in design.instances.values())
    batch = len(vectors) if has_seq else int(corner.batch)
    if capture:                                   # para publicar: só o primeiro lote (ou tudo se sequencial)
        return _sim_batch(lib, models, corner, design, vectors[:batch], work, ngspice, capture, 0, False)
    out = {"ok": True, "fails": [], "vectors": len(vectors), "tpd": None, "where": None,
           "cells": len(design.instances), "parts": len(design.parts), "measured": 0, "missing": 0, "rows": []}
    for i in range(0, len(vectors), batch):
        first = max(0, i - 1)
        r = _sim_batch(lib, models, corner, design, vectors[first:i + batch], work, ngspice, None, first, i > 0)
        out["fails"] += r["fails"]
        out["measured"] += r["measured"]
        out["missing"] += r["missing"]
        out["rows"] += r["rows"]
        if r["tpd"] and (out["tpd"] is None or r["tpd"] > out["tpd"]):
            out["tpd"], out["where"] = r["tpd"], r["where"]
    out["ok"] = not out["fails"]
    return out


def _sim_batch(lib, models, corner, design, vectors, work, ngspice, capture, first, skip0):
    """Um lote: o vetor local k é o vetor first + k; com skip0, o vetor 0 (repetido
    do lote anterior) só dá o estado inicial."""
    lv = levels(lib, corner)
    work = Path(work)
    names = {design.vdd: "vdd", design.gnd: "0"}

    def node(net):
        if net not in names:
            names[net] = f"n{len(names)}"
        return names[net]

    ins = [p for p in design.ports if p.direction == "input"]
    outs = [p for p in design.ports if p.direction == "output"]
    T = corner.step
    src = []
    for p in ins:
        if p.net in (design.vdd, design.gnd):
            continue
        pts = [(k * T, lv.vih if v[p.name] else lv.vil) for k, v in enumerate(vectors)]
        src.append(f"V_{_safe(p.name)} {node(p.net)} 0 {pwl(pts, corner.edge)}")
    cells = sorted({c for c, _ in design.instances.values()})
    lines = []
    for inst, (cell, _) in design.instances.items():
        conns = {pin: node(net) for pin, net in design.conns[inst].items()}
        for pin in lib.subckts[cell].pins:            # pino sem ligação: nó próprio
            if pin not in conns and pin not in (lib.vdd, lib.gnd):
                conns[pin] = node(f"{inst}.{pin}")
        lines.append(instance(lib, cell, _safe(inst), conns))
    # cada saída leva uma carga de referência (a entrada do que vem depois na placa)
    rcell, rpin, _ = fanout_load(lib, cells[0], lib.cells[cells[0]].outputs[0])
    for p in outs:
        others = [x for x in lib.subckts[rcell].pins if x not in (lib.vdd, lib.gnd, rpin)]
        lines.append(instance(lib, rcell, f"ld_{_safe(p.name)}",
                              {rpin: node(p.net), **{x: f"ldo_{_safe(p.name)}_{x}" for x in others}}))
    expect = []
    state = {} if any(lib.cells[c].seq for c, _ in design.instances.values()) else None
    prev_val = None
    for v in vectors:
        prev_val = _evaluate(lib, design, {p.net: v[p.name] for p in ins}, state=state, prev_val=prev_val)
        expect.append({p.name: prev_val.get(p.net) for p in outs})
    meas = []
    for k in range(len(vectors)):
        for p in outs:
            o = _safe(p.name)
            meas.append(f"meas tran s_{o}_{k} FIND v({node(p.net)}) AT={(k + 1) * T - T / 20:.9g}")
            if k and expect[k][p.name] != expect[k - 1][p.name]:
                meas.append(f"meas tran t_{o}_{k} WHEN v({node(p.net)})={corner.vth:g} CROSS=LAST "
                            f"FROM={k * T:.9g} TO={(k + 1) * T:.9g}")
    deck = "\n".join([header(lib, models, corner, cells + [rcell]), *src, *lines,
                      f".tran {T / 500:.3g} {len(vectors) * T:.9g}", ".control", "run", *meas, "quit",
                      ".endc", ".end"])
    path = work / f"{design.top}_{corner.name}_{first}.cir"
    if capture:
        vec = [f"vetor {k} ({k * T * 1e6:g}-{(k + 1) * T * 1e6:g} µs): {_env({x.name: v[x.name] for x in ins})}"
               f"  ->  " + ", ".join(f"s_{_safe(o)}_{k}: {o}={e}" for o, e in expect[k].items())
               for k, v in enumerate(vectors)]
        sig = [node(p.net) for p in ins + outs if p.net not in (design.vdd, design.gnd)]
        labels = {node(p.net): p.name for p in ins + outs}
        about = _about_design(lib, corner, design, lv, vec)
        deck = _capture(deck, capture.name, sig, about)
        path = capture.with_suffix(".cir")
    vals = run_deck(ngspice, path, deck)
    fails, worst, measured, missing, rows = [], (0.0, None), 0, 0, []
    for k, v in enumerate(vectors):
        if skip0 and k == 0:
            continue
        row = {"corner": corner.name, "vector": first + k}
        for p in ins:
            row[p.name] = v[p.name]
        row_ok, row_missing, row_tpd = True, False, None
        for p in outs:
            o = _safe(p.name).lower()
            got = vals.get(f"s_{o}_{k}")
            want = expect[k][p.name]
            t = vals.get(f"t_{o}_{k}")
            dt = (t - k * T) if t is not None else None
            row[f"exp_{p.name}"] = want
            row[f"v_{p.name}"] = "" if got is None else f"{got:.4g}"
            row[f"got_{p.name}"] = "" if got is None or logic(got, lv) is None else logic(got, lv)
            row[f"tpd_{p.name}_s"] = "" if dt is None else f"{dt:.6g}"
            # sem medida: o ngspice não chegou lá (não convergiu); conta à parte, não é saída errada
            if got is None:
                missing += 1
                row_missing = True
                continue
            measured += 1
            if logic(got, lv) != want:
                row_ok = False
                fails.append(f"vetor {first + k} ({_env({x.name: v[x.name] for x in ins})}): {p.name} = "
                             f"{'—' if got is None else f'{got:.2f} V'} (esperado {want})")
            if dt is not None:
                if row_tpd is None or dt > row_tpd:
                    row_tpd = dt
                if dt > worst[0]:
                    worst = (dt, f"{p.name} no vetor {first + k}")
        row["tpd_max_s"] = "" if row_tpd is None else f"{row_tpd:.6g}"
        row["status"] = "missing" if row_missing else ("ok" if row_ok else "fail")
        rows.append(row)
    r = {"ok": not fails, "fails": fails, "vectors": len(vectors), "tpd": worst[0] or None, "where": worst[1],
         "cells": len(design.instances), "parts": len(design.parts), "measured": measured, "missing": missing,
         "rows": rows}
    if capture:
        r["labels"] = labels
    return r


def _about_design(lib, corner, design, lv, vectors):
    cells = sorted({c for c, _ in design.instances.values()})
    return [f"{design.top} — circuito sintetizado pelo pcbflow ({len(design.instances)} células: "
            f"{', '.join(cells)}; {len(design.parts)} componentes)",
            f"família {lib.name}, canto {corner.name} (VDD {corner.vdd:g} V, {corner.temp:g} °C)",
            f"gerado por pcbflow-cellsim --design {design.top} --export; rodar: ngspice -b {design.top}.cir", "",
            f"entradas no nível de pior caso: alto = {lv.vih:g} V, baixo = {lv.vil:g} V; cada saída leva uma "
            "carga de referência", f"saída: 1 se >= {lv.voh_min:g} V, 0 se <= {lv.vol_max:g} V", "",
            "vetores de teste (medida: valor esperado):"] + ["  " + v for v in vectors] + [""]


def write_design_csv(path, design, res):
    """Grava um CSV com as entradas, valores esperados, tensões e atrasos de cada vetor em cada canto."""
    import csv
    ins = [p.name for p in design.ports if p.direction == "input"]
    outs = [p.name for p in design.ports if p.direction == "output"]
    cols = ["corner", "vector", *ins]
    for o in outs:
        cols += [f"exp_{o}", f"v_{o}", f"got_{o}", f"tpd_{o}_s"]
    cols += ["tpd_max_s", "status"]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in res.values():
            for row in r.get("rows", ()):
                w.writerow(row)


def export_design(lib, design, vectors, outdir, res, log=print, window=32, csv_out=True):
    """O netlist do circuito no primeiro canto, um gráfico dos primeiros vetores, o CSV e o resumo."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    ngspice = find_ngspice()
    models, cs = spice_setup(lib)
    corner = cs[0]
    lv = levels(lib, corner)
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    csv_path = None
    if csv_out:
        csv_path = (outdir / f"{design.top}.csv") if csv_out is True else Path(csv_out)
        write_design_csv(csv_path, design, res)
    r = sim_design(lib, models, corner, design, vectors, outdir, ngspice, capture=outdir / design.top)
    dat = outdir / f"{design.top}.dat"
    names = dat.read_text(encoding="utf-8").splitlines()[0].split()
    data = np.loadtxt(dat, skiprows=1, ndmin=2)
    keep = data[:, 0] <= window * corner.step
    data = data[keep]
    sig = names[1:]
    fig, axs = plt.subplots(len(sig), 1, sharex=True, figsize=(10, 0.55 * len(sig) + 1.2), squeeze=False)
    unit, scale = ("ms", 1e3) if corner.step >= 1e-3 else ("µs", 1e6)
    for i, name in enumerate(sig):
        ax = axs[i][0]
        nd = re.sub(r"^v\((.*)\)$", r"\1", name)
        label = r["labels"].get(nd, nd)
        out = any(label == p.name for p in design.ports if p.direction == "output")
        ax.plot(data[:, 0] * scale, data[:, i + 1], lw=1.0, color="#c0392b" if out else "#2c3e50")
        ax.set_ylim(-0.4, corner.vdd + 0.4)
        ax.set_yticks([])
        ax.set_ylabel(label, rotation=0, ha="right", va="center", fontsize=8)
    axs[-1][0].set_xlabel(f"tempo ({unit})")
    fig.suptitle(f"{design.top} — {Path(lib.path).name}, canto {corner.name}: os primeiros {window} vetores",
                 fontsize=11)
    fig.tight_layout()
    fig.savefig(outdir / f"{design.top}.png", dpi=100)
    plt.close(fig)
    dat.unlink()
    for f in outdir.glob(f"{design.top}*.log"):
        f.unlink()
    L = [f"# Circuito `{design.top}` na família `{Path(lib.path).name}` (ngspice)", "",
         f"{len(design.instances)} células, {len(design.parts)} componentes, {len(vectors)} vetores "
         f"(todas as combinações das entradas, simuladas em lotes de {int(cs[0].batch)}). Cada vetor é conferido contra a "
         "lógica do netlist; o caminho crítico é o último cruzamento de uma saída depois da mudança das "
         f"entradas. O netlist publicado tem os primeiros {min(int(cs[0].batch), len(vectors))} vetores.", "",
         "| Canto | Resultado | Caminho crítico |", "|---|---|---|"]
    L[-2:] = ["| Canto | Resultado | Sem convergir | Caminho crítico |", "|---|---|---:|---|"]
    for name, x in res.items():
        tot = x.get("measured", 0) + x.get("missing", 0)
        miss = f"{100 * x['missing'] / tot:.0f} %" if tot and x.get("missing") else "—"
        status = "OK" if x["ok"] else "**%d saídas erradas**" % len(x["fails"])
        L.append(f"| {name} | {status} | {miss} | "
                 + (f"{_ns(x['tpd'])} ({x['where']})" if x.get("tpd") else "—") + " |")
    csv_line = (f"Dados completos de todos os vetores e cantos em [{csv_path.name}]({csv_path.name}). "
                if csv_path and csv_path.parent == outdir else "")
    L += ["", f"{csv_line}Reproduzir (canto {corner.name}): `ngspice -b {design.top}.cir`", "",
          f"![{design.top}]({design.top}.png)", ""]
    (outdir / f"{design.top}.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    readme = outdir / "README.md"
    if readme.is_file():                        # a seção do circuito no README das células
        text = readme.read_text(encoding="utf-8")
        mark = f"## Circuito {design.top}"
        if mark not in text:
            text = text.rstrip() + "\n\n" + "\n".join(
                [mark, "", f"Um circuito inteiro, sintetizado pelo pcbflow: {len(design.instances)} células, "
                 f"{len(design.parts)} componentes e {len(vectors)} vetores. Resultados e gráfico em "
                 f"[{design.top}.md]({design.top}.md); dados em [{design.top}.csv]({design.top}.csv); "
                 f"netlist em [{design.top}.cir]({design.top}.cir).", ""])
            readme.write_text(text + "\n", encoding="utf-8")
    log(f"  {design.top} exportado")


def _safe(name):
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def design_vectors(design, n=None, seed=1, shuffle=False):
    """Todas as combinações das entradas (até 2^12) ou n sorteadas.
    Se houver entradas de clock/reset, gera uma sequência com reset inicial e bordas de clock
    (mudando os dados com clk=0 e subindo clk=1 no passo seguinte, respeitando setup e hold)."""
    import random
    ins = [p.name for p in design.ports if p.direction == "input"]
    clk = next((p for p in ins if p in ("clk", "clock", "C")), None)
    rst_n = next((p for p in ins if p in ("rst_n", "resetn", "R")), None)
    rst = next((p for p in ins if p in ("rst", "reset")), None)
    if clk:
        data_ins = [p for p in ins if p not in (clk, rst_n, rst)]
        total = 2 ** len(data_ins)
        ks = list(range(total))
        if shuffle is not False and shuffle is not None:
            rng = random.Random() if shuffle is True else random.Random(int(shuffle))
            rng.shuffle(ks)
        seq = ks + ks                              # dois giros pelas combinações para percorrer todos os estados
        if n is not None:
            seq = seq[:max(1, n // 2)]
        vecs = []
        base0 = seq[0] if seq else 0
        if rst_n or rst:
            v0 = {p: (base0 >> i) & 1 for i, p in enumerate(data_ins)}
            v0[clk] = 0
            if rst_n:
                v0[rst_n] = 0
            if rst:
                v0[rst] = 1
            vecs.append(v0)
        for k in seq:
            d = {p: (k >> i) & 1 for i, p in enumerate(data_ins)}
            if rst_n:
                d[rst_n] = 1
            if rst:
                d[rst] = 0
            vecs.append({**d, clk: 0})
            vecs.append({**d, clk: 1})
        return vecs
    total = 2 ** len(ins)
    if n is None and total > 4096:
        n = 512
    rng = random.Random() if shuffle is True else random.Random(seed if shuffle is False or shuffle is None else int(shuffle))
    if n is None or n >= total:
        ks = list(range(total))
        if shuffle is not False and shuffle is not None:
            rng.shuffle(ks)
    else:
        ks = rng.sample(range(total), n)
    return [{p: (k >> i) & 1 for i, p in enumerate(ins)} for k in ks]


def check_design(lib, sources, top, work, vectors=None, log=print, jobs=None, shuffle=False):
    ngspice = find_ngspice()
    if not ngspice:
        raise CellSimError("ngspice não encontrado")
    models, corners = spice_setup(lib)
    work = Path(work)
    design = build_design(lib, sources, top, work / "synth")
    vecs = vectors if isinstance(vectors, list) else design_vectors(design, vectors, shuffle=shuffle)
    log(f"  {top}: {len(design.instances)} células, {len(design.parts)} componentes, {len(vecs)} vetores")

    def one(corner):
        try:
            return corner.name, sim_design(lib, models, corner, design, vecs, work, ngspice)
        except CellSimError as e:
            return corner.name, {"ok": False, "fails": [str(e)], "vectors": len(vecs)}
    res = {}
    with ThreadPoolExecutor(max_workers=jobs or min(4, len(corners))) as ex:
        for name, r in ex.map(one, corners):
            res[name] = r
            tot = r.get("measured", 0) + r.get("missing", 0)
            log(f"  {top:<9} {name:<7} {'OK' if r['ok'] else 'FALHOU'}"
                + (f" ({100 * r['missing'] / tot:.0f} % sem convergir)" if tot and r.get("missing") else "")
                + (f", caminho crítico {_ns(r['tpd'])} ({r['where']})" if r.get("tpd") else ""))
    return res, design


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
        ok = [r for r in by.values() if r["ok"]]        # num canto em que a célula falha, não há hold
        ckqs = [r["ckq"][0] for r in ok if r.get("ckq")]
        # conservador: o lado de cima do intervalo do hold (o último que passou)
        holds = [r["hold"][0] or r["hold"][1] for r in ok if r.get("hold") and r["hold"][1]]
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
            ax.plot(data[:, 0] * (1e3 if corner.step >= 1e-3 else 1e6), data[:, i + 1], lw=1.3, color="#c0392b" if out else "#2c3e50")
            if out:
                for y in (lv.voh_min, lv.vol_max):
                    ax.axhline(y, ls="--", lw=0.7, color="#7f8c8d")
            ax.set_ylim(-0.4, corner.vdd + 0.4)
            ax.set_ylabel(label, rotation=0, ha="right", va="center")
            ax.set_yticks([0, round(corner.vdd)])
            ax.grid(alpha=0.25)
        axs[-1][0].set_xlabel(f"tempo ({'ms' if corner.step >= 1e-3 else 'µs'})")
        fig.suptitle(f"{cell} — canto {corner.name} (VDD {corner.vdd:g} V, {corner.temp:g} °C)", fontsize=11)
        fig.tight_layout()
        fig.savefig(outdir / f"{cell}.png", dpi=110)
        plt.close(fig)
        dat.unlink()
        for f in outdir.glob(f"{cell}.log"):
            f.unlink()
        shown[cell] = r["ok"]
        log(f"  {cell:<9} exportado ({'OK' if r['ok'] else 'FALHOU'})")
    if set(cells) != set(lib.cells) and (outdir / "README.md").is_file():
        return                                   # só algumas células: o README e os resultados já existentes ficam
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
    if v is None:
        return "—"
    if v >= 1e-3:
        return f"{v * 1e3:.3g} ms"
    return f"{v * 1e6:.3g} µs" if v >= 1e-6 else f"{v * 1e9:.3g} ns"


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
    ap.add_argument("--design", metavar="TOP", help="simula este circuito combinacional inteiro (com --src)")
    ap.add_argument("--src", nargs="+", help="fontes Verilog do --design")
    ap.add_argument("--vectors", type=int, help="vetores sorteados no --design (padrão: todas as combinações)")
    ap.add_argument("--shuffle", metavar="SEED", nargs="?", type=int, const=True, default=False,
                    help="embaralha a ordem dos vetores do --design (sem argumento usa semente aleatória)")
    ap.add_argument("--window", type=int, default=32,
                    help="número de vetores mostrados no gráfico do --design --export (padrão: 32)")
    ap.add_argument("--csv", metavar="ARQ", nargs="?", const=True, default=None,
                    help="grava CSV com todos os vetores e cantos do --design (padrão no --export: <PASTA>/<TOP>.csv)")
    ap.add_argument("--no-csv", action="store_true", help="não grava o CSV no --design --export")
    args = ap.parse_args(argv)
    t0 = time.time()
    if args.design:
        try:
            lib = Library(resolve_family(args.lib))
            out = Path(args.out or Path("build/cellsim") / f"{args.design}_{Path(lib.path).name}")
            if not args.src:
                raise CellSimError("--design precisa de --src")
            shuf = int(time.time() * 1000) % (2**31) if args.shuffle is True else args.shuffle
            print(f"Simulação analógica do circuito '{args.design}' na família '{lib.name}' (ngspice)"
                  + (f" [shuffle seed={shuf}]" if shuf is not False else ""))
            res, design = check_design(lib, args.src, args.design, out, args.vectors, jobs=args.jobs,
                                       shuffle=shuf)
        except (LibraryError, CellSimError, RuntimeError, ValueError) as e:
            print(f"ERRO: {e}")
            return 3
        for name, r in res.items():
            for f in r["fails"][:10]:
                print(f"  FALHA ({name}): {f}")
        csv_target = False if args.no_csv else (args.csv if args.csv is not None else bool(args.export))
        if csv_target and not args.export:
            cpath = (out / f"{args.design}.csv") if csv_target is True else Path(csv_target)
            write_design_csv(cpath, design, res)
            print(f"  CSV gravado em {cpath}")
        if args.export:
            export_design(lib, design, design_vectors(design, args.vectors, shuffle=shuf), args.export, res,
                          window=args.window, csv_out=csv_target)
        bad = [n for n, r in res.items() if not r["ok"]]
        print(f"{len(res)} cantos: {len(bad)} com falha. Netlists em {out}")
        print(f"Concluído em {time.time() - t0:.0f} s")
        return 1 if bad else 0
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
