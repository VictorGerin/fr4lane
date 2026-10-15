"""Editor de floorplan no navegador.

Uso:
  python -m pcbflow.fpedit rtl/basic/basic_top.floorplan.json
  python -m pcbflow.fpedit "rtl/**/*.floorplan.json"        (padrão glob: precisa casar um arquivo só)

Abre um servidor local (127.0.0.1 por padrão) e o navegador padrão com o
arquivo carregado; se o arquivo não existir, começa vazio e é criado ao salvar.

Para desenhar as fileiras e conferir a capacidade de cada área, o editor lê o
placement.json que o fluxo grava em build/pcb/<top>_*/ (o <top> vem do nome do
arquivo: <top>.floorplan.json). Basta o make pcb-stat (só a síntese) ou um
make pcb, com ou sem floorplan; a rodada só fica desatualizada se o Verilog,
a família ou o número de camadas mudarem. A validação usa as mesmas funções do fluxo.
"""

import argparse
import glob
import json
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from . import floorplan, place
from .floorplan import FloorplanError

PKG = Path(__file__).resolve().parent
REPO = PKG.parents[1]
SUFFIX = ".floorplan.json"


def find_runs(top, extra=None):
    """Rodadas do fluxo para o topo (mais recente primeiro)."""
    found = []
    if extra:
        p = Path(extra)
        found.append(p / "placement.json" if p.is_dir() else p)
    for base in {Path.cwd() / "build" / "pcb", REPO / "build" / "pcb"}:
        found += base.glob(f"{top}/placement.json")
        found += base.glob(f"{top}_*/placement.json")
    seen, runs = set(), []
    for f in found:
        f = f.resolve()
        if f in seen or not f.is_file():
            continue
        seen.add(f)
        runs.append(f)
    runs.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    if extra:                                 # o pedido explicitamente vem primeiro
        want = (Path(extra) / "placement.json" if Path(extra).is_dir() else Path(extra)).resolve()
        runs.sort(key=lambda f: f != want)
    return runs


def run_summary(run_file):
    """(desatualizada, posicionada): a rodada envelheceu se algum dos fontes
    Verilog dela mudou depois; posicionada = não foi só síntese (pcb-stat)."""
    t = run_file.stat().st_mtime
    try:
        d = json.loads(run_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, True
    stale = any(Path(f).is_file() and Path(f).stat().st_mtime > t for f in d.get("sources", []))
    return stale, d.get("placed", True)


def check(data, run, source):
    """Valida o floorplan como o fluxo faria; com uma rodada, refaz as fileiras
    e confere a capacidade de cada área."""
    out = {"errors": [], "usage": [], "slots": [], "bands": [], "logic": None, "board": None}
    try:
        fp = floorplan.parse(data, source)
    except FloorplanError as e:
        out["errors"].append(str(e))
        return out
    if run is None:
        return out
    geo = SimpleNamespace(**run["geo"])
    widths = run["module_width"]
    mods = {m for m in widths if m}
    for path in fp.modules:
        if not any(m == path or m.startswith(path + ".") for m in mods):
            out["errors"].append(f"módulo '{path}' não existe no projeto")
    need = {}
    for m, w in widths.items():
        o = place.owner_of(fp, m)
        need[o] = need.get(o, 0.0) + w
    try:
        lay = place.declared_layout(geo, fp, need, sum(widths.values()), run["min_width"])
    except FloorplanError as e:
        out["errors"].append(str(e))
        return out
    out["errors"] += place.declared_problems(geo, fp, lay, need)
    have = lay["have"]
    for r in fp.modules.values():
        if r.type in ("fence", "region"):
            n, h = need.get(r.path, 0.0), have.get(r.path, 0.0)
            out["usage"].append({"path": r.path, "need": n / 0.9, "have": h, "ok": r.path not in lay["short"]})
    if need.get(None) or have.get("free"):
        out["usage"].append({"path": None, "need": need.get(None, 0.0) / 0.95, "have": have.get("free", 0.0),
                             "ok": not lay["free_short"]})
    out["slots"] = [list(s) for s in lay["slots"]]
    out["bands"] = [[geo.y_top + k * geo.row_pitch, geo.block_h] for k in range(lay["n_global"])]
    out["logic"] = [geo.x0, lay["lx1"]]
    out["board"] = [lay["W"], lay["H"]]
    return out


class Editor:
    def __init__(self, path, runs):
        self.path = path
        self.top = path.name[:-len(SUFFIX)] if path.name.endswith(SUFFIX) else path.stem
        self.runs = runs
        self.lock = threading.Lock()

    def mtime(self):
        return self.path.stat().st_mtime if self.path.exists() else None

    def run(self, i):
        if i is None or not (0 <= i < len(self.runs)):
            return None
        return json.loads(self.runs[i].read_text(encoding="utf-8"))

    def state(self):
        st = {"file": str(self.path), "top": self.top, "exists": self.path.exists(),
              "mtime": self.mtime(), "data": None, "load_error": None, "runs": []}
        if st["exists"]:
            try:
                st["data"] = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                st["load_error"] = str(e)
        for i, f in enumerate(self.runs):
            t = f.stat().st_mtime
            stale, placed = run_summary(f)
            st["runs"].append({"index": i, "dir": str(f.parent), "name": f.parent.name,
                               "time": time.strftime("%d/%m/%Y %H:%M", time.localtime(t)),
                               "stale": stale, "placed": placed})
        return st

    def save(self, data, base_mtime, force):
        floorplan.parse(data, str(self.path))      # não grava o que o fluxo recusaria
        with self.lock:
            cur = self.mtime()
            if not force and cur is not None and base_mtime is not None and abs(cur - base_mtime) > 1e-3:
                return {"conflict": True}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            return {"ok": True, "mtime": self.mtime()}


def make_handler(ed, allowed_hosts):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8"):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _host_ok(self):
            # contra DNS rebinding: só atende pelo nome com que o servidor foi aberto
            if allowed_hosts is None or self.headers.get("Host", "") in allowed_hosts:
                return True
            self._send(403, {"error": "host não permitido"})
            return False

        def do_GET(self):
            if not self._host_ok():
                return
            u = urlparse(self.path)
            if u.path == "/":
                self._send(200, (PKG / "fpedit.html").read_bytes(), "text/html; charset=utf-8")
            elif u.path == "/api/state":
                self._send(200, ed.state())
            else:
                self._send(404, {"error": "não encontrado"})

        def do_POST(self):
            if not self._host_ok():
                return
            try:
                n = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(n).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                self._send(400, {"error": "JSON inválido"})
                return
            u = urlparse(self.path)
            try:
                if u.path == "/api/run":
                    self._send(200, {"run": ed.run(req.get("run"))})
                elif u.path == "/api/check":
                    run = ed.run(req.get("run"))
                    self._send(200, check(req.get("data"), run, ed.path.name))
                elif u.path == "/api/save":
                    self._send(200, ed.save(req.get("data"), req.get("mtime"), req.get("force", False)))
                else:
                    self._send(404, {"error": "não encontrado"})
            except FloorplanError as e:
                self._send(400, {"error": str(e)})

    return Handler


def resolve_file(arg):
    if any(c in arg for c in "*?["):
        hits = sorted(glob.glob(arg, recursive=True))
        if len(hits) != 1:
            raise SystemExit(f"'{arg}' casa {len(hits)} arquivos" + (": " + ", ".join(hits) if hits else "")
                             + "; indique um só")
        arg = hits[0]
    p = Path(arg).resolve()
    if p.is_dir():
        raise SystemExit(f"{arg} é uma pasta; indique o arquivo <top>{SUFFIX}")
    return p


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="python -m pcbflow.fpedit", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help=f"<top>{SUFFIX} (criado ao salvar se não existir)")
    ap.add_argument("--run", help="pasta de uma rodada (build/pcb/<top>_<família>) ou o placement.json dela")
    ap.add_argument("--host", default="127.0.0.1", help="endereço do servidor (padrão: 127.0.0.1)")
    ap.add_argument("--port", type=int, help="porta (padrão: 8765, ou uma livre se estiver ocupada)")
    ap.add_argument("--no-browser", action="store_true", help="não abre o navegador")
    args = ap.parse_args(argv)

    path = resolve_file(args.file)
    ed = Editor(path, [])
    ed.runs = find_runs(ed.top, args.run)
    try:
        srv = ThreadingHTTPServer((args.host, args.port or 8765), None)
    except OSError:
        if args.port:
            raise SystemExit(f"porta {args.port} ocupada")
        srv = ThreadingHTTPServer((args.host, 0), None)
    port = srv.server_address[1]
    local = args.host in ("127.0.0.1", "localhost", "::1")
    allowed = {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"} if local else None
    srv.RequestHandlerClass = make_handler(ed, allowed)
    url = f"http://{'127.0.0.1' if local else args.host}:{port}/"

    print(f"Floorplan: {path}" + ("" if path.exists() else " (novo, criado ao salvar)"))
    if ed.runs:
        print(f"Rodada:    {ed.runs[0].parent}" + (f" (+{len(ed.runs) - 1})" if len(ed.runs) > 1 else ""))
    else:
        print(f"Rodada:    nenhuma em build/pcb/{ed.top}_*/ — rode make pcb-stat PCB_TOP={ed.top} "
              "para ver fileiras e capacidade")
    print(f"Editor:    {url}   (Ctrl+C para sair)")
    if not args.no_browser and not webbrowser.open(url):
        print("           nenhum navegador padrão encontrado; abra o endereço acima")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
