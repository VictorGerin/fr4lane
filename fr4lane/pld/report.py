"""Geração de relatórios de utilização, pinagem ASCII e equações booleanas para chips GAL."""

from pathlib import Path
from typing import Dict, List, Optional

from .devices import GAL22V10, GALDevice
from .packer import PackedGAL
from .synth import SynthesizedDesign


def generate_ascii_pinout(packed: PackedGAL) -> str:
    """Gera um diagrama ASCII detalhado do encapsulamento DIP com a função de cada pino."""
    dev = packed.device
    num_pins = dev.num_pins
    half = num_pins // 2

    lines = []
    lines.append(f"               +-------\\__/-------+")
    for left_pin in range(1, half + 1):
        right_pin = num_pins - left_pin + 1

        left_net = packed.pin_assignment.get(left_pin, "NC")
        right_net = packed.pin_assignment.get(right_pin, "NC")

        # Tags de função
        left_tag = ""
        if left_pin == dev.clk_pin and packed.clk_pin:
            left_tag = "[CLK] "
        elif left_pin in packed.olmc_placements:
            left_tag = "[OUT] "
        elif left_pin in packed.input_pins.values():
            left_tag = "[IN]  "

        right_tag = ""
        if right_pin in packed.olmc_placements:
            right_tag = " [OUT]"
        elif right_pin in packed.input_pins.values():
            right_tag = " [IN]"

        left_str = f"{left_tag}{left_net}".rjust(18)
        right_str = f"{right_net}{right_tag}".ljust(18)

        lines.append(f" {left_str} | {left_pin:2d}           {right_pin:2d} | {right_str}")

    lines.append(f"               +------------------+")
    return "\n".join(lines)


def generate_equations_pld(packed: PackedGAL, design_name: str) -> str:
    """Exporta as equações lógicas no formato padrão CUPL / ABEL para conferência humana."""
    dev = packed.device
    lines = []
    lines.append(f"/* =============================================================== */")
    lines.append(f"/* Chip:   {packed.chip_id} ({dev.name})")
    lines.append(f"/* Design: {design_name}")
    lines.append(f"/* Macrocell Utilization: {packed.macrocell_utilization:.1f}%")
    lines.append(f"/* Product Terms Used:    {packed.total_pterms_used}/{packed.total_pterms_capacity}")
    lines.append(f"/* =============================================================== */")
    lines.append("")
    lines.append(f"Name     {packed.chip_id}_{design_name} ;")
    lines.append(f"Device   {dev.name.lower()} ;")
    lines.append("")

    # Declaração de pinos
    lines.append("/* --- Pin Declarations --- */")
    for pin in range(1, dev.num_pins + 1):
        if pin in packed.pin_assignment:
            sig = packed.pin_assignment[pin]
            if sig not in ("VCC", "GND"):
                lines.append(f"PIN {pin:2d} = {sig} ;")
    lines.append("")

    # Equações booleanas
    lines.append("/* --- Boolean Logic Equations --- */")
    for pin, place in packed.olmc_placements.items():
        cone = place.cone
        op = ".D" if cone.is_registered else ""
        lhs = f"{cone.name}{op}"

        # Monta os termos AND somados com # (OR em CUPL)
        term_strs = []
        for pt in cone.product_terms:
            lits = []
            for sig, bit in pt.literals.items():
                if bit == 1:
                    lits.append(sig)
                else:
                    lits.append(f"!{sig}")
            if lits:
                term_strs.append(" & ".join(lits))
            else:
                term_strs.append("1")

        if not term_strs:
            rhs = "0"
        else:
            rhs = " #\n        ".join(term_strs)

        if not cone.active_high:
            lines.append(f"!{lhs} =\n        {rhs} ;")
        else:
            lines.append(f"{lhs} =\n        {rhs} ;")

        if cone.is_registered and packed.clk_pin:
            clk_name = packed.pin_assignment.get(packed.clk_pin, "CLK")
            lines.append(f"{cone.name}.CLK = {clk_name} ;")
        lines.append("")

    return "\n".join(lines)


def generate_packing_report(
    design: SynthesizedDesign,
    packed_chips: List[PackedGAL],
    out_dir: Optional[Path] = None,
) -> str:
    """Gera um relatório completo em Markdown detalhando o aproveitamento de cada GAL."""
    dev = design.device
    total_olmcs_avail = len(packed_chips) * dev.num_olmcs
    total_olmcs_used = sum(len(c.olmc_placements) for c in packed_chips)
    global_utilization = (total_olmcs_used / total_olmcs_avail) * 100.0 if total_olmcs_avail else 0.0

    total_pterms_used = sum(c.total_pterms_used for c in packed_chips)
    total_pterms_cap = sum(c.total_pterms_capacity for c in packed_chips)

    md = []
    md.append(f"# Relatório de Síntese e Empacotamento GAL: `{design.top}`")
    md.append("")
    md.append(f"- **Dispositivo Alvo:** {dev.name} ({dev.num_pins} pinos, {dev.num_olmcs} macrocélulas por chip)")
    md.append(f"- **Chips GAL Necessários:** {len(packed_chips)}")
    md.append(f"- **Aproveitamento Global de Macrocélulas:** {global_utilization:.1f}% ({total_olmcs_used}/{total_olmcs_avail} OLMCs)")
    md.append(f"- **Termos de Produto Utilizados:** {total_pterms_used}/{total_pterms_cap} pterms")
    md.append(f"- **Entradas Primárias do Sistema:** {len(design.primary_inputs)}")
    md.append(f"- **Saídas Primárias do Sistema:** {len(design.primary_outputs)}")
    md.append("")

    md.append("## Tabela de Chips e Eficiência de Empacotamento")
    md.append("")
    md.append("| Chip | Dispositivo | OLMCs Usadas | Ocupação (%) | P-Terms Usados | Entradas Ext | Feedback Interno |")
    md.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
    for c in packed_chips:
        md.append(
            f"| `{c.chip_id}` | {c.device.name} | {len(c.olmc_placements)}/{c.device.num_olmcs} | "
            f"**{c.macrocell_utilization:.1f}%** | {c.total_pterms_used}/{c.total_pterms_capacity} | "
            f"{len(c.input_pins)} | {len(c.internal_feedbacks)} nets |"
        )
    md.append("")

    md.append("## Detalhamento de Pinos por Chip")
    md.append("")
    for c in packed_chips:
        md.append(f"### Chip `{c.chip_id}` ({c.device.name})")
        md.append(f"```text\n{generate_ascii_pinout(c)}\n```")
        md.append("")

    report_text = "\n".join(md)
    if out_dir:
        (Path(out_dir) / "gal_packing_report.md").write_text(report_text, encoding="utf-8")

    return report_text
