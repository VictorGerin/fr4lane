"""Síntese com Yosys mapeando para a biblioteca de células discretas."""

import os
import re
import shutil
import subprocess
from pathlib import Path

from .progress import Progress

# "6. Executing ABC pass (...)" / "4.12. Executing OPT pass": passo do script e subpasso
_STEP = re.compile(r"^(\d+)(?:\.(\d+))?\. Executing (.+?)(?: pass)?(?: \(.*)?\.?$")


def find_yosys():
    exe = shutil.which("yosys")
    if exe:
        return exe
    for cand in ("C:/msys64/ucrt64/bin/yosys.exe", "C:/msys64/mingw64/bin/yosys.exe"):
        if Path(cand).exists():
            return cand
    raise FileNotFoundError("yosys não encontrado (MSYS2: pacman -S mingw-w64-ucrt-x86_64-yosys)")


def run_yosys(sources, top, liberty, outdir, defines=(), flatten=False, latches=None):
    """Sintetiza e mapeia para as células da biblioteca.

    Por padrão cada módulo é mapeado separadamente e o netlist só é achatado
    no fim: os nomes das células guardam a instância de origem
    (ex.: "u_fa.$abc$..."), o que permite agrupar a placa por módulo.
    flatten=True achata antes do mapeamento, para o ABC otimizar através das
    fronteiras dos módulos (menos células, mas sem a hierarquia).
    latches: (tipos internos, Verilog do techmap) de Library.latch_techmap();
    sem ele um latch inferido fica sem mapear e a síntese para com erro."""
    outdir = Path(outdir)
    json_out = outdir / f"{top}_gates.json"
    hier_out = outdir / f"{top}_hier.json"
    v_out = outdir / f"{top}_gates.v"
    stat_out = outdir / "yosys_stat.txt"
    lib = Path(liberty).as_posix()
    defs = " ".join(f"-D{d}" for d in defines)
    latch_cmds = ""
    if latches:
        types, text = latches
        lmap = outdir / "latch_map.v"
        lmap.write_text(text)
        latch_cmds = (f"dfflegalize {' '.join(f'-cell {t} x' for t in types)}\n"
                      f"techmap -map {lmap.as_posix()}\n")
    reads = "\n".join(f"read_verilog -sv {defs} {Path(s).as_posix()}" for s in sources)
    script = f"""read_liberty -lib {lib}
{reads}
hierarchy -check -top {top}
synth {"-flatten " if flatten else ""}-top {top}
dfflibmap -liberty {lib}
{latch_cmds}abc -liberty {lib}
opt_clean -purge
{"" if flatten else f'''write_json {hier_out.as_posix()}
flatten
opt_clean -purge
'''}setundef -zero
tee -q -o {stat_out.as_posix()} stat -liberty {lib}
check -assert
write_json {json_out.as_posix()}
write_verilog -noattr -noexpr {v_out.as_posix()}
"""
    ys = outdir / "synth.ys"
    ys.write_text(script)
    log = outdir / "yosys.log"
    # o ABC precisa de um diretório temporário gravável; sob o make do MSYS
    # TMP/TEMP podem não estar definidos e o Yosys cai em C:\WINDOWS
    tmp = (outdir / "tmp").resolve()
    tmp.mkdir(exist_ok=True)
    env = dict(os.environ, TMP=str(tmp), TEMP=str(tmp), TMPDIR=str(tmp))
    n_steps = sum(1 for l in script.splitlines() if l.strip())
    # sem -q o Yosys numera cada comando do script: é por aí que se sabe o passo atual
    with open(log, "w", encoding="utf-8") as f, Progress("síntese (Yosys)", tick=True) as pg:
        proc = subprocess.Popen([find_yosys(), "-s", str(ys)], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, env=env)
        top = ""
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace")
            f.write(line)
            m = _STEP.match(line.strip())
            if m:
                name = m.group(3).split(":")[0].strip().rstrip(".")
                if m.group(2) is None:
                    top = name
                    pg.update(info=f"passo {m.group(1)}/{n_steps}: {top}")
                else:
                    pg.update(info=f"passo {m.group(1)}/{n_steps}: {top} › {name}")
        rc = proc.wait()
    if rc != 0:
        tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-30:]
        raise RuntimeError("Yosys falhou:\n" + "\n".join(tail))
    return json_out, v_out, stat_out, (None if flatten else hier_out)
