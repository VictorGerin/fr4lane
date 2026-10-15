# pcbflow — Verilog para PCB com componentes discretos

O pcbflow sintetiza um módulo Verilog com o Yosys, mapeia o resultado para uma biblioteca de células montadas com componentes discretos (MOSFETs, transistores bipolares, resistores…), faz o placement e o roteamento na PCB e gera um projeto KiCad pronto para revisão.

```
Verilog ──Yosys/ABC──▶ células (.lib) ──expansão (.sp)──▶ componentes ──placement──▶ roteamento ──▶ KiCad
                            │                                 │
                            └── simulação gate-level ─────────┴── simulação em nível de componente
```

## Uso

Pré-requisitos: Python ≥ 3.11 (sem dependências externas), Yosys e Icarus Verilog (MSYS2: `pacman -S mingw-w64-ucrt-x86_64-yosys mingw-w64-ucrt-x86_64-iverilog`) e KiCad 8 ou 9 para abrir o resultado.

```sh
# pelo Makefile (usa sim/testbenches/tb_<top>.v se existir)
make pcb PCB_TOP=adder                               # família CMOS (padrão)
make pcb PCB_TOP=adder PCB_LIB=pcbflow/lib/rtl       # família RTL com BC548
make pcb PCB_TOP=counter4 PCB_SRC=pcbflow/examples/counter4.v PCB_TB=pcbflow/examples/tb_counter4.v
make pcb-stat PCB_TOP=ALU                            # só síntese + contagem

# direto
PYTHONPATH=pcbflow python -m pcbflow --lib pcbflow/lib/rtl --top adder \
    --src rtl/RISC_V/ALU/adder.v --tb sim/testbenches/tb_adder.v
```

Opções úteis: `--effort` (esforço do placement), `--row-gap`/`--part-gap` (densidade, em mm), `--route-iter`, `--max-parts`, `--seed`, `--flatten` e `--module-weight` (veja [Módulos na placa](#módulos-na-placa)).

## Bibliotecas de células

Cada família fica numa pasta, e cada célula numa subpasta com três arquivos:

```
pcbflow/lib/
  footprints.json              geometria dos footprints (compartilhada pelas famílias)
  cmos/                        CMOS estático, 2N7002 + BSS84 (SOT-23)
  rtl/                         RTL, BC548 (TO-92) + resistores de 1/4 W
    library.json               dados gerais: alimentação, cabeçalho Liberty, desacoplamento, folgas
    parts.json                 componentes reais: modelo SPICE -> peça, footprint, pinagem
    cells/NOR2/
      NOR2.lib                 o que a célula faz (Liberty) — é o que o Yosys vê
      NOR2.sp                  como a célula é montada (.subckt SPICE)
      NOR2.json                metadados: descrição, layout na placa, max_fanout, dont_use
```

Cada arquivo tem um papel, sem repetir informação dos outros:

- **`.lib`:** pinos, função e área (o custo que o ABC minimiza). Não diz nada sobre a montagem, então a mesma interface vale para qualquer família.
- **`.sp`:** só a parte elétrica, isto é, quais componentes e ligados como:
  ```spice
  .subckt NOR2 A B Y VDD GND
  RL VDD Y  1k            ; pull-up do coletor
  R1 A   b1 10k           ; resistores de base
  R2 B   b2 10k
  Q1 Y   b1 GND NPN       ; Q<nome> coletor base emissor modelo
  Q2 Y   b2 GND NPN
  .ends NOR2
  ```
  São aceitos `M` (MOSFET: dreno gate fonte corpo modelo), `Q` (BJT: coletor base emissor modelo), `R`, `C` e `X` (instância de outro subcircuito). Flip-flops e buffers são montados com `X`, a partir das portas.
- **`.json`:** o que nem o `.lib` nem o `.sp` comportam. Por exemplo, `"layout": {"rows": [["RL","R1","R2"], ["Q1","Q2"]]}` arruma resistores numa fileira e transistores na outra dentro do bloco.
- **`parts.json`:** liga o modelo do `.sp` ao componente físico, por exemplo `"NPN": BC548, footprint TO-92_Inline_Wide, pinos C=1 B=2 E=3`. Para trocar o transistor de uma família inteira, basta mudar este arquivo.
- **`footprints.json`:** geometria neutra (pads, furos, courtyard). O `kicad.py` traduz para o formato do KiCad ao escrever a placa.

Uma subpasta sem `.lib` vira um subcircuito auxiliar: outras células podem usá-lo, mas o Yosys não o enxerga. `"dont_use": true` no JSON tira a célula da síntese sem impedir que ela seja usada dentro de outras.

### Verificações automáticas da biblioteca

A cada execução, antes da síntese:

1. **Consistência:**
   - os pinos do `.lib` e do `.sp` são os mesmos;
   - todo modelo usado existe no `parts.json`;
   - todo footprint existe;
   - o layout cita exatamente os componentes do `.sp`.
2. **Função:** cada `.sp` é simulado em nível de componente contra o comportamento do `.lib`. Células combinacionais são testadas em todas as combinações de entrada; flip-flops, com uma sequência aleatória de dados, clock e reset. Uma montagem errada é barrada antes de chegar à placa.

### Famílias incluídas

| Célula | CMOS (componentes) | RTL (componentes) |
|---|---:|---:|
| INV | 2 | 3 (1 NPN + 2 R) |
| NAND2 / NAND3 | 4 / 6 | — |
| NOR2 / NOR3 | 4 / 6 | 5 / 7 |
| AOI21 / OAI21 | 6 | — |
| BUF | 4 | 6 |
| DFF | 26 (6 NANDs) | 35 (6 NORs + inversor de clock) |
| DFFR (clear assíncrono ativo baixo) | 32 | 42 |

Notas:
- **CMOS sem portas de transmissão:** o diodo de corpo do MOSFET discreto impede que ele funcione como chave bidirecional.
- **Por que só NOR e inversor no RTL:** a NOR é a porta natural dessa família, com transistores em paralelo. NAND em RTL exigiria NPNs empilhados, com margens ruins.
- **Valores do RTL:** pull-up de 1 kΩ e resistor de base de 10 kΩ, a 5 V. Cada porta com saída em 0 consome cerca de 5 mA, e o fan-out fica limitado a 8 (`max_fanout`). O fluxo avisa no relatório as nets que passam do limite.

### Criar uma família nova

Copie uma pasta existente e ajuste três coisas:
- o `parts.json`, com os componentes;
- os `.sp`, com a montagem de cada célula;
- os números do `.lib` (área, e no futuro tempos), se mudarem.

Footprints novos entram em `footprints.json`. O roteador exige que o menor lado de cada pad seja ≥ 0,5 mm, o passo da grade.

## Saídas (`build/pcb/<top>_<família>/`, ex.: `adder_cmos`, `adder_rtl`)

| Arquivo | Conteúdo |
|---|---|
| `<top>_<família>.kicad_pro`, `.kicad_pcb` | projeto KiCad: placa de 4 camadas já posicionada e roteada |
| `report.md` | células, módulos (com a faixa de referências de cada um), componentes, fan-out, pendências e mapa das instâncias do Yosys para a placa |
| `<top>_<família>_bom.csv` | lista de materiais |
| `<top>_gates.v` | netlist gate-level (saída do Yosys) |
| `<top>_switch.v` | netlist em nível de componente, com a mesma interface do módulo |
| `sim_gates.log`, `sim_switch.log` | resultado do testbench contra cada netlist |
| `cells.lib`, `cells_models.v`, `cellcheck/` | Liberty unificado, modelos e verificação das células |

## Como revisar no KiCad

1. Abra o `.kicad_pro` e, no editor de PCB, pressione **B** para preencher os planos (In1.Cu = GND, In2.Cu = VDD).
2. Rode o DRC. O pcbflow já verifica folgas e conectividade por conta própria (passo 5/6), mas o DRC do KiCad é a referência.
3. Cada célula lógica é um **grupo** com o nome da instância (`U12 (NOR2)`, `FF3 (DFFR)`…), dentro do grupo do seu módulo (`u_fa (full_adder)`). O `report.md` liga esses nomes aos do Yosys.
4. Nets que o roteador não fechou, se houver, aparecem no ratsnest e em *Pendências* no relatório.

O projeto não tem esquemático: a referência lógica é o `_switch.v`, que é simulado com o testbench. A geometria dos footprints é aproximada e vem embutida no arquivo. *Update Footprints from Library* troca pelos footprints oficiais.

## Módulos na placa

A hierarquia do Verilog é mantida até a placa:

- **Síntese:** o Yosys mapeia cada módulo separadamente e só achata o netlist no fim, de modo que cada célula sabe de que instância veio (`u_fa`, `u0.u2`…). O preço é que o ABC não otimiza através das fronteiras dos módulos; `--flatten` volta ao mapeamento achatado, que às vezes economiza células mas perde os módulos.
- **Floorplan:** cada módulo instanciado no topo ganha uma região retangular própria, e os blocos só se movem dentro dela. Submódulos dentro de uma região ficam juntos por uma força de agrupamento (`--module-weight`, padrão 2; 0 desliga).
- **KiCad:** grupos aninhados (módulo > submódulo > célula), um contorno tracejado com o nome do módulo na camada *User.Drawings* e a propriedade `Module` em cada componente.
- **Referências** numeradas por módulo: cada módulo tem uma faixa contínua (`u_and: Q1–Q4, R1–R7`), listada no `report.md`.

Para ver cada módulo isolado na placa, instancie-os num topo sem fios em comum, como em `rtl/basic/basic_top.v`.

## Como a placa é montada

- **Simulação em nível de componente:** MOSFETs e BJTs viram as primitivas `nmos`/`pmos` do Verilog, e resistores viram `rtran`, uma ligação resistiva: um transistor conduzindo vence o pull-up. Cada saída de bloco tem um atraso de transporte de 10 ps; com atraso inercial, o Icarus prende glitches como X.
- **Placement:** cada instância de subcircuito vira um bloco desenhado conforme o layout do JSON. Os blocos são distribuídos em fileiras (dentro da região do seu módulo, quando há mais de um), e um anelamento simulado minimiza o comprimento de fio (HPWL). Os conectores de 2,54 mm ficam nas bordas: entradas e alimentação à esquerda, saídas à direita. Há um capacitor de desacoplamento no fim de cada fileira e um de bulk.
- **Roteamento (`route.py`):**
  - grade de 0,5 mm em F.Cu (horizontal) e B.Cu (vertical), com vias para trocar de camada;
  - VDD e GND são planos internos, sem trilha: pads SMD de alimentação ganham uma via curta até o plano, e pads com furo ligam-se a ele direto;
  - os sinais são roteados por negociação (PathFinder): as nets podem disputar espaço no início, e o custo dos pontos disputados sobe a cada iteração até ninguém mais compartilhar;
  - trilha de 0,25 mm, folga de 0,2 mm e via de 0,6/0,3 mm.

## Escala (família CMOS)

| Módulo | Transistores |
|---|---:|
| adder (4 bits) | 144 |
| adder_32bit | 1 254 |
| pipeline_controller | 184 |
| wb_stage | 384 |
| mem_stage | 3 134 |
| if_stage | 4 210 |
| id_stage | 6 950 |
| ALU | 7 176 |
| ex_stage | 11 984 |
| register_file | 51 372 |

O somador de 4 bits sai em cerca de 10 s em CMOS e 22 s em RTL; o de 32 bits em CMOS leva cerca de 6 min. Todos saem 100 % roteados. O processador completo passaria de 80 mil transistores, e o banco de registradores sozinho responde por 60 % disso. O caminho viável é fazer uma placa por estágio, ligadas por conectores, e trocar o banco de registradores por SRAM.
