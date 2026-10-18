"""Reaproveitamento do placement entre rodadas (pcbflow --place-only -> pcbflow).

Depois do placement o fluxo grava <saída>/place_cache.pkl: o design já
sintetizado e dimensionado, a placa posicionada e o que foi apurado até ali
(estatística do Yosys, nets acima do fan-out, simulações que já passaram).
Junto vai uma impressão digital de tudo que influencia esse resultado. Na
rodada seguinte, se a impressão bater, as etapas 0 a 3 são puladas e o fluxo
vai direto ao roteamento; se não bater, ele refaz tudo e diz o que mudou.

A impressão cobre: o conteúdo dos fontes Verilog, todos os arquivos da
família de células (e o footprints.json), o floorplan, as opções que mudam a
placa e o código do pcbflow que roda até o placement (mexer no roteador ou no
editor não invalida um placement salvo). --fresh ignora o cache.
"""

import hashlib
import json
import pickle
import time
from pathlib import Path

FILE = "place_cache.pkl"
VERSION = 1
CODE_DIR = Path(__file__).resolve().parent
# código que roda até o fim do placement (e as classes que vão no pickle)
PLACE_CODE = ("library.py", "liberty.py", "spice.py", "netlist.py", "synth.py", "drive.py",
              "sizing.py", "place.py", "anneal.py", "jit.py", "layout.py", "floorplan.py", "cache.py",
              "hier.py", "route.py")       # com macros, o roteamento deles acontece no placement
# opções do argparse que mudam a síntese ou o placement
PLACE_ARGS = ("top", "layers", "effort", "seed", "density", "row_gap", "part_gap",
              "module_weight", "flatten", "no_size", "macro", "route_iter")
NAMES = {"src": "fontes Verilog", "lib": "biblioteca de células", "floorplan": "floorplan",
         "args": "opções do fluxo", "code": "código do pcbflow"}


def _hash_files(paths, base=None):
    h = hashlib.sha256()
    for p in paths:
        p = Path(p)
        h.update(str(p.relative_to(base) if base else p.resolve()).replace("\\", "/").encode())
        h.update(b"\0")
        h.update(p.read_bytes() if p.is_file() else b"<ausente>")
        h.update(b"\0")
    return h.hexdigest()


def file_hash(path):
    return _hash_files([path]) if path else None


def fingerprint(args):
    """Impressão digital por componente ({nome: hash})."""
    lib = Path(args.lib).resolve()
    lib_files = sorted(p for p in lib.rglob("*") if p.is_file())
    try:
        fp_rel = json.loads((lib / "library.json").read_text(encoding="utf-8")).get("footprints",
                                                                                      "../footprints.json")
        lib_files.append((lib / fp_rel).resolve())
    except (OSError, ValueError):
        pass
    opts = {k: getattr(args, k, None) for k in PLACE_ARGS}
    return {
        "src": _hash_files(args.src),
        "lib": _hash_files(lib_files),
        "floorplan": file_hash(args.floorplan),
        "args": hashlib.sha256(json.dumps(opts, sort_keys=True).encode()).hexdigest(),
        "code": _hash_files([CODE_DIR / f for f in PLACE_CODE], CODE_DIR),
    }


def load(out, key, ignore=()):
    """(dados, motivo): dados do placement salvo se a impressão bate; senão None
    e o motivo em texto (ou None se não há placement salvo). ignore: partes da
    impressão que não contam (--keep-placement ignora o código do pcbflow)."""
    path = Path(out) / FILE
    if not path.is_file():
        return None, None
    try:
        with open(path, "rb") as f:
            data = pickle.load(f)
    except Exception as e:                      # versão antiga, arquivo truncado...
        return None, f"placement salvo ilegível ({type(e).__name__})"
    if data.get("version") != VERSION:
        return None, "placement salvo de outra versão do cache"
    changed = [NAMES[k] for k in NAMES if k not in ignore and data.get("key", {}).get(k) != key.get(k)]
    if changed:
        return None, "mudou: " + ", ".join(changed)
    return data, None


def save(out, key, **data):
    """Grava atomicamente (uma rodada interrompida não deixa um cache pela metade)."""
    path = Path(out) / FILE
    tmp = path.with_suffix(".tmp")
    payload = dict(data, version=VERSION, key=key, time=data.get("time") or time.time())
    with open(tmp, "wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)
