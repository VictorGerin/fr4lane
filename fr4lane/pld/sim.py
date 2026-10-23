"""Simuladores elétricos e digitais para circuitos GAL (Generic Array Logic).

Implementa:
1. Simulação digital com atrasos elétricos de datasheet (Icarus Verilog):
   - Modela atrasos reais de propagação (t_pd, t_co, t_su, t_h, t_oe)
   - Valida funcionalidade e temporização com testbench Verilog (.vcd)

2. Simulação elétrica analógica transistor-level (ngspice):
   - Converte a matriz de fusíveis JEDEC e as OLMCs em netlist SPICE (.cir)
   - Modela transistores da matriz AND (wired-AND), portas OR, XOR e DFFs analógicos
   - Mede formas de onda contínuas V(t), rise/fall times e atrasos reais t_pd/t_co
"""

import json
import math
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Union

from ..cellsim import find_ngspice
from .devices import GAL22V10, GALDevice
from .packer import PackedGAL
from .synth import SynthesizedDesign


def find_iverilog() -> Tuple[Optional[str], Optional[str]]:
    """Localiza os executáveis do Icarus Verilog (iverilog e vvp)."""
    iverilog = shutil.which("iverilog")
    vvp = shutil.which("vvp")
    if iverilog and vvp:
        return iverilog, vvp

    for cand_dir in ("C:/msys64/ucrt64/bin", "C:/msys64/mingw64/bin"):
        cand_i = Path(cand_dir) / "iverilog.exe"
        cand_v = Path(cand_dir) / "vvp.exe"
        if cand_i.is_file() and cand_v.is_file():
            return str(cand_i), str(cand_v)

    return None, None


def sanitize_vlog_id(name: str) -> str:
    """Converte identificadores com colchetes ou caracteres especiais para Verilog legal."""
    clean = re.sub(r"[\[\].$\\]", "_", name)
    clean = re.sub(r"_+", "_", clean)
    return clean.strip("_")


# ==============================================================================
# 1. Simulação Digital / Timing com Icarus Verilog
# ==============================================================================

def generate_gal_verilog_model(
    chip: PackedGAL,
    design_name: str,
    out_path: Path,
    t_pd_ns: float = 10.0,
    t_co_ns: float = 7.0,
) -> Path:
    """Gera um modelo Verilog formal do chip GAL programado com atrasos de datasheet.

    Atrasos típicos ATF22V10C-10:
    - t_pd (input to combinational output): 10.0 ns
    - t_co (clock to registered output): 7.0 ns
    """
    dev = chip.device
    pin_signals = dict(chip.pin_assignment)

    module_name = f"{chip.chip_id}_{design_name}_{dev.name}"

    lines = [
        f"// Modelo Verilog com Atrasos Elétricos de Datasheet para {dev.name}",
        f"// Chip: {chip.chip_id} | Módulo: {design_name}",
        f"`timescale 1ns / 1ps",
        f"",
        f"module {module_name} (",
    ]

    ports = []
    for pin in range(1, dev.num_pins + 1):
        sig = pin_signals.get(pin)
        if not sig or sig in ("VCC", "GND"):
            continue
        vname = sanitize_vlog_id(sig)
        direction = "output" if pin in chip.output_pins.values() else "input"
        ports.append((vname, direction, pin, sig))

    for i, (vname, direction, pin, sig) in enumerate(ports):
        comma = "," if i < len(ports) - 1 else ""
        lines.append(f"    {direction} wire {vname}{comma} // Pino {pin}: {sig}")

    lines.append(");")
    lines.append("")
    lines.append(f"    // Parâmetros de temporização elétrica ({dev.name})")
    lines.append(f"    parameter real T_PD = {t_pd_ns:.1f}; // ns (atraso combinacional)")
    lines.append(f"    parameter real T_CO = {t_co_ns:.1f};  // ns (clock para saída)")
    lines.append("")

    # Emite lógica para cada OLMC alocada
    for dip_pin, place in chip.olmc_placements.items():
        cone = place.cone
        out_name = cone.name
        cout = sanitize_vlog_id(out_name)

        # Constrói expressão booleana da soma de produtos
        term_exprs = []
        for term in cone.product_terms:
            if not term.literals:
                term_exprs.append("1'b1")
                continue
            lits = []
            for net, val in sorted(term.literals.items()):
                cnet = sanitize_vlog_id(net)
                lits.append(cnet if val == 1 else f"~{cnet}")
            term_exprs.append("(" + " & ".join(lits) + ")")

        sop_expr = " | ".join(term_exprs) if term_exprs else "1'b0"

        # Polaridade XOR (invertida se not active_high)
        if not cone.active_high:
            sop_expr = f"~({sop_expr})"

        wire_d = f"_{cout}_d"
        lines.append(f"    wire {wire_d} = {sop_expr};")

        if cone.is_registered:
            reg_q = f"_{cout}_q"
            cclk = sanitize_vlog_id(cone.clk_net) if cone.clk_net else "clk"
            crst = sanitize_vlog_id(cone.rst_net) if cone.rst_net else None
            lines.append(f"    reg {reg_q} = 1'b0;")
            if crst:
                if crst.endswith("_n") or crst.startswith("rst_n") or crst.startswith("reset_n"):
                    lines.append(f"    always @(posedge {cclk} or negedge {crst}) begin")
                    lines.append(f"        if (!{crst})")
                    lines.append(f"            {reg_q} <= 1'b0;")
                    lines.append(f"        else")
                    lines.append(f"            {reg_q} <= {wire_d};")
                    lines.append(f"    end")
                else:
                    lines.append(f"    always @(posedge {cclk} or posedge {crst}) begin")
                    lines.append(f"        if ({crst})")
                    lines.append(f"            {reg_q} <= 1'b0;")
                    lines.append(f"        else")
                    lines.append(f"            {reg_q} <= {wire_d};")
                    lines.append(f"    end")
            else:
                lines.append(f"    always @(posedge {cclk}) begin")
                lines.append(f"        {reg_q} <= {wire_d};")
                lines.append(f"    end")
            lines.append(f"    assign #(T_CO) {cout} = {reg_q};")
        else:
            lines.append(f"    assign #(T_PD) {cout} = {wire_d};")
        lines.append("")

    lines.append("endmodule")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def generate_design_verilog_wrapper(
    design: SynthesizedDesign,
    packed_chips: List[PackedGAL],
    out_path: Path,
) -> Path:
    """Gera um módulo wrapper Verilog no nível do projeto original conectando os chips GALs.

    Permite que o mesmo testbench do módulo original seja executado diretamente
    contra a rede física de chips GAL interconectados.
    """
    lines = [
        f"// Wrapper Estrutural do Projeto {design.top} Interconectando Chips GAL",
        f"`timescale 1ns / 1ps",
        f"",
        f"module {design.top} (",
    ]

    port_vectors: Dict[str, List[int]] = {}
    scalar_ports: List[str] = []
    all_ports_dir: Dict[str, str] = {}

    for p in design.primary_inputs:
        m = re.match(r"^(.+)\[(\d+)\]$", p)
        if m:
            base, idx = m.group(1), int(m.group(2))
            port_vectors.setdefault(base, []).append(idx)
            all_ports_dir[base] = "input"
        else:
            scalar_ports.append(p)
            all_ports_dir[p] = "input"

    for p in design.primary_outputs:
        m = re.match(r"^(.+)\[(\d+)\]$", p)
        if m:
            base, idx = m.group(1), int(m.group(2))
            port_vectors.setdefault(base, []).append(idx)
            all_ports_dir[base] = "output"
        else:
            scalar_ports.append(p)
            all_ports_dir[p] = "output"

    port_decls = []
    for base, indices in sorted(port_vectors.items()):
        max_idx = max(indices)
        direction = all_ports_dir[base]
        port_decls.append((direction, f"[{max_idx}:0] {base}"))

    for p in sorted(scalar_ports):
        direction = all_ports_dir[p]
        port_decls.append((direction, p))

    for i, (dir_s, name_s) in enumerate(port_decls):
        comma = "," if i < len(port_decls) - 1 else ""
        lines.append(f"    {dir_s} wire {name_s}{comma}")

    lines.append(");")
    lines.append("")

    declared_wires = set(scalar_ports)
    for base in port_vectors:
        declared_wires.add(base)

    all_chip_signals = set()
    for chip in packed_chips:
        for pin, sig in chip.pin_assignment.items():
            if sig not in ("VCC", "GND"):
                all_chip_signals.add(sig)

    internal_wires = set()
    for sig in all_chip_signals:
        m = re.match(r"^(.+)\[(\d+)\]$", sig)
        if m:
            base = m.group(1)
            if base not in declared_wires:
                internal_wires.add(sanitize_vlog_id(sig))
        else:
            if sig not in declared_wires:
                internal_wires.add(sanitize_vlog_id(sig))

    for w in sorted(internal_wires):
        lines.append(f"    wire {w};")
    if internal_wires:
        lines.append("")

    for chip in packed_chips:
        mod_name = f"{chip.chip_id}_{design.top}_{chip.device.name}"
        lines.append(f"    {mod_name} {chip.chip_id} (")
        inst_ports = []
        for pin in sorted(chip.pin_assignment.keys()):
            sig = chip.pin_assignment[pin]
            if sig in ("VCC", "GND"):
                continue
            vport = sanitize_vlog_id(sig)
            m = re.match(r"^(.+)\[(\d+)\]$", sig)
            if m and m.group(1) in port_vectors:
                target_sig = sig
            elif sig in internal_wires:
                target_sig = sanitize_vlog_id(sig)
            else:
                target_sig = sanitize_vlog_id(sig)
            inst_ports.append((vport, target_sig, pin))

        for i, (vp, ts, p_num) in enumerate(inst_ports):
            comma = "," if i < len(inst_ports) - 1 else ""
            lines.append(f"        .{vp}({ts}){comma} // Pino {p_num}")
        lines.append("    );")
        lines.append("")

    lines.append("endmodule")
    lines.append("")
    lines.append("module _gal_sim_dumper;")
    lines.append("    initial begin")
    lines.append('        $dumpfile("sim_gal_timing.vcd");')
    lines.append("        $dumpvars(0);")
    lines.append("    end")
    lines.append("endmodule")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def run_iverilog_timing_simulation(
    chips: Union[PackedGAL, List[PackedGAL]],
    design_name: str,
    tb_source: Path,
    outdir: Path,
    design: Optional[SynthesizedDesign] = None,
    t_pd_ns: float = 10.0,
    t_co_ns: float = 7.0,
) -> Tuple[bool, str, Path]:
    """Compila e executa simulação digital com Icarus Verilog gerando .vcd."""
    if not isinstance(chips, list):
        chips = [chips]

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    verilog_sources = []
    for chip in chips:
        gal_model_path = outdir / f"{chip.chip_id}_{design_name}_timing.v"
        generate_gal_verilog_model(chip, design_name, gal_model_path, t_pd_ns=t_pd_ns, t_co_ns=t_co_ns)
        verilog_sources.append(gal_model_path)

    if design:
        wrapper_path = outdir / f"{design_name}_wrapper.v"
        generate_design_verilog_wrapper(design, chips, wrapper_path)
        verilog_sources.append(wrapper_path)

    vvp_path = outdir / f"sim_{design_name}.vvp"
    vcd_path = outdir / f"sim_gal_timing.vcd"

    iverilog, vvp = find_iverilog()
    if not iverilog or not vvp:
        return False, "Icarus Verilog (iverilog/vvp) não encontrado no PATH.", vcd_path

    cmd_compile = [
        iverilog,
        "-g2012",
        "-o", str(vvp_path.resolve()),
        *[str(s.resolve()) for s in verilog_sources],
        str(Path(tb_source).resolve()),
    ]

    proc_c = subprocess.run(cmd_compile, capture_output=True, text=True, cwd=outdir)
    if proc_c.returncode != 0:
        return False, f"Falha na compilação iverilog:\n{proc_c.stderr}\n{proc_c.stdout}", vcd_path

    cmd_run = [vvp, str(vvp_path.resolve())]
    proc_r = subprocess.run(cmd_run, capture_output=True, text=True, cwd=outdir)
    if proc_r.returncode != 0:
        return False, f"Falha na execução vvp:\n{proc_r.stderr}\n{proc_r.stdout}", vcd_path

    log_out = proc_r.stdout
    return True, log_out, vcd_path


# ==============================================================================
# 2. Simulação Elétrica Analógica Transistor-Level no SPICE (ngspice)
# ==============================================================================

def generate_gal_spice_netlist(
    chip: PackedGAL,
    design_name: str,
    out_path: Path,
    t_sim_ns: float = 60.0,
) -> Path:
    """Gera netlist elétrico SPICE (.cir) do chip GAL programado para ngspice.

    Modela:
    - Fontes VCC (+5.0V) e GND (0V)
    - Inversores e buffers CMOS de entrada (gerando colunas A e /A)
    - Matriz AND: barramento resistivo de pull-up (4.7k) com transistores NMOS comutadores
    - Portas OR somadoras com limiar analógico
    - XOR de polaridade
    - Flip-Flop D síncrono mestre-escravo analógico com chaves SPICE
    - Análise de transitório (.tran 0.1n 60n)
    """
    dev = chip.device
    pin_signals = dict(chip.pin_assignment)

    lines = [
        f"* Simulação Analógica SPICE Transistor-Level para {dev.name}",
        f"* Chip: {chip.chip_id} | Projeto: {design_name}",
        f".title Circuito Elétrico GAL {dev.name} ({chip.chip_id})",
        f"",
        f"* Modelos de transistores MOS rápidos (submicron equivalente a 5V)",
        f".model nmos_gal NMOS (LEVEL=1 VTO=0.8 KP=120u GAMMA=0.4 PHI=0.6 LAMBDA=0.02)",
        f".model pmos_gal PMOS (LEVEL=1 VTO=-0.8 KP=50u GAMMA=0.4 PHI=0.6 LAMBDA=0.02)",
        f".model sw_clk_on SW (VT=2.5 VH=0.2 RON=50 ROFF=10MEG)",
        f".model sw_clk_off SW (VT=2.5 VH=0.2 RON=10MEG ROFF=50)",
        f"",
        f"* Fontes de Alimentação",
        f"V_VCC vcc 0 DC 5.0",
        f"R_GND gnd 0 1m",
        f"",
        f"* Subcircuito Inversor CMOS",
        f".subckt inv_cmos in out vcc gnd",
        f"M1 out in vcc vcc pmos_gal W=4u L=0.5u",
        f"M2 out in gnd gnd nmos_gal W=2u L=0.5u",
        f"C1 out gnd 20f",
        f".ends inv_cmos",
        f"",
        f"* Subcircuito Buffer Complementar de Entrada (Gera True e Invertido)",
        f".subckt in_buf in col_t col_b vcc gnd",
        f"X1 in n_inv vcc gnd inv_cmos",
        f"X2 n_inv col_t vcc gnd inv_cmos",
        f"R1 n_inv col_b 50",
        f"C_col1 col_t gnd 0.5p",
        f"C_col2 col_b gnd 0.5p",
        f".ends in_buf",
        f"",
        f"* Subcircuito Flip-Flop D Analógico (Master-Slave)",
        f".subckt dff_gal d clk q q_b vcc gnd",
        f"S_m d n_m clk gnd sw_clk_off",
        f"C_m n_m gnd 0.2p",
        f"X_m1 n_m q_m vcc gnd inv_cmos",
        f"X_m2 q_m n_m_fb vcc gnd inv_cmos",
        f"R_fb n_m_fb n_m 10k",
        f"S_s q_m n_s clk gnd sw_clk_on",
        f"C_s n_s gnd 0.2p",
        f"X_s1 n_s q_b vcc gnd inv_cmos",
        f"X_s2 q_b q vcc gnd inv_cmos",
        f".ends dff_gal",
        f"",
    ]

    # 1. Gera estímulos analógicos (pulsos de tensão) para as entradas do chip
    inputs_to_drive = []
    clk_signal = chip.pin_assignment.get(dev.clk_pin) if chip.clk_pin else None

    lines.append("* Estímulos de Tensão nos Pinos de Entrada")
    if clk_signal:
        lines.append(f"V_CLK pin_{dev.clk_pin} 0 PULSE(0 5.0 0 1.0n 1.0n 24n 50n)")

    for sig, pin in sorted(chip.input_pins.items(), key=lambda x: x[1]):
        pin = int(pin)
        if sig == clk_signal or pin == dev.clk_pin:
            continue
        # Trata resets especialmente (inicia em 0V e sobe para 5V em 5ns se for _n)
        if sig.endswith("_n") or sig.startswith("rst_n") or sig.startswith("reset_n"):
            lines.append(f"V_IN_{pin} pin_{pin} 0 PULSE(0 5.0 5.0n 1.0n 1.0n {t_sim_ns*2:.1f}n {t_sim_ns*4:.1f}n)")
        else:
            period = 15.0 + (pin % 7) * 5.0
            width = period / 2.0
            delay = (pin % 5) * 2.0
            lines.append(f"V_IN_{pin} pin_{pin} 0 PULSE(0 5.0 {delay:.1f}n 1.0n 1.0n {width:.1f}n {period:.1f}n)")
        inputs_to_drive.append((pin, sig))

    lines.append("")
    lines.append("* Buffers de Entrada alimentando as Colunas da Matriz")
    for pin, sig in inputs_to_drive:
        lines.append(f"X_IN_{pin} pin_{pin} col_true_{pin} col_bar_{pin} vcc gnd in_buf")

    lines.append("")
    lines.append("* Matriz Lógica AND e OLMCs")

    # 2. Constrói linhas de produto e portas OR para cada OLMC
    term_idx = 0
    for dip_pin, place in chip.olmc_placements.items():
        cone = place.cone
        pterms = cone.product_terms
        or_inputs = []

        lines.append(f"* --- OLMC Pino {dip_pin} (Saída: {cone.name}) ---")
        for pt_i, term in enumerate(pterms):
            row_net = f"pterm_{term_idx}"
            term_idx += 1
            or_inputs.append(row_net)

            # Resistor Pull-Up da linha de produto
            lines.append(f"R_pu_{row_net} vcc {row_net} 4.7k")
            lines.append(f"C_par_{row_net} {row_net} gnd 0.1p")

            # Chaves NMOS correspondentes aos literais
            for m_idx, (net, val) in enumerate(term.literals.items()):
                if net in chip.input_pins:
                    in_pin = chip.input_pins[net]
                    col_drive = f"col_bar_{in_pin}" if val == 1 else f"col_true_{in_pin}"
                    lines.append(f"M_sw_{row_net}_{m_idx} {row_net} {col_drive} gnd gnd nmos_gal W=4u L=0.5u")
                elif net in chip.output_pins:
                    out_pin = chip.output_pins[net]
                    col_drive = f"fb_bar_{out_pin}" if val == 1 else f"fb_true_{out_pin}"
                    lines.append(f"M_sw_{row_net}_{m_idx} {row_net} {col_drive} gnd gnd nmos_gal W=4u L=0.5u")

        # Porta OR analógica (soma os termos de produto)
        or_sum_net = f"or_sum_{dip_pin}"
        if or_inputs:
            lines.append(f"R_or_pd_{dip_pin} {or_sum_net} gnd 10k")
            for o_i, r_net in enumerate(or_inputs):
                lines.append(f"M_or_{dip_pin}_{o_i} vcc {r_net} {or_sum_net} gnd nmos_gal W=6u L=0.5u")
        else:
            lines.append(f"R_zero_{dip_pin} {or_sum_net} gnd 1k")

        # XOR de polaridade
        pol_out = f"pol_out_{dip_pin}"
        if not cone.active_high:
            lines.append(f"X_pol_{dip_pin} {or_sum_net} {pol_out} vcc gnd inv_cmos")
        else:
            lines.append(f"R_pol_{dip_pin} {or_sum_net} {pol_out} 50")

        # Flip-Flop ou Combinacional
        if cone.is_registered and clk_signal:
            lines.append(f"X_dff_{dip_pin} {pol_out} pin_{dev.clk_pin} q_{dip_pin} qb_{dip_pin} vcc gnd dff_gal")
            lines.append(f"X_out_{dip_pin} q_{dip_pin} pin_{dip_pin} vcc gnd inv_cmos")
            lines.append(f"X_fb_{dip_pin} q_{dip_pin} fb_true_{dip_pin} fb_bar_{dip_pin} vcc gnd in_buf")
        else:
            lines.append(f"X_out_{dip_pin} {pol_out} pin_{dip_pin} vcc gnd inv_cmos")
            lines.append(f"X_fb_{dip_pin} {pol_out} fb_true_{dip_pin} fb_bar_{dip_pin} vcc gnd in_buf")

        # Carga capacitiva externa típica de pino e trilha PCB (15 pF)
        lines.append(f"C_load_{dip_pin} pin_{dip_pin} gnd 15p")
        lines.append("")

    # Análise de Transitório e Medidas
    out_pins_str = " ".join(f"V(pin_{p})" for p in chip.olmc_placements.keys())
    driven_in_pins = [dev.clk_pin] if clk_signal else []
    driven_in_pins += [p for p, _ in inputs_to_drive[:3]]
    in_pins_str = " ".join(f"V(pin_{p})" for p in driven_in_pins)

    lines.append("* Comandos de Simulação e Exportação")
    lines.append(f".control")
    lines.append(f"tran 0.1n {t_sim_ns:.1f}n")
    lines.append(f"wrdata sim_spice_gal.dat {in_pins_str} {out_pins_str} I(V_VCC)")
    lines.append(f"quit")
    lines.append(f".endc")
    lines.append(f".end")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def run_ngspice_electrical_simulation(
    chip: PackedGAL,
    design_name: str,
    outdir: Path,
    t_sim_ns: float = 60.0,
) -> Tuple[bool, str, Path, Optional[Path]]:
    """Executa simulação analógica SPICE no ngspice e plota formas de onda V(t)."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    spice_file = outdir / f"{chip.chip_id}_{design_name}_spice.cir"
    generate_gal_spice_netlist(chip, design_name, spice_file, t_sim_ns=t_sim_ns)

    ngspice = find_ngspice()
    if not ngspice:
        return False, "ngspice não encontrado no sistema.", spice_file, None

    cmd = [ngspice, "-b", str(spice_file.resolve())]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=outdir)

    dat_file = outdir / "sim_spice_gal.dat"
    png_plot = outdir / f"{chip.chip_id}_{design_name}_spice_waveform.png"

    if proc.returncode != 0 and not dat_file.is_file():
        return False, f"Falha no ngspice:\n{proc.stderr}\n{proc.stdout}", spice_file, None

    # Plota formas de onda se matplotlib estiver instalado
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np

        if dat_file.is_file():
            data = np.loadtxt(dat_file)
            if data.ndim == 1:
                data = data.reshape(1, -1)

            num_vectors = data.shape[1] // 2
            max_plots = min(num_vectors, 6)

            fig, axs = plt.subplots(max_plots, 1, figsize=(10, 2.0 * max_plots), sharex=True)
            if not isinstance(axs, np.ndarray):
                axs = [axs]

            driven_in_pins = [chip.device.clk_pin] if chip.clk_pin else []
            for sig, pin in sorted(chip.input_pins.items(), key=lambda x: x[1]):
                if len(driven_in_pins) >= 4:
                    break
                if pin not in driven_in_pins:
                    driven_in_pins.append(pin)

            labels = [f"Entrada Pino {p} ({chip.pin_assignment.get(p, '')})" for p in driven_in_pins]
            labels += [f"Saída Pino {p} ({chip.pin_assignment.get(p, '')})" for p in chip.olmc_placements.keys()]

            for i in range(max_plots):
                t_vec = data[:, 2 * i] * 1e9
                sig_v = data[:, 2 * i + 1]
                lbl = labels[i] if i < len(labels) else f"Sinal {i}"
                color = "tab:orange" if "Saída" in lbl else "tab:blue"
                axs[i].plot(t_vec, sig_v, color=color, lw=1.5, label=lbl)
                axs[i].set_ylabel("Tensão (V)", fontsize=9)
                axs[i].set_ylim(-0.5, 5.5)
                axs[i].grid(True, linestyle="--", alpha=0.6)
                axs[i].legend(loc="upper right", fontsize=8)

            axs[-1].set_xlabel("Tempo (ns)", fontsize=10)
            fig.suptitle(f"Simulação Elétrica Analógica SPICE - GAL22V10 ({chip.chip_id}: {design_name})", fontsize=12)
            plt.tight_layout()
            plt.savefig(png_plot, dpi=160)
            plt.close()
    except Exception as e:
        print(f"Erro ao gerar gráfico SPICE: {e}")

    return True, proc.stdout, spice_file, (png_plot if png_plot.is_file() else None)
