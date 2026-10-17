"""Editor de floorplan no navegador.

Uso:
  python -m pcbflow.fpedit rtl/basic/basic_top.floorplan.json
  python -m pcbflow.fpedit "rtl/**/*.floorplan.json"        (padrão glob: precisa casar um arquivo só)
  python -m pcbflow.fpedit                                   (escolhe o top pelo botão Abrir)

Abre um servidor local (127.0.0.1 por padrão) e o navegador padrão com o
arquivo carregado; se o arquivo não existir, começa vazio e é criado ao salvar.
O botão Abrir troca de top: escolhe um .v/.sv do projeto e o módulo dentro dele;
o floorplan fica em <top>.floorplan.json ao lado do fonte.

Para desenhar as fileiras e conferir a capacidade de cada área, o editor lê o
placement.json que o fluxo grava em build/pcb/<top>_<família>[_2l]/ (a família e
as camadas escolhidas no menu definem a pasta). Os botões do menu rodam o fluxo
pelo make: Síntese (make pcb-stat), Placement (make pcb-place, sem rotear) e
Gerar PCB (make pcb). A validação usa as mesmas funções do fluxo.
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from . import floorplan, place
from .floorplan import FloorplanError

PKG = Path(__file__).resolve().parent
REPO = PKG.parents[1]
LIBS = REPO / "pcbflow" / "lib"
SUFFIX = ".floorplan.json"
HDL = (".v", ".sv")
# alvos do Makefile que o menu pode rodar
TARGETS = {"stat": "pcb-stat", "place": "pcb-place", "pcb": "pcb"}


def find_runs(top):
    """Rodadas do fluxo para o topo (mais recente primeiro)."""
    found = []
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
    return runs


def run_summary(run_file):
    """Família, camadas, se envelheceu (algum fonte Verilog mudou depois) e se
    foi posicionada (não só síntese, pcb-stat)."""
    t = run_file.stat().st_mtime
    try:
        d = json.loads(run_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"family": None, "layers": None, "stale": False, "placed": True}
    stale = any(Path(f).is_file() and Path(f).stat().st_mtime > t for f in d.get("sources", []))
    return {"family": d.get("family"), "layers": d.get("layers"), "stale": stale, "placed": d.get("placed", True)}


def families():
    return sorted(p.name for p in LIBS.iterdir() if (p / "library.json").is_file())


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
    # densidade de cada área: calculada (o módulo se espalha pela área toda) ou
    # fixada no arquivo; o espaço livre usa o padrão do fluxo
    dens, util, _ = place.declared_density(geo, fp, lay["slots"], need, place.PlaceParams().density)
    for r in fp.modules.values():
        if r.type in ("fence", "region"):
            n, h = need.get(r.path, 0.0), have.get(r.path, 0.0)
            out["usage"].append({"path": r.path, "need": n / 0.9, "have": h, "ok": r.path not in lay["short"],
                                 "util": util.get(r.path, 0.0), "density": dens.get(r.path, 0.0),
                                 "fixed": r.density is not None})
    if need.get(None) or have.get("free"):
        out["usage"].append({"path": None, "need": need.get(None, 0.0) / 0.95, "have": have.get("free", 0.0),
                             "ok": not lay["free_short"], "util": util.get("free", 0.0),
                             "density": dens.get("free", 0.0), "fixed": False})
    out["slots"] = [list(s) for s in lay["slots"]]
    out["bands"] = [[geo.y_top + k * geo.row_pitch, geo.block_h] for k in range(lay["n_global"])]
    out["logic"] = [geo.x0, lay["lx1"]]
    out["board"] = [lay["W"], lay["H"]]
    return out


def drop_legacy(data):
    """Tira "density" do topo do floorplan: uma versão anterior do editor gravava
    ali uma densidade padrão, que deixou de existir (a densidade de cada área é
    calculada pelo tamanho dela)."""
    if isinstance(data, dict) and "density" in data:
        data = {k: v for k, v in data.items() if k != "density"}
    return data


# ------------------------------------------------------------ fontes Verilog
def rel(p):
    """Caminho relativo à raiz do projeto (absoluto, se ficar fora dela)."""
    p = Path(p).resolve()
    return p.relative_to(REPO).as_posix() if REPO in p.parents else p.as_posix()


def in_repo(arg):
    """Caminho relativo à raiz do projeto, sem sair dela."""
    p = (REPO / (arg or "")).resolve()
    if p != REPO and REPO not in p.parents:
        raise FloorplanError(f"'{arg}' fica fora do projeto")
    return p


def modules_in(path):
    """Nomes dos módulos declarados num .v/.sv (sem comentários)."""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", " ", text)
    return re.findall(r"\bmodule\s+(?:(?:automatic|static)\s+)?([A-Za-z_]\w*)", text)


def list_dir(arg):
    d = in_repo(arg)
    if not d.is_dir():
        raise FloorplanError(f"'{arg}' não é uma pasta")
    dirs, files = [], []
    for p in sorted(d.iterdir(), key=lambda p: p.name.lower()):
        if p.name.startswith(".") or p.name == "__pycache__":
            continue
        if p.is_dir():
            dirs.append(p.name)
        elif p.suffix in HDL:
            files.append(p.name)
    return {"dir": "" if d == REPO else rel(d), "dirs": dirs, "files": files}


def source_of(fp_path, top):
    """O fonte do top de um floorplan aberto pela linha de comando: <top>.v/.sv
    ao lado dele ou em qualquer lugar de rtl/."""
    for ext in HDL:
        p = fp_path.with_name(top + ext)
        if p.is_file():
            return p
    for ext in HDL:
        hits = sorted((REPO / "rtl").rglob(top + ext))
        if hits:
            return hits[0]
    return None


def floorplan_for(src, top):
    """<top>.floorplan.json ao lado do fonte; se não houver, um já existente em rtl/
    (o mesmo que o make pcb acharia); senão, o novo ao lado do fonte."""
    beside = src.with_name(top + SUFFIX)
    if beside.exists():
        return beside
    hits = sorted((REPO / "rtl").rglob(top + SUFFIX))
    return hits[0] if hits else beside


def default_source(p):
    """O PCB_SRC padrão do Makefile já inclui este fonte? (.v de rtl/, fora de sva/)"""
    r = rel(p)
    return r.startswith("rtl/") and r.endswith(".v") and "/sva/" not in r


# ------------------------------------------------------------ execução do make
def find_make():
    return shutil.which("make") or next((m for m in ("C:/msys64/usr/bin/make.exe",) if Path(m).is_file()), None)


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.CreateJobObjectW.restype = wintypes.HANDLE
    _k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    _k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]

    class _JobLimits(ctypes.Structure):     # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD), ("IoInfo", ctypes.c_uint64 * 6),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    def _job_object(proc):
        """Põe o make num Job Object: os filhos (sh, python, yosys, vvp) herdam o job,
        então cancelar derruba a árvore inteira, e ela morre junto se o editor fechar.
        O taskkill /T não basta: os processos do MSYS escapam dele."""
        h = _k32.CreateJobObjectW(None, None)
        if not h:
            return None
        lim = _JobLimits(LimitFlags=0x2000)     # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if (_k32.SetInformationJobObject(h, 9, ctypes.byref(lim), ctypes.sizeof(lim))
                and _k32.AssignProcessToJobObject(h, int(proc._handle))):
            return h
        _k32.CloseHandle(h)
        return None


class Job:
    """Uma execução do make por vez; o log fica em memória para a página acompanhar."""

    MAX_LINES = 20000

    def __init__(self):
        self.lock = threading.Lock()
        self.id = 0
        self.proc = None
        self.lines = []
        self.dropped = 0
        self.status = "idle"            # idle | running | ok | fail | cancelled
        self.info = {}
        self.progress = None            # último "@progress" da etapa em andamento
        self.winjob = None

    def running(self):
        return self.status == "running"

    def start(self, cmd, info):
        with self.lock:
            if self.running():
                raise FloorplanError("já há uma execução em andamento")
            # PCBFLOW_PROGRESS: o fluxo manda o progresso em linhas "@progress {json}"
            env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", PCBFLOW_PROGRESS="1")
            kw = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
            try:
                proc = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL, **kw)
            except OSError as e:
                raise FloorplanError(f"não foi possível rodar o make: {e}")
            self.winjob = _job_object(proc) if os.name == "nt" else None
            self.id += 1
            self.proc, self.lines, self.dropped, self.status = proc, ["$ " + " ".join(cmd[1:])], 0, "running"
            self.info = dict(info, t0=time.time(), t1=None, rc=None)
            self.progress = None
        threading.Thread(target=self._pump, args=(proc, self.id), daemon=True).start()

    def _pump(self, proc, jid):
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if line.startswith("@progress "):
                # progresso não vai para o log: vira a barra da página
                try:
                    p = json.loads(line[len("@progress "):])
                except ValueError:
                    continue
                with self.lock:
                    self.progress = None if p.get("end") else p
                continue
            with self.lock:
                self.lines.append(line)
                if len(self.lines) > self.MAX_LINES:
                    cut = len(self.lines) - self.MAX_LINES
                    del self.lines[:cut]
                    self.dropped += cut
        rc = proc.wait()
        with self.lock:
            if jid != self.id:
                return
            if self.status == "running":
                self.status = "ok" if rc == 0 else "fail"
            self.progress = None
            self.info.update(rc=rc, t1=time.time())
            self.proc = None
            if self.winjob:
                _k32.CloseHandle(self.winjob)
                self.winjob = None

    def cancel(self):
        with self.lock:
            proc = self.proc
            if not proc or not self.running():
                return
            self.status = "cancelled"
            # o make abre sh -> python -> yosys/iverilog: derruba a árvore inteira
            # (sob o lock: o _pump fecha o handle do job quando o make termina)
            if self.winjob:
                _k32.TerminateJobObject(self.winjob, 1)
                return
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
        else:
            import signal
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

    def snapshot(self, jid, since):
        with self.lock:
            if jid != self.id:
                since = 0
            i = max(0, since - self.dropped)
            info = dict(self.info)
            t1 = info.get("t1") or time.time()
            return {"id": self.id, "status": self.status, "lines": self.lines[i:], "next": self.dropped + len(self.lines),
                    "elapsed": round(t1 - info["t0"], 1) if "t0" in info else None,
                    "progress": self.progress,
                    **{k: info.get(k) for k in ("action", "top", "family", "layers", "run", "rc")}}


class Editor:
    def __init__(self, path=None, top=None, src=None):
        self.lock = threading.Lock()
        self.job = Job()
        self.init = {}
        self.set(path, top, src)

    def set(self, path, top, src):
        self.path = path
        self.top = top if top else (path.name[:-len(SUFFIX)] if path and path.name.endswith(SUFFIX) else path.stem if path else None)
        self.src = src

    def mtime(self):
        return self.path.stat().st_mtime if self.path and self.path.exists() else None

    def runs(self):
        return find_runs(self.top) if self.top else []

    def run(self, name):
        """placement.json de uma rodada do top atual, pelo nome da pasta."""
        for f in self.runs():
            if f.parent.name == name:
                return json.loads(f.read_text(encoding="utf-8"))
        return None

    def state(self):
        st = {"file": str(self.path) if self.path else None, "top": self.top,
              "src": rel(self.src) if self.src else None, "exists": bool(self.path and self.path.exists()),
              "mtime": self.mtime(), "data": None, "load_error": None, "runs": [],
              "families": families(), "init": self.init, "make": bool(find_make())}
        if st["exists"]:
            try:
                st["data"] = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                st["load_error"] = str(e)
        for f in self.runs():
            t = f.stat().st_mtime
            st["runs"].append({"name": f.parent.name, "dir": str(f.parent),
                               "time": time.strftime("%d/%m/%Y %H:%M", time.localtime(t)),
                               "report": (f.parent / "report.md").is_file(), **run_summary(f)})
        return st

    def open(self, src_arg, top):
        if self.job.running():
            raise FloorplanError("espere a execução terminar para trocar de top")
        src = in_repo(src_arg)
        if not src.is_file() or src.suffix not in HDL:
            raise FloorplanError(f"'{src_arg}' não é um arquivo .v/.sv")
        if top not in modules_in(src):
            raise FloorplanError(f"o módulo '{top}' não está declarado em {src.name}")
        with self.lock:
            self.set(floorplan_for(src, top), top, src)
        return self.state()

    def save(self, data, base_mtime, force):
        if not self.path:
            raise FloorplanError("nenhum top aberto")
        data = drop_legacy(data)
        floorplan.parse(data, str(self.path))      # não grava o que o fluxo recusaria
        with self.lock:
            cur = self.mtime()
            if not force and cur is not None and base_mtime is not None and abs(cur - base_mtime) > 1e-3:
                return {"conflict": True}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            return {"ok": True, "mtime": self.mtime()}

    def start(self, action, family, layers, sim=True):
        """Roda um alvo do make com o top, a família e as camadas do menu. O comando
        é montado aqui, a partir de listas fechadas: a página não manda texto livre.
        sim=False passa PCB_TB vazio: o fluxo pula a simulação com o testbench."""
        if not self.top:
            raise FloorplanError("nenhum top aberto")
        if action not in TARGETS:
            raise FloorplanError(f"ação desconhecida: {action}")
        if family not in families():
            raise FloorplanError(f"família desconhecida: {family}")
        if layers not in (2, 4):
            raise FloorplanError("camadas: 2 ou 4")
        if not isinstance(sim, bool):
            raise FloorplanError("simulação: true ou false")
        make = find_make()
        if not make:
            raise FloorplanError("make não encontrado no PATH")
        cmd = [make, TARGETS[action], f"PCB_TOP={self.top}", f"PCB_LIB=pcbflow/lib/{family}",
               f"PCB_FLOORPLAN={rel(self.path) if self.path and self.path.exists() else ''}",
               f"PCB_ARGS=--layers {layers}"]
        if self.src and not default_source(self.src):
            cmd.append(f"PCB_SRC_EXTRA={rel(self.src)}")
        if not sim:
            cmd.append("PCB_TB=")
        name = f"{self.top}_{family}" + ("_2l" if layers == 2 else "")
        self.job.start(cmd, {"action": action, "top": self.top, "family": family, "layers": layers, "run": name})
        return {"ok": True}

    def report(self, name):
        for f in self.runs():
            if f.parent.name == name and (f.parent / "report.md").is_file():
                return (f.parent / "report.md").read_bytes()
        return None


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
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path == "/":
                    self._send(200, (PKG / "fpedit.html").read_bytes(), "text/html; charset=utf-8")
                elif u.path == "/api/state":
                    self._send(200, ed.state())
                elif u.path == "/api/fs":
                    self._send(200, list_dir(q.get("dir", "")))
                elif u.path == "/api/job":
                    self._send(200, ed.job.snapshot(int(q.get("id", 0)), int(q.get("since", 0))))
                elif u.path == "/api/report":
                    body = ed.report(q.get("run", ""))
                    if body is None:
                        self._send(404, {"error": "relatório não encontrado"})
                    else:
                        self._send(200, body, "text/plain; charset=utf-8")
                else:
                    self._send(404, {"error": "não encontrado"})
            except (FloorplanError, ValueError) as e:
                self._send(400, {"error": str(e)})

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
                    self._send(200, check(drop_legacy(req.get("data")), run, ed.path.name if ed.path else "floorplan"))
                elif u.path == "/api/save":
                    self._send(200, ed.save(req.get("data"), req.get("mtime"), req.get("force", False)))
                elif u.path == "/api/modules":
                    p = in_repo(req.get("file"))
                    self._send(200, {"modules": modules_in(p) if p.is_file() else []})
                elif u.path == "/api/open":
                    self._send(200, ed.open(req.get("file"), req.get("top")))
                elif u.path == "/api/job/start":
                    self._send(200, ed.start(req.get("action"), req.get("family"), req.get("layers"),
                                                  req.get("sim", True)))
                elif u.path == "/api/job/cancel":
                    ed.job.cancel()
                    self._send(200, {"ok": True})
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
    ap.add_argument("file", nargs="?", help=f"<top>{SUFFIX} (criado ao salvar se não existir)")
    ap.add_argument("--lib", help="família inicial do menu (pasta da biblioteca ou só o nome, ex.: rtl); "
                                  "padrão: a da rodada mais recente")
    ap.add_argument("--layers", type=int, choices=(2, 4), help="camadas iniciais do menu")
    ap.add_argument("--host", default="127.0.0.1", help="endereço do servidor (padrão: 127.0.0.1)")
    ap.add_argument("--port", type=int, help="porta (padrão: 8765, ou uma livre se estiver ocupada)")
    ap.add_argument("--no-browser", action="store_true", help="não abre o navegador")
    args = ap.parse_args(argv)

    ed = Editor()
    if args.file:
        path = resolve_file(args.file)
        ed.set(path, None, None)
        ed.src = source_of(path, ed.top)
    runs = ed.runs()
    newest = run_summary(runs[0]) if runs else {}
    ed.init = {"family": Path(args.lib).name if args.lib else newest.get("family"),
               "layers": args.layers or newest.get("layers")}
    if ed.init["family"] and ed.init["family"] not in families():
        raise SystemExit(f"família '{ed.init['family']}' não existe em {LIBS}")
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

    if ed.path:
        print(f"Floorplan: {ed.path}" + ("" if ed.path.exists() else " (novo, criado ao salvar)"))
        print(f"Fonte:     {ed.src or 'não encontrado (o make procura <top>.v em rtl/)'}")
    else:
        print("Floorplan: nenhum; escolha o top pelo botão Abrir")
    if runs:
        print(f"Rodadas:   {', '.join(f.parent.name for f in runs)}")
    print(f"Editor:    {url}   (Ctrl+C para sair)")
    if not args.no_browser and not webbrowser.open(url):
        print("           nenhum navegador padrão encontrado; abra o endereço acima")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        ed.job.cancel()
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
