"""Configuração comum dos testes do pcbflow.

Camadas (marcadores do pytest.ini):
  sem marcador  unidade: só Python, rodam em segundos
  tools         precisam do Yosys e do Icarus Verilog
  slow          fluxo completo (síntese, placement, roteamento)
  kicad         precisam do kicad-cli
  ui            página do fpedit no Chrome (Selenium)
Um teste cuja ferramenta não está instalada é pulado, com o motivo no resumo.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PCBFLOW = Path(__file__).resolve().parents[1]          # pasta pcbflow/ (pacote, lib, examples)
REPO = PCBFLOW.parent
DATA = Path(__file__).resolve().parent / "data"
LIB = PCBFLOW / "lib"
FAMILIES = sorted(p.name for p in LIB.iterdir() if (p / "library.json").is_file())

if str(PCBFLOW) not in sys.path:
    sys.path.insert(0, str(PCBFLOW))


def _which(name, fallback):
    return shutil.which(name) or (fallback if Path(fallback).is_file() else None)


HAVE_TOOLS = bool(_which("yosys", "C:/msys64/ucrt64/bin/yosys.exe")
                  and _which("iverilog", "C:/msys64/ucrt64/bin/iverilog.exe"))


def _have_kicad():
    from pcbflow import drc
    return drc.find_cli() is not None


def _have_ui():
    try:
        import selenium  # noqa: F401
    except ImportError:
        return False
    return any(Path(p).is_file() for p in (
        "C:/Program Files/Google/Chrome/Application/chrome.exe",
        "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe")) or bool(
        shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chrome"))


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


class FlowRun:
    """Resultado de uma execução de python -m pcbflow."""

    def __init__(self, rc, log, out):
        self.rc, self.log, self.out = rc, log, Path(out)

    def file(self, name):
        return self.out / name

    def placement(self):
        import json
        return json.loads((self.out / "placement.json").read_text(encoding="utf-8"))

    def __repr__(self):
        return f"FlowRun(rc={self.rc}, out={self.out})\n{self.log[-3000:]}"


def run_flow(out, *args, timeout=900):
    """Roda o fluxo como o usuário roda (outro processo, a partir da pasta pcbflow/)."""
    env = dict(os.environ, PYTHONPATH=str(PCBFLOW), PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    cmd = [sys.executable, "-m", "pcbflow", *map(str, args), "--out", str(out)]
    r = subprocess.run(cmd, cwd=PCBFLOW, env=env, capture_output=True, text=True, encoding="utf-8",
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
