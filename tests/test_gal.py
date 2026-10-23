"""Testes para o subsistema PLD/GAL (Generic Array Logic) do fr4lane."""

import re
from pathlib import Path
import pytest

from fr4lane.pld.devices import GAL16V8, GAL22V10, get_device
from fr4lane.pld.synth import (
    LogicCone,
    ProductTerm,
    _decode_sop_table,
    synthesize_gal,
)
from fr4lane.pld.packer import (
    PackedGAL,
    _can_fit_pterms,
    _calculate_affinity,
    pack_design_to_gals,
)
from fr4lane.pld.jedec import generate_jedec
from fr4lane.pld.flow import run_gal_flow


def test_gal_device_definitions():
    """Valida as especificações de hardware do GAL22V10 e GAL16V8."""
    dev22 = get_device("GAL22V10")
    assert dev22.num_pins == 24
    assert dev22.num_olmcs == 10
    assert dev22.total_fuses == 5892
    assert dev22.matrix_cols == 44
    assert dev22.matrix_rows == 132

    # Verifica simetria das capacidades de termos de produto no GAL22V10
    caps = [olmc.product_terms for olmc in dev22.olmcs]
    assert caps == [8, 10, 12, 14, 16, 16, 14, 12, 10, 8]

    # GAL16V8
    dev16 = get_device("GAL16V8")
    assert dev16.num_pins == 20
    assert dev16.num_olmcs == 8
    assert dev16.total_fuses == 2194
    assert dev16.matrix_cols == 32
    assert dev16.matrix_rows == 64
    assert all(o.product_terms == 8 for o in dev16.olmcs)


def test_decode_sop_table():
    """Valida a decodificação da tabela binária $sop do Yosys."""
    # 2 entradas (A[1], A[0]):
    # A[1] = b, A[0] = a.
    # Termo 1: b=1, a=0 -> '1001'
    # Termo 2: b=0, a=1 -> '0110'
    table = "10010110"
    pterms = _decode_sop_table(table, width=2, depth=2, input_nets=["a", "b"])
    assert len(pterms) == 2
    assert pterms[0].literals == {"b": 1, "a": 0}
    assert pterms[1].literals == {"b": 0, "a": 1}


def test_fit_pterms():
    """Valida o verificador de capacidade de termos de produto."""
    available = [8, 10, 12, 14, 16, 16, 14, 12, 10, 8]

    # Cabe perfeitamente
    assert _can_fit_pterms([16, 15, 12, 8], available) is True
    # Excede a capacidade máxima de qualquer slot (17 > 16)
    assert _can_fit_pterms([17], available) is False
    # Pede três slots de 16 termos, mas só existem dois de 16
    assert _can_fit_pterms([16, 16, 16], available) is False
    # Cabe nos slots [16, 16, 14]
    assert _can_fit_pterms([16, 16, 13], available) is True


def test_packing_input_sharing():
    """Valida se o empacotador agrupa cones que compartilham entradas no mesmo chip."""
    dev = GAL22V10

    # Cria 4 cones que compartilham as mesmas entradas (a, b, c)
    shared_inputs = {"a", "b", "c"}
    cones = []
    for i in range(4):
        c = LogicCone(
            name=f"out_{i}",
            product_terms=[ProductTerm(literals={"a": 1, "b": 0})],
            support_inputs=shared_inputs,
            active_high=True,
        )
        cones.append(c)

    from fr4lane.pld.synth import SynthesizedDesign
    design = SynthesizedDesign(
        top="test_top",
        device=dev,
        primary_inputs=["a", "b", "c"],
        primary_outputs=[f"out_{i}" for i in range(4)],
        clk_net=None,
        cones=cones,
        json_path=Path("dummy.json"),
    )

    chips = pack_design_to_gals(design)
    # Todos os 4 cones devem ser empacotados em exatamente 1 chip GAL22V10
    assert len(chips) == 1
    chip = chips[0]
    assert chip.macrocell_utilization == 40.0
    # As 3 entradas compartilhadas devem ocupar apenas 3 pinos no chip
    assert len(chip.input_pins) == 3


def test_jedec_generation_and_checksum():
    """Valida a estrutura do arquivo JEDEC, contagem de fusíveis e formato de checksum."""
    dev = GAL22V10
    # Cria uma OLMC com 1 termo
    cone = LogicCone(
        name="q0",
        product_terms=[ProductTerm(literals={"in0": 1})],
        support_inputs={"in0"},
        active_high=True,
        is_registered=True,
        clk_net="clk",
    )
    from fr4lane.pld.packer import OLMCPlacement
    olmc0 = dev.olmcs[0]
    placement = OLMCPlacement(olmc=olmc0, cone=cone)

    packed = PackedGAL(
        chip_id="U1",
        device=dev,
        pin_assignment={1: "clk", 2: "in0", 14: "q0", 12: "GND", 24: "VCC"},
        olmc_placements={14: placement},
        input_pins={"in0": 2, "clk": 1},
        output_pins={"q0": 14},
        internal_feedbacks=set(),
        clk_pin=1,
    )

    jed_content = generate_jedec(packed, design_name="test_jedec")

    # Verifica campos JEDEC mandatórios
    assert "\x02" in jed_content
    assert "\x03" in jed_content
    assert "QF5892*" in jed_content
    assert "QP24*" in jed_content
    assert "G0*" in jed_content
    assert "F0*" in jed_content
    # Verifica que o checksum está presente
    m = re.search(r"C([0-9A-Fa-f]{4})\*", jed_content)
    assert m is not None


def test_full_gal_flow_integration(tmp_path):
    """Teste de integração ponta a ponta com Yosys: Verilog -> GAL Flow -> JEDEC + PCB."""
    # Cria um contador síncrono de 4 bits em Verilog
    v_file = tmp_path / "counter4.v"
    v_file.write_text("""
module counter4(
    input clk,
    input rst_n,
    input en,
    output reg [3:0] q
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            q <= 4'b0000;
        else if (en)
            q <= q + 1'b1;
    end
endmodule
""")

    res = run_gal_flow(
        sources=[v_file],
        top="counter4",
        device="GAL22V10",
        outdir=tmp_path / "out_counter4",
    )

    assert res.chip_count == 1
    assert res.macrocell_utilization == 40.0  # 4 bits de contador em 10 OLMCs
    assert len(res.jedec_files) == 1
    assert res.jedec_files[0].exists()
    assert res.pcb_file.exists()
    assert res.report_file.exists()

    # Confere que o JEDEC gerado contém o cabeçalho e checksum válidos
    jed_text = res.jedec_files[0].read_text(encoding="ascii")
    assert "QF5892" in jed_text
    assert "counter4" in jed_text
