"""Inserção de buffers por fan-out (depois do sizing).

O sizing troca uma célula por uma variante mais forte; quando nem a variante
mais forte alimenta as cargas da net (ou a célula não tem variante), aqui a
net ganha uma árvore de buffers:

  - as cargas (entradas de células) são ordenadas por módulo e instância e
    cortadas em grupos que um buffer alimenta (o mesmo critério do sizing:
    max_fanout e drive em pior caso, drive.py); cargas vizinhas ficam no
    mesmo buffer;
  - se quem dirige a net não alimenta todos esses buffers, eles mesmos são
    agrupados sob outro nível de buffers, até caber: a árvore é balanceada,
    toda carga fica à mesma profundidade (o mesmo atraso; importa no clock);
  - as portas de saída do topo continuam na net original.

As entradas do topo também são conferidas, como se fossem dirigidas por um
buffer da família (numa placa por estágio, quem as dirige é uma saída da
placa anterior).

Cada buffer vai para o módulo que contém quem o alimenta e as cargas dele
(o ancestral comum): dentro de um macro, todas as cópias ganham os mesmos
buffers e continuam com o mesmo molde.
"""

from dataclasses import dataclass, field

from . import liberty
from .netlist import common_module, elaborate
from .sizing import _Model, _bus_driver, _natural, _sinks_by_net


@dataclass
class BufferResult:
    cell: str = None                                  # célula usada como buffer
    trees: list = field(default_factory=list)         # (net, quem dirige, cargas, buffers, níveis)
    unresolved: list = field(default_factory=list)    # (net, motivo)

    @property
    def count(self):
        return sum(t[3] for t in self.trees)


def buffer_cell(lib, model):
    """A célula de buffer da família: entrada única, saída = entrada, usável
    na síntese; entre várias, a que alimenta mais cargas, depois a mais barata."""
    best = None
    for name, cell in lib.cells.items():
        if cell.seq or len(cell.inputs) != 1 or len(cell.outputs) != 1 or not lib.usable(name):
            continue
        fn = cell.pins[cell.outputs[0]]["function"].strip()
        if not fn or liberty.parse_expr(fn) != ("var", cell.inputs[0]):
            continue
        cap = _capacity(model, name, cell.outputs[0], [(name, cell.inputs[0])] * 64)
        key = (cap, [-x for x in model.cost(name)[:2]])
        if best is None or key > best[0]:
            best = (key, name)
    return best[1] if best else None


def _capacity(model, cell, pin, sinks):
    """Quantas das cargas 'sinks' ((célula, pino)), na ordem, a saída alimenta."""
    n = 0
    loads = []
    for c, p in sinks:
        loads = loads + model.loads(c, p)
        if not model.judge(cell, pin, loads, n + 1)[0]:
            break
        n += 1
    return n


def _groups(model, cell, pin, sinks, cell_of):
    """Corta 'sinks' ((instância, pino)) em grupos contíguos que uma saída
    (cell, pin) alimenta; None se nem uma carga cabe."""
    groups, cur, loads = [], [], []
    for s in sinks:
        lds = loads + model.loads(cell_of(s), s[1])
        if cur and not model.judge(cell, pin, lds, len(cur) + 1)[0]:
            groups.append(cur)
            cur, lds = [], model.loads(cell_of(s), s[1])
        if not cur and not model.judge(cell, pin, lds, 1)[0]:
            return None
        cur.append(s)
        loads = lds
    if cur:
        groups.append(cur)
    return groups


def buffer_ports(lib, design, el, drives):
    """Um buffer da família na entrada de cada porta de entrada e inout (B1,
    B2...): as cargas da placa passam para a saída dele, e a placa pesa uma
    carga só em cada linha. Numa pilha de placas, é o que deixa um sinal (ou o
    pull-up de um barramento) alimentar todas as placas. Os drivers de
    barramento ficam na linha; só as cargas vão para trás do buffer.
    Devolve [(porta, cargas movidas)]."""
    buf = buffer_cell(lib, _Model(lib, el, drives))
    if buf is None:
        return []
    b_in, b_out = lib.cells[buf].inputs[0], lib.cells[buf].outputs[0]
    sinks = _sinks_by_net(lib, design)
    power = set(lib.supplies())
    used = set(design.nets()) | set(sinks)
    n_buf = sum(1 for i in design.instances if i.startswith("B") and i[1:].isdigit())
    out = []
    for p in design.ports:
        if p.direction not in ("input", "inout") or p.net in power:
            continue
        real = [s for s in sinks.get(p.net, []) if s[0]]
        if not real:
            continue
        new = f"{p.net}.in"
        while new in used:
            new += "_"
        used.add(new)
        n_buf += 1
        inst = f"B{n_buf}"
        design.instances[inst] = (buf, f"$portbuf${p.name}")
        design.conns[inst] = {b_in: p.net, b_out: new}
        design.inst_module[inst] = ""
        for si, sp in real:
            design.conns[si][sp] = new
        out.append((p.name, len(real)))
    if out:
        elaborate(lib, design)
    return out


def buffer_design(lib, design, el, drives, inputs=True):
    """Insere as árvores de buffers no design (instâncias B1, B2...) e o
    reelabora. inputs: confere também as entradas do topo."""
    m = _Model(lib, el, drives)
    res = BufferResult(buffer_cell(lib, m))
    if res.cell is None:
        return res
    buf = res.cell
    b_in, b_out = lib.cells[buf].inputs[0], lib.cells[buf].outputs[0]
    sinks = _sinks_by_net(lib, design)
    module = design.inst_module
    power = set(lib.supplies())

    def cell_of(s):
        return buf if s[0].startswith("\0") else design.instances[s[0]][0]

    def rel(src, dmod, mod):
        """Nome de quem dirige visto do módulo do buffer: o caminho de dmod abaixo
        de mod mais o nome local (o Yosys decora o caminho: _flatten_u0...)."""
        below = dmod.split(".")[len(mod.split(".")) if mod else 0:] if dmod else []
        return "/".join(below + src.split("."))

    # quem dirige cada net: (instância, célula, pino) ou a porta de entrada (como um buffer)
    drivers = []
    for inst, (cell, _) in sorted(design.instances.items(), key=lambda kv: _natural(kv[0])):
        if _bus_driver(lib, cell):
            continue                     # o barramento é dirigido pelo pull-up dele
        for pin in lib.cells[cell].outputs:
            net = design.conns[inst].get(pin)
            if net is not None and net not in power:
                # nome estável do que dirige (o do Yosys, igual em todas as cópias de um módulo):
                # é dele que sai o nome dos buffers, e cópias de um macro continuam iguais
                mod = module.get(inst, "")
                local = design.instances[inst][1].split(".")[len(mod.split(".")) if mod else 0:]
                drivers.append((net, inst, cell, pin, mod, ".".join(local + [pin])))
    if inputs:
        for p in design.ports:
            if p.direction == "input" and p.net not in power:
                drivers.append((p.net, f"(entrada {p.name})", buf, b_out, "", p.name))

    used = set(design.nets()) | set(sinks)
    n_buf = sum(1 for i in design.instances if i.startswith("B") and i[1:].isdigit())
    seen = set()
    for net, who, cell, pin, dmod, src in drivers:
        if net in seen:
            continue
        seen.add(net)
        real = sorted((s for s in sinks.get(net, []) if s[0]),
                      key=lambda s: (module.get(s[0], ""), _natural(s[0]), s[1]))
        lds = [ld for s in real for ld in m.loads(cell_of(s), s[1])]
        if m.judge(cell, pin, lds, len(real))[0]:
            continue
        # níveis: das cargas para cima, até quem dirige aguentar os buffers do topo da árvore
        levels, nodes, why = [], real, None      # nodes: o que o nível atual alimenta
        while True:
            groups = _groups(m, buf, b_out, nodes, cell_of)
            if groups is None:
                why = f"nem um buffer ({buf}) alimenta uma das cargas"
                break
            if len(groups) >= len(nodes) and levels:
                why = f"o buffer ({buf}) não alimenta duas cargas: a árvore não diminui"
                break
            levels.append(groups)
            tops = [(f"\0{len(levels)}.{k}", b_in) for k in range(len(groups))]
            top_lds = [ld for s in tops for ld in m.loads(buf, s[1])]
            if m.judge(cell, pin, top_lds, len(tops))[0]:
                break
            if len(groups) == 1:
                why = f"{who} ({cell}.{pin}) não alimenta nem um buffer"
                break
            nodes = tops
        if why:
            res.unresolved.append((net, why))
            continue

        # aplica, de cima (perto de quem dirige) para baixo
        placed = {}                              # nó virtual "\0nível.k" -> (instância, net de saída)
        count = 0
        for lvl in range(len(levels), 0, -1):
            for k, group in enumerate(levels[lvl - 1]):
                n_buf += 1
                count += 1
                inst = f"B{n_buf}"
                # módulo: ancestral comum de quem alimenta o buffer e das cargas dele
                leaves = _leaves(levels, lvl, k)
                mod = common_module([dmod] + [module.get(s[0], "") for s in leaves])
                in_net = net if lvl == len(levels) else placed[_parent(levels, lvl, k)][1]
                out_net = f"{net}.buf{lvl}_{k}"
                while out_net in used:
                    out_net += "_"
                used.add(out_net)
                yname = (f"{mod}." if mod else "") + f"$fanout${rel(src, dmod, mod)}$L{lvl}_{k}"
                design.instances[inst] = (buf, yname)
                design.conns[inst] = {b_in: in_net, b_out: out_net}
                design.inst_module[inst] = mod
                placed[f"\0{lvl}.{k}"] = (inst, out_net)
                if lvl == 1:
                    for si, sp in group:
                        design.conns[si][sp] = out_net
        res.trees.append((net, who, len(real), count, len(levels)))
    if res.trees:
        elaborate(lib, design)
    return res


def _parent(levels, lvl, k):
    """O nó do nível de cima que alimenta o grupo k do nível lvl."""
    for j, group in enumerate(levels[lvl]):
        if any(s[0] == f"\0{lvl}.{k}" for s in group):
            return f"\0{lvl + 1}.{j}"
    raise KeyError((lvl, k))


def _leaves(levels, lvl, k):
    """As cargas reais (do nível 1) debaixo do grupo k do nível lvl."""
    group = levels[lvl - 1][k]
    if lvl == 1:
        return group
    out = []
    for s in group:
        _, sub = s[0][1:].split(".")
        out += _leaves(levels, lvl - 1, int(sub))
    return out


def check_inputs(lib, design, el, drives):
    """Entradas do topo com mais cargas do que uma saída da família aguenta
    (avaliadas como se dirigidas pelo buffer da família): NetReport do sizing."""
    from .sizing import NetReport
    m = _Model(lib, el, drives)
    buf = buffer_cell(lib, m)
    if buf is None:
        return []
    out_pin = lib.cells[buf].outputs[0]
    sinks = _sinks_by_net(lib, design)
    power = set(lib.supplies())
    out = []
    for p in design.ports:
        if p.direction != "input" or p.net in power:
            continue
        ss = [s for s in sinks.get(p.net, []) if s[0]]
        lds = [ld for si, sp in ss for ld in m.loads(design.instances[si][0], sp)]
        ok, _, voh, margin, limit = m.judge(buf, out_pin, lds, len(ss))
        out.append(NetReport(p.net, f"(entrada {p.name})", buf, out_pin, len(ss), limit, voh, margin, ok))
    return out
