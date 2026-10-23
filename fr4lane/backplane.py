"""Geração automática de Backplane PCB para sistemas multi-placa no fr4lane.

Um sistema multi-placa (como o SERV RV32I ou SAP-1) divide o circuito em várias
placas filhas (ex: u_ctrl, u_pc, u_alu, u_rf_mem) ligadas por um módulo top estrutural.
O gerador de backplane lê a conectividade de interconexão e os conectores físicos
de cada placa filha, criando a PCB do Backplane correspondente com:

  1. Slots mecânicos com barras de soquetes fêmea (PinSocket 2.54 mm) casando
     com as barras de pinos macho de cada placa filha.
  2. Distribuição robusta de alimentação:
     - Borne a parafuso Phoenix MKDS (5.08 mm) para entrada de 5V e GND;
     - Capacitor eletrolítico bulk (1000 µF) na entrada de energia;
     - Capacitores de desacoplamento de 100 nF dedicados para cada slot;
     - Placa de 4 camadas por padrão com planos internos In1.Cu (GND) e In2.Cu (VDD).
  3. Barras de conectores de E/S externa para sinais do sistema (clk, reset,
     barramentos de memória/Wishbone/periféricos).
  4. Furos de fixação mecânica M3 nos quatro cantos.
  5. Roteamento de trilhas ponto-a-ponto e barramentos multiponto entre slots.
  6. Exportação KiCad (.kicad_pcb, .kicad_pro) e renderização 3D raytracing.

Uso via CLI:
  python -m fr4lane.backplane --top serv_system --boards serv_ctrl_board serv_pc_board serv_alu_board serv_rf_mem_board --lib relay
"""

import argparse
import glob
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from . import drc, kicad, layout, route, system, synth
from .layout import Board, Footprint, Pad, Rules, pin_header, pin_socket
from .library import Library, resolve_family


# ------------------------------------------------------------------ Auxiliares de Footprints
def power_terminal(ref, value="POWER_5V", pitch=5.08, x=0.0, y=0.0):
    """Borne de parafuso 2 pinos 5.08mm para alimentação (VDD / GND)."""
    lib_name = "TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal"
    fp = Footprint(ref, value, lib_name, x=x, y=y, courtyard=(-2.5, -4.0, pitch + 2.5, 4.0), tht=True)
    fp.pads.append(Pad("1", 0.0, 0.0, 3.2, 3.2, "rect", tht=True, drill=1.3, fp=fp))
    fp.pads.append(Pad("2", pitch, 0.0, 3.2, 3.2, "oval", tht=True, drill=1.3, fp=fp))
    fp.silk = [
        (-2.5, -4.0, pitch + 2.5, -4.0),
        (pitch + 2.5, -4.0, pitch + 2.5, 4.0),
        (pitch + 2.5, 4.0, -2.5, 4.0),
        (-2.5, 4.0, -2.5, -4.0),
    ]
    return fp


def bulk_capacitor(ref, value="1000uF", pitch=5.0, x=0.0, y=0.0):
    """Capacitor eletrolítico bulk radial D10mm P5mm."""
    lib_name = "Capacitor_THT:CP_Radial_D10.0mm_P5.00mm"
    fp = Footprint(ref, value, lib_name, x=x, y=y, courtyard=(-5.5, -5.5, 5.5, 5.5), tht=True)
    fp.pads.append(Pad("1", -pitch / 2, 0.0, 2.0, 2.0, "rect", tht=True, drill=0.8, fp=fp))
    fp.pads.append(Pad("2", pitch / 2, 0.0, 2.0, 2.0, "oval", tht=True, drill=0.8, fp=fp))
    fp.silk = [
        (-4.0, -2.0, -4.0, 2.0),
        (-5.0, 0.0, -3.0, 0.0),
    ]
    return fp


def decoupling_capacitor(ref, value="100nF", pitch=5.0, x=0.0, y=0.0):
    """Capacitor cerâmico/filme de desacoplamento P5mm."""
    lib_name = "Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P5.00mm"
    fp = Footprint(ref, value, lib_name, x=x, y=y, courtyard=(-3.5, -2.0, 3.5, 2.0), tht=True)
    fp.pads.append(Pad("1", -pitch / 2, 0.0, 1.8, 1.8, "oval", tht=True, drill=0.8, fp=fp))
    fp.pads.append(Pad("2", pitch / 2, 0.0, 1.8, 1.8, "oval", tht=True, drill=0.8, fp=fp))
    fp.silk = [(-2.5, -1.2, 2.5, -1.2), (2.5, 1.2, -2.5, 1.2)]
    return fp


def mounting_hole(ref, x, y):
    """Furo de fixação M3 (3.2 mm drill)."""
    lib_name = "MountingHole:MountingHole_3.2mm_M3"
    fp = Footprint(ref, "M3", lib_name, x=x, y=y, courtyard=(-3.0, -3.0, 3.0, 3.0), tht=True)
    fp.pads.append(Pad("1", 0.0, 0.0, 3.2, 3.2, "circle", tht=True, drill=3.2, fp=fp))
    return fp


# ------------------------------------------------------------------ Motor de Geração
def find_board_placement(board_name, lib_name, search_dirs=None):
    """Localiza o placement.json de uma placa filha gerada anteriormente."""
    dirs = search_dirs or [
        Path("build/pcb") / f"{board_name}_{lib_name}",
        Path("build/pcb") / board_name,
        Path("build") / f"{board_name}_{lib_name}",
        Path("build") / board_name,
        Path(f"build/pcb/{board_name}_{lib_name}"),
    ]
    for d in dirs:
        p = Path(d) / "placement.json"
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    # Busca recursiva no workspace
    candidates = list(Path(".").glob(f"**/{board_name}_{lib_name}*/placement.json")) + \
                 list(Path(".").glob(f"**/{board_name}*/placement.json"))
    if candidates:
        return json.loads(candidates[0].read_text(encoding="utf-8"))
    raise FileNotFoundError(
        f"Não encontrou placement.json da placa '{board_name}' (família '{lib_name}'). "
        f"Execute fr4lane --top {board_name} --lib {lib_name} antes de gerar o backplane."
    )


def clean_net_name(raw_name):
    """Converte identificadores de barramento Verilog para nomes válidos de net KiCad."""
    return str(raw_name).replace("[", "_").replace("]", "").replace(".", "_").replace("$", "")


def generate_backplane(
    top,
    boards,
    lib="relay",
    sources=None,
    slot_pitch=45.0,
    col_gap=7.62,
    layers=4,
    ext_io=True,
    out_dir=None,
    no_route=False,
    no_drc=False,
    render=True,
    title="",
):
    """Gera a placa de circuito impresso completa do Backplane."""
    t0 = time.time()
    lib_family = resolve_family(lib) if isinstance(lib, str) else lib
    lib_family_name = lib_family.name if isinstance(lib_family, Path) else str(lib_family)
    out_dir = Path(out_dir) if out_dir else Path("build/pcb") / f"{top}_backplane_{lib_family_name}"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n=======================================================")
    print(f"  fr4lane Backplane Generator: {top}")
    print(f"  Tecnologia das filhas: {lib_family_name}")
    print(f"  Placas filhas: {', '.join(boards)}")
    print(f"  Camadas: {layers} (plano GND In1.Cu / plano VDD In2.Cu)")
    print(f"  Slot Pitch: {slot_pitch} mm | Gap entre colunas: {col_gap} mm")
    print(f"=======================================================\n")

    # 1. Carrega o placement das placas filhas
    print(f"[1/6] Carregando conectores das placas filhas...")
    board_placements = {}
    for b in boards:
        data = find_board_placement(b, lib_family_name)
        board_placements[b] = data
        conns_count = len(data.get("connectors", []))
        total_pins = sum(len(c.get("pins", [])) for c in data.get("connectors", []))
        print(f"  Placa '{b}': {conns_count} conectores, {total_pins} pinos no total")

    # 2. Descobre fontes se não informadas ou expande globs
    if not sources:
        sources = sorted(glob.glob("rtl/*.sv") + glob.glob("rtl/*.v") + glob.glob("*.sv") + glob.glob("*.v"))
        if not sources:
            sources = sorted(glob.glob(f"examples/**/{top}.sv", recursive=True))
    else:
        expanded = []
        for s in sources:
            if "*" in s or "?" in s:
                g = glob.glob(s)
                expanded.extend(g if g else [s])
            else:
                expanded.append(s)
        sources = sorted(expanded)

    # 3. Conectividade via Yosys
    print(f"[2/6] Sintetizando conectividade multi-placa com Yosys...")
    insts, conns, sys_ports = system.connectivity(sources, top, boards, out_dir)
    print(f"  Instâncias instanciadas no {top}: {len(insts)}")
    print(f"  Ligações inter-placas: {len(conns)}")
    print(f"  Portas externas do sistema: {len(sys_ports)}")

    # 4. Mapeamento de sinais para nomes de net KiCad
    # ext_net_map: net_id -> nome_da_porta_externa
    ext_net_map = {net_id: pname for pname, (pdir, net_id) in sys_ports.items()}
    net_names_by_id = {}
    for (inst, port), net_id in conns.items():
        if net_id in ext_net_map:
            net_names_by_id[net_id] = clean_net_name(ext_net_map[net_id])
        elif net_id not in net_names_by_id:
            net_names_by_id[net_id] = f"net_{net_id}_{clean_net_name(port)}"

    # 5. Geometria e posicionamento mecânico dos slots
    print(f"[3/6] Posicionamento mecânico dos slots e componentes...")
    footprints = []
    board_port_labels = {}

    x_start = 30.0
    y_start = 30.0
    max_y_reached = y_start

    # Posiciona os slots das placas filhas
    slot_positions = {}
    for slot_idx, (inst, bname) in enumerate(insts):
        slot_x = x_start + slot_idx * slot_pitch
        slot_positions[inst] = slot_x
        bdata = board_placements[bname]
        conns_list = bdata.get("connectors", [])

        # Separa conectores por borda/lado
        left_conns = [c for c in conns_list if c.get("side") == "left"]
        right_conns = [c for c in conns_list if c.get("side") == "right"]
        other_conns = [c for c in conns_list if c.get("side") not in ("left", "right")]

        # Se todos os conectores estiverem do mesmo lado, usa coluna única
        cols = []
        if left_conns and right_conns:
            cols = [
                (slot_x, left_conns),
                (slot_x + col_gap, right_conns + other_conns),
            ]
        elif left_conns:
            cols = [(slot_x, left_conns + other_conns)]
        elif right_conns:
            cols = [(slot_x, right_conns + other_conns)]
        else:
            cols = [(slot_x, conns_list)]

        for col_x, col_conns in cols:
            cur_y = y_start
            for c in col_conns:
                pins = c.get("pins", [])
                n_pins = len(pins)
                if n_pins == 0:
                    continue
                # Soquete fêmea correspondente
                ref = f"J_{inst}_{c['name']}"
                fp = pin_socket(ref=ref, n_pins=n_pins, value=f"{inst}:{c['name']}")
                fp.x = col_x
                fp.y = cur_y

                # Associa as nets aos pads
                labels = []
                for p_idx, port in enumerate(pins):
                    pad = fp.pads[p_idx]
                    labels.append(port)
                    if port == "VDD":
                        pad.net = "VDD"
                    elif port == "GND":
                        pad.net = "GND"
                    elif port in ("NC", ""):
                        pad.net = ""
                    else:
                        nid = conns.get((inst, port))
                        if nid is not None:
                            pad.net = net_names_by_id.get(nid, f"net_{nid}")
                        else:
                            pad.net = ""
                board_port_labels[ref] = labels
                footprints.append(fp)
                cur_y += (n_pins - 1) * 2.54 + 6.0
            max_y_reached = max(max_y_reached, cur_y)

        # Capacitor de desacoplamento do slot
        c_dec = decoupling_capacitor(
            ref=f"C_DEC_{slot_idx + 1}",
            value="100nF",
            x=slot_x + col_gap / 2.0,
            y=y_start - 12.0,
        )
        c_dec.pads[0].net = "VDD"
        c_dec.pads[1].net = "GND"
        footprints.append(c_dec)

    last_slot_x = x_start + (len(insts) - 1) * slot_pitch + col_gap

    # 6. Conectores de E/S Externa (EXT_IO)
    ext_io_x = last_slot_x + slot_pitch * 0.9
    if ext_io and sys_ports:
        print(f"  Adicionando conectores de E/S Externa para {len(sys_ports)} sinais do sistema...")
        # Agrupa portas externas
        sorted_sys = sorted(sys_ports.items(), key=lambda kv: (kv[1][0], kv[0]))
        # Divide em barras de pinos de até 40 pinos
        CHUNK_SIZE = 38  # 38 sinais + VDD + GND = 40 pinos
        chunks = [sorted_sys[i : i + CHUNK_SIZE] for i in range(0, len(sorted_sys), CHUNK_SIZE)]

        ext_col_y = [y_start, y_start]
        for ch_idx, chunk in enumerate(chunks):
            n_pins = len(chunk) + 2
            ref = f"J_EXT{ch_idx + 1}"
            col = ch_idx % 2
            fp = pin_header(ref=ref, n_pins=n_pins, value=f"EXT_IO_{ch_idx + 1}")
            fp.x = ext_io_x + col * col_gap
            fp.y = ext_col_y[col]

            fp.pads[0].net = "VDD"
            fp.pads[1].net = "GND"
            labels = ["VDD", "GND"]

            for p_idx, (pname, (pdir, nid)) in enumerate(chunk):
                pad = fp.pads[p_idx + 2]
                pad.net = net_names_by_id.get(nid, clean_net_name(pname))
                labels.append(pname)

            board_port_labels[ref] = labels
            footprints.append(fp)
            ext_col_y[col] += (n_pins - 1) * 2.54 + 6.0
            max_y_reached = max(max_y_reached, ext_col_y[col])
        last_slot_x = ext_io_x + col_gap

    # 7. Conector de alimentação MKDS e Capacitor Bulk
    j_pwr = power_terminal(ref="J_PWR", value="5V_DC_IN", pitch=5.08, x=15.0, y=14.0)
    j_pwr.pads[0].net = "VDD"
    j_pwr.pads[1].net = "GND"
    footprints.append(j_pwr)

    c_bulk = bulk_capacitor(ref="C_BULK", value="1000uF_16V", pitch=5.0, x=30.0, y=14.0)
    c_bulk.pads[0].net = "VDD"
    c_bulk.pads[1].net = "GND"
    footprints.append(c_bulk)

    # 8. Dimensões finais da placa e furos de fixação M3
    board_w = math.ceil((last_slot_x + 25.0) / 5.0) * 5.0
    board_h = math.ceil((max_y_reached + 25.0) / 5.0) * 5.0

    m_margin = 5.0
    footprints.append(mounting_hole("H1", m_margin, m_margin))
    footprints.append(mounting_hole("H2", board_w - m_margin, m_margin))
    footprints.append(mounting_hole("H3", m_margin, board_h - m_margin))
    footprints.append(mounting_hole("H4", board_w - m_margin, board_h - m_margin))

    # Criação do objeto Board do fr4lane
    rules = Rules(grid=0.5, track_width=0.3, clearance=0.25, via_size=0.6, via_drill=0.3)
    board = Board(
        width=board_w,
        height=board_h,
        footprints=footprints,
        vdd="VDD",
        gnd="GND",
        rules=rules,
        layers=layers,
    )
    board.port_labels = board_port_labels

    all_nets = board.nets()
    signal_nets = [n for n in all_nets if n not in ("VDD", "GND")]
    print(f"  Dimensões do Backplane: {board_w:.1f} x {board_h:.1f} mm")
    print(f"  Total de componentes: {len(footprints)}")
    print(f"  Total de nets físicas: {len(all_nets)} ({len(signal_nets)} sinais + VDD + GND)")

    # 9. Roteamento das trilhas
    if not no_route:
        print(f"\n[4/6] Roteando nets inter-placas e barramentos (A* Router)...")
        t_route = time.time()
        route.route(board, max_iter=40)
        dt_route = time.time() - t_route
        routed_tracks = len(board.tracks)
        routed_vias = len(board.vias)
        print(f"  Roteamento concluído em {dt_route:.1f}s ({routed_tracks} segmentos de trilha, {routed_vias} vias)")
        if board.unrouted:
            print(f"  AVISO: {len(board.unrouted)} ligações não puderam ser roteadas 100%:")
            for u in board.unrouted[:10]:
                print(f"    - {u}")
    else:
        print(f"\n[4/6] Roteamento ignorado (--no-route). Placa gerada com rat's nest.")

    # 10. Exportação do projeto KiCad
    print(f"\n[5/6] Exportando projeto KiCad (.kicad_pcb e .kicad_pro)...")
    pcb_title = title or f"{top} Backplane ({lib_family_name.upper()})"
    pro_path = out_dir / f"{top}_backplane.kicad_pro"
    pcb_path = out_dir / f"{top}_backplane.kicad_pcb"

    kicad.write_project(board, pro_path)
    kicad.write_pcb(board, pcb_path, title=pcb_title)
    print(f"  Projeto gravado em: {pcb_path}")

    # DRC opcional
    if not no_drc and not no_route:
        print(f"  Executando DRC do KiCad / preenchimento de zonas...")
        try:
            cli = drc.find_cli()
            if cli:
                rpt = drc.run(cli, pcb_path, out_dir / "drc.json")
                print(f"  DRC: {len(rpt.get('errors', []))} erros, {len(rpt.get('unconnected', []))} desconectados")
        except Exception as e:
            print(f"  DRC nota: {e}")

    # 11. Renderização 3D fotorrealista via KiCad CLI
    render_path = out_dir / "render_3d.png"
    if render:
        print(f"\n[6/6] Renderizando visualização 3D fotorrealista...")
        kicad_cli_bin = None
        for cand in [
            r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe",
            r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe",
            r"C:\Program Files\KiCad\8.0\bin\kicad-cli.exe",
            "kicad-cli",
        ]:
            if Path(cand).is_file() or cand == "kicad-cli":
                kicad_cli_bin = cand
                break

        if kicad_cli_bin:
            cmd = [
                str(kicad_cli_bin),
                "pcb",
                "render",
                "--output",
                str(render_path),
                "--rotate",
                "-45,0,45",
                "--width",
                "1920",
                "--height",
                "1080",
                "--quality",
                "high",
                "--floor",
                str(pcb_path),
            ]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if res.returncode == 0 and render_path.is_file():
                    print(f"  Render 3D gerado com sucesso: {render_path}")
                else:
                    print(f"  Render 3D falhou ou retornou código {res.returncode}: {res.stderr}")
            except Exception as ex:
                print(f"  Não foi possível renderizar 3D: {ex}")
        else:
            print("  kicad-cli não encontrado no sistema.")

    dt_total = time.time() - t0
    print(f"\n=======================================================")
    print(f"  Backplane concluído com sucesso em {dt_total:.1f}s!")
    print(f"  Pasta de saída: {out_dir.resolve()}")
    print(f"=======================================================\n")
    return board, pcb_path, render_path


# ------------------------------------------------------------------ Linha de Comando
def main():
    parser = argparse.ArgumentParser(description="Gera uma placa Backplane para sistema multi-placa no fr4lane.")
    parser.add_argument("--top", required=True, help="Nome do módulo top do sistema (ex: serv_system, sap1)")
    parser.add_argument("--boards", nargs="+", required=True, help="Nomes dos módulos das placas filhas")
    parser.add_argument("--lib", default="relay", help="Família de tecnologia das filhas (relay, cmos4000, etc.)")
    parser.add_argument("--sources", nargs="*", default=None, help="Arquivos SystemVerilog/Verilog da descrição")
    parser.add_argument("--slot-pitch", type=float, default=45.0, help="Distância entre slots adjacentes em mm")
    parser.add_argument("--col-gap", type=float, default=7.62, help="Distância entre colunas de um slot em mm")
    parser.add_argument("--layers", type=int, default=4, help="Número de camadas de cobre (padrão 4)")
    parser.add_argument("--no-ext-io", action="store_true", help="Não adiciona barras de conectores de E/S externa")
    parser.add_argument("--no-route", action="store_true", help="Pula o roteamento automático (somente placement)")
    parser.add_argument("--no-drc", action="store_true", help="Pula o DRC")
    parser.add_argument("--no-render", action="store_true", help="Não gera o render 3D via kicad-cli")
    parser.add_argument("--out", default=None, help="Diretório de saída (padrão: build/pcb/<top>_backplane_<lib>)")
    parser.add_argument("--title", default="", help="Título impresso no carimbo da PCB")

    args = parser.parse_args()

    generate_backplane(
        top=args.top,
        boards=args.boards,
        lib=args.lib,
        sources=args.sources,
        slot_pitch=args.slot_pitch,
        col_gap=args.col_gap,
        layers=args.layers,
        ext_io=not args.no_ext_io,
        out_dir=args.out,
        no_route=args.no_route,
        no_drc=args.no_drc,
        render=not args.no_render,
        title=args.title,
    )


if __name__ == "__main__":
    main()
