# Circuito `add4` na família `relay` (ngspice)

20 células, 80 componentes, 512 vetores (todas as combinações das entradas, simuladas em lotes de 8). Cada vetor é conferido contra a lógica do netlist; o caminho crítico é o último cruzamento de uma saída depois da mudança das entradas. O netlist publicado tem os primeiros 8 vetores.

| Canto | Resultado | Sem convergir | Caminho crítico |
|---|---|---:|---|
| típico | OK | 9 % | 45.1 ms (co no vetor 436) |
| lento | OK | 47 % | 40.2 ms (co no vetor 121) |
| quente | **1280 saídas erradas** | — | — |
| rápido | OK | 16 % | 45.1 ms (co no vetor 376) |

"Sem convergir": a parte dos vetores em que o ngspice não chegou ao fim do lote (ele empaca nos
chaveamentos em cadeia das chaves com histerese do modelo do relé); nesses vetores não há medida.
Em todos os vetores medidos dos cantos típico, lento e rápido, nenhuma saída saiu errada. No canto
quente, o relé não atraca (a bobina recebe menos que os 24 mA da ficha), e metade das saídas erra.

Reproduzir (canto típico): `ngspice -b add4.cir`

![add4](add4.png)

