"""Liberty: leitura de células e expressões booleanas."""

import itertools

import pytest

from fr4lane import liberty
from fr4lane.liberty import LibertyError, eval_expr, expr_vars, parse_expr, same_function, to_verilog


def truth(expr, names):
    ast = parse_expr(expr)
    return [eval_expr(ast, dict(zip(names, bits))) for bits in itertools.product((0, 1), repeat=len(names))]


@pytest.mark.parametrize("expr, table", [
    ("A & B", [0, 0, 0, 1]),
    ("A B", [0, 0, 0, 1]),              # justaposição é AND
    ("A * B", [0, 0, 0, 1]),
    ("A | B", [0, 1, 1, 1]),
    ("A + B", [0, 1, 1, 1]),
    ("A ^ B", [0, 1, 1, 0]),
    ("!(A & B)", [1, 1, 1, 0]),
    ("(A & B)'", [1, 1, 1, 0]),          # negação pós-fixa
    ("!A | B", [1, 1, 0, 1]),
])
def test_operadores(expr, table):
    assert truth(expr, ["A", "B"]) == table


def test_precedencia_and_antes_de_or():
    # A | B & C == A | (B & C)
    assert truth("A | B & C", "ABC") == truth("A | (B & C)", "ABC")
    assert truth("A | B & C", "ABC") != truth("(A | B) & C", "ABC")


def test_constantes_e_variaveis():
    assert expr_vars(parse_expr("A & 1 | !B")) == {"A", "B"}
    assert truth("A & 0", ["A"]) == [0, 0]
    assert truth("A | 1", ["A"]) == [1, 1]


def test_expressao_invalida():
    with pytest.raises(LibertyError):
        parse_expr("A & $B")


def test_to_verilog_mesma_funcao():
    ast = parse_expr("!(A & B) ^ C")
    v = to_verilog(ast)
    assert "~" in v and "^" in v
    # reavalia a string Verilog trocando os operadores pelos do Python
    for bits in itertools.product((0, 1), repeat=3):
        env = dict(zip("ABC", bits))
        py = v.replace("~", "1 ^ ")
        for n, b in env.items():
            py = py.replace(n, str(b))
        assert eval(py) == eval_expr(ast, env)


LIB_TEXT = """
library(teste) {
  cell(NAND2) { area : 4;
    pin(A) { direction : input; }
    pin(B) { direction : input; }
    pin(Y) { direction : output; function : "!(A & B)"; }
  }
  cell(NAND2B) { area : 6;
    pin(P) { direction : input; }
    pin(Q) { direction : input; }
    pin(Z) { direction : output; function : "!P | !Q"; }
  }
  cell(DFF) { area : 20;
    ff(IQ, IQN) { clocked_on : "CK"; next_state : "D"; }
    pin(D) { direction : input; }
    pin(CK) { direction : input; clock : true; }
    pin(Q) { direction : output; function : "IQ"; }
  }
  cell(DLAT) { area : 16;
    latch(IQ, IQN) { enable : "E"; data_in : "D"; }
    pin(D) { direction : input; }
    pin(E) { direction : input; }
    pin(Q) { direction : output; function : "IQ"; }
  }
}
"""


@pytest.fixture
def cells(tmp_path):
    f = tmp_path / "t.lib"
    f.write_text(LIB_TEXT, encoding="utf-8")
    return {c.name: c for c in liberty.read_cells(f)}


def test_read_cells(cells):
    assert set(cells) == {"NAND2", "NAND2B", "DFF", "DLAT"}
    n = cells["NAND2"]
    assert n.area == 4 and n.inputs == ["A", "B"] and n.outputs == ["Y"] and n.seq is None
    assert cells["DFF"].ff["clocked_on"] == "CK" and cells["DFF"].seq is cells["DFF"].ff
    assert cells["DFF"].pins["CK"]["clock"] is True
    assert cells["DLAT"].latch == {"enable": "E", "data_in": "D", "iq": "IQ", "iqn": "IQN"}
    assert cells["DLAT"].seq is cells["DLAT"].latch


def test_same_function(cells):
    # De Morgan: mesma função com nomes de pino diferentes não conta (os pinos são os nomes)
    assert not same_function(cells["NAND2"], "Y", cells["NAND2B"], "Z")
    assert same_function(cells["NAND2"], "Y", cells["NAND2"], "Y")
    # latch e flip-flop nunca são a mesma coisa
    assert not same_function(cells["DFF"], "Q", cells["DLAT"], "Q")
    assert same_function(cells["DLAT"], "Q", cells["DLAT"], "Q")


@pytest.mark.parametrize("body, msg", [
    ('latch(IQ, IQN) { enable : "E"; }', "latch() precisa de enable e data_in"),
    ('ff(IQ, IQN) { clocked_on : "C"; next_state : "D"; } latch(IQ, IQN) { enable : "E"; data_in : "D"; }',
     "ff() e latch() na mesma célula"),
    ('bus(D) { direction : input; }', "bus não suportado"),
])
def test_celulas_recusadas(tmp_path, body, msg):
    f = tmp_path / "bad.lib"
    f.write_text(f"library(x) {{ cell(C) {{ area : 1; {body} pin(Q) {{ direction : output; }} }} }}",
                 encoding="utf-8")
    with pytest.raises(LibertyError, match=msg.replace("(", r"\(").replace(")", r"\)")):
        liberty.read_cells(f)
