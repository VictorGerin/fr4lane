"""Leitura do netlist do Yosys e expansão célula -> subcircuitos SPICE -> componentes."""

import json
import re
from dataclasses import dataclass, field

from .library import CONTROL_ROLES


@dataclass
class Port:
    name: str          # nome do bit, ex.: "sum[2]"
    direction: str     # input | output | inout
    net: str


@dataclass
class Block:
    """Instância de um subcircuito que contém componentes — a unidade de placement."""
    name: str                  # caminho da instância, ex.: FF1.X3
    cell: str                  # subcircuito
    pins: dict                 # pino -> net
    outputs: list              # nets de saída
    inputs: list               # nets de entrada
    group: str                 # instância lógica de origem (ex.: FF1)
    group_cell: str            # célula Liberty de origem (ex.: DFFR)
    parts: list = field(default_factory=list)
    module: str = ""           # instância do módulo Verilog de origem (ex.: u_fa); "" = topo


@dataclass
class Part:
    ref: str                   # Q1, R7... (atribuída no placement)
    name: str                  # nome do elemento no .sp (MP1, RL...)
    model: str                 # chave do parts.json
    value: str                 # valor (R/C) ou número da peça
    pins: dict                 # terminal lógico (D/G/S, C/B/E, 1/2) -> net
    block: Block = None


@dataclass
class Design:
    top: str
    ports: list
    blocks: list
    vdd: str
    gnd: str
    instances: dict = field(default_factory=dict)   # instância lógica -> (célula, nome yosys)
    conns: dict = field(default_factory=dict)       # instância lógica -> {pino: net}
    inst_module: dict = field(default_factory=dict)  # instância lógica -> módulo (ex.: u_fa)
    modules: dict = field(default_factory=dict)      # módulo -> tipo Verilog (ex.: full_adder)

    @property
    def parts(self):
        return [p for b in self.blocks for p in b.parts]

    def nets(self):
        nets = set()
        for p in self.parts:
            nets.update(p.pins.values())
        nets.update(p.net for p in self.ports)
        return nets


_BAD = re.compile(r'[^A-Za-z0-9_\[\]\.\-/+]')


def _clean(name):
    name = name.lstrip("\\")
    return _BAD.sub("_", name)


def scope_of(yname):
    """Instância de módulo de onde veio um nome do netlist achatado.

    '$flatten\\u_fa.$abc$198$new_n7' -> 'u_fa'; 'u_a.u_b.g1' -> 'u_a.u_b'; 'g1' -> ''."""
    segs = [x for x in yname.replace("$flatten", "").replace("\\", "").split(".") if x]
    for i, seg in enumerate(segs):
        if seg.startswith("$"):
            return ".".join(segs[:i])
    return ".".join(segs[:-1])


def _module_types(hier_path, top):
    """Tipo Verilog de cada instância de módulo, a partir do JSON antes do flatten."""
    if not hier_path:
        return {}
    with open(hier_path) as f:
        mods = json.load(f)["modules"]
    out = {}

    def short(t):
        # '$paramod\mux\W=8' -> 'mux'
        return t.split("\\")[1] if t.startswith("$paramod") else t.lstrip("\\")

    def walk(mod, prefix):
        for cname, c in mods[mod]["cells"].items():
            # as células da biblioteca também aparecem como módulos (caixas-pretas)
            if c["type"] in mods and not mods[c["type"]].get("attributes", {}).get("blackbox"):
                path = prefix + _clean(cname)
                out[path] = short(c["type"])
                walk(c["type"], path + ".")

    walk(top, "")
    return out


def _bit_names(module):
    """Escolhe o nome mais legível para cada bit do netlist."""
    best = {}
    for name, info in module["netnames"].items():
        hidden = info.get("hide_name", 0)
        width = len(info["bits"])
        for i, bit in enumerate(info["bits"]):
            if isinstance(bit, str):
                continue
            label = name if width == 1 else f"{name}[{i + info.get('offset', 0)}]"
            label = _clean(label)
            score = (hidden, label.count("."), len(label))
            if bit not in best or score < best[bit][0]:
                best[bit] = (score, label, name)
    names = {}
    used = set()
    for bit, (score, label, raw) in sorted(best.items()):
        if score[0]:
            # net interna sem nome: leva o módulo de origem (ex.: u_fa.N42)
            scope = _clean(scope_of(raw))
            label = f"{scope}.N{bit}" if scope else f"N{bit}"
        while label in used:
            label += "_"
        used.add(label)
        names[bit] = label
    return names


def load_yosys_json(path, top, lib, hier_path=None, termination=True):
    with open(path) as f:
        data = json.load(f)
    module = data["modules"][top]
    names = _bit_names(module)

    def net_of(bit):
        if bit == "1":
            return lib.vdd
        if bit in ("0", "x", "z"):
            return lib.gnd
        return names[bit]

    ports = []
    for pname, info in module["ports"].items():
        width = len(info["bits"])
        for i, bit in enumerate(info["bits"]):
            label = _clean(pname if width == 1 else f"{pname}[{i}]")
            ports.append(Port(label, info["direction"], net_of(bit)))

    design = Design(top, ports, [], lib.vdd, lib.gnd)
    design.modules = _module_types(hier_path, top)
    counters = {"ff": 0, "g": 0}
    for yname, c in sorted(module["cells"].items()):
        ctype = c["type"]
        pins = {p: net_of(b[0]) for p, b in c["connections"].items()}
        if ctype == "$_TBUF_":
            # tri-state do Yosys -> driver de barramento (coletor aberto) da família
            ts = lib.tristate
            if ts is None:
                raise ValueError(f"o Verilog tem tri-state ({_clean(yname)}), mas a família "
                                 f"'{lib.name}' não tem driver de barramento")
            ctype = ts["cell"]
            pins = {ts["data"]: pins["A"], ts["enable"]: pins["E"], ts["out"]: pins["Y"]}
        if ctype not in lib.cells:
            raise ValueError(f"célula {ctype} ({yname}) não está na biblioteca — "
                             "o Yosys deixou algo sem mapear")
        if lib.cells[ctype].seq:
            counters["ff"] += 1
            inst = f"FF{counters['ff']}"
        else:
            counters["g"] += 1
            inst = f"U{counters['g']}"
        design.instances[inst] = (ctype, _clean(yname))
        design.conns[inst] = pins
        design.inst_module[inst] = _clean(scope_of(yname))
    add_termination(lib, design, termination)
    elaborate(lib, design)
    return design


def drivers_by_net(lib, design):
    """net -> [(instância, pino)] das saídas de células ligadas a ela."""
    out = {}
    for inst, (cell, _) in design.instances.items():
        for pin in lib.cells[cell].outputs:
            net = design.conns[inst].get(pin)
            if net is not None and net not in (design.vdd, design.gnd):
                out.setdefault(net, []).append((inst, pin))
    return out


def add_termination(lib, design, termination=True):
    """Confere quem dirige cada net e põe a terminação de barramento da família
    (BT1, BT2...; na RTL, um pull-up) nas linhas de barramento: nets dirigidas
    por drivers tri-state e portas inout sem outro driver. Várias saídas numa
    net só valem se forem todas de drivers de barramento.

    As linhas que não saem da placa sempre ganham a terminação. As que saem
    (portas inout) dependem de termination: True em todas, False em nenhuma, ou
    uma lista de portas (como nos pinos dos conectores): numa pilha de placas,
    cada linha tem a terminação numa placa só.

    A terminação vai para o módulo que contém todos os drivers da linha, com um
    nome tirado do primeiro deles: as cópias de um macro ganham a mesma."""
    inputs = {p.net for p in design.ports if p.direction == "input"}
    bus = []
    drivers = drivers_by_net(lib, design)
    for net, drv in sorted(drivers.items()):
        cells = {design.instances[i][0] for i, _ in drv}
        open_ = all(lib.is_bus_cell(c) for c in cells)
        if len(drv) > 1 and not open_:
            raise ValueError(f"net {net} dirigida por várias saídas ("
                             + ", ".join(f"{i} {design.instances[i][0]}.{p}" for i, p in drv)
                             + "): só drivers de barramento (tri-state) podem dividir uma net")
        if open_:
            if net in inputs:
                raise ValueError(f"net {net}: barramento ligado a uma entrada do topo")
            bus.append((net, drv))
    # porta inout sem driver nesta placa: é uma linha do barramento da pilha
    # que a placa só lê (ou na qual só põe a terminação)
    for p in design.ports:
        if (p.direction == "inout" and p.net not in drivers and p.net not in (design.vdd, design.gnd)
                and all(n != p.net for n, _ in bus)):
            bus.append((p.net, []))
    port_net = {p.name: p.net for p in design.ports if p.direction == "inout"}
    if isinstance(termination, (list, tuple)):
        from .connectors import select_ports
        lines = {n for n, _ in bus}
        chosen = set()
        for name in select_ports(design.ports, termination, "bus_termination"):
            if name not in port_net or port_net[name] not in lines:
                raise ValueError(f"bus_termination: '{name}' não é uma linha de barramento que sai da "
                                 "placa (porta inout de um barramento tri-state)")
            chosen.add(port_net[name])
    else:
        chosen = set(port_net.values()) if termination else set()
    outside = set(port_net.values())
    bus = [(n, d) for n, d in bus if n not in outside or n in chosen]
    if not bus:
        return
    if lib.terminator is None:
        raise ValueError(f"a família '{lib.name}' não tem célula de terminação de barramento")
    cell, pin = lib.terminator["cell"], lib.terminator["pin"]
    for k, (net, drv) in enumerate(bus, 1):
        if drv:
            mod = common_module([design.inst_module.get(i, "") for i, _ in drv])
            first = min(drv, key=lambda d: design.instances[d[0]][1])[0]
            depth = len(mod.split(".")) if mod else 0
            local = "/".join(design.instances[first][1].split(".")[depth:])
        else:
            mod, local = "", net
        inst = f"BT{k}"
        design.instances[inst] = (cell, (f"{mod}." if mod else "") + f"$busterm${local}")
        design.conns[inst] = {pin: net}
        design.inst_module[inst] = mod


def common_module(paths):
    """Ancestral comum de caminhos de módulo ('' = topo)."""
    split = [p.split(".") if p else [] for p in paths]
    out = []
    for parts in zip(*split):
        if len(set(parts)) != 1:
            break
        out.append(parts[0])
    return ".".join(out)


def elaborate(lib, design):
    """(Re)expande as instâncias lógicas em blocos de componentes."""
    design.blocks = []
    for inst, (cell, _) in design.instances.items():
        first = len(design.blocks)
        expand(lib, design, cell, inst, design.conns[inst], inst, cell)
        for b in design.blocks[first:]:
            b.module = design.inst_module.get(inst, "")


def expand(lib, design, subckt, inst, pinmap, group, group_cell):
    """Achata o subcircuito: componentes viram um Block; instâncias X recursam."""
    sub = lib.subckts[subckt]
    supplies = {lib.vdd: lib.vdd, lib.gnd: lib.gnd, "0": lib.gnd}

    def net(node):
        if node in pinmap:
            return pinmap[node]
        if node in supplies:
            return supplies[node]
        return f"{inst}.{node}"

    pinmap = dict(pinmap)
    for pin in sub.pins:
        if pin not in pinmap:
            pinmap[pin] = supplies.get(pin, f"{inst}.{pin}")
    if sub.devices:
        outs = [pinmap[o] for o in lib.outputs_of(subckt)]
        ins = [pinmap[p] for p in sub.pins
               if p not in supplies and pinmap[p] not in outs and p not in lib.outputs_of(subckt)]
        block = Block(inst, subckt, {p: pinmap[p] for p in sub.pins if p not in supplies},
                      outs, ins, group, group_cell)
        for el in sub.devices:
            part = lib.part(el)
            roles = {r: net(n) for r, n in lib.element_roles(el).items()}
            block.parts.append(Part("", el.name, el.model, el.value or part.get("part", el.model),
                                    roles, block))
        design.blocks.append(block)
    for x in sub.instances:
        child = lib.subckts[x.model]
        cmap = {cp: net(n) for cp, n in zip(child.pins, x.nodes)}
        expand(lib, design, x.model, f"{inst}.{x.name}", cmap, group, group_cell)


# --------------------------------------------------------- simulação switch
SIM_PRIMITIVE = {
    "nmos": ("nmos", "D", "S", "G"),
    "pmos": ("pmos", "D", "S", "G"),
    "npn": ("nmos", "C", "E", "B"),     # NPN saturado como chave para GND
    "pnp": ("pmos", "C", "E", "B"),
    "tube": ("nmos", "P", "K", "G"),    # Válvula a vácuo: grade G positiva conduz placa P para o catodo K
}


def write_switch_level_verilog(lib, design, path, module_name=None):
    """Netlist em nível de componente, com a mesma interface do módulo original:
    o testbench RTL roda contra exatamente o circuito que vai para a PCB.
    Transistores viram as primitivas nmos/pmos do Verilog e resistores viram
    rtran (conexão resistiva: um transistor conduzindo vence o pull-up)."""
    by_port = {}
    for p in design.ports:
        base = p.name.split("[")[0]
        by_port.setdefault(base, []).append(p)

    def ident(net):
        # prefixo evita colisão com os nomes das portas (\cin == cin em Verilog)
        return "\\n:" + net + " "

    lines = [f"// Netlist de componentes de '{design.top}' gerado pelo fr4lane", "`timescale 1ns/1ps"]
    lines.append(f"module {module_name or design.top} ({', '.join(by_port)});")
    for base, bits in by_port.items():
        w = f"[{len(bits) - 1}:0] " if len(bits) > 1 or "[" in bits[0].name else ""
        lines.append(f"  {bits[0].direction} {w}{base};")
    lines.append(f"  supply1 {ident(design.vdd)};")
    lines.append(f"  supply0 {ident(design.gnd)};")
    for n in sorted(design.nets() - {design.vdd, design.gnd}):
        lines.append(f"  wire {ident(n)};")
    # Porta inout (barramento que sai da placa): ligação bidirecional (tran),
    # para os drivers das outras placas da pilha chegarem às cargas desta e vice-versa.
    direct = {p.net for p in design.ports if p.direction == "inout"} - {design.vdd, design.gnd}
    for p in design.ports:
        if p.direction == "input":
            if p.net not in (design.vdd, design.gnd):
                lines.append(f"  assign {ident(p.net)} = {_port_ref(p)};")
        elif p.direction == "inout":
            lines.append(f"  tran {ident('$io.' + p.name)}({_port_ref(p)}, {ident(p.net)});")
        else:
            lines.append(f"  assign {_port_ref(p)} = {ident(p.net)};")
    # As redes de componentes são avaliadas sem atraso e cada saída de bloco
    # passa por um atraso de TRANSPORTE pequeno. Com atraso inercial (nas
    # primitivas ou num assign #d) um glitch X de tempo zero fica preso na
    # saída no Icarus; sem atraso nenhum os latches dos flip-flops entram em corrida.
    # Num barramento, os drivers e a terminação ligam ao mesmo nó $raw: o
    # transistor que conduz (forte) vence a terminação (rtran, fraca). Num
    # barramento que sai pela porta inout, ligam direto na net (sem o atraso):
    # o nó é o mesmo em todas as placas, e um atraso só desta placa não o representa.
    driven = {}
    for b in design.blocks:
        for out in b.outputs:
            if out in driven:
                if not (lib.is_bus_cell(b.cell) and lib.is_bus_cell(driven[out][1])):
                    raise ValueError(f"net {out} dirigida por {driven[out][0]} e {b.name}")
                continue
            driven[out] = (b.name, b.cell)
            if out in direct:
                continue
            raw, dly = ident(out + "$raw"), ident(out + "$d")
            lines.append(f"  wire {raw};")
            lines.append(f"  reg {dly};")
            lines.append(f"  always @({raw}) {dly} <= #0.01 {raw};")
            lines.append(f"  assign {ident(out)} = {dly};")
    # Contato de relé que passa uma ENTRADA do bloco adiante (XOR, MUX, latch):
    # na simulação ela entra por um buffer. Com a bobina em X a chave conduz
    # "talvez" e o Icarus deixaria o X voltar pela entrada até quem a dirige,
    # o que pode travar um laço (latch -> XOR -> entrada do latch) em X. No relé
    # real o contato abre antes de fechar e a entrada não é dirigida de volta.
    # Um buffer por bloco: um bloco não contamina os outros que leem a mesma net.
    for b in design.blocks:
        outs = set(b.outputs)
        ins = set()
        for p in b.parts:
            if lib.parts[p.model]["kind"] == "relay":
                ins |= {p.pins[r] for r in ("COM", "NO", "NC")
                        if p.pins[r] in b.inputs and p.pins[r] not in (design.vdd, design.gnd)}
        for n in sorted(ins):
            lines.append(f"  wire {ident(f'{n}$in.{b.name}')};")
            lines.append(f"  assign {ident(f'{n}$in.{b.name}')} = {ident(n)};")
        for p in b.parts:
            kind = lib.parts[p.model]["kind"]
            pins = {r: (n + "$raw" if n in outs and n not in direct and r not in CONTROL_ROLES else n)
                    for r, n in p.pins.items()}
            if kind == "relay":
                pins.update({r: f"{pins[r]}$in.{b.name}" for r in ("COM", "NO", "NC") if pins[r] in ins})
            inst = ident(f"{b.name}.{p.name}")
            if kind in SIM_PRIMITIVE:
                prim, o, i, c = SIM_PRIMITIVE[kind]
                lines.append(f"  {prim} {inst}({ident(pins[o])}, {ident(pins[i])}, {ident(pins[c])});")
            elif kind == "resistor":
                lines.append(f"  rtran {inst}({ident(pins['1'])}, {ident(pins['2'])});")
            elif kind == "relay":
                # contato bidirecional comandado pela bobina: fecha COM-NO energizado, COM-NC solto.
                # Como no relé real, só uma bobina em 1 puxa o contato; em X ou Z (início da
                # simulação, nada dirigindo) ele fica em repouso. Com o X direto no tranif o
                # resultado dependeria da versão do Icarus (a 12 prende laços de flip-flop em X).
                c = ident(f"{b.name}.{p.name}.coil")
                lines.append(f"  wire {c} = ({ident(pins['C1'])} === 1'b1);")
                lines.append(f"  tranif1 {ident(f'{b.name}.{p.name}.no')}({ident(pins['COM'])}, {ident(pins['NO'])}, {c});")
                lines.append(f"  tranif0 {ident(f'{b.name}.{p.name}.nc')}({ident(pins['COM'])}, {ident(pins['NC'])}, {c});")
            elif kind == "core":
                # núcleo de ferrite (CTL/CDL): soma de fluxo magnético dos enrolamentos W1 (+1), W2 (+1) e WB (-1).
                # Quando a FMM líquida >= 1 unidade de corrente coerciva, o núcleo comuta e excita a saída S.
                w1 = f"({ident(pins['W1'])} === 1'b1 ? 1 : 0)"
                w2 = f"({ident(pins['W2'])} === 1'b1 ? 1 : 0)"
                wb = f"({ident(pins['WB'])} === 1'b1 ? 1 : 0)"
                c = ident(f"{b.name}.{p.name}.set")
                lines.append(f"  wire {c} = (({w1} + {w2} - {wb}) >= 1);")
                lines.append(f"  assign {ident(pins['S'])} = {c} ? 1'b1 : 1'bz;")
                lines.append(f"  pulldown ({ident(pins['S'])});")
            elif kind == "diode":
                # diodo retificador/lógico (CDL/DTL):
                # - se o catodo K é entrada do bloco (porta E a diodos da DTL, D1 d1 A), K=0 puxa o anodo A a 0;
                # - se o catodo K é nó interno (porta OU a diodos na CDL/DTL ou diodo de level-shift DS), A=1 conduz 1 para K;
                # - se o anodo A está no GND (diodo de supressão da bobina nos relés), fica sempre reverso.
                if pins["A"] != design.gnd:
                    a_net, k_net = ident(pins["A"]), ident(pins["K"])
                    if pins["K"] in b.inputs:
                        lines.append(f"  assign (strong0, highz1) {a_net} = ({k_net} === 1'b0) ? 1'b0 : 1'bz;")
                    else:
                        lines.append(f"  assign (highz0, strong1) {k_net} = ({a_net} === 1'b1) ? 1'b1 : 1'bz;")
            # capacitores de desacoplamento não afetam a lógica
    lines.append("endmodule")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def _port_ref(p):
    if "[" in p.name:
        base, idx = p.name.split("[")
        return f"{base}[{idx}"
    return p.name
