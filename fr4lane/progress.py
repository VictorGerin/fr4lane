"""Progresso das etapas longas (síntese, simulação, placement, roteamento...).

Três saídas, conforme quem lê:
  - terminal: uma linha reescrita no lugar (\\r), com porcentagem, tempo e
    estimativa do que falta;
  - arquivo/pipe: a mesma linha, mas só a cada ~30 s (o log não incha);
  - fpedit (FR4LANE_PROGRESS=1): linhas "@progress {json}" a cada ~1 s, que o
    servidor do editor intercepta e mostra numa barra (não vão para o log).

Etapas com total conhecido (placement: passos do anelamento; roteamento: nets
da iteração) mostram porcentagem e estimativa; as outras (Yosys, simulação,
DRC) mostram o passo atual e o tempo decorrido, atualizado por um relógio.
"""

import json
import os
import sys
import threading
import time

MACHINE = os.environ.get("FR4LANE_PROGRESS") == "1"
QUIET = False             # processos auxiliares (macros em paralelo) não mostram progresso


def silence():
    global QUIET
    QUIET = True
_lock = threading.Lock()
_active = None            # Progress na tela (terminal), para limpar a linha antes de outro log


def clear_line():
    """Apaga a linha de progresso do terminal (chame antes de imprimir outra coisa)."""
    with _lock:
        p = _active
        if p is not None and p.tty and p.width:
            sys.stdout.write("\r" + " " * p.width + "\r")
            sys.stdout.flush()
            p.width = 0


def fmt_time(s):
    s = int(round(s))
    if s < 60:
        return f"{s} s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m} min {s:02d} s"
    h, m = divmod(m, 60)
    return f"{h} h {m:02d} min"


def _tty():
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


class Progress:
    """Use com 'with': update(done, info) no laço; o relógio (tick=True) mantém o
    tempo andando quando o trabalho não dá notícia (ex.: um processo externo)."""

    def __init__(self, label, total=None, tick=False, show_count=True):
        """total: unidades de trabalho (a fração done/total é o progresso);
        show_count=False esconde o '(done/total)' quando as unidades são pesos."""
        self.label, self.total, self.show_count = label, total, show_count
        self.done, self.info = 0, ""
        self.t0 = time.time()
        self.tty = _tty() and not MACHINE
        self.every = 1.0 if (MACHINE or self.tty) else 30.0
        # num arquivo/pipe a 1ª linha só sai depois de ~30 s: etapas curtas não poluem o log
        self.last = 0.0 if (MACHINE or self.tty) else self.t0
        self.width = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._clock, daemon=True) if tick else None

    def __enter__(self):
        global _active
        _active = self
        if self._thread:
            self._thread.start()
        self._emit(force=MACHINE)
        return self

    def __exit__(self, *exc):
        global _active
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        with _lock:
            if self.tty and self.width:
                sys.stdout.write("\r" + " " * self.width + "\r")
                sys.stdout.flush()
            if MACHINE and not QUIET:
                print("@progress " + json.dumps({"label": self.label, "end": True}), flush=True)
            if _active is self:
                _active = None
        return False

    def _clock(self):
        while not self._stop.wait(1.0):
            self._emit()

    def set_total(self, total):
        self.total = total

    def update(self, done=None, info=None):
        if done is not None:
            self.done = done
        if info is not None:
            self.info = info
        self._emit()

    def elapsed(self):
        return time.time() - self.t0

    def text(self):
        el = self.elapsed()
        parts = [self.label]
        if self.total:
            frac = min(1.0, self.done / self.total)
            parts.append(f"{frac * 100:.0f}%" + (f" ({self.done}/{self.total})" if self.show_count else ""))
        if self.info:
            parts.append(self.info)
        tail = fmt_time(el)
        eta = self.eta()
        if eta is not None:
            tail += f", faltam ~{fmt_time(eta)}"
        parts.append(tail)
        return " · ".join(parts)

    def eta(self):
        el = self.elapsed()
        if not self.total or self.done <= 0 or el < 3:
            return None
        return el * (self.total - self.done) / self.done

    def _emit(self, force=False):
        if QUIET:
            return
        now = time.time()
        if not force and now - self.last < self.every:
            return
        self.last = now
        with _lock:
            if MACHINE:
                eta = self.eta()
                print("@progress " + json.dumps({
                    "label": self.label, "done": self.done, "total": self.total, "info": self.info,
                    "elapsed": round(self.elapsed(), 1), "eta": None if eta is None else round(eta, 1)},
                    ensure_ascii=False), flush=True)
            elif self.tty:
                line = "      " + self.text()
                pad = max(0, self.width - len(line))
                sys.stdout.write("\r" + line + " " * pad)
                sys.stdout.flush()
                self.width = len(line)
            else:
                print("      " + self.text(), flush=True)
