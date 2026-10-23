"""Fluxo completo de síntese, empacotamento, JEDEC e PCB para dispositivos GAL."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .devices import GAL22V10, GALDevice, get_device
from .jedec import generate_jedec
from .packer import PackedGAL, pack_design_to_gals
from .pcb import generate_gal_pcb
from .report import generate_equations_pld, generate_packing_report
from .synth import SynthesizedDesign, synthesize_gal


@dataclass
class GALFlowResult:
    """Resultado consolidado do fluxo de compilação GAL."""
    top: str
    device: str
    chip_count: int
    macrocell_utilization: float
    pterms_used: int
    pterms_capacity: int
    jedec_files: List[Path]
    pld_files: List[Path]
    report_file: Path
    pcb_file: Path
    packed_chips: List[PackedGAL]


def run_gal_flow(
    sources: List[Path],
    top: str,
    device: str = "GAL22V10",
    outdir: Optional[Path] = None,
    defines: Tuple[str, ...] = (),
    layers: int = 4,
    floorplan=None,
) -> GALFlowResult:
    """Executa o pipeline completo: Verilog -> Yosys SOP -> GAL Packing -> JEDEC + PCB."""
    dev = get_device(device)
    if outdir is None:
        outdir = Path("build") / f"{top}_{dev.name.lower()}"
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # 1. Síntese lógica para Soma de Produtos (SOP)
    synth_design = synthesize_gal(sources=sources, top=top, device=device, outdir=outdir, defines=defines)

    # 2. Particionamento e empacotamento com aproveitamento máximo
    packed_chips = pack_design_to_gals(synth_design, chip_prefix="U")

    # 3. Geração dos arquivos de programação JEDEC (.jed) e equações (.pld)
    jedec_files: List[Path] = []
    pld_files: List[Path] = []

    for chip in packed_chips:
        jed_path = outdir / f"{chip.chip_id}_{top}_{dev.name}.jed"
        pld_path = outdir / f"{chip.chip_id}_{top}_{dev.name}.pld"

        generate_jedec(chip, design_name=top, out_path=jed_path)
        pld_text = generate_equations_pld(chip, design_name=top)
        pld_path.write_text(pld_text, encoding="utf-8")

        jedec_files.append(jed_path)
        pld_files.append(pld_path)

    # 4. Geração do relatório detalhado
    report_path = outdir / "gal_packing_report.md"
    generate_packing_report(synth_design, packed_chips, out_dir=outdir)

    # 5. Geração do circuito impresso KiCad (.kicad_pcb)
    pcb_path = outdir / f"{top}_{dev.name.lower()}.kicad_pcb"
    board = generate_gal_pcb(synth_design, packed_chips, out_pcb_path=pcb_path, layers=layers, floorplan=floorplan)

    # 6. Grava placement.json para integração visual com o editor de floorplan (fpedit)
    parts = []
    for f in board.footprints:
        x0, y0, x1, y1 = f.courtyard
        parts.append({
            "ref": f.ref,
            "module": None,
            "box": [round(f.x + x0, 3), round(f.y + y0, 3), round(f.x + x1, 3), round(f.y + y1, 3)]
        })
    placement_data = {
        "top": top,
        "family": dev.name.lower(),
        "library": dev.name,
        "sources": [str(s.resolve()) for s in sources],
        "layers": layers,
        "placed": True,
        "board": [board.width, board.height],
        "floorplan": str(Path(floorplan).resolve()) if floorplan else None,
        "geo": {"row_pitch": 38.0, "pin_pitch": 2.54},
        "min_width": board.width,
        "module_width": {},
        "module_types": {},
        "footprints": parts,
        "macros": None,
        "ports": [{"name": p, "dir": "input" if p in synth_design.primary_inputs else "output"} for p in list(synth_design.primary_inputs) + list(synth_design.primary_outputs)],
        "connectors": [],
    }
    (outdir / "placement.json").write_text(json.dumps(placement_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Métricas globais
    tot_used = sum(len(c.olmc_placements) for c in packed_chips)
    tot_avail = len(packed_chips) * dev.num_olmcs
    glob_util = (tot_used / tot_avail) * 100.0 if tot_avail else 0.0

    tot_pterms = sum(c.total_pterms_used for c in packed_chips)
    tot_cap = sum(c.total_pterms_capacity for c in packed_chips)

    return GALFlowResult(
        top=top,
        device=dev.name,
        chip_count=len(packed_chips),
        macrocell_utilization=glob_util,
        pterms_used=tot_pterms,
        pterms_capacity=tot_cap,
        jedec_files=jedec_files,
        pld_files=pld_files,
        report_file=report_path,
        pcb_file=pcb_path,
        packed_chips=packed_chips,
    )
