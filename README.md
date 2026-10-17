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
make pcb PCB_TOP=adder PCB_LIB=pcbflow/lib/rtl PCB_ARGS="--layers 2"   # placa de 2 camadas
make pcb-stat PCB_TOP=ALU                            # só síntese + contagem
make pcb-place PCB_TOP=basic_top                     # síntese + placement, sem rotear

# direto
PYTHONPATH=pcbflow python -m pcbflow --lib pcbflow/lib/rtl --top adder \
    --src rtl/RISC_V/ALU/adder.v --tb sim/testbenches/tb_adder.v
```

Opções úteis: `--effort` (esforço do placement), `--row-gap`/`--part-gap` (densidade, em mm), `--route-iter`, `--max-parts`, `--seed`, `--floorplan arquivo.json` (veja [Floorplan](#floorplan-posição-dos-módulos-e-keepouts)), `--layers 2|4` (veja [Placa de 2 camadas](#placa-de-2-camadas)), `--synth-only`/`--place-only` (param depois da síntese ou do placement), `--density` (ocupação das fileiras fora das fences/regions, veja [Densidade](#densidade)), `--flatten` e `--module-weight` (veja [Módulos na placa](#módulos-na-placa)), `--fresh` (veja abaixo).

**Placement reaproveitado.** Ao fim do placement o fluxo grava `place_cache.pkl` na pasta da rodada: o design sintetizado e dimensionado, a placa posicionada e as simulações que já rodaram. Na rodada seguinte (ex.: `make pcb-place` e depois `make pcb`), se nada que influencia esse resultado mudou, as etapas 0 a 3 são puladas e o fluxo vai direto ao roteamento: `[0-3/6] ... reaproveitados da rodada de <data>`. A impressão digital cobre o conteúdo dos fontes Verilog, os arquivos da família de células (e o `footprints.json`), o floorplan, as opções que mudam a placa (`--layers`, `--effort`, `--seed`, `--density`, `--row-gap`, `--part-gap`, `--module-weight`, `--flatten`, `--no-size`) e o código do pcbflow que roda até o placement; se algo mudou, o log diz o quê e o fluxo refaz tudo. Uma simulação que já rodou com o mesmo testbench não roda de novo. `--fresh` ignora o cache.

**Progresso.** As etapas longas mostram o andamento: no terminal, uma linha reescrita no lugar; num arquivo ou pipe, uma linha a cada ~30 s. O anelamento do placement e cada iteração do roteamento têm porcentagem e estimativa do que falta (no roteamento, cada net pesa pelo tamanho, porque as maiores ficam por último); a síntese mostra o passo do Yosys (ex.: `passo 16/25: ABC`) e a simulação, a última linha do testbench. Cada etapa termina com o seu tempo (`etapa: 2 min 10 s`).

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

### Fan-out: drive em pior caso e variantes

Cada saída aguenta um número finito de entradas. O fluxo controla isso em dois níveis:

- **`max_fanout`** no `.json`: quantas entradas cada saída da célula pode alimentar (é a "faixa" da célula).
- **Drive elétrico em pior caso**, para famílias que declaram `"electrical"` no `library.json` (hoje a RTL). Com a saída em 1, o pull-up (RL) alimenta as bases das cargas pelos resistores de base (RB). O `drive.py` calcula o nível alto com VDD mínimo, RL no máximo e RB no mínimo da tolerância, e confere se cada carga recebe corrente de base para saturar: `Ib ≥ folga · Ic / β mín.`. NPNs empilhados (NAND) entram com o Vce(sat) de cada um. β mín., Vbe e Vce(sat) ficam no NPN do `parts.json`; VDD, tolerância, folga e `voh_min` ficam em `"electrical"`. Nets internas das células também são conferidas: uma montagem subdimensionada é barrada antes da síntese.

`python -m pcbflow.drive pcbflow/lib/rtl` mostra a capacidade de cada saída (em cargas de `reference_load`, ex.: `INV.A`), o `max_fanout` e a corrente estática.

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
2. **Função:** cada `.sp` é simulado em nível de componente contra o comportamento do `.lib`. Células combinacionais são testadas em todas as combinações de entrada; flip-flops, com uma sequência aleatória de dados, clock e reset. Uma montagem errada é barrada antes de chegar à placa.

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

Notas:
- **CMOS sem portas de transmissão:** o diodo de corpo do MOSFET discreto impede que ele funcione como chave bidirecional.
- **NOR e NAND no RTL:** a NOR é a porta natural dessa família, com transistores em paralelo. A NAND2 empilha dois NPNs em série: a saída só vai a 0 com os dois saturados, e o nível baixo fica em ~2 Vce(sat) (~0,2–0,3 V), ainda abaixo do Vbe que liga a porta seguinte. Não há NAND3: com três NPNs empilhados a margem de ruído no 0 fica pequena demais.
- **Valores do RTL:** pull-up de 1 kΩ e resistor de base de 10 kΩ, a 5 V. Cada porta com saída em 0 consome cerca de 5 mA, e o fan-out fica limitado a 8 (`max_fanout`); pelo cálculo de pior caso (β ≥ 110, folga 3×) o limite elétrico seria 15 cargas de inversor. O fluxo avisa no relatório as nets que passam do limite.

### Criar uma família nova

Copie uma pasta existente e ajuste três coisas:
- o `parts.json`, com os componentes;
- os `.sp`, com a montagem de cada célula;
- os números do `.lib` (área, e no futuro tempos), se mudarem.

Footprints novos entram em `footprints.json`. O roteador exige que o menor lado de cada pad seja ≥ 0,5 mm, o passo da grade.

## Saídas (`build/pcb/<top>_<família>[_2l]/`, ex.: `adder_cmos`, `adder_rtl_2l`)

| Arquivo | Conteúdo |
|---|---|
| `<top>_<família>[_2l].kicad_pro`, `.kicad_pcb` | projeto KiCad: placa de 4 (ou 2) camadas já posicionada e roteada |
| `report.md` | células, módulos (com a faixa de referências de cada um), componentes, fan-out, pendências e mapa das instâncias do Yosys para a placa |
| `<top>_<família>[_2l]_bom.csv` | lista de materiais |
| `<top>_gates.v` | netlist gate-level (saída do Yosys) |
| `<top>_switch.v` | netlist em nível de componente, com a mesma interface do módulo |
| `sim_gates.log`, `sim_switch.log` | resultado do testbench contra cada netlist |
| `cells.lib`, `cells_models.v`, `cellcheck/` | Liberty unificado, modelos e verificação das células |

## Como revisar no KiCad

1. Abra o `.kicad_pro` e, no editor de PCB, pressione **B** para preencher os planos (In1.Cu = GND, In2.Cu = VDD). A placa de 2 camadas não tem planos.
2. Rode o DRC. O pcbflow já verifica folgas e conectividade por conta própria (passo 5/6), mas o DRC do KiCad é a referência.
3. Cada célula lógica é um **grupo** com o nome da instância (`U12 (NOR2)`, `FF3 (DFFR)`…), dentro do grupo do seu módulo (`u_fa (full_adder)`). O `report.md` liga esses nomes aos do Yosys.
4. Nets que o roteador não fechou, se houver, aparecem no ratsnest e em *Pendências* no relatório.

O projeto não tem esquemático: a referência lógica é o `_switch.v`, que é simulado com o testbench. A geometria dos footprints é aproximada e vem embutida no arquivo. *Update Footprints from Library* troca pelos footprints oficiais. Cada footprint aponta para o modelo 3D oficial (`${KICAD<versão>_3DMODEL_DIR}/<lib>.3dshapes/<nome>.step`), então o visualizador 3D (**Alt+3**) funciona sem ajuste. O pcbflow usa a variável da versão mais nova do KiCad instalada; para forçar outra, defina `PCBFLOW_3DMODEL_VAR` (ex.: `KICAD9_3DMODEL_DIR`).

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

## Floorplan: posição dos módulos e keepouts

Por padrão o pcbflow decide sozinho onde cada módulo fica. Com `--floorplan arquivo.json` você fixa áreas em **coordenadas absolutas**, em mm, a partir do canto superior esquerdo da placa. O `make pcb` usa automaticamente `<top>.floorplan.json` se houver um em `rtl/`; `PCB_FLOORPLAN=` desliga. Exemplo completo em [`rtl/basic/basic_top.floorplan.json`](../rtl/basic/basic_top.floorplan.json):

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

No `basic_top` em CMOS (floorplan do repositório), as duas formas saem 100% roteadas:

| | HPWL | Trilhas / vias |
|---|---:|---:|
| densidade calculada (padrão) | 5171 mm | 1302 / 398 |
| `"density": 1` em todas as áreas e `--density 1` (comportamento antigo) | 4686 mm | 1361 / 373 |

**Verificação.** O passo 5/6 confere por conta própria que todo componente de um módulo está na sua fence/region, que nenhum de fora invadiu uma fence e que nada caiu num keepout.

**No KiCad:** os keepouts viram *Rule Areas* (o DRC do KiCad passa a aplicá-los se você editar a placa). As áreas dos módulos são desenhadas em *User.Drawings*: fence com linha cheia, region tracejada, guide pontilhada (ou um círculo, para `near`).

### Editor visual

```sh
make fpedit PCB_TOP=basic_top                        # abre o floorplan do basic_top
make fpedit PCB_TOP=basic_top PCB_LIB=pcbflow/lib/rtl   # já com a família RTL no menu
# ou
PYTHONPATH=pcbflow python -m pcbflow.fpedit rtl/basic/basic_top.floorplan.json
PYTHONPATH=pcbflow python -m pcbflow.fpedit          # sem arquivo: escolhe o top pelo Abrir…
```

Abre um servidor local (só em `127.0.0.1`; `--host`/`--port` mudam isso) e o navegador padrão com o arquivo carregado. Se ele não existir, o editor começa vazio e o cria ao salvar; o `make fpedit` usa `<top>.floorplan.json` ao lado de `<top>.v`. Arraste as áreas para mover, os cantos para redimensionar; as setas movem 0,5 mm (Shift: 5 mm), Delete apaga, Ctrl+Z/Ctrl+Y desfazem/refazem e Ctrl+S salva. Os campos `_comment` do arquivo são preservados.

**Menu do fluxo.** A barra de cima roda o fluxo sem sair do navegador:

- **Abrir…** navega pelas pastas do projeto, mostra os `.v`/`.sv` e, ao escolher um arquivo, os módulos declarados nele; o escolhido vira o top. O floorplan fica em `<top>.floorplan.json` ao lado do fonte (ou o que já existir em `rtl/`). Um top fora de `rtl/` ou em `.sv` entra no `make` por `PCB_SRC_EXTRA`.
- **Família** e **Camadas** escolhem a rodada (`build/pcb/<top>_<família>[_2l]/`) que o editor desenha e que os botões geram.
- **Simulação** (marcada por padrão) roda o testbench `tb_<top>.v`, se existir; desmarcada, o editor passa `PCB_TB=` ao `make` e a etapa é pulada.
- **① Síntese** roda `make pcb-stat`: mede os módulos e a grade de fileiras.
- **② Placement** roda `make pcb-place`: síntese + placement com o floorplan, sem rotear. É o ciclo rápido para ajustar as áreas vendo os componentes no lugar.
- **③ Gerar PCB** roda `make pcb`: placa roteada e projeto KiCad; no fim, o link *report.md* abre o relatório.

Antes de rodar, o editor salva o floorplan. Ao lado do estado da execução, uma barra mostra a etapa em andamento, com porcentagem e estimativa quando a etapa as tem. Depois de um ② Placement, o ③ Gerar PCB reaproveita o placement se o floorplan e o resto não mudaram. O log aparece ao vivo no painel de baixo (clique para abrir), e uma execução por vez pode ser cancelada: o cancelamento derruba a árvore inteira de processos (`make`, `python`, `yosys`, `vvp`), e ela também morre se o editor for fechado. O comando é montado pelo servidor a partir de listas fechadas (alvo, família, camadas), nunca de texto vindo da página.

Para desenhar as fileiras, o placement e a capacidade de cada área, o editor lê o `placement.json` que toda rodada grava. A grade e o quanto cada módulo precisa vêm da síntese e não dependem do floorplan, então basta a ① Síntese para começar; o placement por baixo aparece depois da ② ou da ③. Pelo terminal, o mesmo ciclo é:

```sh
make pcb-stat  PCB_TOP=basic_top PCB_LIB=pcbflow/lib/rtl   # síntese: mede os módulos
make fpedit    PCB_TOP=basic_top                            # desenha vendo o tamanho mínimo
make pcb-place PCB_TOP=basic_top PCB_LIB=pcbflow/lib/rtl    # placement com o floorplan, sem rotear
make pcb       PCB_TOP=basic_top PCB_LIB=pcbflow/lib/rtl    # fluxo completo com o floorplan
```

Os três alvos gravam na mesma pasta, então cada um substitui o `placement.json` do anterior; a rodada só de síntese mostra fileiras e capacidade, sem o placement por baixo. O editor avisa quando um fonte Verilog mudou depois da rodada. A verificação usa as mesmas funções do fluxo: o que o editor aprova o `make pcb` aceita. Sem rodada, ele só confere o formato.

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
