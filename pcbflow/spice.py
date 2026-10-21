"""Leitura de subcircuitos SPICE (.subckt) que descrevem a montagem das células.

Elementos aceitos dentro de um .subckt:
  M<nome> dreno gate fonte corpo MODELO      (MOSFET; corpo ignorado: discreto)
  Q<nome> coletor base emissor [subst] MODELO (BJT)
  R<nome> n1 n2 valor                         (resistor)
  C<nome> n1 n2 valor                         (capacitor)
  D<nome> anodo catodo MODELO                 (diodo)
  K<nome> c1 c2 com na nf MODELO              (relé SPDT: bobina c1/c2, contato comum,
                                               normalmente aberto e normalmente fechado;
                                               convenção do pcbflow, não é o K do SPICE)
  T<nome> w1 w2 wb s gnd MODELO               (núcleo toroidal de ferrite: enrolamentos de
                                               entrada w1/w2 (+N espiras), inibição/bias wb
                                               (-N espiras), saída/sense s e retorno gnd;
                                               convenção do pcbflow para lógica CTL)
  V<nome> p g k MODELO                        (válvula termiônica a vácuo: placa/anodo p,
                                               grade de controle g e catodo/filamento k;
                                               convenção do pcbflow para lógica a válvulas)
  X<nome> nós... SUBCKT                       (instância de outro subcircuito)
Parâmetros no formato chave=valor são ignorados. MODELO é uma chave do
parts.json da família (ex.: NMOS, NPN).
"""

from dataclasses import dataclass, field


class SpiceError(Exception):
    pass


@dataclass
class Element:
    name: str
    letter: str           # M Q R C D K T X
    nodes: list
    model: str = ""       # chave do parts.json ou nome do subcircuito (X)
    value: str = ""       # R/C


@dataclass
class Subckt:
    name: str
    pins: list
    elements: list = field(default_factory=list)
    source: str = ""

    @property
    def devices(self):
        return [e for e in self.elements if e.letter != "X"]

    @property
    def instances(self):
        return [e for e in self.elements if e.letter == "X"]


def _logical_lines(text):
    lines = []
    for raw in text.splitlines():
        line = raw.split(";")[0].split(" $ ")[0].rstrip()
        if not line.strip() or line.lstrip().startswith("*"):
            continue
        if line.lstrip().startswith("+") and lines:
            lines[-1] = (lines[-1][0], lines[-1][1] + " " + line.lstrip()[1:])
        else:
            lines.append((len(lines), line.strip()))
    return [l for _, l in lines]


def read_subckts(path):
    text = open(path, encoding="utf-8").read()
    subs = {}
    cur = None
    for line in _logical_lines(text):
        tok = line.split()
        head = tok[0].lower()
        if head == ".subckt":
            if cur:
                raise SpiceError(f"{path}: .subckt {tok[1]} dentro de {cur.name}")
            pins = [t for t in tok[2:] if "=" not in t and t.lower() != "params:"]
            cur = Subckt(tok[1], pins, source=str(path))
            continue
        if head == ".ends":
            if not cur:
                raise SpiceError(f"{path}: .ends sem .subckt")
            subs[cur.name] = cur
            cur = None
            continue
        if head.startswith("."):
            continue
        if cur is None:
            continue
        name = tok[0]
        letter = name[0].upper()
        rest = [t for t in tok[1:] if "=" not in t]
        try:
            if letter == "M":
                el = Element(name, "M", rest[0:3], model=rest[4])
            elif letter == "Q":
                el = Element(name, "Q", rest[0:3], model=rest[-1] if len(rest) in (4, 5) else rest[3])
            elif letter in ("R", "C"):
                el = Element(name, letter, rest[0:2], model=letter, value=rest[2])
            elif letter == "D":
                el = Element(name, "D", rest[0:2], model=rest[2])
            elif letter == "K":
                el = Element(name, "K", rest[0:5], model=rest[5])
            elif letter == "T":
                el = Element(name, "T", rest[0:5], model=rest[5])
            elif letter == "V":
                el = Element(name, "V", rest[0:3], model=rest[3])
            elif letter == "X":
                el = Element(name, "X", rest[:-1], model=rest[-1])
            else:
                raise SpiceError(f"{path}: elemento '{name}' não suportado (use M, Q, R, C, D, K, T, V ou X)")
        except IndexError:
            raise SpiceError(f"{path}: linha incompleta: {line}") from None
        cur.elements.append(el)
    if cur:
        raise SpiceError(f"{path}: .subckt {cur.name} sem .ends")
    return subs
