"""Restrições de floorplan: posição absoluta (mm) dos módulos e áreas proibidas.

Arquivo JSON (coordenadas em mm a partir do canto superior esquerdo da placa;
retângulos como [x, y, largura, altura]):

  {
    "board":   {"width": 160, "height": 120},              opcional
    "modules": {
      "u_fa":   {"type": "fence",  "rect": [20, 10, 60, 40]},
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

    for name, m in data.get("modules", {}).items():
        where = f"{path}: módulo '{name}'"
        if not isinstance(m, dict):
            raise FloorplanError(f"{where}: esperado um objeto")
        _keys(m, ("type", "rect", "near", "_comment"), where)
        t = m.get("type")
        if t not in TYPES:
            raise FloorplanError(f"{where}: 'type' deve ser {', '.join(TYPES)}")
        if "near" in m:
            if t != "guide":
                raise FloorplanError(f"{where}: 'near' só vale para 'guide'; {t} precisa de 'rect'")
            p = m["near"]
            if not (isinstance(p, (list, tuple)) and len(p) == 2):
                raise FloorplanError(f"{where}: 'near' deve ser [x, y] em mm")
            rect = (float(p[0]), float(p[1]), float(p[0]), float(p[1]))
        elif "rect" in m:
            rect = _rect(m["rect"], where)
        else:
            raise FloorplanError(f"{where}: falta 'rect'")
        fp.modules[name] = ModuleRule(name, t, rect)

    for i, k in enumerate(data.get("keepouts", [])):
        name = k.get("name", f"keepout{i + 1}") if isinstance(k, dict) else ""
        where = f"{path}: keepout '{name}'"
        if not isinstance(k, dict):
            raise FloorplanError(f"{path}: keepout {i + 1}: esperado um objeto")
        _keys(k, ("name", "rect", "what", "layers", "_comment"), where)
        what = k.get("what", ["place", "route"])
        if not what or any(w not in WHAT for w in what):
            raise FloorplanError(f"{where}: 'what' deve conter 'place' e/ou 'route'")
        layers = tuple(k.get("layers", LAYERS))
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
