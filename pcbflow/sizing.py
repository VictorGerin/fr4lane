"""Dimensionamento por fan-out: troca cada instância pela variante mais
econômica que ainda alimenta as suas cargas.

O Yosys só conhece as células base. Depois da síntese, para cada instância,
as variantes da base (lib.variant_group) são tentadas em ordem de custo
(corrente estática, depois área) e fica a primeira em que toda saída passa:

  - no limite elétrico de pior caso (drive.py), quando a família o declara;
  - no max_fanout da célula (entradas ligadas a cada saída), quando declarado.

Uma variante com várias saídas para uma saída da base ("outputs": {"Y": ["Y0",
"Y1"]}) divide as cargas: as entradas são ordenadas por módulo e instância e
cortadas em fatias contíguas de peso parecido, para cargas vizinhas ficarem
na mesma saída. A primeira saída fica com o nome da net original (e com as
portas do topo, se houver); as outras ganham nets novas (<net>.y1, ...).

Trocar uma instância muda a carga que as suas entradas representam (uma
variante econômica tem RB maior), então quem a alimenta é reavaliado. Cada
instância só sobe na ordem de custo, o que garante que o processo termina.
"""

import re
from collections import deque
from dataclasses import dataclass, field

from . import drive
from .netlist import elaborate

_NUM = re.compile(r"(\d+)")


@dataclass
class NetReport:
    net: str
    inst: str
    cell: str
    pin: str
    sinks: int              # entradas ligadas (sem contar portas do topo)
    limit: int = None       # max_fanout da célula
    voh: float = None       # nível alto em pior caso (V)
    margin: float = None    # menor Ib / Ib necessária
    ok: bool = True


@dataclass
class SizeResult:
    changed: list = field(default_factory=list)      # (instância, base, variante, entradas alimentadas)
    unresolved: list = field(default_factory=list)   # instâncias sem variante que atenda


def _natural(s):
    return [int(t) if t.isdigit() else t for t in _NUM.split(s)]


class _Model:
    """Cargas e drives por célula, e o critério de aprovação de uma saída."""

    def __init__(self, lib, el, drives):
        self.lib, self.el, self.drives = lib, el, drives

    def loads(self, cell, pin):
        if not self.drives:
            return []
        return self.drives[cell].pins[pin].loads

    def weight(self, cell, pin):
        if not self.drives:
            return 1.0
        return sum(1 / ld.rb for ld in self.loads(cell, pin))

    def cost(self, cell):
        static = self.drives[cell].static_ma if self.drives else 0.0
        return (static, self.lib.cells[cell].area, cell)

    def judge(self, cell, pin, sink_loads, n_sinks):
        """(ok, nota, voh, margem, limite) de uma saída com as cargas dadas."""
        limit = self.lib.meta_of(cell).get("max_fanout")
        score = float("inf")
        ok = True
        if limit:
            score = limit / n_sinks if n_sinks else float("inf")
            ok = n_sinks <= limit
        voh = margin = None
        if self.drives:
            pd = self.drives[cell].pins[pin]
            r = drive.evaluate(self.el, pd.g_up, pd.loads + sink_loads)
            if r is not None:
                voh, margin = r.voh, r.margin
                score = min(score, margin, r.voh / self.el.voh_min)
                ok = ok and r.ok
        return ok, score, voh, margin, limit


def _sinks_by_net(lib, design):
    sinks = {}
    for inst, (cell, _) in design.instances.items():
        ins = set(lib.cells[cell].inputs)
        for pin, net in design.conns[inst].items():
            if pin in ins:
                sinks.setdefault(net, []).append((inst, pin))
    for p in design.ports:
        if p.direction == "output":
            sinks.setdefault(p.net, []).append(("", p.name))
    return sinks


def _bus_driver(lib, cell):
    """Driver de barramento: só força um nível; quem alimenta as cargas é a
    terminação da linha, avaliada no lugar dele."""
    return lib.tristate is not None and cell == lib.tristate["cell"]


def check_nets(lib, design, el, drives):
    """Avalia toda net dirigida por uma instância (depois do sizing, se houve)."""
    m = _Model(lib, el, drives)
    sinks = _sinks_by_net(lib, design)
    out = []
    for inst, (cell, _) in design.instances.items():
        if _bus_driver(lib, cell):
            continue
        for pin in lib.cells[cell].outputs:
            net = design.conns[inst].get(pin)
            if net is None or net in lib.supplies():
                continue
            ss = [s for s in sinks.get(net, []) if s[0]]
            lds = [ld for si, sp in ss for ld in m.loads(design.instances[si][0], sp)]
            ok, _, voh, margin, limit = m.judge(cell, pin, lds, len(ss))
            out.append(NetReport(net, inst, cell, pin, len(ss), limit, voh, margin, ok))
    return out


def size_design(lib, design, el, drives, log=None):
    m = _Model(lib, el, drives)
    sinks = _sinks_by_net(lib, design)
    driver = {}
    for inst, (cell, _) in design.instances.items():
        for pin in lib.cells[cell].outputs:
            net = design.conns[inst].get(pin)
            if net is not None:
                driver[net] = inst
    base = {inst: cell for inst, (cell, _) in design.instances.items()}
    cands = {inst: sorted(lib.variant_group(c), key=m.cost) for inst, c in base.items()}
    idx = {inst: 0 for inst in base}
    module = design.inst_module

    def current(inst):
        return cands[inst][idx[inst]]

    def split(inst, cell, bpin):
        """Fatias das entradas da net de bpin entre as saídas da célula."""
        vpins = lib.output_map(cell, bpin)
        ss = sinks.get(design.conns[inst][bpin], [])
        ports = [s for s in ss if not s[0]]
        real = sorted((s for s in ss if s[0]), key=lambda s: (module.get(s[0], ""), _natural(s[0]), s[1]))
        if len(vpins) == 1:
            return {vpins[0]: ports + real}
        w = [m.weight(cell if si == inst else current(si), sp) for si, sp in real]
        total, k, acc = sum(w), len(vpins), 0.0
        parts = {v: [] for v in vpins}
        parts[vpins[0]] += ports
        j = 0
        for s, ws in zip(real, w):
            # passa para a próxima saída quando esta já levou a sua parte do peso
            while j < k - 1 and acc >= total * (j + 1) / k:
                j += 1
            parts[vpins[j]].append(s)
            acc += ws
        return parts

    def fits(inst, cell):
        ok_all, worst = True, float("inf")
        for bpin in lib.cells[base[inst]].outputs:
            if design.conns[inst].get(bpin) is None:
                continue
            for vpin, ss in split(inst, cell, bpin).items():
                real = [s for s in ss if s[0]]
                lds = [ld for si, sp in real for ld in m.loads(cell if si == inst else current(si), sp)]
                ok, score, *_ = m.judge(cell, vpin, lds, len(real))
                ok_all &= ok
                worst = min(worst, score)
        return ok_all, worst

    queue = deque(i for i in base if len(cands[i]) > 1)
    queued = set(queue)
    unresolved = set()
    while queue:
        inst = queue.popleft()
        queued.discard(inst)
        cur = idx[inst]
        pick, best = None, (-1.0, cur)
        for j in range(cur, len(cands[inst])):
            ok, score = fits(inst, cands[inst][j])
            if ok:
                pick = j
                break
            if score > best[0]:
                best = (score, j)
        if pick is None:
            pick = best[1]
            unresolved.add(inst)
        else:
            unresolved.discard(inst)
        if pick != cur:
            idx[inst] = pick
            # a carga das entradas mudou: quem as alimenta precisa ser reavaliado
            for pin in lib.cells[base[inst]].inputs:
                d = driver.get(design.conns[inst].get(pin))
                if d and len(cands[d]) > 1 and d not in queued:
                    queue.append(d)
                    queued.add(d)

    # aplica: troca as células e divide as nets das variantes com várias saídas
    res = SizeResult()
    used = set(design.nets()) | set(sinks) | set(driver)
    plans = {}
    for inst in base:
        cell = current(inst)
        if cell != base[inst]:
            plans[inst] = {bpin: split(inst, cell, bpin) for bpin in lib.cells[base[inst]].outputs
                           if design.conns[inst].get(bpin) is not None}
    for inst, plan in plans.items():
        cell = current(inst)
        conns = design.conns[inst]
        n_sinks = 0
        for bpin, parts in plan.items():
            net = conns.pop(bpin)
            for k, (vpin, ss) in enumerate(parts.items()):
                new = net
                if k:
                    new = f"{net}.y{k}"
                    while new in used:
                        new += "_"
                    used.add(new)
                conns[vpin] = new
                for si, sp in ss:
                    if si:
                        design.conns[si][sp] = new
                        n_sinks += 1
        design.instances[inst] = (cell, design.instances[inst][1])
        res.changed.append((inst, base[inst], cell, n_sinks))
    res.unresolved = sorted(unresolved, key=_natural)
    elaborate(lib, design)
    return res
