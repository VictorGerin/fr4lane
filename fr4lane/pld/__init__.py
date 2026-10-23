"""Módulo de síntese, otimização e empacotamento para dispositivos lógicos programáveis (PLD/GAL).

Suporta GAL22V10 (ATF22V10C) e GAL16V8 (ATF16V8B).
Gera arquivos de queima JEDEC (.jed), equações em formato CUPL/ABEL (.pld),
relatórios de aproveitamento (.md) e placas KiCad (.kicad_pcb).
"""

from .devices import GAL16V8, GAL22V10, GALDevice, OLMCDef, get_device
from .flow import GALFlowResult, run_gal_flow
from .jedec import generate_jedec
from .packer import PackedGAL, pack_design_to_gals
from .pcb import generate_gal_pcb
from .report import generate_ascii_pinout, generate_equations_pld, generate_packing_report
from .synth import LogicCone, ProductTerm, SynthesizedDesign, synthesize_gal

__all__ = [
    "GAL16V8",
    "GAL22V10",
    "GALDevice",
    "OLMCDef",
    "get_device",
    "LogicCone",
    "ProductTerm",
    "SynthesizedDesign",
    "synthesize_gal",
    "PackedGAL",
    "pack_design_to_gals",
    "generate_jedec",
    "generate_gal_pcb",
    "generate_ascii_pinout",
    "generate_equations_pld",
    "generate_packing_report",
    "GALFlowResult",
    "run_gal_flow",
]
