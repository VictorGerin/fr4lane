"""Algoritmo de particionamento e empacotamento com aproveitamento máximo de células GAL.

Agrupa cones de lógica booleana em chips GAL minimizando a contagem total de chips,
maximizando o reuso de entradas (input sharing), aproveitando o feedback interno das
OLMCs (0 pinos externos) e encaixando a complexidade dos termos nas capacidades
variáveis de cada macrocélula (8 a 16 termos de produto no GAL22V10).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from .devices import GALDevice, GAL22V10, OLMCDef, get_device
from .synth import LogicCone, SynthesizedDesign


@dataclass
class OLMCPlacement:
    """Alocação de um cone lógico a uma macrocélula física."""
    olmc: OLMCDef
    cone: LogicCone
    is_feedback_only: bool = False      # Usado apenas para feedback interno (tri-state OE=0)


@dataclass
class PackedGAL:
    """Instância física de um chip GAL empacotado e configurado."""
    chip_id: str                        # Identificador do componente (ex: "U1", "U2")
    device: GALDevice                   # Modelo do chip (GAL22V10 / GAL16V8)
    pin_assignment: Dict[int, str]      # Pino DIP -> Nome do sinal líquido (net)
    olmc_placements: Dict[int, OLMCPlacement] # Pino DIP -> Alocação do cone
    input_pins: Dict[str, int]          # Nome do sinal de entrada -> Pino DIP
    output_pins: Dict[str, int]         # Nome do sinal de saída -> Pino DIP
    internal_feedbacks: Set[str]        # Sinais que usam feedback interno da OLMC (0 pinos)
    clk_pin: Optional[int] = None
    rst_pin: Optional[int] = None

    @property
    def macrocell_utilization(self) -> float:
        """Percentual de aproveitamento das macrocélulas do chip (0 a 100%)."""
        return (len(self.olmc_placements) / self.device.num_olmcs) * 100.0

    @property
    def total_pterms_used(self) -> int:
        """Total de termos de produto lógicos consumidos."""
        return sum(p.cone.pterm_count for p in self.olmc_placements.values())

    @property
    def total_pterms_capacity(self) -> int:
        """Capacidade total de termos de produto das macrocélulas ocupadas."""
        return sum(p.olmc.product_terms for p in self.olmc_placements.values())


def _can_fit_pterms(cone_pterms: List[int], available_capacities: List[int]) -> bool:
    """Verifica se uma lista de demandas de termos cabe nas capacidades disponíveis.

    Usa Best-Fit Decreasing: ordena decrescente e encaixa na menor capacidade
    que seja >= à demanda do cone.
    """
    sorted_demands = sorted(cone_pterms, reverse=True)
    caps = sorted(available_capacities, reverse=True)

    if len(sorted_demands) > len(caps):
        return False

    caps_remaining = list(caps)
    for dem in sorted_demands:
        # Encontra a menor capacidade que atende dem (best fit)
        best_idx = -1
        best_cap = 999
        for idx, cap in enumerate(caps_remaining):
            if cap >= dem and cap < best_cap:
                best_cap = cap
                best_idx = idx
        if best_idx == -1:
            return False
        caps_remaining.pop(best_idx)

    return True


def _calculate_affinity(cone_a: LogicCone, cone_b: LogicCone) -> float:
    """Calcula a afinidade entre dois cones para agrupamento no mesmo chip.

    Pontua alto se:
    1. Compartilham muitas entradas (Jaccard similarity).
    2. Um cone alimenta o outro como entrada (feedback interno da OLMC economiza pino).
    3. Compartilham o mesmo sinal de clock (obrigatório se ambos forem registrados).
    """
    if cone_a.is_registered and cone_b.is_registered:
        if cone_a.clk_net != cone_b.clk_net:
            return -100.0  # Incompatíveis no mesmo GAL

    supp_a = cone_a.support_inputs
    supp_b = cone_b.support_inputs

    union_len = len(supp_a | supp_b)
    if union_len == 0:
        jaccard = 1.0
    else:
        jaccard = len(supp_a & supp_b) / union_len

    score = jaccard * 10.0

    # Bônus massivo para feedback interno: A alimenta B ou B alimenta A
    if cone_a.name in supp_b or (cone_a.feedback_name and cone_a.feedback_name in supp_b):
        score += 15.0
    if cone_b.name in supp_a or (cone_b.feedback_name and cone_b.feedback_name in supp_a):
        score += 15.0

    return score


def pack_design_to_gals(design: SynthesizedDesign, chip_prefix: str = "U") -> List[PackedGAL]:
    """Particiona os cones de lógica sintetizados no número mínimo de chips GAL.

    Aproveitamento Máximo:
    - Agrupa cones com alta sobreposição de entradas.
    - Utiliza feedback de macrocélula interna para sinais intermediários.
    - Otimiza alocação de cones grandes (14-16 termos) nos pinos centrais (18 e 19).
    - Converte OLMCs sobressalentes em pinos adicionais de entrada se necessário.
    """
    dev = design.device
    unplaced = list(design.cones)
    packed_chips: List[PackedGAL] = []
    chip_counter = 1

    # Ordena cones não alocados inicialmente por complexidade decrescente (mais termos primeiro)
    unplaced.sort(key=lambda c: (c.pterm_count, len(c.support_inputs)), reverse=True)

    while unplaced:
        current_cluster: List[LogicCone] = []
        cluster_clock: Optional[str] = None
        cluster_resets: Set[str] = set()

        # Seleciona o cone semente (o mais restritivo entre os restantes)
        seed = unplaced.pop(0)
        current_cluster.append(seed)
        if seed.is_registered:
            cluster_clock = seed.clk_net
            if seed.rst_net:
                cluster_resets.add(seed.rst_net)

        # Tenta encher o chip atual até a capacidade máxima de macrocélulas (10 para GAL22V10)
        while len(current_cluster) < dev.num_olmcs and unplaced:
            # Encontra o melhor candidato entre os restantes
            best_idx = -1
            best_score = -999.0

            for idx, candidate in enumerate(unplaced):
                # 1. Verifica compatibilidade de clock
                test_clk = cluster_clock
                if candidate.is_registered:
                    if test_clk is not None and candidate.clk_net != test_clk:
                        continue
                    test_clk = candidate.clk_net

                # 2. Verifica termos de produto
                test_cluster = current_cluster + [candidate]
                caps = [olmc.product_terms for olmc in dev.olmcs]
                demands = [c.pterm_count for c in test_cluster]
                if not _can_fit_pterms(demands, caps):
                    continue

                # 3. Verifica limite de pinos de entrada externos
                # Entradas externas necessárias = união dos suportes menos saídas geradas internamente
                cluster_outputs = {c.name for c in test_cluster}
                cluster_outputs.update(c.feedback_name for c in test_cluster if c.feedback_name)
                ext_inputs = set()
                for c in test_cluster:
                    ext_inputs.update(c.support_inputs - cluster_outputs)
                if test_clk:
                    ext_inputs.discard(test_clk)

                # Pinos de entrada disponíveis: dedicados (menos clock se houver) + macrocélulas sobressalentes
                avail_ded = len(dev.dedicated_inputs) - (1 if test_clk else 0)
                available_in_pins = avail_ded + (dev.num_olmcs - len(test_cluster))
                if len(ext_inputs) > available_in_pins:
                    continue

                # Calcula pontuação de afinidade média com o cluster atual
                score = sum(_calculate_affinity(c, candidate) for c in current_cluster) / len(current_cluster)
                if score > best_score:
                    best_score = score
                    best_idx = idx

            if best_idx != -1:
                chosen = unplaced.pop(best_idx)
                current_cluster.append(chosen)
                if chosen.is_registered and cluster_clock is None:
                    cluster_clock = chosen.clk_net
                if chosen.rst_net:
                    cluster_resets.add(chosen.rst_net)
            else:
                # Nenhum outro cone cabe neste chip mantendo todas as restrições
                break

        # Agora aloca fisicamente os cones escolhidos nas OLMCs do chip
        chip_id = f"{chip_prefix}{chip_counter}"
        chip_counter += 1

        # Mapeia cones para OLMCs via Best-Fit Decreasing
        # Ordena OLMCs disponíveis por capacidade
        sorted_olmcs = sorted(dev.olmcs, key=lambda o: o.product_terms, reverse=True)
        sorted_cluster = sorted(current_cluster, key=lambda c: c.pterm_count, reverse=True)

        olmc_allocations: Dict[int, OLMCPlacement] = {}
        remaining_olmcs = list(sorted_olmcs)

        for cone in sorted_cluster:
            # Menor OLMC que atende cone.pterm_count
            best_olmc_idx = -1
            best_cap = 999
            for o_idx, o in enumerate(remaining_olmcs):
                if o.product_terms >= cone.pterm_count and o.product_terms < best_cap:
                    best_cap = o.product_terms
                    best_olmc_idx = o_idx
            assert best_olmc_idx != -1, f"Erro interno: falha no encaixe de termos para {cone.name}"
            chosen_olmc = remaining_olmcs.pop(best_olmc_idx)
            olmc_allocations[chosen_olmc.dip_pin] = OLMCPlacement(olmc=chosen_olmc, cone=cone)

        # Identifica feedback interno (sinais de saída consumidos neste mesmo chip)
        cluster_out_names = {c.name for c in current_cluster}
        internal_fb: Set[str] = set()
        ext_inputs = set()
        for cone in current_cluster:
            for s in cone.support_inputs:
                if s in cluster_out_names:
                    internal_fb.add(s)
                else:
                    ext_inputs.add(s)

        # Mapeamento de pinos físicos do chip
        pin_map: Dict[int, str] = {
            dev.vcc_pin: "VCC",
            dev.gnd_pin: "GND",
        }
        in_pin_map: Dict[str, int] = {}
        out_pin_map: Dict[str, int] = {}

        # 1. Pino de clock (Pino 1 no GAL22V10)
        clk_pin_used: Optional[int] = None
        if cluster_clock:
            pin_map[dev.clk_pin] = cluster_clock
            in_pin_map[cluster_clock] = dev.clk_pin
            clk_pin_used = dev.clk_pin
            ext_inputs.discard(cluster_clock)
        else:
            # Se não tiver clock, Pino 1 pode ser entrada dedicada
            pass

        # 2. Pinos de saída (OLMCs alocadas)
        for dip_pin, place in olmc_allocations.items():
            pin_map[dip_pin] = place.cone.name
            out_pin_map[place.cone.name] = dip_pin

        # 3. Pinos de entrada dedicada disponíveis
        avail_ded_inputs = [p for p in dev.dedicated_inputs if p not in pin_map]
        sorted_ext_inputs = sorted(list(ext_inputs))

        for inp in sorted_ext_inputs:
            if avail_ded_inputs:
                p = avail_ded_inputs.pop(0)
                pin_map[p] = inp
                in_pin_map[inp] = p
            else:
                # Usa uma OLMC não alocada como pino de entrada (tri-state OE=0)
                assert remaining_olmcs, f"Sem pinos disponíveis para entrada {inp} no chip {chip_id}"
                spare_olmc = remaining_olmcs.pop(0)
                pin_map[spare_olmc.dip_pin] = inp
                in_pin_map[inp] = spare_olmc.dip_pin

        packed_gal = PackedGAL(
            chip_id=chip_id,
            device=dev,
            pin_assignment=pin_map,
            olmc_placements=olmc_allocations,
            input_pins=in_pin_map,
            output_pins=out_pin_map,
            internal_feedbacks=internal_fb,
            clk_pin=clk_pin_used,
            rst_pin=None,
        )
        packed_chips.append(packed_gal)

    return packed_chips
