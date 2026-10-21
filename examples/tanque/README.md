# Controle de bomba d'água (`tanque`)

Máquina de estados finitos (FSM) de 4 estados em ciclo para controle de uma bomba d'água de um reservatório com dois sensores de nível (`nivel_baixo` e `nivel_alto`), sintetizada para componentes discretos pelo `pcbflow`.

<p align="center">
  <img src="../../docs/img/tanque_3d.jpg" alt="Placa da máquina de estados tanque na família RTL (70 BC548 e 107 resistores)" width="780">
</p>

## Estados e funcionamento

| Estado | Código (`estado[1:0]`) | `bomba` | Próximo estado |
|---|:---:|:---:|---|
| `VAZIO` | `00` | `0` | `ENCHENDO` quando `nivel_baixo == 0` |
| `ENCHENDO` | `01` | `1` | `CHEIO` quando `nivel_alto == 1` |
| `CHEIO` | `10` | `0` | `ESVAZIANDO` quando `nivel_alto == 0` |
| `ESVAZIANDO` | `11` | `0` | `VAZIO` quando `nivel_baixo == 0` |

<p align="center">
  <img src="../../docs/img/tanque_top.jpg" alt="Vista superior da placa tanque_rtl (131 x 103 mm, 7 fileiras)" width="780">
</p>

## Placas geradas

### Família RTL (`--lib rtl`)

- **Células:** 21 (`2 DFFR`, `11 NAND2`, `4 INV`, `2 AND2`, `2 NOR2`)
- **Componentes:** 177 (70 transistores BC548 e 107 resistores) + capacitores de desacoplamento
- **Dimensões:** 131 × 103 mm, 4 camadas, 7 fileiras
- **Roteamento e DRC:** 100 % roteada em 7 iterações, 0 violações de folga e 0 erros no DRC do KiCad

### Família CTL — Core-Transistor Logic (`--lib ctl`)

Na família **CTL** (núcleos toroidais de ferrite + transistores NPN BC548), as operações `NOR` e `NAND` (por coincidência de corrente e inibição de fluxo magnético) acontecem diretamente nos enrolamentos dos toroides de ferrite, usando um único transistor regenerador por porta:

- **Células:** 17 (`2 DFFR`, `4 INV`, `2 NAND2`, `3 NOR2`, `3 NOR3`, `1 OR2`, `2 XOR2`)
- **Componentes:** 201 (47 núcleos toroidais de ferrite, 38 transistores BC548 e 116 resistores) + capacitores de desacoplamento
- **Dimensões:** 148 × 103 mm, 4 camadas, 7 fileiras
- **Roteamento e DRC:** 100 % roteada em 9 iterações, 0 violações de folga e 0 erros no DRC do KiCad

<p align="center">
  <img src="../../docs/img/tanque_ctl_3d.jpg" alt="Placa da máquina de estados tanque na família CTL (47 núcleos de ferrite, 38 BC548 e 116 resistores)" width="780">
</p>

<p align="center">
  <img src="../../docs/img/tanque_ctl_top.jpg" alt="Vista superior da placa tanque_ctl (148 x 103 mm, 7 fileiras)" width="780">
</p>

## Como gerar e simular

```sh
cd examples/tanque
pcbflow --top tanque --lib rtl                                    # gera a PCB na família RTL
pcbflow --top tanque --lib ctl                                    # gera a PCB na família CTL (núcleos de ferrite)
pcbflow-cellsim --lib rtl --design tanque --src tanque.v          # simulação analógica SPICE nos 4 cantos (RTL)
pcbflow-cellsim --lib ctl --design tanque --src tanque.v          # simulação analógica SPICE nos 4 cantos (CTL)
```
