"""Projeto que usa o fr4lane: fr4lane.json na raiz dele.

O fr4lane procura o fr4lane.json na pasta atual e nas de cima. Com ele, a
linha de comando e o editor de floorplan (fpedit) sabem onde estão os fontes,
os testbenches e os floorplans de cada top, e onde gravar as rodadas:

  {
    "src":       ["rtl/**/*.v"],                     fontes Verilog (globs a partir da raiz)
    "exclude":   ["rtl/**/sva/**"],                  opcional: fontes a deixar de fora
    "tb":        "sim/testbenches/tb_{top}.v",       opcional: testbench de cada top
    "floorplan": ["rtl/**/{top}.floorplan.json"],    opcional: onde procurar o floorplan
    "out":       "build/pcb"                         opcional: pasta das rodadas (padrão)
  }

{top} é trocado pelo nome do módulo topo. Sem fr4lane.json, a raiz é a pasta
atual e os fontes vêm só de --src.
"""

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path

CONFIG = "fr4lane.json"
KEYS = ("src", "exclude", "tb", "floorplan", "out", "_comment")


class ProjectError(Exception):
    pass


@dataclass
class Project:
    root: Path
    src: list = field(default_factory=list)
    exclude: list = field(default_factory=list)
    tb: str = ""
    floorplan: list = field(default_factory=list)
    out: str = "build/pcb"
    config: Path = None          # o fr4lane.json lido (None: projeto sem configuração)

    def _glob(self, pattern):
        return sorted(p for p in self.root.glob(pattern) if p.is_file())

    def _excluded(self, p):
        rel = p.relative_to(self.root).as_posix()
        return any(fnmatch.fnmatch(rel, pat) for pat in self.exclude)

    def sources(self):
        """Fontes do projeto (caminhos absolutos, sem repetição, na ordem dos globs)."""
        seen, out = set(), []
        for pat in self.src:
            for p in self._glob(pat):
                if p not in seen and not self._excluded(p):
                    seen.add(p)
                    out.append(p)
        return out

    def testbench(self, top):
        if not self.tb:
            return None
        p = self.root / self.tb.replace("{top}", top)
        return p if p.is_file() else None

    def find_floorplan(self, top):
        for pat in self.floorplan:
            hits = self._glob(pat.replace("{top}", top))
            if hits:
                return hits[0]
        return None

    def out_dir(self, tag):
        return self.root / self.out / tag

    def rel(self, p):
        """Caminho relativo à raiz (absoluto, se ficar fora dela)."""
        p = Path(p).resolve()
        return p.relative_to(self.root).as_posix() if p == self.root or self.root in p.parents else p.as_posix()


def _strings(v, key, where):
    if isinstance(v, str):
        v = [v]
    if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
        raise ProjectError(f"{where}: '{key}' deve ser um texto ou uma lista de textos")
    return v


def load(path):
    path = Path(path).resolve()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ProjectError(f"{path}: {e}") from None
    if not isinstance(data, dict):
        raise ProjectError(f"{path}: esperado um objeto JSON")
    extra = set(data) - set(KEYS)
    if extra:
        raise ProjectError(f"{path}: chave(s) desconhecida(s) {sorted(extra)} (aceitas: {', '.join(KEYS[:-1])})")
    tb = data.get("tb", "")
    if not isinstance(tb, str):
        raise ProjectError(f"{path}: 'tb' deve ser um texto (ex.: \"sim/tb_{{top}}.v\")")
    out = data.get("out", "build/pcb")
    if not isinstance(out, str) or not out:
        raise ProjectError(f"{path}: 'out' deve ser uma pasta")
    return Project(path.parent, _strings(data.get("src", []), "src", path),
                   _strings(data.get("exclude", []), "exclude", path), tb,
                   _strings(data.get("floorplan", []), "floorplan", path), out, path)


def find(start=None):
    """O projeto da pasta start (padrão: a atual) ou da primeira acima dela com
    fr4lane.json; sem nenhum, um projeto sem configuração com raiz em start."""
    start = Path(start or Path.cwd()).resolve()
    if start.is_file():
        start = start.parent
    for d in (start, *start.parents):
        if (d / CONFIG).is_file():
            return load(d / CONFIG)
    return Project(start)
