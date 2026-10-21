// Driver de barramento: com en = 1 põe d no barramento; com en = 0 solta as
// linhas (alta impedância). É o papel do 74LS245 em cada módulo do Ben Eater.
//
// Na família RTL, cada bit vira um TBUF de coletor aberto (só puxa a linha para
// 0) e o fr4lane põe a terminação de barramento (um pull-up) em cada linha: com
// nenhum driver habilitado, a linha vai a 1.
module sap1_bus_driver #(parameter int W = sap1_pkg::DW) (
    input  logic         en,
    input  logic [W-1:0] d,
    output tri   [W-1:0] bus      // net (não variável): o barramento tem vários drivers
);
    assign bus = en ? d : 'z;
endmodule
