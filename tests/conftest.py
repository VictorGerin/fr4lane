"""Configuração comum dos testes do fr4lane.

Camadas (marcadores do pytest.ini):
  sem marcador  unidade: só Python, rodam em segundos
  tools         precisam do Yosys e do Icarus Verilog
  slow          fluxo completo (síntese, placement, roteamento)
  kicad         precisam do kicad-cli
  ui            página do fpedit no Chrome (Selenium)
  spice         simulação analógica das células (ngspice)
Um teste cuja ferramenta não está instalada é pulado, com o motivo no resumo.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

FR4LANE = Path(__file__).resolve().parents[1]          # raiz do repositório (pacote, examples, tests)
DATA = Path(__file__).resolve().parent / "data"
LIB = FR4LANE / "fr4lane" / "lib"                       # famílias incluídas no pacote

if str(FR4LANE) not in sys.path:
    sys.path.insert(0, str(FR4LANE))

from fr4lane.library import families  # noqa: E402

FAMILIES = families()


def _which(name, fallback):
    return shutil.which(name) or (fallback if Path(fallback).is_file() else None)


HAVE_TOOLS = bool(_which("yosys", "C:/msys64/ucrt64/bin/yosys.exe")
                  and _which("iverilog", "C:/msys64/ucrt64/bin/iverilog.exe"))


def _have_kicad():
    from fr4lane import drc
    return drc.find_cli() is not None


def chrome_binary():
    """Chrome ou Chromium instalado (None: nenhum)."""
    for p in ("C:/Program Files/Google/Chrome/Application/chrome.exe",
              "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        if Path(p).is_file():
            return p
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        if shutil.which(name):
            return shutil.which(name)
    return None


def _have_ui():
    try:
        import selenium  # noqa: F401
    except ImportError:
        return False
    return chrome_binary() is not None


def pytest_collection_modifyitems(config, items):
    kicad = ui = None
    for item in items:
        if "tools" in item.keywords or "slow" in item.keywords:
            if not HAVE_TOOLS:
                item.add_marker(pytest.mark.skip(reason="Yosys/Icarus Verilog não encontrados"))
        if "kicad" in item.keywords:
            kicad = _have_kicad() if kicad is None else kicad
            if not kicad:
                item.add_marker(pytest.mark.skip(reason="kicad-cli não encontrado"))
        if "ui" in item.keywords:
            ui = _have_ui() if ui is None else ui
            if not ui:
                item.add_marker(pytest.mark.skip(reason="Selenium ou Chrome não encontrados"))
        if "spice" in item.keywords:
            from fr4lane.cellsim import find_ngspice
            if not find_ngspice():
                item.add_marker(pytest.mark.skip(reason="ngspice não encontrado"))


class FlowRun:
    """Resultado de uma execução de python -m fr4lane."""

    def __init__(self, rc, log, out):
        self.rc, self.log, self.out = rc, log, Path(out) if out else None

    def file(self, name):
        return self.out / name

    def placement(self):
        import json
        return json.loads((self.out / "placement.json").read_text(encoding="utf-8"))

    def __repr__(self):
        return f"FlowRun(rc={self.rc}, out={self.out})\n{self.log[-3000:]}"


def run_flow(out, *args, timeout=900, cwd=None):
    """Roda o fluxo como o usuário roda (outro processo). out=None: a pasta de
    saída padrão (a do fr4lane.json do projeto em cwd)."""
    env = dict(os.environ, PYTHONPATH=str(FR4LANE), PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    cmd = [sys.executable, "-m", "fr4lane", *map(str, args)] + (["--out", str(out)] if out else [])
    r = subprocess.run(cmd, cwd=cwd or FR4LANE, env=env, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout)
    return FlowRun(r.returncode, r.stdout + r.stderr, out)


@pytest.fixture(scope="session")
def flow(tmp_path_factory):
    """flow(nome, *args): roda o fluxo uma vez por sessão para cada nome (testes
    diferentes conferem aspectos diferentes da mesma rodada)."""
    cache = {}

    def run(name, *args):
        if name not in cache:
            cache[name] = run_flow(tmp_path_factory.mktemp(name), *args)
        return cache[name]
    return run


def lib_path(family):
    return LIB / family


def data(name):
    return DATA / name
