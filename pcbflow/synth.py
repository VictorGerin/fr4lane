"""Síntese com Yosys mapeando para a biblioteca de células discretas."""

import os
import shutil
import subprocess
from pathlib import Path


def find_yosys():
    exe = shutil.which("yosys")
    if exe:
        return exe
    for cand in ("C:/msys64/ucrt64/bin/yosys.exe", "C:/msys64/mingw64/bin/yosys.exe"):
        if Path(cand).exists():
            return cand
    raise FileNotFoundError("yosys não encontrado (MSYS2: pacman -S mingw-w64-ucrt-x86_64-yosys)")


def run_yosys(sources, top, liberty, outdir, defines=(), flatten=False):
    """Sintetiza e mapeia para as células da biblioteca.

    Por padrão cada módulo é mapeado separadamente e o netlist só é achatado
    no fim: os nomes das células guardam a instância de origem
    (ex.: "u_fa.$abc$..."), o que permite agrupar a placa por módulo.
    flatten=True achata antes do mapeamento, para o ABC otimizar através das
    fronteiras dos módulos (menos células, mas sem a hierarquia)."""
    outdir = Path(outdir)
    json_out = outdir / f"{top}_gates.json"
    hier_out = outdir / f"{top}_hier.json"
    v_out = outdir / f"{top}_gates.v"
    stat_out = outdir / "yosys_stat.txt"
    lib = Path(liberty).as_posix()
    defs = " ".join(f"-D{d}" for d in defines)
    reads = "\n".join(f"read_verilog -sv {defs} {Path(s).as_posix()}" for s in sources)
    script = f"""read_liberty -lib {lib}
{reads}
hierarchy -check -top {top}
synth {"-flatten " if flatten else ""}-top {top}
dfflibmap -liberty {lib}
abc -liberty {lib}
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
    with open(log, "w") as f:
        r = subprocess.run([find_yosys(), "-q", "-s", str(ys)], stdout=f, stderr=subprocess.STDOUT, env=env)
    if r.returncode != 0:
        tail = log.read_text(errors="replace").splitlines()[-30:]
        raise RuntimeError("Yosys falhou:\n" + "\n".join(tail))
    return json_out, v_out, stat_out, (None if flatten else hier_out)
