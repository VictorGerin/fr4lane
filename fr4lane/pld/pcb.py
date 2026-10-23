"""Gerador de layout PCB KiCad para sistemas baseados em chips GAL.

Gera a placa (.kicad_pcb) com soquetes DIP-24 / DIP-20, capacitores de desacoplamento
de 100nF dedicados a cada chip, conector de borda / header de barramento para E/S,
planos de alimentação (VCC e GND) e netlist completo.
"""

import math
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..kicad import write_pcb
from ..layout import Board, Footprint, Pad, Rules, mounting_hole
from .devices import GAL22V10, GALDevice
from .packer import PackedGAL
from .synth import SynthesizedDesign


def make_dip_socket(ref: str, value: str, num_pins: int, x: float, y: float) -> Footprint:
    """Cria o footprint de um circuito integrado DIP padrão KiCad (pino 1 em 0,0)."""
    pads = []
    half = num_pins // 2
    row_pitch = 7.62      # 300 mil entre fileiras
    pin_pitch = 2.54      # 100 mil entre pinos adjacentes
    total_len = (half - 1) * pin_pitch

    # Fileira esquerda: Pinos 1 a half (x = 0, y crescente de 0 até total_len)
    for i in range(half):
        pin_num = str(i + 1)
        shape = "roundrect" if i == 0 else "circle"
        pads.append(
            Pad(
                num=pin_num,
                rx=0.0,
                ry=i * pin_pitch,
                w=1.6,
                h=1.6,
                shape=shape,
                tht=True,
                drill=0.8,
            )
        )

    # Fileira direita: Pinos half+1 a num_pins (x = 7.62, y decrescente de total_len até 0)
    for i in range(half):
        pin_num = str(num_pins - i)
        pads.append(
            Pad(
                num=pin_num,
                rx=row_pitch,
                ry=i * pin_pitch,
                w=1.6,
                h=1.6,
                shape="circle",
                tht=True,
                drill=0.8,
            )
        )

    lib_name = f"Package_DIP:DIP-{num_pins}_W7.62mm"
    courtyard = (-1.5, -1.5, row_pitch + 1.5, total_len + 1.5)

    fp = Footprint(
        ref=ref,
        value=value,
        lib_name=lib_name,
        x=x,
        y=y,
        pads=pads,
        courtyard=courtyard,
        tht=True,
    )
    for p in pads:
        p.fp = fp
    return fp


def make_c0805(ref: str, value: str, x: float, y: float, rot: int = 0) -> Footprint:
    """Capacitor de desacoplamento SMD 0805 (100nF)."""
    pads = [
        Pad(num="1", rx=-0.95, ry=0.0, w=1.0, h=1.3, shape="roundrect"),
        Pad(num="2", rx=0.95, ry=0.0, w=1.0, h=1.3, shape="roundrect"),
    ]
    fp = Footprint(
        ref=ref,
        value=value,
        lib_name="Capacitor_SMD:C_0805_2012Metric",
        x=x,
        y=y,
        pads=pads,
        courtyard=(-1.7, -0.9, 1.7, 0.9),
        tht=False,
        rot=rot,
    )
    for p in pads:
        p.fp = fp
    return fp


def make_connector(ref: str, value: str, num_pins: int, x: float, y: float) -> Footprint:
    """Conector PinHeader de 2 fileiras padrão KiCad (pino 1 em 0,0, pino 2 em 2.54,0)."""
    pads = []
    rows = math.ceil(num_pins / 2)
    pitch = 2.54
    total_len = (rows - 1) * pitch
    col_spacing = 2.54

    for r in range(rows):
        py = r * pitch
        # Pino ímpar na coluna 0
        p1 = str(2 * r + 1)
        shape1 = "roundrect" if r == 0 else "oval"
        pads.append(Pad(num=p1, rx=0.0, ry=py, w=1.7, h=1.7, shape=shape1, tht=True, drill=1.0))
        # Pino par na coluna 1
        if 2 * r + 2 <= num_pins:
            p2 = str(2 * r + 2)
            pads.append(Pad(num=p2, rx=col_spacing, ry=py, w=1.7, h=1.7, shape="oval", tht=True, drill=1.0))

    lib_name = f"Connector_PinHeader_2.54mm:PinHeader_2x{rows:02d}_P2.54mm_Vertical"
    courtyard = (-1.5, -1.5, col_spacing + 1.5, total_len + 1.5)

    fp = Footprint(
        ref=ref,
        value=value,
        lib_name=lib_name,
        x=x,
        y=y,
        pads=pads,
        courtyard=courtyard,
        tht=True,
    )
    for p in pads:
        p.fp = fp
    return fp


def generate_gal_pcb(
    design: SynthesizedDesign,
    packed_chips: List[PackedGAL],
    out_pcb_path: Path,
    layers: int = 4,
) -> Board:
    """Gera o arquivo de circuito impresso KiCad (.kicad_pcb) com os chips GAL."""
    dev = design.device
    num_chips = len(packed_chips)

    # Disposição equilibrada dos chips em grade colunas x linhas
    if num_chips <= 4:
        cols_count = 1
        chips_per_col = num_chips
    elif num_chips <= 8:
        cols_count = 2
        chips_per_col = math.ceil(num_chips / 2)
    elif num_chips <= 12:
        cols_count = 3
        chips_per_col = math.ceil(num_chips / 3)
    else:
        cols_count = math.ceil(num_chips / 4)
        chips_per_col = 4

    chip_spacing_x = 35.0  # mm entre colunas de GALs
    chip_spacing_y = 38.0  # mm entre linhas de GALs
    margin_x = 18.0
    margin_y = 18.0

    board_w = margin_x * 2 + cols_count * chip_spacing_x + 22.0  # espaço extra para conector
    board_h = margin_y * 2 + chips_per_col * chip_spacing_y

    footprints: List[Footprint] = []

    # 1. Posiciona os chips GAL e seus capacitores de desacoplamento
    for idx, chip in enumerate(packed_chips):
        col_idx = idx // chips_per_col
        row_idx = idx % chips_per_col

        cx = margin_x + col_idx * chip_spacing_x + 5.0
        cy = margin_y + row_idx * chip_spacing_y + 5.0

        # Soquete DIP
        socket = make_dip_socket(chip.chip_id, dev.name, dev.num_pins, cx, cy)
        # Atribui nets aos pads do soquete
        for pad in socket.pads:
            pin_num = int(pad.num)
            net_name = chip.pin_assignment.get(pin_num, "")
            pad.net = net_name
        footprints.append(socket)

        # Capacitor de desacoplamento (100nF) ao lado do pino 24 (VCC)
        cap_ref = f"C{idx + 1}"
        cap_x = cx + 7.62 + 4.5
        cap_y = cy
        cap = make_c0805(cap_ref, "100nF", cap_x, cap_y)
        cap.pad("1").net = "VCC"
        cap.pad("2").net = "GND"
        footprints.append(cap)

    # 2. Conector de E/S na borda direita
    io_signals = list(design.primary_inputs) + list(design.primary_outputs)
    io_signals.append("VCC")
    io_signals.append("GND")
    if design.clk_net and design.clk_net not in io_signals:
        io_signals.insert(0, design.clk_net)

    conn_rows = math.ceil(len(io_signals) / 2)
    conn_len = (conn_rows - 1) * 2.54
    conn_x = board_w - 12.0
    conn_y = (board_h - conn_len) / 2.0
    conn = make_connector("J1", f"IO_{design.top}", len(io_signals), conn_x, conn_y)

    for idx, sig in enumerate(io_signals):
        pad_num = str(idx + 1)
        try:
            p = conn.pad(pad_num)
            p.net = sig
        except KeyError:
            pass
    footprints.append(conn)

    # 3. Furos de fixação nos 4 cantos (M3)
    hole_inset = 5.0
    footprints.append(mounting_hole("H1", hole_inset, hole_inset, "M3"))
    footprints.append(mounting_hole("H2", board_w - hole_inset, hole_inset, "M3"))
    footprints.append(mounting_hole("H3", hole_inset, board_h - hole_inset, "M3"))
    footprints.append(mounting_hole("H4", board_w - hole_inset, board_h - hole_inset, "M3"))

    rules = Rules()
    board = Board(
        width=board_w,
        height=board_h,
        footprints=footprints,
        vdd="VCC",
        gnd="GND",
        rules=rules,
        layers=layers,
    )

    # Salva o arquivo de placa KiCad
    out_pcb_path = Path(out_pcb_path)
    out_pcb_path.parent.mkdir(parents=True, exist_ok=True)
    write_pcb(board, out_pcb_path, title=f"PLD-{design.top} ({len(packed_chips)}x {dev.name})")

    return board
