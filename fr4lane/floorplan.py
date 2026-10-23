"""Restrições de floorplan: posição absoluta (mm) dos módulos e áreas proibidas.

Arquivo JSON (coordenadas em mm a partir do canto superior esquerdo da placa;
retângulos como [x, y, largura, altura]):

  {
    "board":   {"width": 160, "height": 120},              opcional
    "modules": {
      "u_fa":   {"type": "fence",  "rect": [20, 10, 60, 40], "decoupling": true},
      "u_mux4": {"type": "region", "rect": [90, 10, 50, 40]},
      "u_dff":  {"type": "guide",  "near": [30, 90]}        ou "rect"
    },
    "keepouts": [
      {"name": "furo", "rect": [0, 0, 8, 8], "what": ["place", "route"],
       "layers": ["F.Cu", "B.Cu"]}                          layers opcional
    ]
  }

Tipos (os mesmos das ferramentas de chip; no Altium seriam "rooms"):
  fence   os componentes do módulo ficam dentro e nenhum outro entra;
  region  os componentes do módulo ficam dentro, mas outros podem entrar;
  guide   preferência: o anelamento paga um custo quando o módulo sai da área.
Keepout: "place" proíbe componentes; "route" proíbe trilhas e vias nas camadas
dadas. As restrições de módulo valem só para o posicionamento — fios de
outros módulos podem atravessar uma fence; para impedir, use um keepout.

Densidade: uma fence/region espalha o módulo pela área toda, e a densidade
dela é calculada (o que o módulo precisa / o que a área oferece): o tamanho
da área é o controle. "density" (0 a 1, só fence/region) é um ajuste
avançado: com valor acima da calculada, o módulo se agrupa até essa ocupação
onde a fiação o puxa; 1 encosta tudo à esquerda e em cima.

Desacoplamento: as fileiras livres (fora das áreas) levam um capacitor de
desacoplamento cada, mesmo quando uma área as corta em vários trechos — o
trilho de alimentação é o mesmo. Dentro de uma fence/region não há
capacitor, a não ser com "decoupling": true (um no fim de cada trecho da
área).

Macros: "macros": ["adder", ...] lista tipos de módulo (os nomes do Verilog)
implementados à parte, uma vez por estrutura, e copiados em cada instância
(hier.py). Uma fence/region com o caminho de uma instância de macro diz onde
ela fica; sem isso, o macro vai para dentro da área do módulo que o contém ou,
sem nenhuma, para uma faixa abaixo das áreas declaradas (sem floorplan: o alto
da placa).
"macro_keepout": true proíbe as trilhas e vias de fora (as do roteamento de
cima e as do macro que contém outro) no retângulo de cada macro: elas só
chegam aos pinos, pela borda. Sem ele, o espaço livre de dentro do macro fica
disponível para as rotas de fora.
"macro_channel": 4 é a largura (mm) do canal livre em volta de cada macro
(padrão 1,5): entre dois macros vizinhos ficam dois canais. Mais largo, mais
espaço para as rotas que passam entre eles, sobretudo com "macro_keepout".

Barramentos: "bus_termination" diz em quais linhas de barramento que saem
da placa (portas inout) ela põe a terminação (na família RTL, o pull-up):
true (padrão) em todas, false em nenhuma, ou uma lista de portas no formato
dos pinos dos conectores ("bus_a", "bus_b[3:0]", "ack"). Numa pilha de placas,
cada linha tem a terminação numa placa só (veja system.py). As linhas de
barramento que não saem da placa sempre têm a terminação nela.
"buffer_ports": true põe um buffer na entrada de cada porta de entrada e
inout (a placa pesa uma carga só em cada linha da pilha); uma lista de portas
limita os buffers a elas.

Conectores: "connectors" fixa a borda, a posição e a pinagem das barras de
pinos de E/S (o que permite casar os conectores de placas vizinhas):

    "connectors": [
      {"name": "J_IN", "side": "left", "at": 20.32, "pins": ["VDD", "GND", "a[*]", "b[7:0]"]},
      {"name": "J_OP", "side": "top",  "pins": ["op[3:0]", "NC", "GND"]}
    ]

  side   left, right, top ou bottom;
  at     posição do pino 1 em mm: da borda de cima da placa (left/right) ou da
         esquerda (top/bottom); sem ele, o conector entra depois dos outros da
         mesma borda;
  pins   a ordem física dos pinos (até 40): portas do topo ("ci", "a[3]"), um
         barramento inteiro ("a[*]", do bit 0 para cima), uma faixa ("a[7:0]",
         na ordem escrita), "VDD", "GND" ou "NC" (pino sem ligação).
As portas que nenhum conector lista vão para os conectores automáticos: as
entradas na borda esquerda e as saídas na direita (connectors.py).

Módulos são caminhos de instância (u_fa, u0.u2), os mesmos do report.md. Um
caminho vale para todos os submódulos dele; se um submódulo também tiver
regra, vale a mais específica.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

TYPES = ("fence", "region", "guide")
WHAT = ("place", "route")
LAYERS = ("F.Cu", "B.Cu")
SIDES = ("left", "right", "top", "bottom")
MAX_PINS = 40          # maior barra de pinos 1xN da biblioteca do KiCad
CONNECTOR_TYPES = ("pin_header", "pin_socket", "card_edge", "screw_terminal", "idc_box_header", "din41612")


class FloorplanError(Exception):
    pass


@dataclass
class ModuleRule:
    path: str
    type: str
    rect: tuple            # (x0, y0, x1, y1) em mm
    density: float = None  # ocupação-alvo das fileiras (None = calculada: espalha pela área)
    decoupling: bool = False  # capacitor de desacoplamento em cada trecho da área


@dataclass
class Keepout:
    name: str
    rect: tuple            # (x0, y0, x1, y1)
    place: bool
    route: bool
    layers: tuple


@dataclass
class MountingHoleRule:
    ref: str
    x: float
    y: float
    size: str = "M3"


@dataclass
class Connector:
    name: str
    side: str              # left | right | top | bottom
    at: float              # posição do pino 1 ao longo da borda (mm), ou None (automático)
    pins: list             # textos do arquivo: portas, barramentos, VDD, GND, NC
    type: str = "pin_header" # pin_header | pin_socket | card_edge | screw_terminal | idc_box_header | din41612
    pitch: float = 2.54


@dataclass
class Floorplan:
    source: str
    board: tuple = None                        # (largura, altura) ou None (automático)
    modules: dict = field(default_factory=dict)   # caminho -> ModuleRule
    keepouts: list = field(default_factory=list)
    macros: list = field(default_factory=list)    # tipos de módulo implementados como macro
    macro_keepout: bool = False                    # nenhuma rota de fora por cima dos macros
    macro_channel: float = None                    # canal em volta de cada macro, mm (None: o padrão)
    connectors: list = field(default_factory=list)  # Connector, na ordem do arquivo
    mounting_holes: list = field(default_factory=list) # MountingHoleRule
    bus_termination: object = True             # True, False ou [portas]: terminação das linhas que saem
    buffer_ports: object = False               # True, False ou [portas]: buffer na entrada das portas

    def rule_of(self, module_path):
        """Regra mais específica que vale para um caminho de módulo (ou None)."""
        best = None
        for path, rule in self.modules.items():
            if module_path == path or module_path.startswith(path + "."):
                if best is None or len(path) > len(best.path):
                    best = rule
        return best


def overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def contains(outer, inner):
    return outer[0] <= inner[0] and outer[1] <= inner[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def _rect(v, where):
    if (not isinstance(v, (list, tuple)) or len(v) != 4
            or not all(isinstance(x, (int, float)) for x in v)):
        raise FloorplanError(f"{where}: 'rect' deve ser [x, y, largura, altura] em mm")
    x, y, w, h = map(float, v)
    if w <= 0 or h <= 0 or x < 0 or y < 0:
        raise FloorplanError(f"{where}: retângulo {v} com largura/altura <= 0 ou coordenada negativa")
    return (x, y, x + w, y + h)


def _keys(d, allowed, where):
    extra = set(d) - set(allowed)
    if extra:
        raise FloorplanError(f"{where}: chave(s) desconhecida(s) {sorted(extra)} (aceitas: {', '.join(allowed)})")


def load(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise FloorplanError(f"{path}: {e}") from None
    return parse(data, path)


def _num(v, what, where):
    try:
        return float(v)
    except (TypeError, ValueError):
        raise FloorplanError(f"{where}: '{what}' deve ser um número (mm)") from None


def _density(v, where):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 < v <= 1:
        raise FloorplanError(f"{where}: 'density' deve ser um número de 0 (exclusive) a 1")
    return float(v)


def _ports_option(data, key, default, path):
    """true, false ou uma lista de portas (como nos pinos dos conectores)."""
    v = data.get(key, default)
    if isinstance(v, bool):
        return v
    if isinstance(v, list) and v and all(isinstance(x, str) and x.strip() for x in v):
        return [x.strip() for x in v]
    raise FloorplanError(f"{path}: '{key}' deve ser true, false ou uma lista de portas "
                         "(ex.: [\"bus\", \"mar[3:0]\"])")


def parse(data, path="floorplan"):
    """Valida um floorplan já lido do JSON (path só aparece nas mensagens)."""
    if not isinstance(data, dict):
        raise FloorplanError(f"{path}: esperado um objeto JSON")
    _keys(data, ("board", "modules", "keepouts", "macros", "macro_keepout", "macro_channel", "connectors",
                 "mounting_holes", "bus_termination", "buffer_ports", "_comment"), path)
    fp = Floorplan(str(path))
    macros = data.get("macros", [])
    if not isinstance(macros, list) or not all(isinstance(m, str) and m for m in macros):
        raise FloorplanError(f"{path}: 'macros' deve ser uma lista de tipos de módulo (ex.: [\"adder\"])")
    fp.macros = list(macros)
    if not isinstance(data.get("macro_keepout", False), bool):
        raise FloorplanError(f"{path}: 'macro_keepout' deve ser true ou false")
    fp.macro_keepout = data.get("macro_keepout", False)
    if "macro_channel" in data:
        v = data["macro_channel"]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0.5 <= v <= 50:
            raise FloorplanError(f"{path}: 'macro_channel' deve ser a largura do canal em mm, de 0,5 a 50")
        fp.macro_channel = float(v)
    fp.bus_termination = _ports_option(data, "bus_termination", True, path)
    fp.buffer_ports = _ports_option(data, "buffer_ports", False, path)

    if "board" in data:
        b = data["board"]
        if not isinstance(b, dict):
            raise FloorplanError(f"{path}: 'board' deve ser {{\"width\": ..., \"height\": ...}}")
        _keys(b, ("width", "height"), f"{path}: board")
        try:
            fp.board = (float(b["width"]), float(b["height"]))
        except (KeyError, TypeError, ValueError):
            raise FloorplanError(f"{path}: 'board' precisa de 'width' e 'height' numéricos (mm)") from None
        if fp.board[0] <= 0 or fp.board[1] <= 0:
            raise FloorplanError(f"{path}: 'board' com largura/altura <= 0")

    modules = data.get("modules", {})
    if not isinstance(modules, dict):
        raise FloorplanError(f"{path}: 'modules' deve ser um objeto {{\"caminho\": {{...}}}}")
    keepouts = data.get("keepouts", [])
    if not isinstance(keepouts, list):
        raise FloorplanError(f"{path}: 'keepouts' deve ser uma lista")
    for name, m in modules.items():
        where = f"{path}: módulo '{name}'"
        if not isinstance(m, dict):
            raise FloorplanError(f"{where}: esperado um objeto")
        _keys(m, ("type", "rect", "near", "density", "decoupling", "_comment"), where)
        t = m.get("type")
        if t not in TYPES:
            raise FloorplanError(f"{where}: 'type' deve ser {', '.join(TYPES)}")
        if "near" in m:
            if t != "guide":
                raise FloorplanError(f"{where}: 'near' só vale para 'guide'; {t} precisa de 'rect'")
            p = m["near"]
            if not (isinstance(p, (list, tuple)) and len(p) == 2):
                raise FloorplanError(f"{where}: 'near' deve ser [x, y] em mm")
            x, y = _num(p[0], "near", where), _num(p[1], "near", where)
            rect = (x, y, x, y)
        elif "rect" in m:
            rect = _rect(m["rect"], where)
        else:
            raise FloorplanError(f"{where}: falta 'rect'")
        density = None
        if "density" in m:
            if t == "guide":
                raise FloorplanError(f"{where}: 'density' só vale para fence e region")
            density = _density(m["density"], where)
        decoupling = m.get("decoupling", False)
        if not isinstance(decoupling, bool):
            raise FloorplanError(f"{where}: 'decoupling' deve ser true ou false")
        if decoupling and t == "guide":
            raise FloorplanError(f"{where}: 'decoupling' só vale para fence e region")
        fp.modules[name] = ModuleRule(name, t, rect, density, decoupling)

    for i, k in enumerate(keepouts):
        name = k.get("name", f"keepout{i + 1}") if isinstance(k, dict) else ""
        where = f"{path}: keepout '{name}'"
        if not isinstance(k, dict):
            raise FloorplanError(f"{path}: keepout {i + 1}: esperado um objeto")
        _keys(k, ("name", "rect", "what", "layers", "_comment"), where)
        what = k.get("what", ["place", "route"])
        if not isinstance(what, list) or not what or any(w not in WHAT for w in what):
            raise FloorplanError(f"{where}: 'what' deve conter 'place' e/ou 'route'")
        layers = k.get("layers", LAYERS)
        layers = tuple(layers) if isinstance(layers, (list, tuple)) else ()
        if not layers or any(l not in LAYERS for l in layers):
            raise FloorplanError(f"{where}: 'layers' deve conter 'F.Cu' e/ou 'B.Cu'")
        fp.keepouts.append(Keepout(name, _rect(k.get("rect"), where), "place" in what, "route" in what, layers))

    holes = data.get("mounting_holes", [])
    if not isinstance(holes, list):
        raise FloorplanError(f"{path}: 'mounting_holes' deve ser uma lista")
    for i, h in enumerate(holes):
        where = f"{path}: mounting_hole {i + 1}"
        if isinstance(h, dict):
            _keys(h, ("ref", "x", "y", "at", "size", "_comment"), where)
            ref = h.get("ref", f"H{i+1}")
            size = h.get("size", "M3")
            if "at" in h:
                at = h["at"]
                if not isinstance(at, (list, tuple)) or len(at) != 2:
                    raise FloorplanError(f"{where}: 'at' deve ser [x, y] em mm")
                x, y = map(float, at)
            elif "x" in h and "y" in h:
                x, y = float(h["x"]), float(h["y"])
            else:
                raise FloorplanError(f"{where}: esperado 'at': [x, y] ou 'x' e 'y'")
            fp.mounting_holes.append(MountingHoleRule(ref, x, y, size))
        elif isinstance(h, (list, tuple)) and len(h) == 2:
            fp.mounting_holes.append(MountingHoleRule(f"H{i+1}", float(h[0]), float(h[1]), "M3"))
        else:
            raise FloorplanError(f"{where}: esperado objeto ou [x, y]")

    conns = data.get("connectors", [])
    if not isinstance(conns, list):
        raise FloorplanError(f"{path}: 'connectors' deve ser uma lista")
    names = set()
    for i, c in enumerate(conns):
        if not isinstance(c, dict):
            raise FloorplanError(f"{path}: conector {i + 1}: esperado um objeto")
        name = c.get("name")
        where = f"{path}: conector '{name}'" if name else f"{path}: conector {i + 1}"
        _keys(c, ("name", "side", "at", "pins", "type", "pitch", "_comment"), where)
        if not isinstance(name, str) or not name.strip():
            raise FloorplanError(f"{where}: falta 'name'")
        if name in names:
            raise FloorplanError(f"{where}: nome repetido")
        names.add(name)
        if c.get("side") not in SIDES:
            raise FloorplanError(f"{where}: 'side' deve ser {', '.join(SIDES)}")
        at = c.get("at")
        if at is not None:
            at = _num(at, "at", where)
            if at < 0:
                raise FloorplanError(f"{where}: 'at' não pode ser negativo")
        conn_type = c.get("type", "pin_header")
        if conn_type not in CONNECTOR_TYPES:
            raise FloorplanError(f"{where}: 'type' inválido '{conn_type}' (aceitos: {', '.join(CONNECTOR_TYPES)})")
        pitch = _num(c.get("pitch", 2.54), "pitch", where) if "pitch" in c else 2.54
        pins = c.get("pins")
        if not isinstance(pins, list) or not pins or not all(isinstance(x, str) and x.strip() for x in pins):
            raise FloorplanError(f"{where}: 'pins' deve ser uma lista de textos (portas, \"a[*]\", "
                                 "\"VDD\", \"GND\", \"NC\")")
        fp.connectors.append(Connector(name, c["side"], at, [x.strip() for x in pins], type=conn_type, pitch=pitch))

    # áreas obrigatórias não podem se sobrepor (a não ser um submódulo dentro do pai)
    hard = [r for r in fp.modules.values() if r.type in ("fence", "region")]
    for i, a in enumerate(hard):
        for b in hard[i + 1:]:
            nested = a.path.startswith(b.path + ".") or b.path.startswith(a.path + ".")
            if overlap(a.rect, b.rect) and not nested:
                raise FloorplanError(f"{path}: as áreas de '{a.path}' ({a.type}) e '{b.path}' ({b.type}) "
                                     "se sobrepõem")
    if fp.board:
        W, H = fp.board
        for r in list(fp.modules.values()) + fp.keepouts:
            if r.rect[2] > W or r.rect[3] > H:
                what = f"módulo '{r.path}'" if isinstance(r, ModuleRule) else f"keepout '{r.name}'"
                raise FloorplanError(f"{path}: {what} sai da placa de {W:g} x {H:g} mm")
    return fp
