"""Capacidade de drive em pior caso (DC) das saídas resistivas (família RTL).

Uma saída RTL em 1 é um pull-up (RL para o VDD) alimentando as bases das
cargas, cada uma por um resistor de base (RB) até um Vbe. O nível alto cai
com o número de cargas; cada carga precisa de corrente de base suficiente para
saturar o seu transistor. Em pior caso:

  VOH: VDD mínimo, RL no máximo da tolerância, RB das cargas no mínimo;
  Ib de cada carga = (VOH - Vbe - Ve) / RB máximo, onde Ve é a tensão no
       emissor (Vce(sat) de cada NPN empilhado abaixo, ex.: NAND);
  Ib necessária = folga · Ic máxima / β mínimo, com Ic máxima = (VDD máximo -
       n·Vce(sat)) / RL mínimo do coletor (n = NPNs da pilha).

A net passa se toda carga recebe a Ib necessária e VOH >= voh_min.

Parâmetros: "electrical" no library.json (vdd, tolerância, folga, voh_min)
e beta_min/vbe/vce_sat do NPN no parts.json. Famílias sem "electrical" (CMOS:
entrada capacitiva) não têm limite DC; só o max_fanout, se declarado.

Uso: python -m pcbflow.drive pcbflow/lib/rtl   (capacidade de cada célula)
"""

import re
import sys
from dataclasses import dataclass, field

from .netlist import Design, expand

_SI = {"t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3, "m": 1e-3, "u": 1e-6, "µ": 1e-6, "n": 1e-9, "p": 1e-12}


def parse_value(s):
    """'4.7k' -> 4700, '1meg' -> 1e6, '330' -> 330, '4k7' -> 4700."""
    t = s.strip().lower().rstrip("ω").removesuffix("ohm")
    m = re.fullmatch(r"(\d+)(k|meg|m|r)(\d+)", t)          # notação 4k7 / 4r7
    if m:
        mult = {"k": 1e3, "meg": 1e6, "m": 1e6, "r": 1.0}[m.group(2)]
        return float(f"{m.group(1)}.{m.group(3)}") * mult
    m = re.fullmatch(r"([0-9.]+(?:e[-+]?\d+)?)(meg|[tgkmuµnp])?", t)
    if not m:
        raise ValueError(f"valor '{s}' não reconhecido")
    return float(m.group(1)) * _SI.get(m.group(2) or "", 1.0)


@dataclass
class Electrical:
    vdd_min: float
    vdd_max: float
    tol: float               # tolerância dos resistores (0.05 = 5 %)
    overdrive: float         # Ib mínima = overdrive · Ic / β
    voh_min: float           # nível alto mínimo aceito
    beta_min: float
    vbe: float
    vce_sat: float
    reference_load: str = ""  # "CELULA.PINO" usado para exprimir capacidade em cargas

    @property
    def vdd_nom(self):
        return (self.vdd_min + self.vdd_max) / 2


def electrical_of(lib):
    """Parâmetros elétricos da família, ou None se ela não declara "electrical"."""
    e = lib.meta.get("electrical")
    if not e:
        return None
    npn = [p for p in lib.parts.values() if p.get("kind") == "npn"]
    if not npn:
        raise ValueError("library.json: 'electrical' declarado, mas parts.json não tem NPN")
    for key in ("beta_min", "vbe", "vce_sat"):
        if key not in npn[0]:
            raise ValueError(f"parts.json: o NPN precisa de '{key}' para o cálculo de drive")
    vdd = e.get("vdd", [4.75, 5.25])
    return Electrical(vdd[0], vdd[1], e.get("resistor_tol", 0.05), e.get("overdrive", 3.0),
                      e.get("voh_min", 1.5), min(p["beta_min"] for p in npn),
                      max(p["vbe"] for p in npn), max(p["vce_sat"] for p in npn),
                      e.get("reference_load", ""))


@dataclass
class Load:
    """Uma entrada vista pela net que a alimenta: RB até uma base."""
    rb: float          # ohms (nominal)
    ic: float          # corrente de coletor máxima do(s) transistor(es) dessa base (A); 0 = desconhecida
    ve: float          # tensão no emissor quando saturado (NPNs empilhados abaixo)


@dataclass
class PinDrive:
    g_up: float = 0.0                 # condutância nominal do pull-up (1/ohm); 0 = não dirige pull-up
    loads: list = field(default_factory=list)


@dataclass
class CellDrive:
    pins: dict                        # pino -> PinDrive
    internal: dict                    # net interna -> PinDrive
    static_ma: float                  # corrente se todos os pull-ups estiverem em 0 (custo)


def analyze_cell(lib, el, cell, ext=None):
    """Pull-ups e cargas de cada pino e de cada net interna da célula.

    ext: {pino: condutância} de pull-ups de fora da célula (a terminação numa
    saída de coletor aberto). Só entram na corrente de coletor dos NPNs que puxam
    esse pino; a célula não dirige o pino para 1 nem gasta essa corrente."""
    ext = ext or {}
    sub = lib.subckts[cell]
    pins = [p for p in sub.pins if p not in lib.supplies()]
    d = Design(cell, [], [], lib.vdd, lib.gnd)
    expand(lib, d, cell, "c", {p: p for p in pins}, "c", cell)
    parts = d.parts
    kind = {id(p): lib.parts[p.model]["kind"] for p in parts}
    npns = [p for p in parts if kind[id(p)] == "npn"]
    g_up = {}
    base_res = []
    for p in parts:
        if kind[id(p)] != "resistor":
            continue
        a, b = p.pins["1"], p.pins["2"]
        r = parse_value(p.value)
        if lib.vdd in (a, b):
            other = b if a == lib.vdd else a
            if other != lib.gnd:
                g_up[other] = g_up.get(other, 0.0) + 1.0 / r
            continue
        bases = {t.pins["B"] for t in npns}
        if b in bases and a not in bases:
            base_res.append((a, b, r))
        elif a in bases and b not in bases:
            base_res.append((b, a, r))

    pull = {**{p: g for p, g in ext.items() if p in pins}, **g_up}

    def stack(t):
        """(Ic máxima, Ve) do NPN t saturado, seguindo a pilha série até o pull-up e o GND."""
        n, c, seen = 1, t.pins["C"], {id(t)}
        while c not in pull:
            up = [u for u in npns if u.pins["E"] == c and id(u) not in seen]
            if not up:
                return 0.0, 0.0
            seen.add(id(up[0]))
            n, c = n + 1, up[0].pins["C"]
        ve, e = 0.0, t.pins["E"]
        while e != lib.gnd:
            dn = [u for u in npns if u.pins["C"] == e and id(u) not in seen]
            if not dn:
                break
            seen.add(id(dn[0]))
            n, ve, e = n + 1, ve + el.vce_sat, dn[0].pins["E"]
        ic = max(0.0, el.vdd_max - n * el.vce_sat) * pull[c] / (1 - el.tol)
        return ic, ve

    out = {}
    for net, base, r in base_res:
        ic, ve = 0.0, 0.0
        for t in npns:
            if t.pins["B"] == base:
                i, v = stack(t)
                ic, ve = ic + i, max(ve, v)
        out.setdefault(net, PinDrive()).loads.append(Load(r, ic, ve))
    for net, g in g_up.items():
        out.setdefault(net, PinDrive()).g_up = g
    pin_drive = {p: out.get(p, PinDrive()) for p in pins}
    internal = {n: v for n, v in out.items() if n not in pins}
    static = sum(g_up.values()) * el.vdd_nom * 1e3
    return CellDrive(pin_drive, internal, static)


@dataclass
class NetEval:
    voh: float
    margin: float      # menor Ib/Ib necessária entre as cargas (inf se não há cargas com Ic conhecida)
    ok: bool


def evaluate(el, g_up, loads):
    """Nível alto e folga de corrente de base em pior caso; None se a net não tem pull-up."""
    if g_up <= 0:
        return None
    gu = g_up / (1 + el.tol)
    on = list(loads)
    while True:
        num = gu * el.vdd_min + sum((el.vbe + ld.ve) / (ld.rb * (1 - el.tol)) for ld in on)
        den = gu + sum(1 / (ld.rb * (1 - el.tol)) for ld in on)
        v = num / den
        still = [ld for ld in on if el.vbe + ld.ve < v]
        if len(still) == len(on):
            break
        on = still
    margin = float("inf")
    for ld in loads:
        if ld.ic <= 0:
            continue
        ib = max(0.0, v - el.vbe - ld.ve) / (ld.rb * (1 + el.tol))
        margin = min(margin, ib / (el.overdrive * ld.ic / el.beta_min))
    return NetEval(v, margin, margin >= 1 and v >= el.voh_min)


def capacity(el, g_up, own_loads, ref_loads, limit=200):
    """Quantas cópias de ref_loads a saída aguenta (além das cargas internas)."""
    n = 0
    while n < limit:
        r = evaluate(el, g_up, own_loads + ref_loads * (n + 1))
        if r is None or not r.ok:
            break
        n += 1
    return n


def library_drive(lib):
    """(Electrical, {célula: CellDrive}) da família; (None, {}) se ela não tem modelo DC."""
    el = electrical_of(lib)
    if el is None:
        return None, {}
    drives = {name: analyze_cell(lib, el, name) for name in lib.cells}
    if lib.tristate and lib.terminator and lib.terminator["level"] == 1:
        # o driver de barramento puxa a corrente da terminação (pull-up) da linha
        t, ts = lib.terminator, lib.tristate
        drives[ts["cell"]] = analyze_cell(lib, el, ts["cell"], {ts["out"]: drives[t["cell"]].pins[t["pin"]].g_up})
    return el, drives


def check_internal(lib, el, drives):
    """Nets internas das células que não passam no pior caso (montagem mal dimensionada)."""
    p = []
    for name, cd in drives.items():
        for net, pd in cd.internal.items():
            r = evaluate(el, pd.g_up, pd.loads)
            if r and not r.ok:
                p.append(f"{name}: net interna {net} sem drive no pior caso "
                         f"(VOH {r.voh:.2f} V, Ib/Ib mín. {r.margin:.2f})")
    return p


def reference_loads(lib, el, drives):
    if not el or not el.reference_load:
        return None
    cell, _, pin = el.reference_load.partition(".")
    if cell not in drives or pin not in drives[cell].pins:
        raise ValueError(f"library.json: reference_load '{el.reference_load}' não existe")
    return drives[cell].pins[pin].loads


def capacity_table(lib, el, drives):
    """Linhas (célula, base, pino, capacidade em cargas de referência, corrente estática)."""
    ref = reference_loads(lib, el, drives)
    rows = []
    for name, cd in drives.items():
        base = lib.meta_of(name).get("variant_of", name)
        for pin in lib.cells[name].outputs:
            pd = cd.pins[pin]
            # o driver de barramento não leva a linha a 1: quem alimenta as cargas é a terminação
            cap = capacity(el, pd.g_up, pd.loads, ref) if ref is not None and pd.g_up else None
            rows.append((name, base, pin, cap, cd.static_ma))
    return rows


def main(argv=None):
    from .library import Library
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("uso: python -m pcbflow.drive <pasta da família>")
        return 2
    lib = Library(argv[0])
    el, drives = library_drive(lib)
    if el is None:
        print(f"{lib.name}: a família não declara 'electrical' (sem limite DC de fan-out)")
        return 0
    print(f"{lib.name}: VDD {el.vdd_min}–{el.vdd_max} V, β mín. {el.beta_min:g}, Vbe {el.vbe} V, "
          f"Vce(sat) {el.vce_sat} V, folga {el.overdrive:g}×, resistores ±{el.tol * 100:g} %")
    print(f"capacidade em cargas '{el.reference_load}' (pior caso)\n")
    print(f"{'célula':<12}{'base':<10}{'saída':<7}{'cargas':>7}{'max_fanout':>12}{'mA (0)':>9}")
    for name, base, pin, cap, ma in sorted(capacity_table(lib, el, drives), key=lambda r: (r[1], r[0], r[2])):
        mf = lib.meta_of(name).get("max_fanout", "—")
        print(f"{name:<12}{base:<10}{pin:<7}{'—' if cap is None else cap:>7}{mf:>12}{ma:>9.2f}")
    for p in check_internal(lib, el, drives):
        print("AVISO: " + p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
