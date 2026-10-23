"""Gerador de arquivos JEDEC padrão (.jed) para programação de chips GAL.

Compatível com programadores de hardware universais:
- XGecu T48 / TL866II Plus (via software Minipro)
- Wellon / TOP / RT809H / LabTool
- Simuladores de lógica programável (MAME jedutil, WinCUPL, etc.)
"""

from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .devices import GALDevice, GAL22V10, OLMCDef
from .packer import PackedGAL
from .synth import LogicCone, ProductTerm


def generate_jedec(packed: PackedGAL, design_name: str, out_path: Optional[Path] = None) -> str:
    """Gera o conteúdo do arquivo JEDEC (.jed) pronto para gravação física."""
    dev = packed.device
    num_fuses = dev.total_fuses
    logic_fuses = dev.logic_fuses
    cols = dev.matrix_cols
    rows = dev.matrix_rows

    # Inicializa todos os fusíveis lógicos com 0 (linha desabilitada / termo nulo: A * /A = 0)
    fuse_array = [0] * num_fuses

    # 1. Mapeamento das OLMCs na matriz lógica
    for pin, place in packed.olmc_placements.items():
        olmc = place.olmc
        cone = place.cone

        # Termo de Output Enable (OE)
        oe_start = olmc.oe_row * cols
        if place.is_feedback_only or not cone.is_primary_output:
            # Desativa o buffer tri-state de saída (tudo 0 = OE sempre desabilitado, pino livre)
            for c in range(cols):
                fuse_array[oe_start + c] = 0
        else:
            # Saída sempre habilitada: todos os fusíveis desconectados (1) -> pull-up interno = 1
            for c in range(cols):
                fuse_array[oe_start + c] = 1

        # Termos lógicos (SOP)
        for term_idx, pterm in enumerate(cone.product_terms):
            row_idx = olmc.logic_start_row + term_idx
            row_start = row_idx * cols

            # Por padrão, entradas não usadas no termo são desconectadas (ambos fusíveis = 1)
            for c in range(cols):
                fuse_array[row_start + c] = 1

            # Conecta os literais do termo
            for sig_name, bit_val in pterm.literals.items():
                pin_num = None
                is_internal_fb = sig_name in packed.internal_feedbacks

                if sig_name in packed.input_pins:
                    pin_num = packed.input_pins[sig_name]
                elif sig_name in packed.output_pins:
                    pin_num = packed.output_pins[sig_name]

                if pin_num is not None and pin_num in dev.pin_to_column:
                    col_base = dev.pin_to_column[pin_num]

                    # No GAL22V10:
                    # Se for pino de saída registrado (OLMC registered), a saída Q do flip-flop
                    # é internamente invertida antes de entrar na matriz AND (especificação Lattice/GALasm).
                    # Por isso inverte a polaridade da coluna de feedback.
                    is_reg = (pin_num in packed.olmc_placements and 
                              packed.olmc_placements[pin_num].cone.is_registered)

                    effective_bit = bit_val
                    if is_reg and dev.name == "GAL22V10":
                        effective_bit = 1 if bit_val == 0 else 0

                    if effective_bit == 1:
                        # True não-invertido: coluna True conectada (0), coluna Invertida desconectada (1)
                        fuse_array[row_start + col_base] = 0
                        fuse_array[row_start + col_base + 1] = 1
                    else:
                        # Invertido: coluna True desconectada (1), coluna Invertida conectada (0)
                        fuse_array[row_start + col_base] = 1
                        fuse_array[row_start + col_base + 1] = 0

    # 2. Bits de arquitetura das OLMCs
    if dev.name == "GAL22V10":
        # No GAL22V10:
        # Endereço 5808 a 5827: 10 pares intercalados de (XOR, S1) para OLMC 0 a 9
        # OLMC 0 = Pino 14 ... OLMC 9 = Pino 23
        # XOR: 1 = Active-High, 0 = Active-Low
        # S1:  0 = Registered (DFF), 1 = Combinational / Input
        arch_addr = 5808
        for olmc_idx, olmc in enumerate(dev.olmcs):
            pin = olmc.dip_pin
            xor_val = 1
            s1_val = 1

            if pin in packed.olmc_placements:
                place = packed.olmc_placements[pin]
                xor_val = 1 if place.cone.active_high else 0
                s1_val = 0 if place.cone.is_registered else 1
            else:
                # OLMC não utilizada ou configurada como entrada dedicada
                xor_val = 1
                s1_val = 1

            fuse_array[arch_addr + olmc_idx * 2] = xor_val
            fuse_array[arch_addr + olmc_idx * 2 + 1] = s1_val

        # 3. Assinatura eletrônica do usuário (UES - 64 bits em 5828..5891)
        # Grava o identificador do chip (ex: "U1_SAP1 ")
        ues_str = f"{packed.chip_id}_{design_name}"[:8].ljust(8)
        ues_bits = []
        for ch in ues_str:
            ascii_val = ord(ch)
            for b in range(8):
                ues_bits.append((ascii_val >> b) & 1)

        sig_addr = 5828
        for b_idx, bit in enumerate(ues_bits):
            fuse_array[sig_addr + b_idx] = bit

    elif dev.name == "GAL16V8":
        # Configuração para GAL16V8 (2194 fusíveis)
        # XOR em 2048..2055, UES em 2056..2119, AC1 em 2120..2127, SYN em 2192, AC0 em 2193
        for olmc_idx, olmc in enumerate(dev.olmcs):
            pin = olmc.dip_pin
            xor_val = 1
            if pin in packed.olmc_placements:
                xor_val = 1 if packed.olmc_placements[pin].cone.active_high else 0
            fuse_array[2048 + olmc_idx] = xor_val
            fuse_array[2120 + olmc_idx] = 1

        # UES (64 bits)
        ues_str = f"{packed.chip_id}"[:8].ljust(8)
        for c_idx, ch in enumerate(ues_str):
            for b in range(8):
                fuse_array[2056 + c_idx * 8 + b] = (ord(ch) >> b) & 1

        fuse_array[2192] = 1  # SYN
        fuse_array[2193] = 1  # AC0

    # 4. Cálculo do Fuse Checksum padrão JEDEC
    fuse_checksum = 0
    cur_byte = 0
    for idx, bit in enumerate(fuse_array):
        cur_byte |= (bit << (idx % 8))
        if (idx % 8) == 7:
            fuse_checksum = (fuse_checksum + cur_byte) & 0xFFFF
            cur_byte = 0
    if (len(fuse_array) % 8) != 0:
        fuse_checksum = (fuse_checksum + cur_byte) & 0xFFFF

    # 5. Formatação do arquivo JEDEC
    lines = []
    lines.append(f"\x02")  # STX
    lines.append(f"NOTE FR4LANE GAL SYNTHESIZER & PACKER*")
    lines.append(f"NOTE DESIGN: {design_name}*")
    lines.append(f"NOTE CHIP: {packed.chip_id} ({dev.name})*")
    lines.append(f"NOTE UTILIZATION: {packed.macrocell_utilization:.1f}% ({len(packed.olmc_placements)}/{dev.num_olmcs} OLMCs)*")
    lines.append(f"QP{dev.num_pins}*")
    lines.append(f"QF{num_fuses}*")
    lines.append(f"G0*")
    lines.append(f"F0*")

    # Matriz de fusíveis com linhas compactadas
    for row in range(rows):
        start_addr = row * cols
        row_bits = "".join(str(fuse_array[start_addr + c]) for c in range(cols))
        # Escreve a linha somente se contiver algum bit 1 (economiza tamanho do arquivo JEDEC)
        if "1" in row_bits:
            lines.append(f"L{start_addr:04d} {row_bits}*")

    # Arquitetura (XOR, S1) e UES
    if dev.name == "GAL22V10":
        arch_bits = "".join(str(fuse_array[5808 + i]) for i in range(20))
        lines.append(f"L5808 {arch_bits}*")
        sig_bits = "".join(str(fuse_array[5828 + i]) for i in range(64))
        lines.append(f"L5828 {sig_bits}*")
    elif dev.name == "GAL16V8":
        xor_bits = "".join(str(fuse_array[2048 + i]) for i in range(8))
        lines.append(f"L2048 {xor_bits}*")
        sig_bits = "".join(str(fuse_array[2056 + i]) for i in range(64))
        lines.append(f"L2056 {sig_bits}*")
        ac1_bits = "".join(str(fuse_array[2120 + i]) for i in range(8))
        lines.append(f"L2120 {ac1_bits}*")
        lines.append(f"L2192 {fuse_array[2192]}{fuse_array[2193]}*")

    # Checksum de fusíveis
    lines.append(f"C{fuse_checksum:04X}*")
    lines.append(f"\x03")  # ETX

    body = "\r\n".join(lines) + "\r\n"

    # Checksum de transmissão de arquivo (soma simples entre STX e ETX)
    file_checksum = sum(ord(c) for c in body if ord(c) != 0x02) & 0xFFFF
    body += f"{file_checksum:04X}\r\n"

    if out_path:
        out_path = Path(out_path)
        out_path.write_bytes(body.encode("ascii"))

    return body
