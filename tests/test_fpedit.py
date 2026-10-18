"""Editor de floorplan: validação (check), utilitários e a API HTTP com um
servidor de verdade (numa thread), sem rodar o make."""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from conftest import data, lib_path
from pcbflow import fpedit, project
from pcbflow.floorplan import FloorplanError


# ------------------------------------------------------------ uma rodada
@pytest.fixture(scope="module")
def hier_run(flow):
    """placement.json de uma rodada do hier8 com add4 e fa como macros (medidos)."""
    r = flow("hier_macros", "--top", "hier8", "--src", data("hier8.v"), "--lib", lib_path("rtl"), "--no-drc",
             "--tb", data("tb_hier8.v"), "--macro", "fa", "--macro", "add4", "--fresh")
    assert r.rc == 0, r
    return r.placement()


@pytest.fixture(scope="module")
def flat_run(flow):
    """Rodada só de síntese, sem macros (as medidas são do projeto inteiro)."""
    r = flow("hier_stat", "--top", "hier8", "--src", data("hier8.v"), "--lib", lib_path("rtl"), "--synth-only")
    assert r.rc == 0, r
    return r.placement()


# ---------------------------------------------------------------- check()
def test_check_sem_rodada_so_confere_formato():
    assert fpedit.check({"modules": {}}, None, "fp")["errors"] == []
    out = fpedit.check({"modules": {"a": {"type": "x"}}}, None, "fp")
    assert out["errors"] and "'type' deve ser" in out["errors"][0]


@pytest.mark.slow
def test_check_modulo_inexistente(flat_run):
    out = fpedit.check({"modules": {"zz": {"type": "fence", "rect": [0, 0, 10, 10]}}}, flat_run, "fp")
    assert any("'zz' não existe" in e for e in out["errors"])


@pytest.mark.slow
def test_check_capacidade_da_area(flat_run):
    small = fpedit.check({"modules": {"lo": {"type": "fence", "rect": [20, 10, 20, 15]}}}, flat_run, "fp")
    assert any("não cabe na área" in e for e in small["errors"])
    big = fpedit.check({"modules": {"lo": {"type": "fence", "rect": [20, 10, 400, 200]}}}, flat_run, "fp")
    assert big["errors"] == []
    u = next(x for x in big["usage"] if x["path"] == "lo")
    assert u["ok"] and 0 < u["util"] < 1


@pytest.mark.slow
def test_check_macros_estimados_sem_medida(flat_run):
    out = fpedit.check({"macros": ["add4"]}, flat_run, "fp")
    inst = {m["path"]: m for m in out["macros"]["instances"]}
    assert set(inst) == {"lo", "hi"} and not inst["lo"]["measured"] and inst["lo"]["w"] > 0
    # sem macros as fileiras contam o projeto todo; com eles, só a lógica solta
    need_all = fpedit.check({}, flat_run, "fp")["usage"][0]["need"]
    need_glue = sum(u["need"] for u in out["usage"])
    assert need_glue < need_all


@pytest.mark.slow
def test_check_macros_medidos(hier_run):
    out = fpedit.check({"macros": ["add4", "fa"]}, hier_run, "fp")
    inst = {m["path"]: m for m in out["macros"]["instances"]}
    tpl = hier_run["macros"]["templates"]
    assert set(inst) == {"lo", "hi"}                     # fa fica dentro de add4
    assert inst["lo"]["measured"] and (inst["lo"]["w"], inst["lo"]["h"]) == \
        (tpl[hier_run["macros"]["instances"]["lo"]["template"]]["w"],
         tpl[hier_run["macros"]["instances"]["lo"]["template"]]["h"])


@pytest.mark.slow
def test_check_erros_e_avisos_de_macro(hier_run):
    fp = {"macros": ["add4", "fa"], "board": {"width": 120, "height": 300},
          "modules": {"hi": {"type": "fence", "rect": [10, 10, 20, 20]},
                      "lo.f0": {"type": "fence", "rect": [60, 200, 20, 20]}}}
    out = fpedit.check(fp, hier_run, "fp")
    assert any("não comporta o macro add4" in e for e in out["errors"])
    assert any("lo.f0" in w and "dentro do macro 'lo'" in w for w in out["warnings"])
    # mesmo com erro, todos os macros continuam com posição (o editor os desenha)
    assert all(m["rect"] for m in out["macros"]["instances"])


@pytest.mark.slow
def test_check_macro_fora_da_placa_fixa(hier_run):
    fp = {"macros": ["add4"], "board": {"width": 60, "height": 60}}
    out = fpedit.check(fp, hier_run, "fp")
    assert any("fora da placa" in e for e in out["errors"])


@pytest.mark.slow
def test_check_tipo_de_macro_inexistente(hier_run):
    out = fpedit.check({"macros": ["nada"]}, hier_run, "fp")
    assert any("macro 'nada'" in e for e in out["errors"])


@pytest.mark.slow
def test_check_rodada_antiga(hier_run):
    old = dict(hier_run, module_width={"": 10.0})          # versão anterior: só a lógica solta medida
    out = fpedit.check({}, old, "fp")
    assert any("versão anterior" in w for w in out["warnings"])


# ------------------------------------------------------------ utilitários
@pytest.fixture
def proj(tmp_path, monkeypatch):
    """Projeto temporário com pcbflow.json (fontes em rtl/, testbench em sim/)."""
    (tmp_path / "rtl" / "sub").mkdir(parents=True)
    (tmp_path / "rtl" / "a.v").write_text("module a; endmodule\n", encoding="utf-8")
    (tmp_path / "rtl" / "sub" / "b.v").write_text("module b; endmodule\n", encoding="utf-8")
    (tmp_path / "pcbflow.json").write_text(json.dumps({"src": ["rtl/**/*.v"]}), encoding="utf-8")
    p = project.load(tmp_path / "pcbflow.json")
    monkeypatch.setattr(fpedit, "PROJ", p)
    return p


def test_in_project_nao_sai_do_projeto(proj):
    assert fpedit.in_project("rtl") == (proj.root / "rtl").resolve()
    for bad in ("..", "../..", "rtl/../../x"):
        with pytest.raises(FloorplanError):
            fpedit.in_project(bad)


def test_modules_in_ignora_comentarios(tmp_path):
    f = tmp_path / "x.v"
    f.write_text("// module falso1;\n/* module falso2 ( */\nmodule a(); endmodule\n"
                 "module automatic b; endmodule\n", encoding="utf-8")
    assert fpedit.modules_in(f) == ["a", "b"]


def test_drop_legacy():
    assert fpedit.drop_legacy({"density": 0.5, "modules": {}}) == {"modules": {}}
    assert fpedit.drop_legacy({"modules": {}}) == {"modules": {}}


def test_fontes_passadas_ao_fluxo(proj, tmp_path):
    # top entre os fontes do pcbflow.json: o pcbflow usa os do projeto
    assert fpedit.flow_sources(proj.root / "rtl" / "a.v") == []
    # top fora deles: os do projeto mais ele
    extra = tmp_path / "outro" / "c.sv"
    extra.parent.mkdir()
    extra.write_text("module c; endmodule\n", encoding="utf-8")
    assert fpedit.flow_sources(extra) == ["rtl/a.v", "rtl/sub/b.v", "outro/c.sv"]


def test_fontes_sem_pcbflow_json(tmp_path, monkeypatch):
    monkeypatch.setattr(fpedit, "PROJ", project.Project(tmp_path))
    (tmp_path / "x" / "y").mkdir(parents=True)
    for f in ("x/top.v", "x/y/m.sv", "z.v"):
        (tmp_path / f).write_text("", encoding="utf-8")
    assert fpedit.flow_sources(tmp_path / "x" / "top.v") == ["x/top.v", "x/y/m.sv"]


def test_comando_do_menu(proj, monkeypatch):
    # o botão monta um comando python -m pcbflow com valores conhecidos (sem rodar)
    got = {}
    monkeypatch.setattr(fpedit.Job, "start", lambda self, cmd, info: got.update(cmd=cmd, info=info))
    ed = fpedit.Editor()
    ed.set(proj.root / "rtl" / "a.floorplan.json", None, proj.root / "rtl" / "a.v")
    ed.start("place", "rtl", 2, sim=False)
    cmd = got["cmd"]
    assert cmd[1:3] == ["-m", "pcbflow"] and cmd[cmd.index("--top") + 1] == "a"
    assert ["--lib", "rtl"] == cmd[cmd.index("--lib"):cmd.index("--lib") + 2]
    assert "--place-only" in cmd and "--no-tb" in cmd and "--no-floorplan" in cmd and "--src" not in cmd
    assert got["info"]["run"] == "a_rtl_2l"
    (proj.root / "rtl" / "a.floorplan.json").write_text("{}", encoding="utf-8")
    ed.start("pcb", "cmos", 4)
    cmd = got["cmd"]
    assert cmd[cmd.index("--floorplan") + 1] == "rtl/a.floorplan.json"
    assert "--no-tb" not in cmd and "--synth-only" not in cmd and "--place-only" not in cmd


# ------------------------------------------------------------- API HTTP
class Api:
    def __init__(self, base, host=None):
        self.base, self.host = base, host

    def req(self, path, body=None, host=None):
        r = urllib.request.Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                                   headers={"Content-Type": "application/json"})
        if host or self.host:
            r.add_header("Host", host or self.host)
        try:
            with urllib.request.urlopen(r, timeout=30) as resp:
                raw = resp.read()
                ctype = resp.headers.get("Content-Type", "")
                return resp.status, (json.loads(raw) if "json" in ctype else raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")


@pytest.fixture
def server(tmp_path, monkeypatch):
    """Editor com o floorplan num projeto temporário (sem pcbflow.json); a rodada
    é procurada em <projeto>/build/pcb/<top>_*/placement.json."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(fpedit, "PROJ", project.Project(tmp_path))
    (tmp_path / "rtl").mkdir()
    fp = tmp_path / "hier8.floorplan.json"
    ed = fpedit.Editor()
    ed.set(fp, None, None)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), None)
    port = srv.server_address[1]
    srv.RequestHandlerClass = fpedit.make_handler(ed, {f"127.0.0.1:{port}"})
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    yield Api(f"http://127.0.0.1:{port}"), ed, fp, tmp_path
    srv.shutdown()
    srv.server_close()


def put_run(tmp_path, name, placement):
    d = tmp_path / "build" / "pcb" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "placement.json").write_text(json.dumps(placement), encoding="utf-8")


def test_api_pagina_e_estado(server):
    api, ed, fp, _ = server
    code, html = api.req("/")
    assert code == 200 and "<title>Editor de floorplan</title>" in html and "renderMacros" in html
    code, st = api.req("/api/state")
    assert code == 200 and st["top"] == "hier8" and st["exists"] is False and st["data"] is None
    assert "rtl" in st["families"]


def test_api_host_nao_permitido(server):
    api = server[0]
    code, body = api.req("/api/state", host="evil.example:80")
    assert code == 403


def test_api_salvar_e_conflito(server):
    api, ed, fp, _ = server
    data_ = {"macros": ["add4"], "modules": {"lo": {"type": "fence", "rect": [1, 1, 10, 10]}}}
    code, r = api.req("/api/save", {"data": data_, "mtime": None})
    assert code == 200 and r["ok"] and json.loads(fp.read_text(encoding="utf-8")) == data_
    # outro programa mudou o arquivo: salvar com o mtime antigo é recusado sem force
    code, r2 = api.req("/api/save", {"data": {}, "mtime": r["mtime"] - 10})
    assert code == 200 and r2.get("conflict")
    assert json.loads(fp.read_text(encoding="utf-8")) == data_
    code, r3 = api.req("/api/save", {"data": {}, "mtime": r["mtime"] - 10, "force": True})
    assert r3["ok"] and json.loads(fp.read_text(encoding="utf-8")) == {}


def test_api_nao_grava_floorplan_invalido(server):
    api, ed, fp, _ = server
    code, r = api.req("/api/save", {"data": {"modules": {"a": {"type": "x"}}}, "mtime": None})
    assert code == 400 and "'type' deve ser" in r["error"] and not fp.exists()


def test_api_tira_densidade_antiga(server):
    api, ed, fp, _ = server
    api.req("/api/save", {"data": {"density": 0.7, "modules": {}}, "mtime": None})
    assert "density" not in json.loads(fp.read_text(encoding="utf-8"))


def test_api_navegacao_presa_no_projeto(server):
    api = server[0]
    code, r = api.req("/api/fs?dir=rtl")
    assert code == 200 and r["dir"] == "rtl"
    code, r = api.req("/api/fs?dir=../..")
    assert code == 400 and "fora do projeto" in r["error"]
    code, r = api.req("/api/modules", {"file": "../../segredo.v"})
    assert code == 400


def test_api_execucao_so_com_valores_conhecidos(server):
    api = server[0]
    for body, msg in [({"action": "rm", "family": "rtl", "layers": 4}, "ação desconhecida"),
                      ({"action": "stat", "family": "../x", "layers": 4}, "família desconhecida"),
                      ({"action": "stat", "family": "rtl", "layers": 3}, "camadas"),
                      ({"action": "stat", "family": "rtl", "layers": 4, "sim": "sim"}, "simulação")]:
        code, r = api.req("/api/job/start", body)
        assert code == 400 and msg in r["error"], (body, r)
    code, r = api.req("/api/job?id=0&since=0")
    assert code == 200 and r["status"] == "idle"


def test_api_relatorio_inexistente(server):
    assert server[0].req("/api/report?run=nada")[0] == 404


@pytest.mark.slow
def test_api_rodada_e_check(server, hier_run):
    api, ed, fp, tmp = server
    put_run(tmp, "hier8_rtl", hier_run)
    code, st = api.req("/api/state")
    assert [r["name"] for r in st["runs"]] == ["hier8_rtl"] and st["runs"][0]["family"] == "rtl"
    code, r = api.req("/api/run", {"run": "hier8_rtl"})
    assert r["run"]["macros"]["types"] == ["add4", "fa"]
    code, c = api.req("/api/check", {"data": {"macros": ["add4"]}, "run": "hier8_rtl"})
    assert code == 200 and c["errors"] == [] and len(c["macros"]["instances"]) == 2
