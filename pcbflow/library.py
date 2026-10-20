"""Biblioteca de células de uma família (pasta pcbflow/lib/<família>/).

  library.json            dados gerais (alimentação, cabeçalho Liberty, desacoplamento)
  parts.json              componentes reais: modelo SPICE -> peça, footprint, pinagem
  cells/<CELULA>/
      <CELULA>.lib        o que a célula faz (Liberty) — é o que o Yosys vê
      <CELULA>.sp         como a célula é montada (.subckt SPICE)
      <CELULA>.json       metadados (descrição, layout, max_fanout, dont_use, variant_of...)

Uma pasta sem .lib é um subcircuito auxiliar: pode ser usado por outras
células (X...), mas não é oferecido ao Yosys.

Variantes: uma célula com "variant_of": "<BASE>" faz a mesma função da base
com outra montagem (resistores maiores, saídas duplicadas, buffers...). O
Yosys só vê a base; depois da síntese o pcbflow troca cada instância pela
variante mais econômica que ainda alimenta as suas cargas (sizing.py). Uma
variante pode ter várias saídas para uma saída da base, cada uma com uma parte
das cargas: "outputs": {"Y": ["Y0", "Y1"]}.

Barramentos (tri-state): os papéis vêm do atributo driver_type do Liberty.
  driver     saída com three_state e driver_type open_drain (só força o 0:
             coletor ou dreno aberto) ou open_source (só força o 1), ex.:
             function "A", three_state "!E", driver_type open_drain;
  terminação célula sem entradas com driver_type pull_up (function "1") ou
             pull_down (function "0"): segura a linha no nível que o driver
             não força (na família RTL, um resistor de 1k para o VDD).
O Yosys mapeia cada "assign bus = en ? d : 'z" para $_TBUF_; o pcbflow troca
cada um pelo driver da família e põe a terminação em cada linha de barramento
(netlist.py). As duas células ficam fora da síntese do ABC.
"""

import json
from pathlib import Path

from . import liberty, spice

# terminais lógicos de cada tipo de componente, na ordem dos nós no SPICE
KIND_ROLES = {
    "nmos": ("D", "G", "S"),
    "pmos": ("D", "G", "S"),
    "npn": ("C", "B", "E"),
    "pnp": ("C", "B", "E"),
    "resistor": ("1", "2"),
    "capacitor": ("1", "2"),
    # relé SPDT: bobina C1 (+) e C2 (no GND); contato comum, normalmente aberto, normalmente fechado
    "relay": ("C1", "C2", "COM", "NO", "NC"),
    "diode": ("A", "K"),
}
SPICE_LETTER = {"nmos": "M", "pmos": "M", "npn": "Q", "pnp": "Q", "resistor": "R", "capacitor": "C",
                "relay": "K", "diode": "D"}
CONTROL_ROLES = {"G", "B", "C1", "C2"}
KIND_ROW = {"pmos": 0, "pnp": 0, "resistor": 1, "capacitor": 1, "diode": 1, "nmos": 2, "npn": 2, "relay": 2}
PASSIVE_KINDS = ("resistor", "capacitor", "diode")   # não dirigem a saída de um bloco

# driver_type do Liberty nos barramentos: o nível que o driver força e o da terminação
OPEN = {"open_drain": 0, "open_source": 1}
PULL = {"pull_up": 1, "pull_down": 0}


# famílias que vêm com o pcbflow (cmos, rtl, relay): --lib aceita o nome de uma
# delas ou o caminho da pasta de uma família própria
FAMILIES_DIR = Path(__file__).resolve().parent / "lib"


def families():
    """Nomes das famílias incluídas no pcbflow."""
    return sorted(p.name for p in FAMILIES_DIR.iterdir() if (p / "library.json").is_file())


def resolve_family(arg):
    """Pasta da família: o caminho dado (se for uma pasta de família) ou, pelo
    nome, uma das incluídas no pcbflow."""
    p = Path(arg)
    if p.is_dir() and (p / "library.json").is_file():
        return p.resolve()
    if p.is_file():
        raise LibraryError(f"{arg}: aponte para a pasta da família (ex.: rtl ou minha_familia/)")
    if (FAMILIES_DIR / str(arg) / "library.json").is_file():
        return FAMILIES_DIR / str(arg)
    raise LibraryError(f"família '{arg}' não encontrada: use o nome de uma das incluídas "
                       f"({', '.join(families())}) ou o caminho da pasta de uma família")


class LibraryError(Exception):
    pass


class Library:
    def __init__(self, path):
        self.path = resolve_family(path)          # nome de uma família incluída ou pasta
        meta = json.loads((self.path / "library.json").read_text(encoding="utf-8"))
        self.meta = meta
        self.name = meta.get("name", self.path.name)
        self.family = meta.get("family", self.path.name)
        sup = meta.get("supply", {})
        self.vdd = sup.get("vdd", "VDD")
        self.gnd = sup.get("gnd", "GND")
        self.supply_voltage = sup.get("voltage", "")
        self.placement = meta.get("placement", {})
        self.parts = json.loads((self.path / "parts.json").read_text(encoding="utf-8"))
        fp_path = (self.path / meta.get("footprints", "../footprints.json")).resolve()
        self.footprints = {k: v for k, v in json.loads(fp_path.read_text(encoding="utf-8")).items()
                           if not k.startswith("_")}
        self.subckts = {}
        self.cells = {}           # células Liberty (oferecidas ao Yosys)
        self.cell_meta = {}
        for d in sorted(p for p in (self.path / "cells").iterdir() if p.is_dir()):
            for sp in sorted(d.glob("*.sp")):
                for name, sub in spice.read_subckts(sp).items():
                    if name in self.subckts:
                        raise LibraryError(f"subcircuito {name} definido duas vezes "
                                           f"({self.subckts[name].source} e {sp})")
                    self.subckts[name] = sub
            for lf in sorted(d.glob("*.lib")):
                for c in liberty.read_cells(lf):
                    if c.name in self.cells:
                        raise LibraryError(f"célula Liberty {c.name} definida duas vezes")
                    self.cells[c.name] = c
            for jf in sorted(d.glob("*.json")):
                self.cell_meta[jf.stem] = json.loads(jf.read_text(encoding="utf-8"))
        self.variants = {}        # base -> [base, variantes...]
        for name in self.cells:
            base = self.meta_of(name).get("variant_of")
            if base:
                self.variants.setdefault(base, []).append(name)
        self.tristate = None      # driver de barramento: {"cell", "data", "enable", "out", "drives"}
        self.terminator = None    # terminação de barramento: {"cell", "pin", "level"}
        problems = self._find_bus_cells() + self.check()
        if problems:
            raise LibraryError("biblioteca inconsistente:\n  " + "\n  ".join(problems))

    # ------------------------------------------------------------ consultas
    def meta_of(self, cell):
        return self.cell_meta.get(cell, {})

    def usable(self, cell):
        """A célula é oferecida ao Yosys? (variantes nunca: entram no sizing; driver
        e terminação de barramento também não: o pcbflow os põe depois da síntese)"""
        meta = self.meta_of(cell)
        return not (meta.get("dont_use", False) or meta.get("variant_of") or self.is_bus_cell(cell))

    def is_bus_cell(self, cell):
        """Driver ou terminação de barramento: a saída pode dividir a net com
        outras dessas duas."""
        return ((self.tristate is not None and cell == self.tristate["cell"])
                or (self.terminator is not None and cell == self.terminator["cell"]))

    def _find_bus_cells(self):
        """Acha o driver (saída com three_state) e a terminação de barramento da
        família, pelo driver_type do Liberty."""
        p = []
        drivers, terms = [], []
        for name, cell in self.cells.items():
            ts = [o for o in cell.outputs if cell.pins[o].get("three_state")]
            if ts:
                drivers.append((name, ts))
            elif any(cell.pins[o].get("driver_type") in PULL for o in cell.outputs):
                terms.append(name)
        for name, ts in drivers:
            cell = self.cells[name]
            try:
                f = liberty.parse_expr(cell.pins[ts[0]]["function"] or "?")
                t = liberty.parse_expr(cell.pins[ts[0]]["three_state"])
            except liberty.LibertyError as e:
                p.append(f"{name}.lib: {e}")
                continue
            # a forma que o $_TBUF_ do Yosys tem: Y = E ? A : z, com enable ativo alto
            if (len(ts) != 1 or len(cell.outputs) != 1 or cell.seq or f[0] != "var"
                    or t[0] != "not" or t[1][0] != "var" or len(cell.inputs) != 2
                    or {f[1], t[1][1]} != set(cell.inputs)):
                p.append(f"{name}.lib: driver de barramento deve ter duas entradas e uma saída com "
                         "function \"A\" e three_state \"!E\" (enable ativo alto)")
                continue
            drives = OPEN.get(cell.pins[ts[0]].get("driver_type"))
            if drives is None:
                p.append(f"{name}.lib: o driver de barramento só força um nível na linha: declare "
                         "driver_type : open_drain (coletor ou dreno aberto, força o 0) ou open_source (força o 1)")
                continue
            if self.tristate:
                p.append(f"dois drivers de barramento: {self.tristate['cell']} e {name}")
                continue
            self.tristate = {"cell": name, "data": f[1], "enable": t[1][1], "out": ts[0], "drives": drives}
        for name in terms:
            cell = self.cells[name]
            pin = cell.outputs[0]
            level = PULL.get(cell.pins[pin]["driver_type"])
            if cell.inputs or len(cell.outputs) != 1 or cell.pins[pin]["function"].strip() != str(level):
                p.append(f"{name}.lib: a terminação de barramento não tem entradas e tem uma saída só, com "
                         "function \"1\" (driver_type : pull_up) ou \"0\" (pull_down)")
            elif self.terminator:
                p.append(f"duas células de terminação de barramento: {self.terminator['cell']} e {name}")
            else:
                self.terminator = {"cell": name, "pin": pin, "level": level}
        if self.tristate:
            want = {0: "pull_up", 1: "pull_down"}[self.tristate["drives"]]
            if not self.terminator:
                p.append(f"{self.tristate['cell']}: driver de barramento sem célula de terminação "
                         f"(uma célula sem entradas com driver_type : {want})")
            elif self.terminator["level"] == self.tristate["drives"]:
                p.append(f"{self.terminator['cell']}: a terminação deve segurar o nível que o driver "
                         f"({self.tristate['cell']}) não força: driver_type : {want}")
        return p

    def variant_group(self, base):
        """A base e as suas variantes (as que podem substituí-la depois da síntese)."""
        return [base] + self.variants.get(base, [])

    def output_map(self, cell, base_pin):
        """Saídas da célula (base ou variante) que fazem o papel da saída base_pin da base."""
        return self.meta_of(cell).get("outputs", {}).get(base_pin, [base_pin])

    def part(self, element):
        return self.parts[element.model]

    def element_roles(self, element):
        """Mapeia os nós de um elemento SPICE para os terminais lógicos do componente."""
        kind = self.part(element)["kind"]
        return dict(zip(KIND_ROLES[kind], element.nodes))

    def supplies(self):
        return {self.vdd, self.gnd}

    def outputs_of(self, subckt_name):
        """Pinos de saída de um subcircuito: do Liberty quando existe; senão,
        pinos ligados ao canal (dreno/fonte, coletor/emissor) de algum transistor."""
        if subckt_name in self.cells:
            return self.cells[subckt_name].outputs
        sub = self.subckts[subckt_name]
        outs = []
        for pin in sub.pins:
            if pin in self.supplies():
                continue
            for el in sub.devices:
                if self.part(el)["kind"] in PASSIVE_KINDS:
                    continue
                if any(n == pin and r not in CONTROL_ROLES for r, n in self.element_roles(el).items()):
                    outs.append(pin)
                    break
        return outs

    def count_parts(self, subckt_name):
        sub = self.subckts[subckt_name]
        return len(sub.devices) + sum(self.count_parts(x.model) for x in sub.instances)

    # ----------------------------------------------------------- consistência
    def check(self):
        p = []
        for key, part in self.parts.items():
            if part.get("kind") not in KIND_ROLES:
                p.append(f"parts.json: {key}: kind '{part.get('kind')}' desconhecido "
                         f"(use {', '.join(KIND_ROLES)})")
                continue
            if part.get("footprint") not in self.footprints:
                p.append(f"parts.json: {key}: footprint '{part.get('footprint')}' sem geometria em footprints.json")
                continue
            for role in KIND_ROLES[part["kind"]]:
                if role not in part.get("pins", {}):
                    p.append(f"parts.json: {key}: falta o pino '{role}' em 'pins'")
            pads = {pd["num"] for pd in self.footprints[part["footprint"]]["pads"]}
            for role, num in part.get("pins", {}).items():
                if num not in pads:
                    p.append(f"parts.json: {key}: pino {role} -> pad {num} inexistente no footprint")
        for key in self.meta.get("decoupling", {}).values():
            if key not in self.parts:
                p.append(f"library.json: decoupling usa '{key}', que não está no parts.json")
        for name, sub in self.subckts.items():
            for el in sub.elements:
                if el.letter == "X":
                    if el.model not in self.subckts:
                        p.append(f"{name}: {el.name} instancia subcircuito inexistente '{el.model}'")
                    elif len(el.nodes) != len(self.subckts[el.model].pins):
                        p.append(f"{name}: {el.name} liga {len(el.nodes)} nós, mas {el.model} tem "
                                 f"{len(self.subckts[el.model].pins)} pinos")
                    continue
                part = self.parts.get(el.model)
                if part is None:
                    p.append(f"{name}: {el.name} usa o modelo '{el.model}', que não está no parts.json")
                elif SPICE_LETTER.get(part["kind"]) != el.letter:
                    p.append(f"{name}: {el.name} é '{el.letter}' mas {el.model} é {part['kind']}")
                elif part["kind"] == "relay" and el.nodes[1] not in (self.gnd, "0"):
                    # a simulação liga o contato pela tensão de C1 (bobina do lado de C2 no GND)
                    p.append(f"{name}: {el.name}: o lado C2 da bobina deve ir ao {self.gnd}")
            rows = self.meta_of(name).get("layout", {}).get("rows")
            if rows:
                names = [n for row in rows for n in row]
                devs = {e.name for e in sub.devices}
                for n in set(names) - devs:
                    p.append(f"{name}.json: layout cita '{n}', que não é componente do .sp")
                for n in devs - set(names):
                    p.append(f"{name}.json: componente '{n}' não aparece no layout")
        for name, cell in self.cells.items():
            if name not in self.subckts:
                p.append(f"{name}.lib: não há .subckt {name} (como a célula é montada?)")
                continue
            sub_pins = set(self.subckts[name].pins) - self.supplies()
            if sub_pins != set(cell.pins):
                p.append(f"{name}: pinos do .lib {sorted(cell.pins)} != pinos do .sp {sorted(sub_pins)}")
            for pin, d in cell.pins.items():
                if d["direction"] != "output":
                    continue
                f = d["function"]
                if not f:
                    p.append(f"{name}.lib: saída {pin} sem function")
                    continue
                try:
                    ast = liberty.parse_expr(f)
                except liberty.LibertyError as e:
                    p.append(f"{name}.lib: {e}")
                    continue
                allowed = set(cell.inputs) | ({cell.seq["iq"], cell.seq["iqn"]} if cell.seq else set())
                extra = liberty.expr_vars(ast) - allowed
                if extra:
                    p.append(f"{name}.lib: function de {pin} usa {sorted(extra)}")
        for base, names in self.variants.items():
            for v in names:
                p += self._check_variant(base, v)
        return p

    def _check_variant(self, base, v):
        if base not in self.cells:
            return [f"{v}.json: variant_of '{base}', que não é uma célula com .lib"]
        if self.meta_of(base).get("variant_of"):
            return [f"{v}.json: variant_of '{base}', que já é variante de outra célula"]
        b, c = self.cells[base], self.cells[v]
        if set(b.inputs) != set(c.inputs):
            return [f"{v}: entradas {sorted(c.inputs)} != entradas da base {base} {sorted(b.inputs)}"]
        p = []
        omap = self.meta_of(v).get("outputs", {})
        for k in set(omap) - set(b.outputs):
            p.append(f"{v}.json: outputs cita '{k}', que não é saída de {base}")
        mapped = []
        for bpin in b.outputs:
            for vpin in self.output_map(v, bpin):
                mapped.append(vpin)
                if vpin not in c.pins or c.pins[vpin]["direction"] != "output":
                    p.append(f"{v}: '{vpin}' (papel de {base}.{bpin}) não é saída de {v}")
                elif not liberty.same_function(b, bpin, c, vpin):
                    p.append(f"{v}.{vpin} não faz a mesma função que {base}.{bpin}")
        for vpin in c.outputs:
            if mapped.count(vpin) != 1:
                p.append(f"{v}: a saída {vpin} deve fazer o papel de exatamente uma saída de {base} "
                         f"(use \"outputs\" no {v}.json)")
        return p

    # ------------------------------------------------------------ geração
    def write_liberty(self, path):
        out = [f"/* Gerado pelo pcbflow a partir dos .lib de {self.path.as_posix()}/cells */",
               f"library({self.name}) {{"]
        out += ["  " + l for l in self.meta.get("liberty_header", [])]
        for name, cell in self.cells.items():
            if self.usable(name):
                out.append(f"  /* {Path(cell.source).name} */")
                out.append("  " + cell.text.replace("\n", "\n  ").rstrip())
        out.append("}")
        Path(path).write_text("\n".join(out) + "\n", encoding="utf-8")

    def latch_techmap(self):
        """Mapeamento dos latches para as células latch() da biblioteca (o
        dfflibmap do Yosys só mapeia flip-flops): (tipos internos aceitos pelo
        dfflegalize, Verilog do techmap) ou None se a família não tem latch.
        Usa a célula de menor área para cada polaridade de enable; a que faltar
        o dfflegalize monta com um inversor."""
        variants = {v for names in self.variants.values() for v in names}
        best = {}
        for cell in self.cells.values():
            lt = cell.latch
            if not lt or cell.name in variants or "clear" in lt or "preset" in lt:
                continue
            en, din = liberty.parse_expr(lt["enable"]), liberty.parse_expr(lt["data_in"])
            q = [o for o in cell.outputs if cell.pins[o]["function"].strip() == lt["iq"]]
            if din[0] != "var" or not q:
                continue
            if en[0] == "var":
                kind, pin = "P", en[1]
            elif en[0] == "not" and en[1][0] == "var":
                kind, pin = "N", en[1][1]
            else:
                continue
            if kind not in best or cell.area < best[kind][0].area:
                best[kind] = (cell, pin, din[1], q[0])
        if not best:
            return None
        cells, text = [], ["// latches internos do Yosys -> células latch() da biblioteca (gerado pelo pcbflow)"]
        for kind, (cell, en, din, q) in sorted(best.items()):
            cells.append(f"$_DLATCH_{kind}_")
            text += [f"module \\$_DLATCH_{kind}_ (input E, input D, output Q);",
                     f"  {cell.name} _TECHMAP_REPLACE_ (.{en}(E), .{din}(D), .{q}(Q));",
                     "endmodule"]
        return cells, "\n".join(text) + "\n"

    def write_verilog_models(self, path):
        """Modelos comportamentais (a partir do Liberty) para a simulação gate-level."""
        out = ["// Modelos das células gerados do Liberty pelo pcbflow", "`timescale 1ns/1ps"]
        for cell in self.cells.values():
            out += self.reference_model(cell, cell.name)
        # o netlist do Yosys deixa os drivers de barramento como $_TBUF_ (veja synth.py)
        out += ["module \\$_TBUF_ (A, E, Y);", "  input A, E;", "  output Y;",
                "  assign #0.01 Y = E ? A : 1'bz;", "endmodule\n"]
        Path(path).write_text("\n".join(out) + "\n", encoding="utf-8")

    def reference_model(self, cell, module_name):
        ports = cell.inputs + cell.outputs
        out = [f"module {module_name} ({', '.join(ports)});"]
        if cell.inputs:
            out.append(f"  input {', '.join(cell.inputs)};")
        out.append(f"  output {', '.join(cell.outputs)};")
        if cell.ff:
            ff = cell.ff
            iq, iqn = ff["iq"], ff["iqn"]
            clk = liberty.to_verilog(liberty.parse_expr(ff["clocked_on"]))
            nxt = liberty.to_verilog(liberty.parse_expr(ff["next_state"]))
            out.append(f"  reg {iq};")
            out.append(f"  wire {iqn} = ~{iq};")
            out.append(f"  wire ck_ = {clk};")
            sens = ["posedge ck_"]
            body = []
            for k, val in (("clear", "1'b0"), ("preset", "1'b1")):
                if k in ff:
                    out.append(f"  wire {k}_ = {liberty.to_verilog(liberty.parse_expr(ff[k]))};")
                    sens.append(f"posedge {k}_")
                    body.append(f"if ({k}_) {iq} <= {val}; else ")
            out.append(f"  always @({' or '.join(sens)}) {''.join(body)}{iq} <= {nxt};")
        elif cell.latch:
            lt = cell.latch
            iq, iqn = lt["iq"], lt["iqn"]
            en = liberty.to_verilog(liberty.parse_expr(lt["enable"]))
            din = liberty.to_verilog(liberty.parse_expr(lt["data_in"]))
            body = []
            for k, val in (("clear", "1'b0"), ("preset", "1'b1")):
                if k in lt:
                    body.append(f"if ({liberty.to_verilog(liberty.parse_expr(lt[k]))}) {iq} = {val}; else ")
            out.append(f"  reg {iq};")
            out.append(f"  wire {iqn} = ~{iq};")
            # transparente enquanto enable = 1; com enable = 0 guarda o último valor
            out.append(f"  always @* {''.join(body)}if ({en}) {iq} = {din};")
        for o in cell.outputs:
            expr = liberty.to_verilog(liberty.parse_expr(cell.pins[o]["function"]))
            if cell.pins[o].get("driver_type") in PULL and not cell.pins[o].get("three_state"):
                # fraco: perde para o driver que força o outro nível
                out.append(f"  {'pullup' if PULL[cell.pins[o]['driver_type']] else 'pulldown'} ({o});")
            elif cell.pins[o].get("three_state"):
                off = liberty.to_verilog(liberty.parse_expr(cell.pins[o]["three_state"]))
                out.append(f"  assign #0.01 {o} = {off} ? 1'bz : {expr};")
            else:
                out.append(f"  assign #0.01 {o} = {expr};")
        out.append("endmodule\n")
        return out

    # ------------------------------------------------------------- layout
    def block_layout(self, subckt_name, part_gap):
        """Posição de cada componente dentro do bloco (origem do footprint,
        relativa ao canto superior esquerdo) e o tamanho do bloco."""
        sub = self.subckts[subckt_name]
        devs = {e.name: e for e in sub.devices}
        rows = self.meta_of(subckt_name).get("layout", {}).get("rows")
        if not rows:
            by = {}
            for e in sub.devices:
                by.setdefault(KIND_ROW[self.part(e)["kind"]], []).append(e.name)
            rows = [by[k] for k in sorted(by)]
        pos = {}
        y = 0.0
        width = 0.0
        for row in rows:
            geo = [self.footprints[self.part(devs[n])["footprint"]]["courtyard"] for n in row]
            h = max(c[3] - c[1] for c in geo)
            x = 0.0
            for n, c in zip(row, geo):
                pos[n] = (x - c[0], y + h / 2 - (c[1] + c[3]) / 2)
                x += (c[2] - c[0]) + part_gap
            width = max(width, x - part_gap)
            y += h + part_gap
        return pos, width, y - part_gap
