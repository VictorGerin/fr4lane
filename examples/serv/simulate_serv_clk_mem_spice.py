#!/usr/bin/env python3
"""
simulate_serv_clk_mem_spice.py:
Gera e executa a simulação analógica SPICE transistor-level no ngspice
para o Controlador Discreto RTL de Clock e Memórias do SERV (BC548B).
"""

import os
import re
import subprocess
import sys
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt

SERV_DIR = Path("C:/Users/victo/Documents/pcbflow/examples/serv")
BUILD_DIR = SERV_DIR / "build/pcb/serv_clk_mem_ctrl_rtl"
RTL_LIB_DIR = Path("C:/Users/victo/Documents/pcbflow/fr4lane/lib/rtl")
CIR_PATH = BUILD_DIR / "serv_clk_mem_spice.cir"
DAT_PATH = BUILD_DIR / "sim_spice_rtl.dat"
PNG_PATH = BUILD_DIR / "serv_clk_mem_spice_waveform.png"

# Mapeamento de pinos dos subcircuitos RTL
PIN_ORDER = {
    "INV": ["A", "Y"],
    "BUF": ["A", "Y"],
    "NOR2": ["A", "B", "Y"],
    "NOR3": ["A", "B", "C", "Y"],
    "NAND2": ["A", "B", "Y"],
    "AND2": ["A", "B", "Y"],
    "DFF": ["D", "C", "Q"],
    "DFFR": ["D", "C", "R", "Q"]
}

def build_spice_netlist():
    gates_v = (BUILD_DIR / "serv_clk_mem_ctrl_gates.v").read_text(encoding="utf-8")
    
    # 1. Carrega modelo do BC548B e alias para NPN
    bjt_model = (RTL_LIB_DIR / "spice/BC548B.lib").read_text(encoding="utf-8")
    bjt_model += "\n.model NPN NPN(Is=7.049f Xti=3 Eg=1.11 Vaf=54.76 Bf=250 Ise=78.17f Ne=1.479 Ikf=24.96m Nkf=.5381 Xtb=1.5 Br=1.2 Isc=27.51f Nc=1.775 Ikr=3.321 Rc=.9706 Cjc=4.25p Mjc=.3147 Vjc=.5697 Fc=.5 Cje=11.5p Mje=.6715 Vje=.5 Tr=10n Tf=410.7p Itf=1.12 Xtf=26.19 Vtf=10)\n"
    
    # 2. Carrega todos os subcircuitos das células usadas
    subckts = []
    for cell in ["INV", "BUF", "NOR2", "NOR3", "NAND2", "AND2", "DFF", "DFFR"]:
        sp_file = RTL_LIB_DIR / f"cells/{cell}/{cell}.sp"
        if sp_file.exists():
            subckts.append(sp_file.read_text(encoding="utf-8"))
            
    # 3. Parse das instâncias no Verilog
    # Exemplo:
    # AND2 _206_ (
    #   .A(_101_),
    #   .B(_108_),
    #   .Y(o_rom_cs)
    # );
    inst_pattern = re.compile(r"(\w+)\s+(_\d+_)\s*\((.*?)\);", re.DOTALL)
    port_pattern = re.compile(r"\.(\w+)\(([^)]+)\)")
    
    instances_spice = []
    
    # Mapeamento de nomes seguros para nós SPICE
    def sanitize(name):
        name = name.strip()
        if name in ["1'b0", "1'h0", "1'd0", "1'b1", "1'h1", "1'd1"]:
            return "gnd" if "0" in name else "vcc"
        # Substitui colchetes por sublinhado: i_ibus_adr[8] -> i_ibus_adr_8
        name = re.sub(r"[\[\]]", "_", name)
        name = re.sub(r"[\\]", "", name)
        name = name.strip("_")
        return name

    for match in inst_pattern.finditer(gates_v):
        cell_type = match.group(1)
        inst_name = match.group(2)
        conns_text = match.group(3)
        
        conns = {}
        for pm in port_pattern.finditer(conns_text):
            pname = pm.group(1)
            netname = sanitize(pm.group(2))
            conns[pname] = netname
            
        if cell_type in PIN_ORDER:
            ordered_pins = [conns.get(p, "gnd") for p in PIN_ORDER[cell_type]]
            pins_str = " ".join(ordered_pins)
            instances_spice.append(f"X{inst_name} {pins_str} vcc gnd {cell_type}")
            
    cir_content = [
        "* Simulação Analógica SPICE Transistor-Level RTL (BC548B)",
        "* Placa: serv_clk_mem_ctrl (Clock e Memórias do SERV)",
        ".title Circuito RTL Discreto - serv_clk_mem_ctrl",
        "",
        "* Modelo de Transistor Gummel-Poon",
        bjt_model,
        "",
        "* Subcircuitos das Portas Lógicas RTL",
        "\n".join(subckts),
        "",
        "* Fontes de Alimentação",
        "V_VCC vcc 0 DC 5.0",
        "R_GND gnd 0 1m",
        "",
        "* Estímulos de Entrada Analógicos",
        "* Clock base do oscilador: 10 MHz (T=100ns, 50ns alto, tr=2ns, tf=2ns)",
        "V_raw_clk i_raw_clk 0 PULSE(0 5.0 5n 2n 2n 48n 100n)",
        "* Modo Automático ativado",
        "V_auto i_auto_mode 0 DC 5.0",
        "* Botão de passo manual liberado",
        "V_step i_step_btn 0 DC 0.0",
        "* Botão de Reset: pulso inicial de 60ns",
        "V_rst i_rst_btn 0 PWL(0n 5.0 60n 5.0 62n 0.0)",
        "",
        "* Estímulos de Barramento (Wishbone)",
        "* Leitura de ROM em 0x00: cyc sobe em 180ns e desce em 290ns",
        "V_ibus_cyc i_ibus_cyc 0 PWL(0n 0.0 180n 0.0 182n 5.0 290n 5.0 292n 0.0)",
        "V_ibus_adr i_ibus_adr_0 0 DC 0.0",
        "V_ibus_adr_hi i_ibus_adr_31 0 DC 0.0",
        "",
        "* Leitura de RAM em 0x100: cyc sobe em 360ns e desce em 470ns",
        "V_dbus_cyc i_dbus_cyc 0 PWL(0n 0.0 360n 0.0 362n 5.0 470n 5.0 472n 0.0)",
        "V_dbus_adr_8 i_dbus_adr_8 0 PWL(0n 0.0 350n 0.0 352n 5.0 500n 5.0)",
        "V_dbus_we i_dbus_we 0 DC 0.0",
        "",
        "* Instâncias das 131 Portas Lógicas RTL (BC548B + Resistores)",
        "\n".join(instances_spice),
        "",
        "* Cargas capacitivas parasitas de saída e conexões do backplane (10 pF)",
        "C_clk o_clk 0 10p",
        "C_rst o_rst 0 10p",
        "C_iack o_ibus_ack 0 10p",
        "C_dack o_dbus_ack 0 10p",
        "C_rom o_rom_cs 0 10p",
        "C_ram o_ram_cs 0 10p",
        "C_busy o_bus_busy 0 10p",
        "",
        "* Análise Transitória e Gravação de Dados",
        ".tran 0.2n 500n",
        ".control",
        "run",
        "wrdata sim_spice_rtl.dat v(i_raw_clk) v(o_clk) v(i_rst_btn) v(o_rst) v(i_ibus_cyc) v(o_rom_cs) v(o_ibus_ack) v(i_dbus_cyc) v(o_ram_cs) v(o_dbus_ack) v(o_bus_busy)",
        "quit",
        ".endc",
        ".end"
    ]
    
    CIR_PATH.write_text("\n".join(cir_content), encoding="utf-8")
    print(f"[OK] Netlist SPICE gerado com sucesso: {CIR_PATH}")

def run_ngspice():
    print("[*] Executando simulação analógica transitória no ngspice...")
    cmd = ["ngspice", "-b", "-o", "ngspice.log", CIR_PATH.name]
    res = subprocess.run(cmd, cwd=BUILD_DIR, capture_output=True, text=True)
    log_file = BUILD_DIR / "ngspice.log"
    log_text = log_file.read_text(encoding="utf-8", errors="replace") if log_file.exists() else ""
    if res.returncode != 0 or "Error on line" in log_text:
        print("[!] Erro ao rodar ngspice:")
        print(log_text[-1000:])
        sys.exit(1)
    print(f"[OK] Simulação SPICE concluída. Dados exportados para: {DAT_PATH}")

def plot_waveforms():
    print("[*] Processando formas de onda analógicas...")
    if not DAT_PATH.exists():
        print(f"[!] Arquivo de dados {DAT_PATH} não encontrado.")
        sys.exit(1)
        
    data = np.loadtxt(DAT_PATH)
    time_ns = data[:, 0] * 1e9
    
    # Ordem dos canais gravados no wrdata:
    # 0: time
    # 1: v(i_raw_clk)
    # 2: v(o_clk)
    # 3: v(i_rst_btn)
    # 4: v(o_rst)
    # 5: v(i_ibus_cyc)
    # 6: v(o_rom_cs)
    # 7: v(o_ibus_ack)
    # 8: v(i_dbus_cyc)
    # 9: v(o_ram_cs)
    # 10: v(o_dbus_ack)
    # 11: v(o_bus_busy)
    
    v_raw_clk = data[:, 1]
    v_o_clk   = data[:, 2]
    v_rst_btn = data[:, 3]
    v_o_rst   = data[:, 4]
    v_ibus_cyc= data[:, 5]
    v_rom_cs  = data[:, 6]
    v_ibus_ack= data[:, 7]
    v_dbus_cyc= data[:, 8]
    v_ram_cs  = data[:, 9]
    v_dbus_ack= data[:, 10]
    v_busy    = data[:, 11]
    
    fig, axes = plt.subplots(6, 1, figsize=(15, 13), sharex=True)
    fig.patch.set_facecolor('#0d1117')
    
    for ax in axes:
        ax.set_facecolor('#161b22')
        ax.grid(True, color='#30363d', linestyle='--', alpha=0.6)
        ax.tick_params(colors='#c9d1d9', labelsize=10)
        for spine in ax.spines.values():
            spine.set_color('#30363d')
            
    # 1. Clock Oscilador vs Clock da CPU
    axes[0].plot(time_ns, v_raw_clk, color='#8b949e', linestyle=':', label='i_raw_clk (Oscilador 10 MHz)', alpha=0.7)
    axes[0].plot(time_ns, v_o_clk, color='#58a6ff', linewidth=2.0, label='o_clk (Clock do SERV no Backplane - 5 MHz)')
    axes[0].set_ylabel('Clock (V)', color='#58a6ff', fontweight='bold', fontsize=11)
    axes[0].legend(loc='upper right', facecolor='#161b22', edgecolor='#30363d', labelcolor='#c9d1d9')
    axes[0].set_ylim(-0.5, 5.5)
    
    # 2. Reset Manual vs Reset Sincronizado
    axes[1].plot(time_ns, v_rst_btn, color='#f85149', linestyle='--', label='i_rst_btn (Botão Manual)', alpha=0.8)
    axes[1].plot(time_ns, v_o_rst, color='#ff7b72', linewidth=2.0, label='o_rst (Reset Síncrono da CPU)')
    axes[1].set_ylabel('Reset (V)', color='#ff7b72', fontweight='bold', fontsize=11)
    axes[1].legend(loc='upper right', facecolor='#161b22', edgecolor='#30363d', labelcolor='#c9d1d9')
    axes[1].set_ylim(-0.5, 5.5)
    
    # 3. Barramento Wishbone de Instrução (ibus ROM)
    axes[2].plot(time_ns, v_ibus_cyc, color='#d29922', linestyle='--', label='i_ibus_cyc (Leitura de ROM)')
    axes[2].plot(time_ns, v_rom_cs, color='#3fb950', linewidth=1.8, label='o_rom_cs (Chip Select AT28C256)')
    axes[2].plot(time_ns, v_ibus_ack, color='#a371f7', linewidth=2.0, label='o_ibus_ack (Handshake ACK)')
    axes[2].set_ylabel('ROM ibus (V)', color='#3fb950', fontweight='bold', fontsize=11)
    axes[2].legend(loc='upper right', facecolor='#161b22', edgecolor='#30363d', labelcolor='#c9d1d9')
    axes[2].set_ylim(-0.5, 5.5)
    
    # 4. Barramento Wishbone de Dados (dbus RAM)
    axes[3].plot(time_ns, v_dbus_cyc, color='#d29922', linestyle='--', label='i_dbus_cyc (Leitura de RAM 0x100)')
    axes[3].plot(time_ns, v_ram_cs, color='#2ea043', linewidth=1.8, label='o_ram_cs (Chip Select AS6C62256)')
    axes[3].plot(time_ns, v_dbus_ack, color='#f0883e', linewidth=2.0, label='o_dbus_ack (Handshake ACK)')
    axes[3].set_ylabel('RAM dbus (V)', color='#2ea043', fontweight='bold', fontsize=11)
    axes[3].legend(loc='upper right', facecolor='#161b22', edgecolor='#30363d', labelcolor='#c9d1d9')
    axes[3].set_ylim(-0.5, 5.5)
    
    # 5. Atividade de Barramento
    axes[4].plot(time_ns, v_busy, color='#79c0ff', linewidth=1.8, label='o_bus_busy (Atividade de Barramento)')
    axes[4].set_ylabel('Busy (V)', color='#79c0ff', fontweight='bold', fontsize=11)
    axes[4].legend(loc='upper right', facecolor='#161b22', edgecolor='#30363d', labelcolor='#c9d1d9')
    axes[4].set_ylim(-0.5, 5.5)
    
    # 6. Zoom Transições Analógicas dos Transistores BJT BC548B
    idx = (time_ns >= 150) & (time_ns <= 350)
    axes[5].plot(time_ns[idx], v_o_clk[idx], color='#58a6ff', linewidth=1.8, label='Clock (transição com slew-rate finito)')
    axes[5].plot(time_ns[idx], v_ibus_ack[idx], color='#a371f7', linewidth=2.0, label='ACK (comutação BJT: VOL ~ 0.2V, VOH ~ 4.8V)')
    axes[5].set_ylabel('Analógico (V)', color='#a371f7', fontweight='bold', fontsize=11)
    axes[5].legend(loc='upper right', facecolor='#161b22', edgecolor='#30363d', labelcolor='#c9d1d9')
    axes[5].set_ylim(-0.5, 5.5)
    axes[5].set_xlim(0, 500)
    
    axes[5].set_xlabel('Tempo (nanossegundos)', color='#c9d1d9', fontsize=12, fontweight='bold')
    
    plt.suptitle('Simulação Elétrica Transistor-Level no SPICE (ngspice) - Tecnologia Discreta RTL (BC548B)\n'
                 'Placa Filha de Clock e Memórias conectada ao Backplane do SERV RISC-V',
                 color='#f0f6fc', fontsize=14, fontweight='bold', y=0.98)
                 
    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.savefig(PNG_PATH, dpi=180, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close()
    print(f"[OK] Gráfico de formas de onda gerado com sucesso: {PNG_PATH}")

if __name__ == "__main__":
    build_spice_netlist()
    run_ngspice()
    plot_waveforms()
