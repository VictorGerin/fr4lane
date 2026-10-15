"""Escrita do projeto KiCad (formato KiCad 8; abre também no KiCad 9)."""

import json
import os
import re
from pathlib import Path

from .layout import new_uuid

OX, OY = 20.0, 20.0          # deslocamento da placa na folha


def _q(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _n(v):
    return f"{v:.4f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def _model_dir_var():
    """Variável do KiCad que aponta para a biblioteca de modelos 3D. O nome muda
    com a versão (KICAD8_3DMODEL_DIR, KICAD9_..., KICAD10_...): usa a versão
    mais nova instalada, ou PCBFLOW_3DMODEL_VAR se definida."""
    if os.environ.get("PCBFLOW_3DMODEL_VAR"):
        return os.environ["PCBFLOW_3DMODEL_VAR"]
    versions = []
    for base in (Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "KiCad",
                 Path("/usr/share/kicad"), Path("/Applications/KiCad")):
        if base.is_dir():
            for d in base.iterdir():
                m = re.match(r"(\d+)", d.name)
                if m:
                    versions.append(int(m.group(1)))
    return f"KICAD{max(versions) if versions else 8}_3DMODEL_DIR"


def _model_path(fp, var):
    """'Package_TO_SOT_SMD:SOT-23' -> '${VAR}/Package_TO_SOT_SMD.3dshapes/SOT-23.step'.
    A origem dos footprints do pcbflow é a mesma dos oficiais, então o modelo
    entra sem deslocamento."""
    if ":" not in fp.lib_name:
        return None
    lib, name = fp.lib_name.split(":", 1)
    return f"${{{var}}}/{lib}.3dshapes/{name}.step"


def _font(size, thick):
    return f"(effects (font (size {_n(size)} {_n(size)}) (thickness {_n(thick)})))"


def write_pcb(board, path, title=""):
    nets = board.nets()
    nid = {n: i + 1 for i, n in enumerate(nets)}
    L = []
    w = L.append
    pw = max(297.0, board.width + 2 * OX)
    ph = max(210.0, board.height + 2 * OY)
    w("(kicad_pcb")
    w("\t(version 20240108)")
    w('\t(generator "pcbflow")')
    w('\t(generator_version "0.1")')
    w("\t(general (thickness 1.6) (legacy_teardrops no))")
    w(f'\t(paper "User" {_n(pw)} {_n(ph)})')
    if title:
        w(f"\t(title_block (title {_q(title)}) (comment 1 \"Gerado pelo pcbflow (Yosys + células de componentes discretos)\"))")
    w("\t(layers")
    inner = ('1 "In1.Cu" power', '2 "In2.Cu" power') if board.layers >= 4 else ()
    for item in ('0 "F.Cu" signal', *inner, '31 "B.Cu" signal',
                 '32 "B.Adhes" user "B.Adhesive"', '33 "F.Adhes" user "F.Adhesive"',
                 '34 "B.Paste" user', '35 "F.Paste" user',
                 '36 "B.SilkS" user "B.Silkscreen"', '37 "F.SilkS" user "F.Silkscreen"',
                 '38 "B.Mask" user', '39 "F.Mask" user',
                 '40 "Dwgs.User" user "User.Drawings"', '41 "Cmts.User" user "User.Comments"',
                 '44 "Edge.Cuts" user', '45 "Margin" user',
                 '46 "B.CrtYd" user "B.Courtyard"', '47 "F.CrtYd" user "F.Courtyard"',
                 '48 "B.Fab" user', '49 "F.Fab" user'):
        w(f"\t\t({item})")
    w("\t)")
    w("\t(setup (pad_to_mask_clearance 0) (allow_soldermask_bridges_in_footprints no))")
    w('\t(net 0 "")')
    for n in nets:
        w(f"\t(net {nid[n]} {_q(n)})")

    board.model_var = _model_dir_var()
    for fp in board.footprints:
        _footprint(w, fp, nid, board)

    # contorno da placa
    w(f"\t(gr_rect (start {_n(OX)} {_n(OY)}) (end {_n(OX + board.width)} {_n(OY + board.height)}) "
      f"(stroke (width 0.1) (type default)) (fill none) (layer \"Edge.Cuts\") (uuid {_q(new_uuid())}))")
    if title:
        w(f"\t(gr_text {_q(title)} (at {_n(OX + 1)} {_n(OY - 1.5)} 0) (layer \"Cmts.User\") "
          f"(uuid {_q(new_uuid())}) (effects (font (size 1.5 1.5) (thickness 0.2)) (justify left)))")

    # planos internos (In1 = GND, In2 = VDD), só na placa de 4 camadas. Preencher no KiCad com "B".
    for layer, net in ((("In1.Cu", board.gnd), ("In2.Cu", board.vdd)) if board.layers >= 4 else ()):
        if net not in nid:
            continue
        m = 0.3
        pts = [(OX + m, OY + m), (OX + board.width - m, OY + m),
               (OX + board.width - m, OY + board.height - m), (OX + m, OY + board.height - m)]
        w(f"\t(zone (net {nid[net]}) (net_name {_q(net)}) (layer {_q(layer)}) (uuid {_q(new_uuid())}) "
          f"(hatch edge 0.5) (connect_pads (clearance {_n(board.rules.clearance)})) (min_thickness 0.25) "
          f"(filled_areas_thickness no) (fill (thermal_gap 0.5) (thermal_bridge_width 0.5)) "
          f"(polygon (pts {' '.join(f'(xy {_n(x)} {_n(y)})' for x, y in pts)})))")

    for t in board.tracks:
        w(f"\t(segment (start {_n(OX + t.x1)} {_n(OY + t.y1)}) (end {_n(OX + t.x2)} {_n(OY + t.y2)}) "
          f"(width {_n(t.width)}) (layer {_q(t.layer)}) (net {nid[t.net]}) (uuid {_q(t.uuid)}))")
    for v in board.vias:
        w(f"\t(via (at {_n(OX + v.x)} {_n(OY + v.y)}) (size {_n(v.size)}) (drill {_n(v.drill)}) "
          f"(layers \"F.Cu\" \"B.Cu\") (net {nid[v.net]}) (uuid {_q(v.uuid)}))")

    _groups(w, board)
    w(")")
    Path(path).write_text("\n".join(L) + "\n", encoding="utf-8")


def _groups(w, board):
    """Grupos de célula dentro de grupos de módulo (u_a > u_a.u_b > U8 (NAND2)) e,
    em User.Drawings, um contorno com o nome de cada módulo."""
    cells = getattr(board, "group_cells", {})
    gmod = getattr(board, "group_modules", {})
    types = getattr(board, "module_types", {})
    by_uuid = {fp.uuid: fp for fp in board.footprints}
    members = {}                 # módulo -> uuids (grupos de célula e de submódulo)
    boxes = {}
    for name, fps in sorted(board.groups.items()):
        cell = cells.get(name, "")
        label = f"{name} ({cell})" if cell else name
        gid = new_uuid()
        w(f"\t(group {_q(label)} (uuid {_q(gid)}) (members {' '.join(_q(m) for m in fps)}))")
        mod = gmod.get(name)
        if not mod:
            continue
        members.setdefault(mod, []).append(gid)
        parts = mod.split(".")
        for k in range(1, len(parts) + 1):
            box = boxes.setdefault(".".join(parts[:k]), [1e9, 1e9, -1e9, -1e9])
            for u in fps:
                fp = by_uuid[u]
                x0, y0, x1, y1 = fp.courtyard
                box[0] = min(box[0], fp.x + x0)
                box[1] = min(box[1], fp.y + y0)
                box[2] = max(box[2], fp.x + x1)
                box[3] = max(box[3], fp.y + y1)
    # do mais profundo para o mais raso: o grupo do submódulo entra no do pai
    for mod in sorted(boxes, key=lambda m: -m.count(".")):
        gid = new_uuid()
        label = f"{mod} ({types[mod]})" if mod in types else mod
        w(f"\t(group {_q(label)} (uuid {_q(gid)}) (members {' '.join(_q(m) for m in members.get(mod, []))}))")
        if "." in mod:
            members.setdefault(mod.rsplit(".", 1)[0], []).append(gid)
        inset = 0.6 * mod.count(".")          # submódulos ficam por dentro do pai
        x0, y0, x1, y1 = boxes[mod]
        x0, y0 = OX + x0 - 1.0 + inset, OY + y0 - 1.0 + inset
        x1, y1 = OX + x1 + 1.0 - inset, OY + y1 + 1.0 - inset
        w(f"\t(gr_rect (start {_n(x0)} {_n(y0)}) (end {_n(x1)} {_n(y1)}) "
          f"(stroke (width 0.15) (type dash)) (fill none) (layer \"Dwgs.User\") (uuid {_q(new_uuid())}))")
        w(f"\t(gr_text {_q(label)} (at {_n(x0 + 0.3)} {_n(y0 - 0.8)} 0) (layer \"Dwgs.User\") "
          f"(uuid {_q(new_uuid())}) (effects (font (size 1 1) (thickness 0.15)) (justify left)))")


def _footprint(w, fp, nid, board):
    tht = fp.tht
    x0, y0, x1, y1 = fp.courtyard
    w(f"\t(footprint {_q(fp.lib_name)}")
    w('\t\t(layer "F.Cu")')
    w(f"\t\t(uuid {_q(fp.uuid)})")
    w(f"\t\t(at {_n(OX + fp.x)} {_n(OY + fp.y)})")
    ref_y = y0 - 0.6 if not tht else -2.6
    w(f"\t\t(property \"Reference\" {_q(fp.ref)} (at 0 {_n(ref_y)} 0) (layer \"F.SilkS\") "
      f"(uuid {_q(new_uuid())}) {_font(0.6, 0.1)})")
    w(f"\t\t(property \"Value\" {_q(fp.value)} (at 0 {_n(y1 + 0.6)} 0) (layer \"F.Fab\") "
      f"(uuid {_q(new_uuid())}) {_font(0.6, 0.1)})")
    mod = getattr(board, "group_modules", {}).get(fp.group)
    if mod:
        w(f"\t\t(property \"Module\" {_q(mod)} (at 0 0 0) (layer \"F.Fab\") (hide yes) "
          f"(uuid {_q(new_uuid())}) {_font(0.5, 0.08)})")
    if fp.group:
        w(f"\t\t(property \"Cell\" {_q(fp.group)} (at 0 0 0) (layer \"F.Fab\") (hide yes) "
          f"(uuid {_q(new_uuid())}) {_font(0.5, 0.08)})")
    w(f"\t\t(attr {'through_hole' if tht else 'smd'})")
    for a, b, c, d in ((x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)):
        w(f"\t\t(fp_line (start {_n(a)} {_n(b)}) (end {_n(c)} {_n(d)}) (stroke (width 0.05) (type solid)) "
          f"(layer \"F.CrtYd\") (uuid {_q(new_uuid())}))")
    for a, b, c, d in fp.silk:
        w(f"\t\t(fp_line (start {_n(a)} {_n(b)}) (end {_n(c)} {_n(d)}) (stroke (width 0.12) (type solid)) "
          f"(layer \"F.SilkS\") (uuid {_q(new_uuid())}))")
    labels = getattr(board, "port_labels", {}).get(fp.ref)
    for pad in fp.pads:
        net = f" (net {nid[pad.net]} {_q(pad.net)})" if pad.net else ""
        func = f" (pinfunction {_q(pad.function)}) (pintype \"passive\")" if pad.function else ""
        if pad.tht:
            w(f"\t\t(pad {_q(pad.num)} thru_hole {pad.shape} (at {_n(pad.rx)} {_n(pad.ry)}) "
              f"(size {_n(pad.w)} {_n(pad.h)}) (drill {_n(pad.drill)}) (layers \"*.Cu\" \"*.Mask\") "
              f"(remove_unused_layers no){net}{func} (uuid {_q(new_uuid())}))")
        else:
            rr = " (roundrect_rratio 0.25)" if pad.shape == "roundrect" else ""
            w(f"\t\t(pad {_q(pad.num)} smd {pad.shape} (at {_n(pad.rx)} {_n(pad.ry)}) "
              f"(size {_n(pad.w)} {_n(pad.h)}) (layers \"F.Cu\" \"F.Paste\" \"F.Mask\"){rr}{net}{func} "
              f"(uuid {_q(new_uuid())}))")
    if labels:
        left_side = fp.x < board.width / 2
        for pad, text in zip(fp.pads, labels):
            dx = 1.6 if left_side else -1.6
            just = "left" if left_side else "right"
            w(f"\t\t(fp_text user {_q(text)} (at {_n(dx)} {_n(pad.ry)} 0) (layer \"F.SilkS\") "
              f"(uuid {_q(new_uuid())}) (effects (font (size 0.7 0.7) (thickness 0.1)) (justify {just})))")
    model = _model_path(fp, board.model_var)
    if model:
        w(f"\t\t(model {_q(model)} (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))")
    w("\t)")


def write_project(board, path):
    rules = board.rules
    pro = {
        "board": {
            "design_settings": {
                "defaults": {"board_outline_line_width": 0.1, "copper_line_width": 0.2},
                "rules": {
                    "min_clearance": rules.clearance,
                    "min_track_width": 0.2,
                    "min_via_diameter": 0.5,
                    "min_via_annular_width": 0.1,
                    "min_through_hole_diameter": 0.3,
                    "min_copper_edge_clearance": rules.edge_clearance - 0.05,
                    "min_hole_clearance": 0.25,
                },
            },
        },
        "meta": {"filename": Path(path).name, "version": 1},
        "net_settings": {
            "classes": [{
                "name": "Default",
                "clearance": rules.clearance,
                "track_width": rules.track_width,
                "via_diameter": rules.via_size,
                "via_drill": rules.via_drill,
                "microvia_diameter": 0.3,
                "microvia_drill": 0.1,
                "diff_pair_width": 0.2,
                "diff_pair_gap": 0.25,
                "diff_pair_via_gap": 0.25,
                "wire_width": 6,
                "bus_width": 12,
                "line_style": 0,
                "schematic_color": "rgba(0, 0, 0, 0.000)",
                "pcb_color": "rgba(0, 0, 0, 0.000)",
                "priority": 2147483647,
            }],
            "meta": {"version": 3},
        },
    }
    Path(path).write_text(json.dumps(pro, indent=2), encoding="utf-8")


def write_bom(board, path):
    rows = {}
    for fp in board.footprints:
        key = (fp.value, fp.lib_name)
        rows.setdefault(key, []).append(fp.ref)

    def refkey(r):
        import re
        m = re.match(r"([A-Z]+)(\d+)", r)
        return (m.group(1), int(m.group(2))) if m else (r, 0)

    lines = ["Qtd;Valor;Footprint;Referências"]
    for (value, lib_name), refs in sorted(rows.items(), key=lambda kv: refkey(kv[1][0])):
        refs.sort(key=refkey)
        lines.append(f"{len(refs)};{value};{lib_name};{','.join(refs)}")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
