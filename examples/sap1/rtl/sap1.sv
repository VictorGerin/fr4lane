// SAP-1 ("Simple As Possible"), o computador de 8 bits do livro Digital
// Computer Electronics (Malvino), na versão em protoboard do Ben Eater:
// barramento de 8 bits, registradores A e B, ALU de soma e subtração com
// flags de carry e zero, RAM de 16 bytes, contador de programa de 4 bits e
// controle por microcódigo. As instruções estão em sap1_pkg.sv.
//
// O computador é uma pilha de placas ligadas por um conector comum, e este
// módulo é o "backplane": só liga as placas, sem lógica própria.
//   sap1_ctrl_board  controle, IR, PC, MAR e o painel de programação (terminação do barramento)
//   sap1_alu_board   A, B, ALU, flags e saída
//   sap1_ram_board   4 bytes de RAM; a mesma placa 4 vezes, com o banco nos jumpers
//
// Diferenças em relação ao original, para virar placas de componentes discretos:
// - cada fonte põe o seu dado no barramento por um driver tri-state
//   (sap1_bus_driver), como os 74LS245 do original; na família RTL o driver é
//   de coletor aberto e cada linha do barramento tem uma terminação (um pull-up);
// - o microcódigo, que no original fica em EEPROMs, vira lógica combinacional;
// - tudo roda num clock só: o contador de passos e os registradores mudam na
//   borda de subida, e o HLT congela o contador de passos em vez de cortar o clock;
// - a RAM é programada pelo painel da placa de controle, pelo próprio barramento.
//
// Uso: com prog = 1 a CPU fica parada e cada borda de clock com prog_we = 1
// grava prog_data em prog_addr. Depois, prog = 0 e um pulso em rst_n começam o
// programa do endereço 0.
//
// Este arquivo só pode ter o módulo sap1: na simulação do sistema
// (pcbflow-system), as placas vêm dos netlists delas.
module sap1 (
    input  logic       clk,
    input  logic       rst_n,      // reset assíncrono, ativo baixo
    input  logic       prog,       // 1: CPU parada, RAM gravada pelo painel
    input  logic       prog_we,
    input  logic [3:0] prog_addr,
    input  logic [7:0] prog_data,
    output logic [7:0] out,        // registrador de saída (display)
    output logic       out_load,   // 1 no ciclo em que a saída é carregada
    output logic       halted      // 1 depois de um HLT
);
    // o conector da pilha
    tri   [7:0] bus;
    logic [3:0] mar;
    logic       ri, ro, ai, ao, bi, eo, su, fi, oi, cf, zf;

    sap1_ctrl_board u_ctrl (.clk, .rst_n, .bus, .mar, .ri, .ro, .ai, .ao, .bi, .eo, .su, .fi, .oi,
                            .cf, .zf, .prog, .prog_we, .prog_addr, .prog_data, .out_load, .halted);
    sap1_alu_board  u_alu  (.clk, .rst_n, .bus, .ai, .ao, .bi, .eo, .su, .fi, .oi, .cf, .zf, .out);
    sap1_ram_board  u_ram0 (.clk, .bus, .mar, .ri, .ro, .bank(2'd0));
    sap1_ram_board  u_ram1 (.clk, .bus, .mar, .ri, .ro, .bank(2'd1));
    sap1_ram_board  u_ram2 (.clk, .bus, .mar, .ri, .ro, .bank(2'd2));
    sap1_ram_board  u_ram3 (.clk, .bus, .mar, .ri, .ro, .bank(2'd3));
endmodule
