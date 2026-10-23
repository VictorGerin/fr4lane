"""Síntese lógica com Yosys e ABC visando matrizes de fusíveis GAL (SOP).

Gera cobertura de Soma de Produtos (SOP) via Espresso/ABC com restrições
de entradas por cone e termos de produto compatíveis com a arquitetura do chip.
"""

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .devices import GALDevice, GAL22V10, get_device


def find_yosys() -> str:
    """Localiza o binário do Yosys no PATH ou em diretórios padrão do MSYS2/Windows."""
    exe = shutil.which("yosys")
    if exe:
        return exe
    for cand in ("C:/msys64/ucrt64/bin/yosys.exe", "C:/msys64/mingw64/bin/yosys.exe"):
        if Path(cand).exists():
            return cand
    raise FileNotFoundError("Yosys não encontrado no sistema. Instale o Yosys ou adicione ao PATH.")


@dataclass
class ProductTerm:
    """Um termo de produto (AND) em uma equação SOP.
    literals mapeia o nome da net -> 1 (não invertido / True) ou 0 (invertido / False).
    """
    literals: Dict[str, int] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return len(self.literals) == 0


@dataclass
class LogicCone:
    """Cone de lógica que implementa uma função booleana em Soma de Produtos (SOP)."""
    name: str                           # Nome da net ou porta de saída
    product_terms: List[ProductTerm]    # Lista de termos AND somados (OR)
    support_inputs: Set[str]            # Conjunto de nets de entrada necessárias
    active_high: bool = True            # Polaridade da saída (True = XOR=1, False = XOR=0)
    is_registered: bool = False         # True se alimenta um Flip-Flop D da OLMC
    clk_net: Optional[str] = None       # Net de clock (se registered)
    rst_net: Optional[str] = None       # Net de reset assíncrono (se houver)
    oe_terms: Optional[List[ProductTerm]] = None # Termo de OE (None = sempre ativo)
    is_primary_output: bool = True      # True se sai para um pino externo da placa
    feedback_name: Optional[str] = None # Nome da net interna que alimenta outros cones

    @property
    def pterm_count(self) -> int:
        return len(self.product_terms)


@dataclass
class SynthesizedDesign:
    """Resultado da síntese lógica pronto para particionamento e empacotamento."""
    top: str
    device: GALDevice
    primary_inputs: List[str]
    primary_outputs: List[str]
    clk_net: Optional[str]
    cones: List[LogicCone]
    json_path: Path


def _decode_sop_table(table_str: str, width: int, depth: int, input_nets: List[str]) -> List[ProductTerm]:
    """Decodifica a tabela binária do $sop do Yosys em termos de produto.

    No Yosys:
    A tabela tem largura 2 * width * depth bits.
    Para cada termo (de 0 a depth-1):
      Cada entrada i (de 0 a width-1) tem 2 bits:
      '00' = don't care (não participa do termo)
      '01' = invertido (0)
      '10' = não-invertido (1)
      '11' = inválido / contradição
    Os pares estão ordenados de A[width-1] até A[0] (MSB na esquerda).
    """
    terms: List[ProductTerm] = []
    term_bits = 2 * width
    expected_len = term_bits * depth

    # Pad or slice se necessário
    padded = table_str.zfill(expected_len)
    if len(padded) > expected_len:
        padded = padded[-expected_len:]

    for d in range(depth):
        t_slice = padded[d * term_bits : (d + 1) * term_bits]
        lits: Dict[str, int] = {}
        for idx in range(width):
            # idx 0 corresponde a A[width-1], idx width-1 corresponde a A[0]
            bit_pair = t_slice[idx * 2 : idx * 2 + 2]
            net_name = input_nets[width - 1 - idx]
            if bit_pair == "01":
                lits[net_name] = 0
            elif bit_pair == "10":
                lits[net_name] = 1
            elif bit_pair == "00":
                pass  # don't care
            elif bit_pair == "11":
                # Contradição lógica (termo nulo)
                lits.clear()
                break
        if lits or bit_pair == "00":
            terms.append(ProductTerm(literals=lits))

    return terms


def synthesize_gal(
    sources: List[Path],
    top: str,
    device: str = "GAL22V10",
    outdir: Optional[Path] = None,
    defines: Tuple[str, ...] = (),
) -> SynthesizedDesign:
    """Executa a síntese com Yosys e ABC mapeando para Soma de Produtos."""
    dev = get_device(device)
    if outdir is None:
        outdir = Path("build") / f"{top}_{dev.name.lower()}"
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    json_out = outdir / f"{top}_sop.json"
    log_out = outdir / "yosys_sop.log"
    ys_script = outdir / "synth_sop.ys"

    defs = " ".join(f"-D{d}" for d in defines)
    reads = "\n".join(f"read_verilog -sv {defs} {Path(s).resolve().as_posix()}" for s in sources)

    # Restrições de síntese do ABC baseadas no dispositivo GAL
    max_p = 16 if dev.name == "GAL22V10" else 8
    max_in = dev.max_inputs

    script_content = f"""{reads}
hierarchy -check -top {top}
proc
flatten
tribuf
opt_expr
opt_clean
synth -top {top}
dfflegalize -cell $_DFF_PN0_ 01 -cell $_DFF_P_ 01
abc -sop -I {max_in} -P {max_p}
opt_clean -purge
write_json {json_out.resolve().as_posix()}
"""
    ys_script.write_text(script_content, encoding="utf-8")

    env = dict(os.environ)

    proc = subprocess.run(
        [find_yosys(), "-s", str(ys_script.resolve())],
        capture_output=True,
        text=True,
        cwd=outdir,
        env=env,
    )
    log_out.write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        tail = proc.stdout.splitlines()[-25:]
        raise RuntimeError(f"Yosys falhou na síntese SOP (código {proc.returncode}):\n" + "\n".join(tail))

    # Parse do JSON do Yosys
    data = json.loads(json_out.read_text(encoding="utf-8"))
    mod = data["modules"][top]

    # Mapeamento de bits para nomes de nets
    bit_to_name: Dict[int, str] = {}
    for netname, ninfo in mod["netnames"].items():
        for b_idx, bit in enumerate(ninfo["bits"]):
            if isinstance(bit, int):
                # Se for vetor, anexa índice [0], [1]...
                suffix = f"[{b_idx}]" if len(ninfo["bits"]) > 1 else ""
                clean_name = f"{netname}{suffix}"
                # Prioriza nomes sem prefixos internos ($)
                if bit not in bit_to_name or (bit_to_name[bit].startswith("$") and not clean_name.startswith("$")):
                    bit_to_name[bit] = clean_name

    def get_net_name(bit_id: int) -> str:
        return bit_to_name.get(bit_id, f"net_{bit_id}")

    # Portas primárias
    prim_inputs: List[str] = []
    prim_outputs: List[str] = []
    for pname, pinfo in mod["ports"].items():
        for b_idx, bit in enumerate(pinfo["bits"]):
            sname = f"{pname}[{b_idx}]" if len(pinfo["bits"]) > 1 else pname
            if pinfo["direction"] == "input":
                prim_inputs.append(sname)
            elif pinfo["direction"] in ("output", "inout"):
                prim_outputs.append(sname)

    # Identifica inversores $_NOT_ para saber se a saída de um $sop foi invertida pelo ABC
    sop_inverters: Dict[int, int] = {} # input_bit -> output_bit
    for cname, cell in mod["cells"].items():
        if cell["type"] == "$_NOT_":
            a_bit = cell["connections"]["A"][0]
            y_bit = cell["connections"]["Y"][0]
            sop_inverters[a_bit] = y_bit

    # Identifica Flip-Flops
    # bit_q -> (cell, clk_net, rst_net, d_bit)
    ff_by_q: Dict[int, Tuple[str, Optional[str], int]] = {}
    clk_signal: Optional[str] = None
    for cname, cell in mod["cells"].items():
        if cell["type"] in ("$_DFF_P_", "$_DFF_PN0_"):
            c_bit = cell["connections"]["C"][0]
            d_bit = cell["connections"]["D"][0]
            q_bit = cell["connections"]["Q"][0]
            r_bit = cell["connections"].get("R", [None])[0]
            clk_net = get_net_name(c_bit)
            rst_net = get_net_name(r_bit) if r_bit is not None else None
            clk_signal = clk_net
            ff_by_q[q_bit] = (clk_net, rst_net, d_bit)

    # Mapeia células $sop
    # y_bit -> (cell, input_names, terms)
    sop_by_y: Dict[int, Tuple[List[str], List[ProductTerm]]] = {}
    for cname, cell in mod["cells"].items():
        if cell["type"] == "$sop":
            width = int(cell["parameters"]["WIDTH"], 2)
            depth = int(cell["parameters"]["DEPTH"], 2)
            table_str = cell["parameters"]["TABLE"]
            a_bits = cell["connections"]["A"]
            y_bit = cell["connections"]["Y"][0]
            in_names = [get_net_name(b) for b in a_bits]
            pterms = _decode_sop_table(table_str, width, depth, in_names)
            sop_by_y[y_bit] = (in_names, pterms)

    # Monta os LogicCones para todas as saídas e registradores
    cones: List[LogicCone] = []

    # 1. Registradores (Flip-Flops)
    for q_bit, (clk_net, rst_net, d_bit) in ff_by_q.items():
        q_name = get_net_name(q_bit)
        active_high = True
        actual_d_bit = d_bit

        # Se D vier de um inversor que vem de um SOP
        # Inversor conectado a D:
        for sop_out, not_out in sop_inverters.items():
            if not_out == d_bit:
                active_high = False
                actual_d_bit = sop_out
                break

        if actual_d_bit in sop_by_y:
            in_names, pterms = sop_by_y[actual_d_bit]
            supp = set()
            for pt in pterms:
                supp.update(pt.literals.keys())
        else:
            # D é diretamente uma net ou constante
            src_name = get_net_name(actual_d_bit)
            in_names = [src_name]
            pterms = [ProductTerm(literals={src_name: 1})]
            supp = {src_name}

        is_prim = q_name in prim_outputs
        cone = LogicCone(
            name=q_name,
            product_terms=pterms,
            support_inputs=supp,
            active_high=active_high,
            is_registered=True,
            clk_net=clk_net,
            rst_net=rst_net,
            is_primary_output=is_prim,
            feedback_name=q_name,
        )
        cones.append(cone)

    # 2. Saídas combinacionais primárias (que não vêm de flip-flop)
    ff_q_bits = set(ff_by_q.keys())
    for out_name in prim_outputs:
        # Encontra o bit da porta
        target_bit = None
        for b, n in bit_to_name.items():
            if n == out_name:
                target_bit = b
                break
        if target_bit is None or target_bit in ff_q_bits:
            continue

        active_high = True
        actual_src_bit = target_bit

        # Verifica se passou por inversor
        for sop_out, not_out in sop_inverters.items():
            if not_out == target_bit:
                active_high = False
                actual_src_bit = sop_out
                break

        if actual_src_bit in sop_by_y:
            in_names, pterms = sop_by_y[actual_src_bit]
            supp = set()
            for pt in pterms:
                supp.update(pt.literals.keys())
        else:
            # Saída ligada diretamente a um sinal de entrada ou constante
            src_name = get_net_name(actual_src_bit)
            in_names = [src_name]
            pterms = [ProductTerm(literals={src_name: 1})]
            supp = {src_name}

        cone = LogicCone(
            name=out_name,
            product_terms=pterms,
            support_inputs=supp,
            active_high=active_high,
            is_registered=False,
            is_primary_output=True,
            feedback_name=out_name,
        )
        cones.append(cone)

    return SynthesizedDesign(
        top=top,
        device=dev,
        primary_inputs=prim_inputs,
        primary_outputs=prim_outputs,
        clk_net=clk_signal,
        cones=cones,
        json_path=json_out,
    )
