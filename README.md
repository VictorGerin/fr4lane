# pcbflow — Verilog para PCB com componentes discretos

[![Licença: MIT](https://img.shields.io/badge/licen%C3%A7a-MIT-blue.svg)](LICENSE)

O pcbflow transforma um módulo Verilog numa placa de circuito impresso feita só de componentes discretos: transistores MOSFET, transistores bipolares com resistores (lógica RTL) ou relés. Ele sintetiza o circuito com o Yosys, mapeia o resultado para uma biblioteca de portas montadas com esses componentes, confere por simulação que a placa faz o mesmo que o Verilog, posiciona e roteia tudo e entrega um projeto KiCad pronto para revisão e fabricação.

```
Verilog ──Yosys/ABC──▶ células (.lib) ──expansão (.sp)──▶ componentes ──placement──▶ roteamento ──▶ KiCad
                            │                                 │
                            └── simulação gate-level ─────────┴── simulação em nível de componente
```

É um fluxo de projeto de chip (síntese, biblioteca de células, floorplan, placement, roteamento, verificação) aplicado a uma PCB. Serve para construir computadores e circuitos digitais "à moda antiga", com portas lógicas visíveis, a partir de um RTL comum.

**Exemplo de resultado:** a ALU de 32 bits do [riscv-pipelined](https://github.com/VictorGerin/riscv-pipelined) na família RTL vira uma placa de 860 x 681 mm com 3 234 transistores BC548 e 4 908 resistores, totalmente roteada em 4 camadas (66 mil trilhas, 6 mil vias), com 0 erros no DRC do KiCad. A geração leva cerca de 17 minutos, com os somadores e os estágios do shifter montados como [macros](#macros-fluxo-hierárquico).

**O que tem:**

- três famílias de células incluídas: **CMOS** (2N7002 + BSS84), **RTL** (BC548 + resistores) e **relés** (SPDT de 5 V), com portas, flip-flops e latches; e um formato simples para criar outras;
- verificação de cada célula montada contra a função declarada, e simulação do circuito inteiro em nível de componente com o seu testbench;
- dimensionamento por fan-out em pior caso elétrico (família RTL);
- floorplan com fences, regions, guides e keepouts, editado num [editor visual](#editor-visual) no navegador;
- placement por anelamento simulado e roteamento por negociação (PathFinder) em grade, compilados com numba;
- fluxo hierárquico com [macros](#macros-fluxo-hierárquico): blocos repetidos são montados uma vez e copiados;
- placas de 4 camadas (VDD e GND em planos) ou de [2 camadas](#placa-de-2-camadas);
- projeto KiCad com grupos por módulo, modelos 3D, lista de materiais e DRC.

**Sumário:** [Instalação](#instalação) · [Uso](#uso) · [Como funciona](#como-funciona) · [Bibliotecas de células](#bibliotecas-de-células) · [Saídas](#saídas) · [Revisar no KiCad](#como-revisar-no-kicad) · [Módulos e macros](#módulos-na-placa) · [Montagem da placa](#como-a-placa-é-montada) · [Floorplan](#floorplan-posição-dos-módulos-e-keepouts) · [Editor visual](#editor-visual) · [2 camadas](#placa-de-2-camadas) · [Testes](#testes) · [Arquitetura](#arquitetura-do-código) · [Limitações](#limitações-conhecidas) · [Licença](#licença)

## Instalação

Pré-requisitos:

- Python ≥ 3.10;
- [Yosys](https://github.com/YosysHQ/yosys) e [Icarus Verilog](https://github.com/steveicarus/iverilog) no PATH;
- [KiCad](https://www.kicad.org/) 8 ou mais novo, para abrir o resultado e rodar o DRC (opcional para gerar a placa; testado com o 9 e o 10).

| Sistema | Yosys e Icarus Verilog |
|---|---|
| Windows (MSYS2) | `pacman -S mingw-w64-ucrt-x86_64-yosys mingw-w64-ucrt-x86_64-iverilog` |
| Debian / Ubuntu | `sudo apt install yosys iverilog` |
| macOS (Homebrew) | `brew install yosys icarus-verilog` |

```sh
git clone https://github.com/VictorGerin/pcbflow.git
cd pcbflow
pip install -e ".[fast]"        # editável; [fast] traz o numba, que compila o placement e o roteador
# ou, sem clonar:
pip install "pcbflow[fast] @ git+https://github.com/VictorGerin/pcbflow.git"
```

Sem o numba, o resultado é o mesmo, só que de 10 a 20 vezes mais devagar. A instalação cria três comandos: `pcbflow` (o fluxo), `pcbflow-fpedit` (o [editor de floorplan](#editor-visual)) e `pcbflow-drc` (o [DRC do KiCad](#como-revisar-no-kicad)); `python -m pcbflow` também funciona.

A suíte de testes passa inteira no Windows (Yosys 0.66, Icarus 13, KiCad 10) e no Linux (Debian 13: Yosys 0.52, Icarus 12, KiCad 9), incluindo os testes da página do editor no Chrome/Chromium e o DRC do KiCad.

### Docker

O `Dockerfile` monta o ambiente Linux de referência (Debian 13 com Yosys, Icarus Verilog, KiCad e Chromium) e roda os testes:

```sh
docker build -t pcbflow .
docker run --rm --shm-size=1g pcbflow                                        # a suíte de testes
docker run --rm -v "$PWD/meu_projeto:/proj" -w /proj pcbflow pcbflow --top meu_top   # um projeto seu
```

`--build-arg WITH_KICAD=0` deixa o KiCad de fora (imagem bem menor; o DRC fica pulado). Para rodar os testes contra o código da sua pasta, sem reconstruir a imagem: `docker run --rm -v "$PWD:/pcbflow" pcbflow`.

## Uso

```sh
pcbflow --top counter4 --src examples/counter4.v --tb examples/tb_counter4.v   # família CMOS (padrão)
pcbflow --top counter4 --src examples/counter4.v --lib rtl                     # família RTL com BC548
pcbflow --top counter4 --src examples/counter4.v --lib relay --layers 2       # relés, placa de 2 camadas
pcbflow --top counter4 --src examples/counter4.v --synth-only                 # só síntese + contagem
pcbflow --top counter4 --src examples/counter4.v --place-only                 # síntese + placement, sem rotear
```

Com `--tb`, o testbench roda contra o netlist de portas e contra o de componentes; uma falha é reconhecida pelas marcas `[ERRO`, `ERROR`, `FAILED` ou `FALHOU` na saída (veja [Simulação](#simulação-em-nível-de-componente)).

`--lib` aceita o nome de uma família incluída (`cmos`, `rtl`, `relay`) ou a pasta de uma família própria (veja [Criar uma família nova](#criar-uma-família-nova)). A rodada vai para `build/pcb/<top>_<família>[_2l]/` (veja [Saídas](#saídas)).

### Projeto (`pcbflow.json`)

Num projeto com vários módulos, um `pcbflow.json` na raiz diz onde estão os fontes, os testbenches e os floorplans, e o comando fica só `pcbflow --top <módulo>`:

```json
{
  "src":       ["rtl/**/*.v"],
  "exclude":   ["rtl/**/sva/**"],
  "tb":        "sim/testbenches/tb_{top}.v",
  "floorplan": ["rtl/**/{top}.floorplan.json"],
  "out":       "build/pcb"
}
```

O pcbflow procura o `pcbflow.json` na pasta atual e nas de cima (ou em `--project`). `src` e `exclude` são globs a partir da raiz; `{top}` é trocado pelo nome do módulo. Só `src` é obrigatório. Sem `--src`, entram os fontes do projeto; sem `--tb`, o testbench do top, se existir (`--no-tb` desliga); sem `--floorplan`, o primeiro que casar (`--no-floorplan` desliga); sem `--out`, `<out>/<top>_<família>[_2l]/`. O log diz o testbench e o floorplan que vieram do projeto.

Opções úteis: `--effort` (esforço do placement), `--row-gap`/`--part-gap` (densidade, em mm), `--route-iter`, `--max-parts`, `--seed`, `--floorplan arquivo.json` (veja [Floorplan](#floorplan-posição-dos-módulos-e-keepouts)), `--layers 2|4` (veja [Placa de 2 camadas](#placa-de-2-camadas)), `--synth-only`/`--place-only` (param depois da síntese ou do placement), `--density` (ocupação das fileiras fora das fences/regions, veja [Densidade](#densidade)), `--flatten` e `--module-weight` (veja [Módulos na placa](#módulos-na-placa)), `--macro` (veja [Macros](#macros-fluxo-hierárquico)), `--fresh` (veja abaixo).

**Placement reaproveitado.** Ao fim do placement o fluxo grava `place_cache.pkl` na pasta da rodada: o design sintetizado e dimensionado, a placa posicionada e as simulações que já rodaram. Na rodada seguinte (ex.: `pcbflow --place-only` e depois `pcbflow`), se nada que influencia esse resultado mudou, as etapas 0 a 3 são puladas e o fluxo vai direto ao roteamento: `[0-3/6] ... reaproveitados da rodada de <data>`. A impressão digital cobre o conteúdo dos fontes Verilog, os arquivos da família de células (e o `footprints.json`), o floorplan, as opções que mudam a placa (`--layers`, `--effort`, `--seed`, `--density`, `--row-gap`, `--part-gap`, `--module-weight`, `--flatten`, `--no-size`) e o código do pcbflow que roda até o placement; se algo mudou, o log diz o quê e o fluxo refaz tudo. Uma simulação que já rodou com o mesmo testbench não roda de novo. `--fresh` ignora o cache.

**Roteamento retomável.** Ao fim de cada iteração o roteador grava um ponto de controle (`route_state.pkl`: os caminhos de cada net e o histórico de disputa). Se a rodada for interrompida (Ctrl+C, o *Cancelar* do editor, queda), rodar de novo com as mesmas entradas reaproveita o placement e **continua da última iteração completa** (`retomado do ponto de controle: 3 iteração(ões) já feita(s)`), com o mesmo resultado de uma rodada sem interrupção. Com o roteamento já concluído (ex.: o DRC falhou depois), a rodada seguinte o reaproveita inteiro. O ponto de controle só vale para a mesma placa e a mesma versão do roteador; `--fresh` começa do zero. A retomada é entre iterações: uma iteração interrompida no meio é refeita.

**Progresso.** As etapas longas mostram o andamento: no terminal, uma linha reescrita no lugar; num arquivo ou pipe, uma linha a cada ~30 s. O anelamento do placement e cada iteração do roteamento têm porcentagem e estimativa do que falta (no roteamento, cada net pesa pelo tamanho, porque as maiores ficam por último); a síntese mostra o passo do Yosys (ex.: `passo 16/25: ABC`) e a simulação, a última linha do testbench. Cada etapa termina com o seu tempo (`etapa: 2 min 10 s`).

## Como funciona

Cada rodada passa por seis etapas, que aparecem no log com o tempo de cada uma:

| Etapa | O que faz | Onde |
|---|---|---|
| **[0/6] Biblioteca** | lê a família de células, confere a consistência dos arquivos, simula cada montagem (`.sp`) contra a função declarada (`.lib`) e confere o drive em pior caso | `library.py`, `cellcheck.py`, `drive.py` |
| **[1/6] Síntese** | o Yosys sintetiza o Verilog e mapeia para as células da família (cada módulo à parte, para a hierarquia chegar à placa); o pcbflow expande cada célula nos seus componentes e troca as que estouram o fan-out por variantes mais fortes | `synth.py`, `netlist.py`, `sizing.py` |
| **[2/6] Simulação** | roda o seu testbench duas vezes: contra o netlist de portas e contra o netlist de componentes (transistores, resistores, relés) | `__main__.py`, `netlist.py` |
| **[3/6] Placement** | arruma os componentes de cada célula num bloco, distribui os blocos em fileiras (respeitando o floorplan) e minimiza o comprimento de fio por anelamento simulado; com macros, monta e roteia cada bloco repetido à parte | `place.py`, `anneal.py`, `hier.py` |
| **[4/6] Roteamento** | liga VDD/GND aos planos e roteia os sinais numa grade de 0,5 mm, por negociação entre as nets | `route.py` |
| **[5/6] Verificação** | confere folgas, conectividade e as regras do floorplan sobre o cobre gerado, independentemente do roteador | `check.py` |
| **[6/6] KiCad** | escreve o projeto, a lista de materiais e o `report.md`; com o `kicad-cli` instalado, roda o DRC do KiCad | `kicad.py`, `drc.py` |

`--synth-only` para depois da etapa 2 e `--place-only` depois da 3. Com as mesmas entradas, uma nova rodada reaproveita o placement e retoma o roteamento de onde parou (veja abaixo).

## Bibliotecas de células

Cada família fica numa pasta, e cada célula numa subpasta com três arquivos:

```
pcbflow/lib/                     (dentro do pacote)
  footprints.json              geometria dos footprints (compartilhada pelas famílias)
  cmos/                        CMOS estático, 2N7002 + BSS84 (SOT-23)
  rtl/                         RTL, BC548 (TO-92) + resistores de 1/4 W
  relay/                       relés SPDT de 5 V + diodo 1N4148 de supressão em cada bobina
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
  São aceitos `M` (MOSFET: dreno gate fonte corpo modelo), `Q` (BJT: coletor base emissor modelo), `R`, `C`, `D` (diodo: anodo catodo modelo), `K` (relé SPDT: bobina+ bobina- comum NA NF modelo; convenção do pcbflow, com a bobina- no GND) e `X` (instância de outro subcircuito). Flip-flops e buffers são montados com `X`, a partir das portas.
- **`.json`:** o que nem o `.lib` nem o `.sp` comportam. Por exemplo, `"layout": {"rows": [["RL","R1","R2"], ["Q1","Q2"]]}` arruma resistores numa fileira e transistores na outra dentro do bloco.
- **`parts.json`:** liga o modelo do `.sp` ao componente físico, por exemplo `"NPN": BC548, footprint TO-92_Inline_Wide, pinos C=1 B=2 E=3`. Para trocar o transistor de uma família inteira, basta mudar este arquivo.
- **`footprints.json`:** geometria neutra (pads, furos, courtyard). O `kicad.py` traduz para o formato do KiCad ao escrever a placa.

Uma subpasta sem `.lib` vira um subcircuito auxiliar: outras células podem usá-lo, mas o Yosys não o enxerga. `"dont_use": true` no JSON tira a célula da síntese sem impedir que ela seja usada dentro de outras.

### Fan-out: drive em pior caso e variantes

Cada saída aguenta um número finito de entradas. O fluxo controla isso em dois níveis:

- **`max_fanout`** no `.json`: quantas entradas cada saída da célula pode alimentar (é a "faixa" da célula).
- **Drive elétrico em pior caso**, para famílias que declaram `"electrical"` no `library.json` (hoje a RTL). Com a saída em 1, o pull-up (RL) alimenta as bases das cargas pelos resistores de base (RB). O `drive.py` calcula o nível alto com VDD mínimo, RL no máximo e RB no mínimo da tolerância, e confere se cada carga recebe corrente de base para saturar: `Ib ≥ folga · Ic / β mín.`. NPNs empilhados (NAND) entram com o Vce(sat) de cada um. β mín., Vbe e Vce(sat) ficam no NPN do `parts.json`; VDD, tolerância, folga e `voh_min` ficam em `"electrical"`. Nets internas das células também são conferidas: uma montagem subdimensionada é barrada antes da síntese.

`python -m pcbflow.drive rtl` mostra a capacidade de cada saída (em cargas de `reference_load`, ex.: `INV.A`), o `max_fanout` e a corrente estática.

**Variantes.** Uma célula com `"variant_of": "<BASE>"` faz a mesma função da base com outra montagem, para outra faixa de fan-out. O Yosys só vê a base. Depois da síntese o fluxo troca cada instância pela variante **mais econômica** (menor corrente estática, depois menor área) em que todas as saídas passam nos dois critérios acima. Uma variante pode ter várias saídas no lugar de uma da base, cada uma com uma parte das cargas:

```json
{ "variant_of": "AND2", "outputs": {"Y": ["Y0", "Y1"]}, "max_fanout": 10 }
```

As entradas são divididas em fatias contíguas (por módulo e instância), de peso elétrico parecido. `Y0` fica com o nome da net original; as outras saídas ganham nets novas (`<net>.y1`...). A verificação confere que as saídas da variante fazem a mesma função que a da base, e a simulação de componentes (`--tb`) roda sobre a placa já dimensionada. O `report.md` lista as trocas e as nets que nem a variante mais forte atende. `--no-size` desliga as trocas.

Atenção: o ABC escolhe células por função e área, sem saber de fan-out, e pode montar a lógica com outras portas (ex.: NAND2 + NOR2 em vez de AND2). Nesse caso a net que estoura é de uma célula sem variante, e o fluxo só avisa.

### Verificações automáticas da biblioteca

A cada execução, antes da síntese:

1. **Consistência:**
   - os pinos do `.lib` e do `.sp` são os mesmos;
   - todo modelo usado existe no `parts.json`;
   - todo footprint existe;
   - o layout cita exatamente os componentes do `.sp`.
2. **Função:** cada `.sp` é simulado em nível de componente contra o comportamento do `.lib`. Células combinacionais são testadas em todas as combinações de entrada; flip-flops, com uma sequência aleatória de dados, clock e reset; latches, com dados e enable mudando em passos separados (transparente e travado). Uma montagem errada é barrada antes de chegar à placa.

### Famílias incluídas

| Célula | CMOS (componentes) | RTL (componentes) |
|---|---:|---:|
| INV | 2 | 3 (1 NPN + 2 R) |
| NAND2 / NAND3 | 4 / 6 | 5 (NPNs em série) / — |
| AND2 (NAND2 + INV, até 10 entradas) | — | 8 |
| AND2_X2 (variante: NAND2 + 2 INV, até 2×10 entradas) | — | 11 |
| NOR2 / NOR3 | 4 / 6 | 5 / 7 |
| AOI21 / OAI21 | 6 | — |
| BUF | 4 | 6 |
| DFF | 26 (6 NANDs) | 35 (6 NORs + inversor de clock) |
| DFFR (clear assíncrono ativo baixo) | 32 | 42 |
| DLAT (latch D, transparente com E = 1) | 16 (4 NANDs) | 23 (4 NORs + inversor) |

A família de relés (`lib/relay`) tem INV, BUF, AND2, NAND2, OR2, NOR2, XOR2, XNOR2 e MUX2 com 1 ou 2 relés (o contato é uma chave bidirecional: o MUX2 sai com 1 relé e o XOR2 com 2), DFF com 4, DFFR com 6 e DLAT com 2, cada bobina com seu diodo. O relé é genérico (5 pinos em grade de 2,54 mm): troque a geometria e a pinagem em `footprints.json` e `parts.json` pelas do relé escolhido antes de fabricar.

Notas:
- **CMOS sem portas de transmissão:** o diodo de corpo do MOSFET discreto impede que ele funcione como chave bidirecional.
- **NOR e NAND no RTL:** a NOR é a porta natural dessa família, com transistores em paralelo. A NAND2 empilha dois NPNs em série: a saída só vai a 0 com os dois saturados, e o nível baixo fica em ~2 Vce(sat) (~0,2–0,3 V), ainda abaixo do Vbe que liga a porta seguinte. Não há NAND3: com três NPNs empilhados a margem de ruído no 0 fica pequena demais.
- **Valores do RTL:** pull-up de 1 kΩ e resistor de base de 10 kΩ, a 5 V. Cada porta com saída em 0 consome cerca de 5 mA, e o fan-out fica limitado a 8 (`max_fanout`); pelo cálculo de pior caso (β ≥ 110, folga 3×) o limite elétrico seria 15 cargas de inversor. O fluxo avisa no relatório as nets que passam do limite.

### Latches

Um `always @*` que não atribui a saída em todos os caminhos vira latch no Yosys. A célula de latch declara um grupo `latch()` no `.lib`:

```
latch(IQ, IQN) { enable : "E"; data_in : "D"; }
```

O `dfflibmap` do Yosys só mapeia flip-flops, então o fluxo gera um `latch_map.v` a partir dessas células e roda `dfflegalize` + `techmap` antes do ABC. Enable ativo baixo vira inversor + DLAT; clear e preset viram lógica na entrada. Sem célula de latch na família, um latch inferido fica sem mapear e o fluxo para com erro logo depois da síntese.

Na simulação de componentes, uma entrada de bloco que passa por contato de relé (XOR, MUX, latch) entra por um buffer: com a bobina ainda em X, o Icarus deixaria o X voltar pelo contato até a fonte da entrada, o que pode travar um laço em X. No relé real o contato abre antes de fechar e a entrada não é dirigida de volta.

### Criar uma família nova

Copie uma das famílias de `pcbflow/lib/` para uma pasta sua (ex.: `minha_familia/`) e ajuste três coisas:
- o `parts.json`, com os componentes;
- os `.sp`, com a montagem de cada célula;
- os números do `.lib` (área, e no futuro tempos), se mudarem.

Depois é só `pcbflow --lib minha_familia/ ...`: a verificação da etapa 0 diz o que estiver inconsistente e simula cada célula. A chave `"footprints"` do `library.json` aponta o arquivo de geometria, relativo à pasta da família: as famílias CMOS e RTL usam o `../footprints.json` compartilhado, e a de relés tem o seu (`"footprints": "footprints.json"`). Numa cópia fora do pacote, copie também o arquivo de footprints e ajuste essa chave. O roteador exige que o menor lado de cada pad seja ≥ 0,5 mm, o passo da grade.

## Saídas

Cada rodada grava numa pasta `build/pcb/<top>_<família>[_2l]/` (ex.: `adder_cmos`, `adder_rtl_2l`; a base muda com `out` no `pcbflow.json` ou `--out`):

| Arquivo | Conteúdo |
|---|---|
| `<top>_<família>[_2l].kicad_pro`, `.kicad_pcb` | projeto KiCad: placa de 4 (ou 2) camadas já posicionada e roteada |
| `report.md` | células, módulos (com a faixa de referências de cada um), componentes, fan-out, pendências e mapa das instâncias do Yosys para a placa |
| `<top>_<família>[_2l]_bom.csv` | lista de materiais |
| `<top>_gates.v` | netlist gate-level (saída do Yosys) |
| `<top>_switch.v` | netlist em nível de componente, com a mesma interface do módulo |
| `sim_gates.log`, `sim_switch.log` | resultado do testbench contra cada netlist |
| `cells.lib`, `cells_models.v`, `cellcheck/` | Liberty unificado, modelos e verificação das células |
| `synth.ys`, `yosys.log`, `yosys_stat.txt`, `latch_map.v` | script, log e estatísticas do Yosys; mapeamento dos latches |
| `<top>_gates.json`, `<top>_hier.json` | netlists do Yosys (achatado e por módulo) |
| `placement.json` | grade de fileiras, medidas dos módulos e dos macros e posição dos componentes, para o editor de floorplan |
| `place_cache.pkl`, `route_state.pkl` | placement reaproveitável e ponto de controle do roteamento (veja [Uso](#uso)) |
| `drc.json` | relatório do DRC do KiCad, quando roda |

## Como revisar no KiCad

1. Abra o `.kicad_pro` e, no editor de PCB, pressione **B** para preencher os planos (In1.Cu = GND, In2.Cu = VDD). A placa de 2 camadas não tem planos.
2. Rode o DRC. O pcbflow já verifica folgas e conectividade por conta própria (passo 5/6) e, se achar o `kicad-cli`, roda o DRC do KiCad no fim (`--no-drc` pula). O DRC do KiCad é a referência; para rodá-lo de novo sobre uma placa já gerada: `pcbflow-drc build/pcb/<rodada>/<rodada>.kicad_pcb`. Antes do DRC os planos são preenchidos e a placa é salva preenchida: pelo próprio `kicad-cli` no KiCad 10 (`--refill-zones --save-board`) ou, no 8 e no 9, pela API Python do KiCad (`pcbnew`), usando o Python que vem com ele (no Windows, o `python.exe` ao lado do `kicad-cli`; no Linux, o do sistema; ou o de `PCBFLOW_KICAD_PYTHON`). Sem nenhum dos dois, o DRC roda com os planos vazios e avisa que a ligação de VDD/GND pelos planos não foi conferida.
3. Cada célula lógica é um **grupo** com o nome da instância (`U12 (NOR2)`, `FF3 (DFFR)`…), dentro do grupo do seu módulo (`u_fa (full_adder)`). O `report.md` liga esses nomes aos do Yosys.
4. Nets que o roteador não fechou, se houver, aparecem no ratsnest e em *Pendências* no relatório.

O projeto não tem esquemático: a referência lógica é o `_switch.v`, que é simulado com o testbench. A geometria dos footprints é aproximada e vem embutida no arquivo. *Update Footprints from Library* troca pelos footprints oficiais. Cada footprint aponta para o modelo 3D oficial (`${KICAD<versão>_3DMODEL_DIR}/<lib>.3dshapes/<nome>.step`), então o visualizador 3D (**Alt+3**) funciona sem ajuste. O pcbflow usa a variável da versão mais nova do KiCad instalada; para forçar outra, defina `PCBFLOW_3DMODEL_VAR` (ex.: `KICAD9_3DMODEL_DIR`).

## Módulos na placa

A hierarquia do Verilog é mantida até a placa:

- **Síntese:** o Yosys mapeia cada módulo separadamente e só achata o netlist no fim, de modo que cada célula sabe de que instância veio (`u_fa`, `u0.u2`…). O preço é que o ABC não otimiza através das fronteiras dos módulos; `--flatten` volta ao mapeamento achatado, que às vezes economiza células mas perde os módulos.
- **Floorplan:** cada módulo instanciado no topo ganha uma região retangular própria, e os blocos só se movem dentro dela. Submódulos dentro de uma região ficam juntos por uma força de agrupamento (`--module-weight`, padrão 2; 0 desliga).
- **KiCad:** grupos aninhados (módulo > submódulo > célula), um contorno tracejado com o nome do módulo na camada *User.Drawings* e a propriedade `Module` em cada componente.
- **Referências** numeradas por módulo: cada módulo tem uma faixa contínua (`u_and: Q1–Q4, R1–R7`), listada no `report.md`.

Para ver cada módulo isolado na placa, instancie-os num topo sem fios em comum (ex.: o `basic_top` do projeto [riscv-pipelined](https://github.com/VictorGerin/riscv-pipelined), que junta portas, somadores e flip-flops).

### Macros (fluxo hierárquico)

Para circuitos grandes, módulos podem ser implementados à parte e copiados, no padrão da indústria: **o topo decide onde cada bloco fica (top-down) e cada bloco é feito de baixo para cima (bottom-up)**.

```sh
pcbflow --top adder_32bit --lib rtl --macro adder --macro adder_16bit
```

ou, no floorplan, `"macros": ["adder", "adder_16bit"]`. Um macro é um **tipo** de módulo (o nome do Verilog):

1. **Moldes:** as instâncias do tipo com a mesma estrutura (mesmas portas ligadas do mesmo jeito) compartilham um molde; uma instância diferente (ex.: o sizing trocou uma célula dela) ganha molde próprio. Cada molde é posicionado e roteado **uma vez**, sozinho, num retângulo com margem de 1,5 mm.
2. **Pinos:** cada net que sai do macro ganha um pino na borda: o lado mais perto dos terminais da net e, nele, o ponto livre mais perto (F.Cu nas laterais, B.Cu em cima e embaixo; pinos a 1 mm um do outro).
3. **Hierarquia e paralelismo:** um macro pode conter outros (o `adder_16bit` acima é feito de 4 `adder` prontos); os moldes do mesmo nível rodam em processos separados, em paralelo.
4. **Montagem:** cada instância recebe uma cópia do seu molde (componentes, trilhas e vias, com nets e instâncias renomeadas), num retângulo reservado com um canal livre de 1,5 mm em volta para chegar aos pinos. O resto do circuito ("cola") é posicionado normalmente, puxado pelos pinos dos macros, e o roteamento de cima só liga os pinos e os pads da cola: muito menos nets e buscas menores.
5. **Onde fica cada macro:** sem floorplan, os macros vão para o alto da placa, em prateleiras, e a cola vai para as fileiras de baixo. Com floorplan, uma fence/region com o caminho da instância (ex.: `add_comp_inst.main_adder`) diz onde ela fica (a área tem de comportar o macro mais o canal; o erro diz o tamanho necessário); sem isso, o macro vai para dentro da área do módulo que o contém (empacotado a partir do canto superior esquerdo) ou, se nenhum módulo acima dele tem área, para uma faixa abaixo das áreas declaradas. O log mostra o tamanho de cada molde para dimensionar as áreas.

Instâncias do mesmo tipo podem ganhar moldes diferentes: no `fanout_test` do riscv-pipelined, a `u_and2` alimenta 16 NOTs, o sizing a troca por `AND2_X2` e ela fica com molde próprio, maior. O cobre de um macro pronto é obstáculo para as rotas de fora (até da própria net, que só entra pelo pino), mas o espaço livre dentro dele continua disponível para elas.

A simulação de componentes, a verificação de conectividade e o DRC continuam sobre a placa inteira, então um erro de montagem aparece. O editor de floorplan escolhe os macros e mostra onde cada um fica (veja [Macros no editor](#macros-no-editor)). Limites: só placas de 4 camadas (VDD/GND nos planos internos); e os pinos são escolhidos só pelo lado de dentro do macro (o topo não opina).

## Como a placa é montada

### Simulação em nível de componente

O netlist de componentes (`<top>_switch.v`) é Verilog estrutural que o Icarus simula com o mesmo testbench do RTL:

- MOSFETs viram as primitivas `nmos`/`pmos`; um NPN saturado vira uma chave `nmos` entre coletor e emissor (e um PNP, `pmos`);
- resistores viram `rtran`, uma ligação resistiva: um transistor conduzindo vence o pull-up, como no circuito real;
- o contato de um relé vira duas chaves bidirecionais comandadas pela bobina (`tranif1` entre comum e NA, `tranif0` entre comum e NF). Como no relé real, só uma bobina em 1 puxa o contato: em X ou Z (no início da simulação, nada dirigindo) ele fica em repouso, o que também deixa o resultado igual em qualquer versão do Icarus. Uma entrada de bloco que passa por contato entra por um buffer, para o X de uma bobina ainda indefinida não voltar pelo contato até a fonte;
- capacitores e diodos (desacoplamento, supressão da bobina) não afetam a lógica e ficam de fora;
- cada saída de bloco tem um atraso de transporte de 10 ps; com atraso inercial, o Icarus prenderia glitches como X.

O pcbflow considera que o testbench falhou se a saída tiver `[ERRO`, `ERROR`, `FAILED` ou `FALHOU` (o `vvp` não devolve o código do `$finish`).

### Placement

Cada instância de célula vira um bloco desenhado conforme o `"layout"` do seu `.json` (ex.: resistores numa fileira, transistores na outra). Os blocos vão para fileiras de uma grade fixa, dentro da região do seu módulo ou da área do floorplan, e um anelamento simulado troca blocos de lugar ou leva um bloco para outra posição permitida, minimizando o comprimento de fio (HPWL), com uma força que mantém cada módulo agrupado (`--module-weight`). O anelamento roda compilado pelo numba (`anneal.py`) e é reprodutível: a mesma semente (`--seed`) dá o mesmo placement, com ou sem numba; `--effort` aumenta o número de passos.

Os conectores de 2,54 mm ficam nas bordas (entradas e alimentação à esquerda, saídas à direita). Cada fileira livre leva um capacitor de desacoplamento, e a placa tem um de bulk (veja [Densidade](#densidade) para as áreas).

### Roteamento

O roteador (`route.py`) trabalha numa grade de 0,5 mm com duas camadas de sinal: F.Cu só com trilhas horizontais e B.Cu só com verticais, trocando de camada por via. Trilha de 0,25 mm, folga de 0,2 mm, via de 0,6/0,3 mm.

1. **Alimentação.** Na placa de 4 camadas, VDD e GND são planos internos: cada pad SMD de alimentação ganha uma via curta até o plano, e os pads com furo ligam-se a ele direto. Na de 2 camadas, veja [Placa de 2 camadas](#placa-de-2-camadas).
2. **Negociação (PathFinder).** Cada net é roteada com uma busca A* (compilada pelo numba) que pode, no início, passar por pontos já usados por outras. A cada iteração, o custo dos pontos disputados sobe (1,6× por iteração) e o histórico de disputa de cada ponto acumula (+0,4 por iteração em conflito), até nenhuma net dividir espaço com outra. O limite de pontos explorados por busca acompanha o tamanho da net (20 vezes a área do seu retângulo, entre 400 mil e 8 milhões); se mesmo assim ela não acha caminho, tenta de novo ignorando a disputa, para toda net participar da negociação.
3. **Teto adaptativo.** O custo de disputa tem teto de 300 vezes o custo de um passo: sem teto, a estimativa do A* deixa de orientar a busca e as nets que precisam contornar congestionamento estouram o limite. Quando a negociação estaciona (as nets em conflito param de cair por 4 iterações, tipicamente nets trocando de lugar sem nenhuma desistir), o teto sobe 3× (até 100 mil); se isso faz o número de conflitos disparar, ele volta um passo. O log mostra cada mudança (`negociação estacionada: teto ... sobe para 900`).
4. **Melhor iteração.** O roteador guarda a iteração com menos conflitos. Se a última for pior, a etapa seguinte parte da melhor.
5. **Passada final.** Ao fim das iterações (`--route-iter`, padrão 40), as nets ainda em conflito são arrancadas, e cada uma tenta de novo contra a placa já roteada, sem cruzar ninguém e com o limite de busca máximo.
6. **Arrancar e rerrotear.** Para cada net que ainda não passa, o roteador acha um caminho que cruza poucas outras, arranca essas, coloca a net e rerroteia as arrancadas. Uma arrancada que não volta limpa pode arrancar outras por sua vez, numa cadeia de até 5 níveis. Se a cadeia não fecha, tudo volta como estava: só fica a troca que diminui as pendências.
7. **Limpeza e pendências.** Vias de sinal com cobre numa camada só são removidas. O que não fechou vai para *Pendências* no `report.md`, marcado como bloqueio físico (sem caminho nem com a placa vazia, ex.: um pad cercado) ou falta de espaço (resolva com `--row-gap`, densidade ou floorplan).

Ao fim de cada iteração o estado vai para o ponto de controle (`route_state.pkl`), com a melhor iteração junto, e uma rodada interrompida continua de onde parou.

A busca A* e o anelamento são os laços pesados e rodam compilados pelo [numba](https://numba.pydata.org/), com a grade em arrays numpy: de 10 a 20 vezes mais rápido que em Python puro, com o mesmo resultado. Sem o numba, o log avisa (`busca A*: Python puro`). A primeira rodada depois de mudar esses arquivos compila as funções (alguns segundos); depois elas ficam em cache em `__pycache__`.

## Floorplan: posição dos módulos e keepouts

Por padrão o pcbflow decide sozinho onde cada módulo fica. Com `--floorplan arquivo.json` você fixa áreas em **coordenadas absolutas**, em mm, a partir do canto superior esquerdo da placa. Num projeto com `pcbflow.json`, o fluxo usa o floorplan que a chave `floorplan` achar para o top (veja [Projeto](#projeto-pcbflowjson)); `--no-floorplan` desliga. Exemplo:

```json
{
  "board":   { "width": 230, "height": 150 },
  "modules": {
    "u_fa":   { "type": "fence",  "rect": [17, 5, 78, 42] },
    "u_mux4": { "type": "region", "rect": [101, 5, 88, 42] },
    "u_dff":  { "type": "guide",  "near": [150, 95] }
  },
  "keepouts": [
    { "name": "furo_fixacao", "rect": [120, 52, 10, 10], "what": ["place", "route"] },
    { "name": "area_livre",   "rect": [150, 52, 25, 20], "what": ["place"], "layers": ["F.Cu"] }
  ]
}
```

`rect` é `[x, y, largura, altura]`. `board` é opcional: sem ele, a placa cresce até caber tudo e conter as áreas.

| Tipo | Componentes do módulo | Componentes de outros módulos |
|---|---|---|
| `fence` | obrigatoriamente dentro | não entram |
| `region` | obrigatoriamente dentro | podem usar o espaço que sobrar |
| `guide` (`rect` ou `near`) | preferem ficar perto; cada bloco paga a distância até a área | — |

Keepouts: `"place"` proíbe componentes; `"route"` proíbe trilhas e vias nas camadas de `layers` (padrão: as duas). As regras de módulo valem só para o **posicionamento**, como nas ferramentas de chip: fios de outros módulos podem atravessar uma fence. Para impedir, use um keepout de roteamento.

Os módulos são caminhos de instância (`u_fa`, `u0.u2`), os mesmos da seção *Módulos* do `report.md`. Uma regra vale para os submódulos do caminho, e a mais específica prevalece.

**Fileiras.** Os componentes ficam em fileiras de uma grade fixa, e uma área de fence/region só usa as fileiras que couberem **inteiras** dentro dela. O passo da grade depende da família e do número de camadas: o RTL usa 13,05 mm em 4 camadas e 15,55 mm em 2. A seção *Floorplan* do `report.md` lista a área de lógica e a faixa de y de cada fileira, e mostra quanto de fileira cada área usa e oferece. Se uma área não comportar o módulo, o fluxo para antes do roteamento e diz quanto falta e onde ficam as fileiras próximas.

### Densidade

**O tamanho da área é o controle.** Uma fence/region espalha o módulo por igual pela área toda: as fileiras recebem a mesma carga, e a sobra de cada fileira é repartida entre os blocos (os vãos viram canais para as trilhas verticais). A densidade da área é calculada, não digitada:

> densidade = o que o módulo precisa ÷ o que a área oferece (em mm de fileira)

Área maior = densidade menor = módulo mais espalhado; área menor = mais compacto (até ~90%, acima disso a verificação acusa que não cabe). O editor recalcula a densidade enquanto você arrasta ou redimensiona a área.

**Desacoplamento:** cada fileira livre (fora das áreas) leva um capacitor de desacoplamento (`decoupling.row` do `library.json`), mesmo quando uma fence/region a corta em vários trechos: o trilho de alimentação é o mesmo. Dentro de uma fence/region não há capacitor por padrão. `"decoupling": true` na área põe um no fim de cada trecho dela, e o espaço dele é reservado. No editor é a caixa *Desacoplamento* da área.

Ajuste avançado: `"density"` numa fence/region fixa uma densidade **acima** da calculada. O módulo então se agrupa até essa ocupação onde a fiação o puxa, deixando o resto da área livre, como o *target density* das ferramentas de chip (`global_placement -density` no OpenROAD). `"density": 1` reproduz o comportamento antigo: blocos encostados à esquerda e nas primeiras fileiras. O editor mostra quando uma área tem densidade fixa e oferece um botão para voltar a calculá-la.

Fora das fences/regions, os módulos sem área se agrupam a 80% das fileiras livres (`--density` muda isso; 1 = compacto). Sem floorplan, as regiões automáticas já saem justas (8% de folga), e a densidade só reparte essa folga dentro das fileiras.

No `basic_top` do riscv-pipelined em CMOS (com o floorplan de lá), as duas formas saem 100% roteadas:

| | HPWL | Trilhas / vias |
|---|---:|---:|
| densidade calculada (padrão) | 5171 mm | 1302 / 398 |
| `"density": 1` em todas as áreas e `--density 1` (comportamento antigo) | 4686 mm | 1361 / 373 |

**Verificação.** O passo 5/6 confere por conta própria que todo componente de um módulo está na sua fence/region, que nenhum de fora invadiu uma fence e que nada caiu num keepout.

**No KiCad:** os keepouts viram *Rule Areas* (o DRC do KiCad passa a aplicá-los se você editar a placa). As áreas dos módulos são desenhadas em *User.Drawings*: fence com linha cheia, region tracejada, guide pontilhada (ou um círculo, para `near`).

### Editor visual

```sh
pcbflow-fpedit rtl/basic/basic_top.floorplan.json             # abre um floorplan (criado ao salvar se não existir)
pcbflow-fpedit rtl/basic/basic_top.floorplan.json --lib rtl   # já com a família RTL no menu
pcbflow-fpedit                                                # sem arquivo: escolhe o top pelo Abrir…
```

Abre um servidor local (só em `127.0.0.1`; `--host`/`--port` mudam isso) e o navegador padrão com o arquivo carregado. Se ele não existir, o editor começa vazio e o cria ao salvar. O projeto é o do `pcbflow.json` acima do arquivo aberto (ou da pasta atual; `--project` escolhe outro): é nele que o editor procura fontes, testbenches e rodadas. Arraste as áreas para mover, os cantos para redimensionar; as setas movem 0,5 mm (Shift: 5 mm), Delete apaga, Ctrl+Z/Ctrl+Y desfazem/refazem e Ctrl+S salva. Os campos `_comment` do arquivo são preservados.

**Menu do fluxo.** A barra de cima roda o fluxo sem sair do navegador:

- **Abrir…** navega pelas pastas do projeto, mostra os `.v`/`.sv` e, ao escolher um arquivo, os módulos declarados nele; o escolhido vira o top. O floorplan fica em `<top>.floorplan.json` ao lado do fonte (ou o que o `floorplan` do `pcbflow.json` achar). Os botões passam ao pcbflow os fontes do projeto; um top fora deles entra junto. Sem `pcbflow.json`, entram os `.v`/`.sv` da pasta do top e das de baixo.
- **Família** e **Camadas** escolhem a rodada (`<out>/<top>_<família>[_2l]/`, `build/pcb` por padrão) que o editor desenha e que os botões geram.
- **Simulação** (marcada por padrão) roda o testbench do top (`tb` do `pcbflow.json`), se existir; desmarcada, o editor passa `--no-tb` e a etapa é pulada.
- **① Síntese** roda `pcbflow --synth-only`: mede os módulos e a grade de fileiras.
- **② Placement** roda `pcbflow --place-only`: síntese + placement com o floorplan, sem rotear. É o ciclo rápido para ajustar as áreas vendo os componentes no lugar.
- **③ Gerar PCB** roda o `pcbflow` completo: placa roteada e projeto KiCad; no fim, o link *report.md* abre o relatório.

Antes de rodar, o editor salva o floorplan. Ao lado do estado da execução, uma barra mostra a etapa em andamento, com porcentagem e estimativa quando a etapa as tem. Depois de um ② Placement, o ③ Gerar PCB reaproveita o placement se o floorplan e o resto não mudaram. O log aparece ao vivo no painel de baixo (clique para abrir), e uma execução por vez pode ser cancelada: o cancelamento derruba a árvore inteira de processos (`python`, `yosys`, `iverilog`, `vvp`), e ela também morre se o editor for fechado. O comando é montado pelo servidor a partir de listas fechadas (ação, família, camadas), nunca de texto vindo da página.

Para desenhar as fileiras, o placement e a capacidade de cada área, o editor lê o `placement.json` que toda rodada grava. A grade e o quanto cada módulo precisa vêm da síntese e não dependem do floorplan, então basta a ① Síntese para começar; o placement por baixo aparece depois da ② ou da ③. Pelo terminal, o mesmo ciclo é:

```sh
pcbflow --top basic_top --lib rtl --synth-only               # síntese: mede os módulos
pcbflow-fpedit rtl/basic/basic_top.floorplan.json             # desenha vendo o tamanho mínimo
pcbflow --top basic_top --lib rtl --place-only               # placement com o floorplan, sem rotear
pcbflow --top basic_top --lib rtl                            # fluxo completo com o floorplan
```

As três rodadas gravam na mesma pasta, então cada um substitui o `placement.json` do anterior; a rodada só de síntese mostra fileiras e capacidade, sem o placement por baixo. O editor avisa quando um fonte Verilog mudou depois da rodada. A verificação usa as mesmas funções do fluxo: o que o editor aprova o `pcbflow` aceita. Sem rodada, ele só confere o formato.

### Macros no editor

A seção **Macros** do painel lista os tipos de módulo do projeto, com o número de instâncias. Marcar um tipo grava `"macros": [...]` no floorplan, e o fluxo passa a montar cada instância dele como macro (posicionada e roteada sozinha e copiada pronta na placa, veja [Macros](#macros-fluxo-hierárquico)). Não é preciso passar `--macro`: os botões do menu usam o floorplan.

- **Tamanho:** o de um macro só existe depois que ele é montado. Depois de um ② Placement com o tipo marcado, o painel mostra o tamanho medido de cada molde; antes disso, o editor usa uma estimativa pela largura de fileira do módulo (≈ 1,25 vez a área das fileiras, mais a borda), marcada como *estimado* e com contorno tracejado no desenho.
- **Onde fica:** o desenho mostra cada macro do topo onde o fluxo o porá, com o canal de acesso aos pinos em volta (tracejado). O cálculo é a mesma função do `hier.py` (`macro_spots`), então a posição bate com a da placa: com uma fence com o caminho da instância, no canto superior esquerdo dela; sem isso, empacotado na área do módulo que o contém ou numa faixa abaixo das áreas declaradas.
- **Controlar a posição:** clique num macro no desenho, ou na instância em *Módulos do projeto* (marcada com a etiqueta *macro*), para criar uma fence do tamanho exato dele (macro + canal), no lugar onde ele está; depois arraste a fence. Com uma área de macro selecionada, o painel mostra o tamanho necessário e o botão **Ajustar ao macro**.
- **Verificação:** com macros, as fileiras e a capacidade são calculadas só para a lógica solta, com os macros como keepout, como no fluxo. Uma área pequena demais para o macro, macros que não cabem na área do módulo que os contém, ou um macro fora de uma placa de tamanho fixo viram erro. Uma área dentro de outro macro (ex.: a de um `adder` quando o `adder_16bit` que o contém também é macro) vira aviso, porque o fluxo a ignora.

## Placa de 2 camadas

Com `--layers 2` não há planos internos. Os sinais continuam em F.Cu (horizontais) e B.Cu (verticais), como na de 4 camadas, e a alimentação vira uma grade de cobre desenhada pelo placement:

- um trilho de VDD acima e um de GND abaixo de cada fileira (F.Cu, 0,8 mm). As células já têm a parte ligada ao VDD em cima (PMOS, resistores de pull-up) e a ligada ao GND embaixo (NMOS, emissores);
- troncos verticais de 1 mm na B.Cu dos dois lados da lógica, ligados aos trilhos por vias e aos pinos VDD/GND dos conectores;
- o roteador liga cada pad de alimentação ao trilho mais próximo, negociando espaço junto com os sinais;
- a verificação (passo 5/6) confere de verdade a conectividade de VDD e GND, já que não há plano para supor.

Os canais entre fileiras ficam 2,5 mm mais largos para caber os trilhos, e a família pode pedir mais folga entre componentes (`"part_gap_2layer"` no `library.json`; a CMOS usa 1,0 mm, porque no SOT-23 o pino da fonte do PMOS fica do lado oposto ao trilho de VDD). A placa sai uns 10 a 25 % maior que a de 4 camadas.

| | 4 camadas | 2 camadas |
|---|---|---|
| `adder`, RTL | 135 x 97 mm | 143 x 112 mm |
| `basic_top`, RTL | 156 x 149 mm | 174 x 175 mm |

Os trilhos de 0,8 mm levam cerca de 2 A em cobre de 1 oz, folga suficiente para as placas deste tamanho. Para projetos com muitas centenas de portas RTL (5 mA por porta com saída em 0), vale conferir a corrente total.

## Escala (família CMOS)

Módulos do processador do [riscv-pipelined](https://github.com/VictorGerin/riscv-pipelined):

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

O somador de 4 bits sai em poucos segundos; a ALU em RTL, com macros, em cerca de 17 min (veja o exemplo no início). Todos saem 100 % roteados. O processador completo passaria de 80 mil transistores, e o banco de registradores sozinho responde por 60 % disso. O caminho viável é fazer uma placa por estágio, ligadas por conectores, e trocar o banco de registradores por SRAM.

## Testes

A suíte em `tests/` (pytest) confere o próprio pcbflow. A validação de cada placa (verificação das células, simulações, folgas, conectividade e DRC) diz que *aquela* placa está certa; os testes dizem que uma mudança no código não quebrou o que funcionava.

```sh
pip install -e ".[fast,test]"     # uma vez: pytest e selenium
python -m pytest                  # tudo o que as ferramentas instaladas permitem (~2 min)
python -m pytest -m "not slow"    # só os de unidade, sem o fluxo completo (~10 s)
python -m pytest -k fpedit -x     # um grupo, parando no primeiro erro
```

| Arquivo | O que confere |
|---|---|
| `test_liberty.py` | expressões booleanas (operadores, precedência, `to_verilog`) e leitura de células, flip-flops e latches; o que o leitor recusa |
| `test_floorplan.py` | formato do floorplan: o que é aceito e cada mensagem de recusa |
| `test_library.py` | as três famílias: consistência `.sp` x `.lib` x `parts.json`, drive em pior caso, latches, `.lib` gerado; leitor SPICE; `cellcheck` de cada família e de montagens sabotadas de propósito (tem de acusar) |
| `test_check_cache_misc.py` | folgas, conectividade e keepouts numa placa feita à mão; cache do placement; valores SPICE, tempos, escopos |
| `test_project.py` | `pcbflow.json`: fontes com exclusões, testbench e floorplan por top, procura nas pastas de cima, o que é recusado, e o fluxo pegando tudo do projeto (e `--no-tb`/`--no-floorplan`) |
| `test_hier_geom.py` | posição dos macros (com e sem floorplan, área pequena, macros dentro da área do pai) e o floorplan da lógica solta |
| `test_flow.py` | fluxo completo: `counter4` nas três famílias (simulações OK, 0 violações, 0 nets incompletas, arquivos do KiCad), 2 e 4 camadas, latches, testbench que falha, reaproveitamento do placement, determinismo, macros (um molde para cópias iguais, cópias idênticas), previsão do editor igual ao placement real, erros de entrada e DRC do KiCad (com o `kicad-cli` preenchendo os planos, com o `pcbnew` e sem nenhum dos dois) |
| `test_fpedit.py` | validação do editor (capacidade, macros medidos e estimados, avisos), o comando que cada botão monta, uma execução de verdade pelo menu e o cancelamento dela (a árvore de processos termina), e a API HTTP com um servidor de verdade: salvar e conflito, Host não permitido, navegação presa ao projeto, execução só com valores conhecidos |
| `test_fpedit_ui.py` | a página no Chrome (ou Chromium): macros do arquivo, marcar/desmarcar tipos, clicar e arrastar macros, área pequena e *Ajustar ao macro*, avisos, salvar, barra de progresso |

Os testes são marcados por dependência (`pytest.ini`): `tools` (Yosys e Icarus), `slow` (fluxo completo), `kicad` (`kicad-cli`) e `ui` (Selenium e Chrome). O que não está instalado é pulado, com o motivo no resumo. Os projetos de teste ficam em `tests/data/` (`hier8.v`: somador de 8 bits feito de 2 `add4` de 4 `fa`; `latch_demo.v`), e cada rodada do fluxo vai para uma pasta temporária do pytest.

## Arquitetura do código

```
pcbflow/
  __main__.py     linha de comando: encadeia as etapas, simulação, report.md, placement.json
  project.py      pcbflow.json: fontes, testbench, floorplan e pasta de saída de um projeto
  library.py      família de células: leitura, consistência, Liberty unificado, modelos Verilog
  liberty.py      leitor de Liberty (.lib) e das expressões booleanas
  spice.py        leitor dos .subckt (.sp)
  cellcheck.py    simula cada montagem contra a função do .lib
  drive.py        drive elétrico em pior caso (níveis, corrente de base, capacidade de fan-out)
  synth.py        script e execução do Yosys (mapeamento por módulo, latches)
  netlist.py      netlist do Yosys -> células -> componentes; escreve o netlist de componentes
  sizing.py       troca células por variantes conforme o fan-out
  floorplan.py    formato e validação do floorplan
  place.py        blocos, fileiras, áreas do floorplan e placement
  anneal.py       anelamento simulado do placement (numba)
  hier.py         fluxo hierárquico: moldes de macro, cópias e posição dos macros
  route.py        roteamento por negociação, passada final, rip-up, ponto de controle (numba)
  jit.py          numba opcional: compila se instalado, Python puro se não
  check.py        verificação de folgas, conectividade e floorplan sobre o cobre
  layout.py       modelo da placa: footprints, pads, trilhas, vias, regras
  kicad.py        escreve .kicad_pcb, .kicad_pro e a lista de materiais
  drc.py          DRC pelo kicad-cli (pcbflow-drc)
  cache.py        reaproveitamento do placement entre rodadas
  progress.py     linhas de progresso no terminal e no editor
  fpedit.py       editor de floorplan: servidor HTTP local e validação
  fpedit.html     a página do editor (sem dependências externas)
  lib/            famílias de células: cmos, rtl, relay e footprints.json
examples/         counter4.v e o seu testbench
tests/            suíte pytest (veja Testes)
```

Os dados passam de uma etapa para outra assim: o Yosys devolve um netlist JSON de células; `netlist.py` o transforma num `Design` (instâncias lógicas e, para cada uma, os blocos e componentes da sua montagem); `place.py` (ou `hier.py`, com macros) produz um `Board` com footprints posicionados; `route.py` acrescenta trilhas e vias ao mesmo `Board`; `check.py` e `kicad.py` leem esse `Board`. O `Design` e o `Board` são guardados em `place_cache.pkl` para a rodada seguinte.

## Limitações conhecidas

- **Sem análise de tempo:** o `.lib` não tem atrasos; a frequência máxima da placa não é calculada. A simulação de componentes confere a lógica, não o tempo.
- **Footprints aproximados:** a geometria vem do `footprints.json` e é fiel o bastante para o roteamento; antes de fabricar, confira ou use *Update Footprints from Library* no KiCad. O relé é genérico.
- **Fan-out:** só a família RTL tem modelo elétrico; nas outras vale o `max_fanout` de cada célula. Quando o ABC usa uma célula sem variante mais forte, o fluxo só avisa (não insere buffers).
- **Macros:** só em placas de 4 camadas, e os pinos são escolhidos olhando só para dentro do macro.
- **Tamanho:** placas com dezenas de milhares de componentes levam horas para rotear; o `--max-parts` (padrão 20 000) para o fluxo antes do placement acima disso.
- **Editor:** o menu do fpedit lista só as famílias incluídas no pcbflow; uma família própria roda pela linha de comando.

## Licença

[MIT](LICENSE).
