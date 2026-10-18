"""Confere, por simulação, que a montagem (.sp) de cada célula faz o que o
Liberty (.lib) declara. Combinacionais: todas as combinações de entrada.
Sequenciais: sequência aleatória de dados, bordas de clock (ou enable, nos
latches) e resets."""

import shutil
import subprocess
from pathlib import Path

from . import liberty
from .netlist import Design, Port, expand, write_switch_level_verilog


def _inactive_value(expr, pin):
    """Valor do pino que deixa clear/preset inativo (expressão de uma variável)."""
    ast = liberty.parse_expr(expr)
    for v in (0, 1):
        if not liberty.eval_expr(ast, {pin: v}):
            return v
    return 0


def check_cells(lib, outdir):
    outdir = Path(outdir).resolve() / "cellcheck"
    outdir.mkdir(parents=True, exist_ok=True)
    files = []
    tb = ["`timescale 1ns/1ps", "module tb_cells;", "  integer k, fails;"]
    body = ["  initial begin", "    fails = 0;"]
    for name, cell in lib.cells.items():
        d = Design(name, [Port(p, "input", p) for p in cell.inputs] +
                   [Port(p, "output", p) for p in cell.outputs], [], lib.vdd, lib.gnd)
        expand(lib, d, name, "dut", {p: p for p in cell.pins}, "dut", name)
        f = outdir / f"impl_{name}.v"
        write_switch_level_verilog(lib, d, f, module_name=f"impl_{name}")
        files.append(f)
        pre = f"c_{name}_"
        for p in cell.inputs:
            tb.append(f"  reg {pre}{p};")
        for o in cell.outputs:
            tb.append(f"  wire {pre}{o}_i, {pre}{o}_r;")
        conn_i = ", ".join([f".{p}({pre}{p})" for p in cell.inputs] + [f".{o}({pre}{o}_i)" for o in cell.outputs])
        conn_r = ", ".join([f".{p}({pre}{p})" for p in cell.inputs] + [f".{o}({pre}{o}_r)" for o in cell.outputs])
        tb.append(f"  impl_{name} i_{name}({conn_i});")
        tb.append(f"  ref_{name} r_{name}({conn_r});")
        ins = "{" + ", ".join(f"{pre}{p}" for p in cell.inputs) + "}"
        compare = []
        for o in cell.outputs:
            compare.append(f"      if ({pre}{o}_r !== 1'bx && {pre}{o}_i !== {pre}{o}_r) begin "
                           f"$display(\"CELLFAIL {name}.{o} entradas=%b obtido=%b esperado=%b\", "
                           f"{ins}, {pre}{o}_i, {pre}{o}_r); fails = fails + 1; end")
        if not cell.seq:
            n = len(cell.inputs)
            body.append(f"    for (k = 0; k < {2 ** n}; k = k + 1) begin")
            body.append(f"      {ins} = k; #1;")
            body += compare
            body.append("    end")
        elif cell.latch:
            # latch: D e enable mudam em passos separados (mudar os dois juntos
            # é corrida no circuito real); confere transparente e travado
            lt = cell.latch
            en = sorted(liberty.expr_vars(liberty.parse_expr(lt["enable"])))[0]
            asyn = {}
            for key in ("clear", "preset"):
                if key in lt:
                    for v in liberty.expr_vars(liberty.parse_expr(lt[key])):
                        asyn[v] = _inactive_value(lt[key], v)
            data = [p for p in cell.inputs if p != en and p not in asyn]
            body.append(f"    {pre}{en} = 1;")
            for p in data:
                body.append(f"    {pre}{p} = 0;")
            for p, v in asyn.items():
                body.append(f"    {pre}{p} = {1 - v}; #2; {pre}{p} = {v};")
            body.append("    #5;")
            body.append("    for (k = 0; k < 400; k = k + 1) begin")
            for p in data:
                body.append(f"      {pre}{p} = $random;")
            body.append("      #5;")
            body += compare
            body.append(f"      {pre}{en} = $random;")
            for p, v in asyn.items():
                body.append(f"      {pre}{p} = (($random & 7) == 0) ? {1 - v} : {v};")
            body.append("      #5;")
            body += compare
            body.append("    end")
        else:
            ff = cell.ff
            clk = sorted(liberty.expr_vars(liberty.parse_expr(ff["clocked_on"])))[0]
            asyn = {}
            for key in ("clear", "preset"):
                if key in ff:
                    for v in liberty.expr_vars(liberty.parse_expr(ff[key])):
                        asyn[v] = _inactive_value(ff[key], v)
            data = [p for p in cell.inputs if p != clk and p not in asyn]
            body.append(f"    {pre}{clk} = 0;")
            for p in data:
                body.append(f"    {pre}{p} = 0;")
            for p, v in asyn.items():
                body.append(f"    {pre}{p} = {1 - v}; #2; {pre}{p} = {v};")
            body.append("    for (k = 0; k < 400; k = k + 1) begin")
            for p in data:
                body.append(f"      {pre}{p} = $random;")
            for p, v in asyn.items():
                body.append(f"      {pre}{p} = (($random & 7) == 0) ? {1 - v} : {v};")
            body.append("      #5;")
            body += compare
            body.append(f"      {pre}{clk} = ~{pre}{clk}; #5;")
            body += compare
            body.append("    end")
        ref = outdir / f"ref_{name}.v"
        ref.write_text("`timescale 1ns/1ps\n" + "\n".join(lib.reference_model(cell, f"ref_{name}")) + "\n")
        files.append(ref)
    body += ['    $display("CELLDONE %0d", fails);', "    $finish;", "  end"]
    tbf = outdir / "tb_cells.v"
    tbf.write_text("\n".join(tb + body + ["endmodule"]) + "\n")
    iverilog = shutil.which("iverilog") or "C:/msys64/ucrt64/bin/iverilog.exe"
    vvp = shutil.which("vvp") or "C:/msys64/ucrt64/bin/vvp.exe"
    vvpf = outdir / "tb_cells.vvp"
    r = subprocess.run([iverilog, "-g2012", "-o", str(vvpf), str(tbf)] + [str(f) for f in files],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return [f"falha ao compilar a verificação de células:\n{r.stdout}{r.stderr}"]
    r = subprocess.run([vvp, "-n", str(vvpf)], capture_output=True, text=True, cwd=outdir)
    text = r.stdout + r.stderr
    (outdir / "cellcheck.log").write_text(text)
    fails = [l for l in text.splitlines() if l.startswith("CELLFAIL")]
    if "CELLDONE" not in text:
        fails.append("a simulação de verificação não terminou:\n" + text[-2000:])
    return fails[:40]
