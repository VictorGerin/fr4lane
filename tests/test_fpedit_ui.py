"""Página do fpedit no Chrome (Selenium): o que a pessoa faz com o mouse e os
botões, com uma rodada de verdade do hier8 (add4 e fa como macros)."""

import json
import threading
import time
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from conftest import data, lib_path
from pcbflow import fpedit, project

pytestmark = [pytest.mark.ui, pytest.mark.slow]


@pytest.fixture(scope="module")
def hier_run(flow):
    r = flow("hier_macros", "--top", "hier8", "--src", data("hier8.v"), "--lib", lib_path("rtl"), "--no-drc",
             "--tb", data("tb_hier8.v"), "--macro", "fa", "--macro", "add4", "--fresh")
    assert r.rc == 0, r
    return r.placement()


@pytest.fixture(scope="module")
def browser():
    from selenium import webdriver
    opt = webdriver.ChromeOptions()
    opt.add_argument("--headless=new")
    opt.add_argument("--window-size=1500,950")
    opt.set_capability("goog:loggingPrefs", {"browser": "ALL"})
    d = webdriver.Chrome(options=opt)
    yield d
    d.quit()


@pytest.fixture
def page(tmp_path, monkeypatch, hier_run, browser):
    """Abre o editor com um floorplan inicial; devolve (driver, js, arquivo)."""
    def open_with(fp_data):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(fpedit, "PROJ", project.Project(tmp_path))
        run_dir = tmp_path / "build" / "pcb" / "hier8_rtl"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "placement.json").write_text(json.dumps(hier_run), encoding="utf-8")
        fp = tmp_path / "hier8.floorplan.json"
        fp.write_text(json.dumps(fp_data), encoding="utf-8")
        ed = fpedit.Editor()
        ed.set(fp, None, None)
        ed.init = {"family": "rtl", "layers": 4}
        srv = ThreadingHTTPServer(("127.0.0.1", 0), None)
        port = srv.server_address[1]
        srv.RequestHandlerClass = fpedit.make_handler(ed, {f"127.0.0.1:{port}"})
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
        browser.get(f"http://127.0.0.1:{port}/")
        wait(lambda: js("return !!(result && result.usage && run)"))
        return fp
    servers = []
    js = browser.execute_script

    def wait(cond, timeout=10):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if cond():
                return
            time.sleep(0.1)
        raise AssertionError("a página não chegou ao estado esperado")

    def settle():
        time.sleep(0.8)         # a verificação roda 200 ms depois da edição e responde em poucos ms

    yield SimpleNamespace(open=open_with, js=js, d=browser, settle=settle, wait=wait)
    for s in servers:
        s.shutdown()
        s.server_close()


def js_errors(d):
    return [l for l in d.get_log("browser") if l["level"] == "SEVERE" and "favicon" not in l["message"]]


def test_carrega_macros_do_arquivo(page):
    page.open({"macros": ["add4", "fa"]})
    js = page.js
    assert js("return macroTypes().join(',')") == "add4,fa"
    assert js("return result.macros.instances.map(m => m.path).sort().join(',')") == "hi,lo"
    assert len(page.d.find_elements("css selector", "#gMacros [data-kind=macro]")) == 2
    assert "medido" in page.d.find_element("id", "macros").text
    assert js("return document.getElementById('gParts').getAttribute('opacity')") == "1"
    assert not js_errors(page.d)


def test_marcar_e_desmarcar_tipos(page):
    page.open({})
    js, d = page.js, page.d

    def toggle(t):
        row = next(l for l in d.find_elements("css selector", "#macros label.mrow")
                   if l.text.split("\n")[0] == t)
        row.find_element("tag name", "input").click()
        page.settle()
    toggle("add4")
    assert js("return data.macros") == ["add4"]
    assert js("return result.macros.instances.length") == 2
    # o placement desenhado foi feito com add4 e fa: com só add4 ele fica esmaecido e há aviso
    assert js("return document.getElementById('gParts').getAttribute('opacity')") == "0.25"
    assert "outros macros" in d.find_element("id", "checks").text
    toggle("fa")
    assert js("return data.macros") == ["add4", "fa"]
    toggle("add4")
    toggle("fa")
    assert js("return 'macros' in data") is False and js("return result.macros") is None
    js("undo()")
    page.settle()
    assert js("return data.macros") == ["fa"]


def test_clique_no_macro_cria_fence_do_tamanho_dele(page):
    page.open({"macros": ["add4", "fa"]})
    js, d = page.js, page.d
    m = js("return macroOf('hi')")
    from selenium.webdriver import ActionChains
    g = d.find_element("css selector", "#gMacros [data-key='hi'] rect:nth-child(2)")
    ActionChains(d).move_to_element(g).click().perform()
    page.settle()
    r = js("return data.modules.hi.rect")
    ring = js("return result.macros.ring")
    assert r[2] == pytest.approx(m["w"] + 2 * ring, abs=0.5) and r[3] == pytest.approx(m["h"] + 2 * ring, abs=0.5)
    assert js("return result.errors.length") == 0
    assert "Ajustar ao macro" in d.find_element("id", "props").text


def test_arrastar_macro_move_a_fence(page):
    page.open({"macros": ["add4", "fa"]})
    js, d = page.js, page.d
    from selenium.webdriver import ActionChains
    o0 = js("return macroOf('lo').origin")
    k = js("return mmPerPx()")
    g = d.find_element("css selector", "#gMacros [data-key='lo'] rect:nth-child(2)")
    ActionChains(d).move_to_element(g).click_and_hold().move_by_offset(40, 30).move_by_offset(40, 30) \
        .release().perform()
    page.settle()
    o1 = js("return macroOf('lo').origin")
    assert js("return !!data.modules.lo")
    assert o1[0] - o0[0] == pytest.approx(80 * k, abs=2) and o1[1] - o0[1] == pytest.approx(60 * k, abs=2)
    assert js("return undoStack.length") == 1               # criar + mover = um passo
    js("undo()")
    page.settle()
    assert js("return !data.modules.lo")


def test_fence_pequena_e_ajustar(page):
    page.open({"macros": ["add4", "fa"], "modules": {"hi": {"type": "fence", "rect": [200, 10, 20, 20]}}})
    js, d = page.js, page.d
    assert any("não comporta o macro add4" in e for e in js("return result.errors"))
    assert len(d.find_elements("css selector", "#gMacros [data-key='hi']")) == 1   # continua desenhado
    js("select({kind: 'mod', key: 'hi'})")
    btn = next(b for b in d.find_elements("css selector", "#props button") if b.text == "Ajustar ao macro")
    btn.click()
    page.settle()
    assert js("return result.errors.length") == 0


def test_area_dentro_de_macro_avisa(page):
    page.open({"macros": ["add4", "fa"], "modules": {"lo.f1": {"type": "fence", "rect": [300, 300, 40, 40]}}})
    assert any("dentro do macro 'lo'" in w for w in page.js("return result.warnings"))
    page.js("select({kind: 'mod', key: 'lo.f1'})")
    assert "o fluxo ignora esta área" in page.d.find_element("id", "props").text


def test_salvar_grava_o_arquivo(page):
    fp = page.open({"modules": {}})
    js = page.js
    js("toggleMacro('add4', true)")
    page.settle()
    js("save()")
    page.wait(lambda: json.loads(fp.read_text(encoding="utf-8")).get("macros") == ["add4"])
    assert js("return dirty") is False


def test_desacoplamento_mostra_o_que_esta_no_arquivo(page):
    # caixa de seleção marcada a partir do arquivo (o helper tratava checked: "" como desmarcado)
    page.open({"modules": {"lo": {"type": "fence", "rect": [20, 10, 400, 200], "decoupling": True}}})
    page.js("select({kind: 'mod', key: 'lo'})")
    box = page.d.find_element("css selector", "#props input[type=checkbox]")
    assert box.is_selected()


def test_barra_de_progresso_legivel(page):
    page.open({})
    js, d = page.js, page.d
    js("""jobPolling = true;       // o polling real não sobrescreve o estado simulado
          renderJob({status: 'running', action: 'pcb', run: 'hier8_rtl', elapsed: 754,
                     progress: {label: 'roteamento', done: 1832, total: 2524,
                                info: 'iteração 7 · 505 nets em conflito', elapsed: 754, eta: 312}});""")
    box = d.find_element("id", "jobProg")
    assert box.is_displayed()
    assert d.find_element("id", "jobProgPct").text == "73%"
    assert d.find_element("id", "jobProgInfo").text == "iteração 7 · 505 nets em conflito"
    assert d.find_element("id", "jobProgTime").text == "12:34 · faltam ~5:12"
    assert box.get_attribute("aria-valuenow") == "73"
    # o texto usa a cor normal, não a apagada (era ilegível durante a execução)
    assert js("return getComputedStyle(document.getElementById('jobProg')).color") == \
        js("return getComputedStyle(document.body).color")
    # sem total (Yosys, simulação): barra indeterminada, sem porcentagem
    js("renderProgress({label: 'síntese (Yosys)', info: 'passo 3/14', elapsed: 5})")
    assert "indet" in d.find_element("css selector", "#jobProg .track").get_attribute("class")
    assert d.find_element("id", "jobProgPct").text == "" and box.get_attribute("aria-valuenow") is None
    js("renderJob({status: 'ok', action: 'pcb', run: 'hier8_rtl', elapsed: 800, progress: null})")
    assert not box.is_displayed()
