# SERV (RV32I / RV32E Bit-Serial) no fr4lane

Implementação em **SystemVerilog moderno** do núcleo [SERV](https://github.com/olofk/serv) (o menor processador RISC-V do mundo, criado por Olof Kindgren, vencedor do prêmio *World's Smallest RISC-V CPU*), particionado em **10 placas modulares (1 módulo por PCB)** em **Tecnologia RTL de Transistores Discretos** (BC548 + resistores de 1/4 W).

---

## 1. Arquitetura Modular em 10 PCBs (Tecnologia RTL)

Para viabilizar a fabricação, montagem prática e depuração individual, a CPU foi particionada em **10 placas modulares** conectadas por um backplane padronizado:

| # | Módulo (PCB) | Arquivo RTL | Função Principal | Transistores (BC548) | Resistores | Total Componentes |
|---|---|---|---|---:|---:|---:|
| **1** | **`serv_rf_if`** | [`rtl/serv_rf_if.sv`](rtl/serv_rf_if.sv) | Multiplexador do Banco de Registradores | 21 | 32 | **53** |
| **2** | **`serv_mem_if`** | [`rtl/serv_mem_if.sv`](rtl/serv_mem_if.sv) | Alinhamento de Memória (Byte/Half/Word) | 61 | 95 | **156** |
| **3** | **`serv_alu`** | [`rtl/serv_alu.sv`](rtl/serv_alu.sv) | ALU Serial de 1 bit (ADD/SUB/XOR/OR/AND/SLT) | 115 | 176 | **291** |
| **4** | **`serv_state`** | [`rtl/serv_state.sv`](rtl/serv_state.sv) | FSM Principal de Controle | 324 | 499 | **823** |
| **5** | **`serv_decode`** | [`rtl/serv_decode.sv`](rtl/serv_decode.sv) | Decodificador de Instruções RISC-V | 365 | 559 | **924** |
| **6** | **`serv_rf_ram_if`** | [`rtl/serv_rf_ram_if.sv`](rtl/serv_rf_ram_if.sv) | Adaptador Serial para SRAM Externa de 2 bits | 467 | 714 | **1.181** |
| **7** | **`serv_ctrl`** | [`rtl/serv_ctrl.sv`](rtl/serv_ctrl.sv) | Program Counter (PC) e Somador de Saltos | 513 | 774 | **1.287** |
| **8** | **`serv_bufreg`** | [`rtl/serv_bufreg.sv`](rtl/serv_bufreg.sv) | Registrador Shift de Endereço/Deslocamento | 736 | 1.122 | **1.858** |
| **9** | **`serv_immdec`** | [`rtl/serv_immdec.sv`](rtl/serv_immdec.sv) | Gerador e Extensor Serial de Imediatos | 781 | 1.196 | **1.977** |
| **10**| **`serv_bufreg2`** | [`rtl/serv_bufreg2.sv`](rtl/serv_bufreg2.sv) | Registrador Shift de Dados e Memória | 1.037 | 1.590 | **2.627** |
| **TOTAL** | **CPU Completa** | **10 Placas Modulares** | **RV32E / RV32I Completo** | **4.420 NPN** | **6.757 Res** | **11.177** |

---

## 2. Galeria 3D e Simulações Analógicas SPICE

### Renderização 3D da Placa da ALU (`serv_alu`) em RTL
Placa compacta de 158 × 131 mm com 115 transistores BC548B e 176 resistores, roteada a 100% com 0 conflitos:

<p align="center">
  <img src="img/serv_alu_rtl_3d.png" alt="Placa da ALU do SERV em Transistores RTL (3D)" width="780">
</p>

---

### Simulações Elétricas Analógicas SPICE (ngspice)

Cada célula e módulo foi simulado no **ngspice** com o modelo de transistor real do **BC548B** através do `fr4lane-cellsim`, sob 4 cantos PVT (típico, lento, rápido e quente):

#### 1. Formas de Onda Transitórias da ALU (`serv_alu`)
Simulação analógica completa dos 291 componentes discretos da ALU executando operações seriais com medição de atraso do caminho crítico (1,65 µs):

<p align="center">
  <img src="img/spice/serv_alu.png" alt="Formas de Onda SPICE da ALU" width="780">
</p>

#### 2. Célula Sequencial: Flip-Flop Tipo D (`DFF` em RTL)
Verificação analógica da captura na borda de subida do clock, tempos de setup e hold com transistores BC548:

<p align="center">
  <img src="img/spice/DFF.png" alt="Simulação SPICE do DFF RTL" width="780">
</p>

#### 3. Célula Combinacional: Porta Lógica NAND2
Curvas de chaveamento de transistores bipolares com carga de saída de pior caso:

<p align="center">
  <img src="img/spice/NAND2.png" alt="Simulação SPICE da NAND2 RTL" width="780">
</p>

---

## 3. Metodologia de Verificação em 3 Níveis

Para garantir 100% de confiabilidade entre o código SystemVerilog e a placa física, o projeto implementa 3 níveis de validação:

```
┌────────────────────────────────────────────────────────────────────────┐
│ Nível 1: Testbenches Unitários e Vetores de Teste (SystemVerilog)     │
│   tb/tb_serv_<modulo>.sv com vetores exaustivos e determinísticos      │
├────────────────────────────────────────────────────────────────────────┤
│ Nível 2: Simulação Gate-Level e Switch-Level de Transistores (fr4lane) │
│   Verificação do netlist de transistores (.sp) contra o modelo Liberty │
├────────────────────────────────────────────────────────────────────────┤
│ Nível 3: Simulação Analógica SPICE Transitória (ngspice)              │
│   Medição de tempos reais de propagação e cantos PVT (típico/lento/...) │
└────────────────────────────────────────────────────────────────────────┘
```

### Executando a Bateria de Testes dos 10 Módulos

```bash
# Executa a síntese e simulação elétrica dos 10 módulos individualmente
python run_all_rtl_modules.py
```

Resultado da execução automatizada:
```text
==============================================================================
Módulo             | NPN   | Res   | Total  | Gate-Lvl | Transistor | Status
------------------------------------------------------------------------------
serv_alu           | 115   | 176   | 291    | PASS     | PASS       | [ PASS ]
serv_ctrl          | 513   | 774   | 1287   | PASS     | PASS       | [ PASS ]
serv_immdec        | 781   | 1196  | 1977   | PASS     | PASS       | [ PASS ]
serv_decode        | 365   | 559   | 924    | PASS     | PASS       | [ PASS ]
serv_state         | 324   | 499   | 823    | PASS     | PASS       | [ PASS ]
serv_bufreg        | 736   | 1122  | 1858   | PASS     | PASS       | [ PASS ]
serv_bufreg2       | 1037  | 1590  | 2627   | PASS     | PASS       | [ PASS ]
serv_mem_if        | 61    | 95    | 156    | PASS     | PASS       | [ PASS ]
serv_rf_if         | 21    | 32    | 53     | PASS     | PASS       | [ PASS ]
serv_rf_ram_if     | 467   | 714   | 1181   | PASS     | PASS       | [ PASS ]
------------------------------------------------------------------------------
TOTAL CPU (10 PCBs) | 4420  | 6757  | 11177  | ALL OK   | ALL OK     | [ PASS ]
==============================================================================
```

---

## 4. Barramento Estruturado em SystemVerilog (`serv_pkg.sv`)

A arquitetura utiliza structs empacotadas (`struct packed`) e unions (`union packed`) para máxima organização:

1. **Barramento Externo do Sistema ([`sys_req_t`](rtl/serv_pkg.sv))**:
   Unifica `ibus` (instruções), `dbus` (dados Wishbone) e `rf` (SRAM externa de registradores) em uma única struct.
2. **Barramento de Empilhamento ([`j_stack_t`](rtl/serv_pkg.sv))**:
   Agrupa mais de 30 sinais de controle e temporização em uma `union packed` de 70 bits, permitindo acesso semântico (`stack.signals.timing.cnt_en`) ou acesso aos pinos físicos brutos da placa (`stack.raw_pins`).
3. **Decodificador RISC-V ([`riscv_inst_t`](rtl/serv_pkg.sv))**:
   Union sobreposta aos formatos de instrução R, I, S, B, U e J.

---

## 5. Compilação e Testes em C com Clang / LLVM

O SERV suporta a compilação de código C bare-metal para **RV32E** (`ilp32e`) e **RV32I** com validação automática de estado:

```bash
# Executa todos os testes em C com RV32E e PC_WIDTH=13
python run_c_test.py --all

# Executa em modo padrão RV32I
python run_c_test.py --rv32i --all

# Limpa artefatos temporários
python run_c_test.py --clean
```

Testes inclusos na suíte:
- `test_simple.c`: Aritmética básica e verificação de retorno de função.
- `test_fibonacci.c`: Sequência de Fibonacci iterativa.
- `test_fibonacci_rec.c`: Fibonacci recursivo (testa chamadas de função e pilha de registradores).
- `test_array.c`: Manipulação de ponteiros, arrays e laços na memória RAM.
