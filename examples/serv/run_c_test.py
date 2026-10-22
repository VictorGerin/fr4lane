#!/usr/bin/env python3
"""
run_c_test.py : Compila código C para RV32I via Clang/LLVM, gera firmware
e executa no testbench SystemVerilog do processador SERV com validação automática.

Uso:
  python run_c_test.py sw_test/test_simple.c
  python run_c_test.py sw_test/test_fibonacci.c
  python run_c_test.py sw_test/test_array.c
  python run_c_test.py --all
"""

import os
import sys
import re
import shutil
import subprocess
import argparse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SW_TEST_DIR = BASE_DIR / "sw_test"
TB_DIR = BASE_DIR / "tb"
RTL_DIR = BASE_DIR / "rtl"
BUILD_DIR = BASE_DIR / "build" / "sw_sim"

def find_tool(name, extra_paths=None, check_riscv=False):
    # Procura primeiro nos caminhos com suporte verificado (ex.: MSYS2 clang64)
    if extra_paths:
        for p in extra_paths:
            candidate = Path(p) / (name + ".exe" if os.name == "nt" else name)
            if candidate.is_file():
                if check_riscv and name == "clang":
                    # Confere se tem suporte a riscv32
                    res = subprocess.run([str(candidate), "-print-targets"], capture_output=True, text=True)
                    if "riscv32" in res.stdout:
                        return str(candidate)
                else:
                    return str(candidate)
    # Procura no PATH padrao
    found = shutil.which(name)
    if found:
        if check_riscv and name == "clang":
            res = subprocess.run([found, "-print-targets"], capture_output=True, text=True)
            if "riscv32" in res.stdout:
                return found
        else:
            return found
    return None

CLANG_PATHS = [
    r"C:\msys64\clang64\bin",
    r"C:\msys64\ucrt64\bin",
    r"C:\msys64\usr\bin",
]
IVERILOG_PATHS = [
    r"C:\msys64\ucrt64\bin",
    r"C:\msys64\clang64\bin",
    r"C:\msys64\mingw64\bin",
]

CLANG = find_tool("clang", CLANG_PATHS, check_riscv=True)
LLVM_OBJCOPY = find_tool("llvm-objcopy", CLANG_PATHS)
HEXDUMP = find_tool("hexdump", [r"C:\msys64\usr\bin", r"C:\msys64\ucrt64\bin", r"C:\msys64\clang64\bin"])
IVERILOG = find_tool("iverilog", IVERILOG_PATHS)
VVP = find_tool("vvp", IVERILOG_PATHS)

def check_tools():
    missing = []
    if not CLANG: missing.append("clang (com suporte a target riscv32)")
    if not LLVM_OBJCOPY: missing.append("llvm-objcopy")
    if not IVERILOG: missing.append("iverilog")
    if not VVP: missing.append("vvp")
    if missing:
        print("[ERRO] Ferramentas necessárias não encontradas:")
        for m in missing:
            print(f"  - {m}")
        sys.exit(1)

def bin_to_hex(bin_path, hex_path, word_count=2048):
    """Converte binario bruto little-endian em linhas hexadecimais de 32 bits."""
    with open(bin_path, "rb") as f:
        data = f.read()

    words = []
    for i in range(0, len(data), 4):
        chunk = data[i:i+4]
        if len(chunk) < 4:
            chunk = chunk + b"\x00" * (4 - len(chunk))
        word = int.from_bytes(chunk, byteorder="little")
        words.append(f"{word:08X}")

    while len(words) < word_count:
        words.append("00000013")  # NOP

    with open(hex_path, "w") as f:
        for w in words:
            f.write(w + "\n")

def compile_testbench(pc_width=13, with_e=0):
    """Compila o testbench tb_serv_c.sv com os fontes RTL se necessario."""
    vvp_file = BUILD_DIR / f"tb_serv_c_{pc_width}_e{with_e}.vvp"
    tb_file = TB_DIR / "tb_serv_c.sv"
    pkg_file = RTL_DIR / "serv_pkg.sv"
    other_rtl = [f for f in sorted(RTL_DIR.glob("*.sv")) if f.name != "serv_pkg.sv"]

    sources = [pkg_file] + other_rtl + [tb_file]
    latest_source_mtime = max(f.stat().st_mtime for f in sources)

    if vvp_file.exists() and vvp_file.stat().st_mtime > latest_source_mtime:
        return vvp_file

    arch_str = "RV32E" if with_e else "RV32I"
    print(f"[BUILD] Compilando testbench SystemVerilog (tb_serv_c com PC_WIDTH={pc_width}, ISA={arch_str})...")
    cmd = [
        IVERILOG, "-g2012",
        f"-Ptb_serv_c.PC_WIDTH={pc_width}",
        f"-Ptb_serv_c.WITH_E={with_e}",
        "-s", "tb_serv_c",
        "-o", str(vvp_file),
    ] + [str(f) for f in sources]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        print("[ERRO] Falha ao compilar testbench com iverilog:")
        print(res.stderr)
        sys.exit(1)
    return vvp_file

def run_test(c_file, expected_override=None, timeout=500000, pc_width=13, rv32e=False):
    c_path = Path(c_file).resolve()
    if not c_path.is_file():
        print(f"[ERRO] Arquivo C nao encontrado: {c_file}")
        return False

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    test_name = c_path.stem

    # Detecta expectativa no proprio arquivo C: // EXPECTED: <num>
    expected = expected_override
    if expected is None:
        content = c_path.read_text(encoding="utf-8", errors="ignore")
        match = re.search(r"//\s*EXPECTED:\s*(-?\d+)", content)
        if match:
            expected = int(match.group(1))

    # Caminhos dos artefatos
    crt0_s = SW_TEST_DIR / "crt0.s"
    link_ld = SW_TEST_DIR / "link.ld"
    crt0_o = BUILD_DIR / "crt0.o"
    test_o = BUILD_DIR / f"{test_name}.o"
    test_elf = BUILD_DIR / f"{test_name}.elf"
    test_bin = BUILD_DIR / f"{test_name}.bin"
    test_hex = BUILD_DIR / f"{test_name}.hex"

    march = "rv32e" if rv32e else "rv32i"
    mabi = "ilp32e" if rv32e else "ilp32"
    with_e = 1 if rv32e else 0

    # 1. Monta crt0.s
    res = subprocess.run([
        CLANG, f"--target=riscv32", f"-march={march}", f"-mabi={mabi}",
        "-c", str(crt0_s), "-o", str(crt0_o)
    ], capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[ERRO] Falha ao montar {crt0_s}:", res.stderr)
        return False

    # 2. Compila arquivo C
    res = subprocess.run([
        CLANG, f"--target=riscv32", f"-march={march}", f"-mabi={mabi}",
        "-O2", "-ffreestanding", "-nostdlib",
        "-c", str(c_path), "-o", str(test_o)
    ], capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[ERRO] Falha ao compilar {c_path}:", res.stderr)
        return False

    # 3. Faz o link com ld.lld via Clang
    res = subprocess.run([
        CLANG, f"--target=riscv32", f"-march={march}", f"-mabi={mabi}",
        "-fuse-ld=lld", "-nostdlib", f"-Wl,-T,{link_ld}",
        str(crt0_o), str(test_o), "-o", str(test_elf)
    ], capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[ERRO] Falha no link do programa:", res.stderr)
        return False

    # 4. Extrai binario
    res = subprocess.run([
        LLVM_OBJCOPY, "-O", "binary", str(test_elf), str(test_bin)
    ], capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[ERRO] Falha no llvm-objcopy:", res.stderr)
        return False

    # 5. Converte para formato hex do Verilog usando hexdump
    if HEXDUMP:
        with open(test_hex, "w") as f:
            subprocess.run([HEXDUMP, "-v", "-e", '1/4 "%08X\\n"', str(test_bin)], stdout=f, check=True)
    else:
        bin_to_hex(test_bin, test_hex)

    # 6. Compila o testbench SystemVerilog
    vvp_file = compile_testbench(pc_width=pc_width, with_e=with_e)

    # 7. Executa simulacao no VVP
    hex_arg = str(test_hex).replace("\\", "/")
    vvp_cmd = [VVP, str(vvp_file), f"+firmware={hex_arg}", f"+timeout={timeout}"]
    if expected is not None:
        vvp_cmd.append(f"+expected={expected}")

    arch_label = "RV32E" if rv32e else "RV32I"
    print(f"\n---> Executando teste: {c_path.name} ({arch_label}, PC_WIDTH={pc_width})")
    res = subprocess.run(vvp_cmd, capture_output=True, text=True)
    print(res.stdout)
    if res.stderr:
        print(res.stderr)

    if res.returncode != 0 or "[FAIL]" in res.stdout:
        return False
    return True

def main():
    check_tools()
    parser = argparse.ArgumentParser(description="Executa testes em C no processador SERV via Clang/Icarus.")
    parser.add_argument("c_file", nargs="?", help="Arquivo .c a ser executado")
    parser.add_argument("--pc-width", type=int, default=13, help="Largura do PC em bits (ex: 32, 16, 13; padrao: 13)")
    parser.add_argument("--rv32e", action="store_true", default=True, help="Usa especificacao RV32E (16 registradores, padrao: True)")
    parser.add_argument("--rv32i", dest="rv32e", action="store_false", help="Usa especificacao RV32I completa (32 registradores)")
    parser.add_argument("--expected", type=int, help="Valor esperado de retorno (substitui // EXPECTED: no .c)")
    parser.add_argument("--timeout", type=int, default=500000, help="Timeout maximo em ciclos (padrao: 500000)")
    parser.add_argument("--all", action="store_true", help="Executa todos os testes presentes em sw_test/*.c")
    parser.add_argument("--clean", action="store_true", help="Limpa todos os arquivos temporarios em build/sw_sim")
    args = parser.parse_args()

    if args.clean:
        if BUILD_DIR.exists():
            print(f"[CLEAN] Removendo pasta de temporarios: {BUILD_DIR}")
            shutil.rmtree(BUILD_DIR)
            print("[CLEAN] Pasta limpa com sucesso.")
        else:
            print("[CLEAN] Nada a limpar.")
        sys.exit(0)

    if args.all:
        c_files = sorted(list(SW_TEST_DIR.glob("*.c")))
        if not c_files:
            print("[AVISO] Nenhum arquivo .c encontrado em sw_test/")
            return
        results = []
        arch_name = "RV32E" if args.rv32e else "RV32I"
        for cf in c_files:
            ok = run_test(cf, timeout=args.timeout, pc_width=args.pc_width, rv32e=args.rv32e)
            results.append((cf.name, ok))
        print("\n" + "="*50)
        print(f" RESUMO DA BATERIA DE TESTES C NO SERV ({arch_name}, PC_WIDTH={args.pc_width}):")
        print("="*50)
        all_ok = True
        for name, ok in results:
            status = "[ PASS ]" if ok else "[ FAIL ]"
            if not ok: all_ok = False
            print(f" {status} {name}")
        print("="*50)
        sys.exit(0 if all_ok else 1)

    if not args.c_file:
        parser.print_help()
        print("\nExemplo:")
        print("  python run_c_test.py sw_test/test_simple.c --pc-width 13")
        sys.exit(1)

    ok = run_test(args.c_file, expected_override=args.expected, timeout=args.timeout, pc_width=args.pc_width, rv32e=args.rv32e)
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
