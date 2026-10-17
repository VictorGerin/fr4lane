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
class Floorplan:
    source: str
    board: tuple = None                        # (largura, altura) ou None (automático)
    modules: dict = field(default_factory=dict)   # caminho -> ModuleRule
    keepouts: list = field(default_factory=list)

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


def parse(data, path="floorplan"):
    """Valida um floorplan já lido do JSON (path só aparece nas mensagens)."""
    if not isinstance(data, dict):
        raise FloorplanError(f"{path}: esperado um objeto JSON")
    _keys(data, ("board", "modules", "keepouts", "_comment"), path)
    fp = Floorplan(str(path))

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
