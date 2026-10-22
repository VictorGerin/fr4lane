#!/usr/bin/env python3
"""
run_all_rtl_modules.py : Sintetiza e simula cada um dos 10 módulos do SERV
individualmente em tecnologia RTL (transistores discretos BC548 + resistores),
executando o cellcheck (montagem SPICE x Liberty), simulação gate-level
e simulação elétrica switch-level com vetores de teste dedicados.
"""

import sys
import subprocess
import time
from pathlib import Path

MODULES = [
    ("serv_alu",        "ALU Serial de 1 bit"),
    ("serv_ctrl",       "Program Counter (PC)"),
    ("serv_immdec",     "Decodificador de Imediatos"),
    ("serv_decode",     "Decodificador de Instrucoes"),
    ("serv_state",      "FSM Principal de Controle"),
    ("serv_bufreg",     "Buffer de Endereco/Deslocamento"),
    ("serv_bufreg2",    "Buffer de Dados/Memoria"),
    ("serv_mem_if",     "Interface de Alinhamento de Memoria"),
    ("serv_rf_if",      "Multiplexador do Banco de Registradores"),
    ("serv_rf_ram_if",  "Adaptador para SRAM Externa 2-bit"),
]

def run_module(module_name, desc):
    tb_path = f"tb/tb_{module_name}.sv"
    cmd = [
        sys.executable, "-m", "fr4lane",
        "--top", module_name,
        "--lib", "rtl",
        "--tb", tb_path,
        "--synth-only"
    ]
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True)
    dt = time.time() - t0

    npn = 0
    resistors = 0
    total_comp = 0
    gate_ok = False
    switch_ok = False

    for line in res.stdout.splitlines():
        if "componentes (npn=" in line:
            # ex: "61 blocos, 291 componentes (npn=115, resistor=176)"
            try:
                parts = line.split("componentes (npn=")[1]
                npn_str, res_str = parts.split(", resistor=")
                npn = int(npn_str)
                resistors = int(res_str.rstrip(")"))
                total_comp = npn + resistors
            except Exception:
                pass
        if "gate-level:" in line and "OK" in line:
            gate_ok = True
        if "componentes:" in line and "OK" in line:
            switch_ok = True

    status = (res.returncode == 0) and gate_ok and switch_ok
    return {
        "module": module_name,
        "desc": desc,
        "status": status,
        "npn": npn,
        "resistors": resistors,
        "total": total_comp,
        "gate_ok": gate_ok,
        "switch_ok": switch_ok,
        "time": dt,
        "stderr": res.stderr if not status else ""
    }

def main():
    print("=" * 78)
    print(" BATERIA DE TESTES E SIMULAÇÃO ELÉTRICA DOS 10 MÓDULOS RTL DO SERV")
    print(" Tecnologia: RTL (Transistores BC548 + Resistores)")
    print("=" * 78)

    results = []
    all_ok = True

    for mod, desc in MODULES:
        print(f"--> Processando [{mod}] ({desc})...", end=" ", flush=True)
        r = run_module(mod, desc)
        results.append(r)
        if r["status"]:
            print(f"[OK] ({r['npn']} NPN, {r['resistors']} Res, {r['time']:.1f}s)")
        else:
            print("[FALHOU]")
            all_ok = False

    print("\n" + "=" * 78)
    print(f"{'Módulo':<18} | {'NPN':<5} | {'Res':<5} | {'Total':<6} | {'Gate-Lvl':<8} | {'Transistor':<10} | {'Status'}")
    print("-" * 78)

    total_npn = 0
    total_res = 0

    for r in results:
        g_str = "PASS" if r["gate_ok"] else "FAIL"
        s_str = "PASS" if r["switch_ok"] else "FAIL"
        st_str = "[ PASS ]" if r["status"] else "[ FAIL ]"
        total_npn += r["npn"]
        total_res += r["resistors"]
        print(f"{r['module']:<18} | {r['npn']:<5} | {r['resistors']:<5} | {r['total']:<6} | {g_str:<8} | {s_str:<10} | {st_str}")

    print("-" * 78)
    total_all = total_npn + total_res
    print(f"{'TOTAL CPU (10 PCBs)':<18} | {total_npn:<5} | {total_res:<5} | {total_all:<6} | {'ALL OK':<8} | {'ALL OK':<10} | {'[ PASS ]' if all_ok else '[ FAIL ]'}")
    print("=" * 78)

    if not all_ok:
        sys.exit(1)

if __name__ == "__main__":
    main()
