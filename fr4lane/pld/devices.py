"""Definições de hardware e matriz de fusíveis para dispositivos GAL (Generic Array Logic).

Suporta GAL22V10 (ATF22V10C) e GAL16V8 (ATF16V8B).
Especifica a pinagem DIP/PLCC, limites de termos de produto por macrocélula,
mapeamento de pinos para colunas da matriz AND, e bits de configuração (XOR, S1/AC0/AC1).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class OLMCDef:
    """Definição de uma macrocélula lógica de saída (OLMC)."""
    index: int                  # Índice da OLMC (0..N-1)
    dip_pin: int                # Pino físico no encapsulamento DIP
    plcc_pin: int               # Pino físico no encapsulamento PLCC
    product_terms: int          # Quantidade de termos de produto lógicos disponíveis
    oe_row: int                 # Linha do termo de Output Enable (OE)
    logic_start_row: int        # Primeira linha dos termos de produto lógicos


@dataclass
class GALDevice:
    """Especificação arquitetural de um chip GAL."""
    name: str                   # Ex: 'GAL22V10', 'GAL16V8'
    num_pins: int               # Total de pinos (ex: 24, 20)
    num_olmcs: int              # Quantidade de macrocélulas (10, 8)
    max_inputs: int             # Máximo de entradas simultâneas
    matrix_cols: int            # Colunas da matriz AND (ex: 44, 32)
    matrix_rows: int            # Linhas da matriz AND (ex: 132, 64)
    total_fuses: int            # Total de fusíveis no arquivo JEDEC (ex: 5892, 2194)
    logic_fuses: int            # Fusíveis da matriz lógica (ex: 5808, 2048)
    vcc_pin: int                # Pino de alimentação (+5V)
    gnd_pin: int                # Pino de terra (GND)
    clk_pin: int                # Pino de clock síncrono dedicado
    dedicated_inputs: List[int] # Lista de pinos exclusivos para entrada
    pin_to_column: Dict[int, int] # Pino DIP -> Coluna inicial (True = col, Inverted = col+1)
    olmcs: List[OLMCDef]        # Lista de macrocélulas em ordem física (14..23 ou 12..19)
    sp_row: Optional[int] = None # Linha do termo Synchronous Preset (se suportado)
    ar_row: Optional[int] = None # Linha do termo Asynchronous Reset (se suportado)


# ==============================================================================
# GAL22V10 / ATF22V10C (24-pin DIP, 28-pin PLCC)
# ==============================================================================
# Pinout DIP-24:
# Pin 1:  CLK / IN0
# Pins 2..11: IN1..IN10
# Pin 12: GND
# Pin 13: IN11
# Pins 14..23: OLMC 0..9 (I/O com capacidade variável de termos de produto)
# Pin 24: VCC
#
# Distribuição simétrica de termos de produto por OLMC:
# Pin 14 (OLMC 0): 8 termos lógicos (+ 1 OE = 9 linhas)
# Pin 15 (OLMC 1): 10 termos lógicos (+ 1 OE = 11 linhas)
# Pin 16 (OLMC 2): 12 termos lógicos (+ 1 OE = 13 linhas)
# Pin 17 (OLMC 3): 14 termos lógicos (+ 1 OE = 15 linhas)
# Pin 18 (OLMC 4): 16 termos lógicos (+ 1 OE = 17 linhas)
# Pin 19 (OLMC 5): 16 termos lógicos (+ 1 OE = 17 linhas)
# Pin 20 (OLMC 6): 14 termos lógicos (+ 1 OE = 15 linhas)
# Pin 21 (OLMC 7): 12 termos lógicos (+ 1 OE = 13 linhas)
# Pin 22 (OLMC 8): 10 termos lógicos (+ 1 OE = 11 linhas)
# Pin 23 (OLMC 9): 8 termos lógicos (+ 1 OE = 9 linhas)
#
# Linhas Especiais:
# Linha 0: Synchronous Preset (SP)
# Linha 131: Asynchronous Reset (AR)
# Total de linhas = 132 linhas * 44 colunas = 5808 fusíveis lógicos.
# ==============================================================================

GAL22V10_OLMCS = [
    OLMCDef(index=0, dip_pin=14, plcc_pin=16, product_terms=8,  oe_row=122, logic_start_row=123),
    OLMCDef(index=1, dip_pin=15, plcc_pin=18, product_terms=10, oe_row=111, logic_start_row=112),
    OLMCDef(index=2, dip_pin=16, plcc_pin=19, product_terms=12, oe_row=98,  logic_start_row=99),
    OLMCDef(index=3, dip_pin=17, plcc_pin=20, product_terms=14, oe_row=83,  logic_start_row=84),
    OLMCDef(index=4, dip_pin=18, plcc_pin=21, product_terms=16, oe_row=66,  logic_start_row=67),
    OLMCDef(index=5, dip_pin=19, plcc_pin=23, product_terms=16, oe_row=49,  logic_start_row=50),
    OLMCDef(index=6, dip_pin=20, plcc_pin=24, product_terms=14, oe_row=34,  logic_start_row=35),
    OLMCDef(index=7, dip_pin=21, plcc_pin=25, product_terms=12, oe_row=21,  logic_start_row=22),
    OLMCDef(index=8, dip_pin=22, plcc_pin=26, product_terms=10, oe_row=10,  logic_start_row=11),
    OLMCDef(index=9, dip_pin=23, plcc_pin=27, product_terms=8,  oe_row=1,   logic_start_row=2),
]

# Mapeamento do pino DIP para coluna da matriz AND:
# Cada pino gera 2 colunas: True (col) e Invertido (col + 1).
# Baseado na especificação oficial da Lattice Semiconductor e GALasm.
GAL22V10_PIN_TO_COLUMN = {
    1:  0,
    2:  4,
    3:  8,
    4:  12,
    5:  16,
    6:  20,
    7:  24,
    8:  28,
    9:  32,
    10: 36,
    11: 40,
    13: 42,
    14: 38,
    15: 34,
    16: 30,
    17: 26,
    18: 22,
    19: 18,
    20: 14,
    21: 10,
    22: 6,
    23: 2,
}

GAL22V10 = GALDevice(
    name="GAL22V10",
    num_pins=24,
    num_olmcs=10,
    max_inputs=22,
    matrix_cols=44,
    matrix_rows=132,
    total_fuses=5892,
    logic_fuses=5808,
    vcc_pin=24,
    gnd_pin=12,
    clk_pin=1,
    dedicated_inputs=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13],
    pin_to_column=GAL22V10_PIN_TO_COLUMN,
    olmcs=GAL22V10_OLMCS,
    sp_row=0,
    ar_row=131,
)


# ==============================================================================
# GAL16V8 / ATF16V8B (20-pin DIP, 20-pin PLCC)
# ==============================================================================
# Pinout DIP-20:
# Pin 1:  CLK / IN
# Pins 2..9: IN
# Pin 10: GND
# Pin 11: /OE / IN
# Pins 12..19: OLMC 0..7 (cada uma com 8 termos de produto)
# Pin 20: VCC
# Total de 64 linhas * 32 colunas = 2048 fusíveis lógicos. Total = 2194 fusíveis.
# ==============================================================================

GAL16V8_OLMCS = [
    OLMCDef(index=0, dip_pin=19, plcc_pin=19, product_terms=8, oe_row=-1, logic_start_row=0),
    OLMCDef(index=1, dip_pin=18, plcc_pin=18, product_terms=8, oe_row=-1, logic_start_row=8),
    OLMCDef(index=2, dip_pin=17, plcc_pin=17, product_terms=8, oe_row=-1, logic_start_row=16),
    OLMCDef(index=3, dip_pin=16, plcc_pin=16, product_terms=8, oe_row=-1, logic_start_row=24),
    OLMCDef(index=4, dip_pin=15, plcc_pin=15, product_terms=8, oe_row=-1, logic_start_row=32),
    OLMCDef(index=5, dip_pin=14, plcc_pin=14, product_terms=8, oe_row=-1, logic_start_row=40),
    OLMCDef(index=6, dip_pin=13, plcc_pin=13, product_terms=8, oe_row=-1, logic_start_row=48),
    OLMCDef(index=7, dip_pin=12, plcc_pin=12, product_terms=8, oe_row=-1, logic_start_row=56),
]

GAL16V8_PIN_TO_COLUMN = {
    1:  2,
    2:  0,
    3:  4,
    4:  8,
    5:  12,
    6:  16,
    7:  20,
    8:  24,
    9:  28,
    11: -1,
    12: 30,
    13: 26,
    14: 22,
    15: 18,
    16: 14,
    17: 10,
    18: 6,
    19: 2,
}

GAL16V8 = GALDevice(
    name="GAL16V8",
    num_pins=20,
    num_olmcs=8,
    max_inputs=16,
    matrix_cols=32,
    matrix_rows=64,
    total_fuses=2194,
    logic_fuses=2048,
    vcc_pin=20,
    gnd_pin=10,
    clk_pin=1,
    dedicated_inputs=[1, 2, 3, 4, 5, 6, 7, 8, 9],
    pin_to_column=GAL16V8_PIN_TO_COLUMN,
    olmcs=GAL16V8_OLMCS,
)

DEVICES = {
    "GAL22V10": GAL22V10,
    "ATF22V10C": GAL22V10,
    "GAL16V8": GAL16V8,
    "ATF16V8B": GAL16V8,
}


def get_device(name: str) -> GALDevice:
    """Retorna a especificação do dispositivo pelo nome (case-insensitive)."""
    clean = name.strip().upper()
    if clean in DEVICES:
        return DEVICES[clean]
    raise ValueError(f"Dispositivo GAL desconhecido: '{name}'. Suportados: {list(DEVICES.keys())}")
