"""Linha de comando para o compilador GAL: fr4lane-pld."""

import argparse
import sys
from pathlib import Path

from .. import project
from .devices import DEVICES
from .flow import run_gal_flow


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(
        prog="fr4lane-pld",
        description="Compilador e empacotador de circuitos Verilog para chips GAL (Generic Array Logic)."
    )
    ap.add_argument("--top", required=True, help="Módulo topo do circuito")
    ap.add_argument("--src", nargs="+", help="Arquivos fonte Verilog/SystemVerilog")
    ap.add_argument("--device", default="GAL22V10", choices=list(DEVICES.keys()),
                    help="Dispositivo alvo: GAL22V10 (padrão) ou GAL16V8")
    ap.add_argument("--out", help="Diretório de saída para arquivos .jed, .pld, relatório e PCB")
    ap.add_argument("--layers", type=int, choices=(2, 4), default=4,
                    help="Camadas da placa PCB (4 = planos internos VCC/GND; 2 = trilhos de alimentação)")
    ap.add_argument("--project", help="Pasta do projeto com fr4lane.json (opcional)")

    args = ap.parse_args(argv)

    try:
        proj = project.find(args.project)
    except Exception:
        proj = None

    sources = []
    if args.src:
        for s in args.src:
            sources.append(Path(s))
    elif proj:
        sources = proj.sources()

    if not sources:
        print("ERRO: Nenhuma fonte Verilog informada (--src ou 'src' no fr4lane.json).", file=sys.stderr)
        return 1

    outdir = Path(args.out) if args.out else (proj.out_dir(f"{args.top}_{args.device.lower()}") if proj else Path("build") / f"{args.top}_{args.device.lower()}")

    print(f"[*] Iniciando síntese e empacotamento GAL para '{args.top}'...")
    print(f"[*] Dispositivo alvo: {args.device}")
    print(f"[*] Fontes: {[s.name for s in sources]}")
    print(f"[*] Saída: {outdir}")

    try:
        result = run_gal_flow(
            sources=sources,
            top=args.top,
            device=args.device,
            outdir=outdir,
            layers=args.layers,
        )
    except Exception as e:
        print(f"ERRO durante o fluxo GAL: {e}", file=sys.stderr)
        return 2

    print("\n" + "=" * 60)
    print(f"[✓] Compilação GAL concluída com sucesso!")
    print(f"    - Chips GAL necessários: {result.chip_count}x {result.device}")
    print(f"    - Aproveitamento de macrocélulas: {result.macrocell_utilization:.1f}%")
    print(f"    - Termos de produto: {result.pterms_used}/{result.pterms_capacity}")
    print(f"    - Arquivos JEDEC gerados:")
    for jf in result.jedec_files:
        print(f"      -> {jf.resolve()}")
    print(f"    - Relatório detalhado: {result.report_file.resolve()}")
    print(f"    - Placa KiCad: {result.pcb_file.resolve()}")
    print("=" * 60 + "\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
