"""Leitura de arquivos Liberty (.lib) e das expressões booleanas de 'function'.

Só o necessário para o pcbflow: grupos, atributos, células, pinos e ff().
Os trechos de texto de cada cell() são preservados para montar a biblioteca
unificada que o Yosys lê, sem reformatar o que o usuário escreveu.
"""

import re
from dataclasses import dataclass, field

_TOK = re.compile(r'\s+|/\*.*?\*/|//[^\n]*|\\\n|"(?:[^"\\]|\\.)*"|[(){}:;,]|[^\s(){}:;,"]+', re.S)


class LibertyError(Exception):
    pass


@dataclass
class Group:
    name: str
    args: list
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    start: int = 0
    end: int = 0

    def groups(self, name):
        return [g for g in self.children if g.name == name]


def _unquote(s):
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] == '"' else s


def _tokenize(text):
    out = []
    for m in _TOK.finditer(text):
        s = m.group()
        if s.isspace() or s.startswith("/*") or s.startswith("//") or s == "\\\n":
            continue
        out.append((s, m.start(), m.end()))
    return out


def parse(text):
    """Devolve a lista de grupos de nível superior."""
    toks = _tokenize(text)
    pos = 0

    def peek():
        return toks[pos][0] if pos < len(toks) else None

    def stmt():
        nonlocal pos
        name, start, _ = toks[pos]
        pos += 1
        if peek() == ":":
            pos += 1
            vals = []
            while peek() not in (";", "}", None):
                vals.append(_unquote(toks[pos][0]))
                pos += 1
            if peek() == ";":
                pos += 1
            return ("attr", name, " ".join(vals))
        if peek() != "(":
            raise LibertyError(f"esperado '(' ou ':' depois de '{name}' (posição {start})")
        pos += 1
        args = []
        while peek() != ")":
            if peek() is None:
                raise LibertyError(f"')' faltando em '{name}'")
            if peek() != ",":
                args.append(_unquote(toks[pos][0]))
            pos += 1
        pos += 1
        if peek() == "{":
            pos += 1
            g = Group(name, args, start=start)
            while peek() != "}":
                if peek() is None:
                    raise LibertyError(f"'}}' faltando no grupo {name}({', '.join(args)})")
                item = stmt()
                if item[0] == "group":
                    g.children.append(item[1])
                else:
                    g.attrs.setdefault(item[1], item[2])
            g.end = toks[pos][2]
            pos += 1
            return ("group", g)
        if peek() == ";":
            pos += 1
        return ("complex", name, args)

    tops = []
    while pos < len(toks):
        item = stmt()
        if item[0] == "group":
            tops.append(item[1])
    return tops


# --------------------------------------------------------------------- células
@dataclass
class LibCell:
    name: str
    area: float
    pins: dict            # nome -> {"direction", "function", "clock"}
    ff: dict = None       # clocked_on, next_state, clear, preset, iq, iqn
    text: str = ""
    source: str = ""

    @property
    def inputs(self):
        return [p for p, d in self.pins.items() if d["direction"] == "input"]

    @property
    def outputs(self):
        return [p for p, d in self.pins.items() if d["direction"] == "output"]


def read_cells(path):
    text = open(path, encoding="utf-8").read()
    try:
        tops = parse(text)
    except LibertyError as e:
        raise LibertyError(f"{path}: {e}") from None
    groups = []
    for g in tops:
        if g.name == "library":
            groups += g.groups("cell")
        elif g.name == "cell":
            groups.append(g)
    cells = []
    for g in groups:
        pins = {}
        for p in g.groups("pin"):
            for pname in p.args:
                pins[pname] = {"direction": p.attrs.get("direction", ""),
                               "function": p.attrs.get("function", ""),
                               "clock": p.attrs.get("clock", "false") == "true"}
        if g.groups("bus") or g.groups("latch"):
            raise LibertyError(f"{path}: célula {g.args[0]}: bus/latch não suportados")
        ff = None
        if g.groups("ff"):
            f = g.groups("ff")[0]
            ff = dict(f.attrs)
            ff["iq"], ff["iqn"] = (f.args + ["", ""])[:2]
        cells.append(LibCell(g.args[0], float(g.attrs.get("area", 0)), pins, ff,
                             text[g.start:g.end], str(path)))
    return cells


# ---------------------------------------------------------------- expressões
_ETOK = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_\[\]\.]*|[01]|[!'&*|+^()])")


def parse_expr(s):
    """Expressão Liberty -> AST: ('var',n) ('const',v) ('not',a) ('and'|'or'|'xor',a,b)."""
    toks = []
    s = s.strip()
    i = 0
    while i < len(s):
        m = _ETOK.match(s, i)
        if not m:
            raise LibertyError(f"expressão inválida: {s!r}")
        toks.append(m.group(1))
        i = m.end()
        while i < len(s) and s[i].isspace():
            i += 1
    pos = 0

    def peek():
        return toks[pos] if pos < len(toks) else None

    def starts_operand(t):
        return t is not None and (t in ("(", "!") or t[0].isalnum() or t[0] == "_")

    def p_or():
        nonlocal pos
        a = p_xor()
        while peek() in ("|", "+"):
            pos += 1
            a = ("or", a, p_xor())
        return a

    def p_xor():
        nonlocal pos
        a = p_and()
        while peek() == "^":
            pos += 1
            a = ("xor", a, p_and())
        return a

    def p_and():
        nonlocal pos
        a = p_unary()
        while peek() in ("&", "*") or starts_operand(peek()):
            if peek() in ("&", "*"):
                pos += 1
            a = ("and", a, p_unary())
        return a

    def p_unary():
        nonlocal pos
        if peek() == "!":
            pos += 1
            return ("not", p_unary())
        a = p_atom()
        while peek() == "'":
            pos += 1
            a = ("not", a)
        return a

    def p_atom():
        nonlocal pos
        t = peek()
        if t is None:
            raise LibertyError(f"expressão incompleta: {s!r}")
        pos += 1
        if t == "(":
            a = p_or()
            if peek() != ")":
                raise LibertyError(f"')' faltando em {s!r}")
            pos += 1
            return a
        if t in ("0", "1"):
            return ("const", int(t))
        return ("var", t)

    ast = p_or()
    if pos != len(toks):
        raise LibertyError(f"sobra em {s!r}: {toks[pos:]}")
    return ast


def expr_vars(ast):
    if ast[0] == "var":
        return {ast[1]}
    if ast[0] == "const":
        return set()
    return set().union(*(expr_vars(a) for a in ast[1:]))


def to_verilog(ast, rename=lambda n: n):
    k = ast[0]
    if k == "var":
        return rename(ast[1])
    if k == "const":
        return f"1'b{ast[1]}"
    if k == "not":
        return f"~({to_verilog(ast[1], rename)})"
    op = {"and": "&", "or": "|", "xor": "^"}[k]
    return f"({to_verilog(ast[1], rename)} {op} {to_verilog(ast[2], rename)})"
