// Placa de controle: contador de passos e microcódigo, registrador de
// instrução, contador de programa, registrador de endereço da memória (MAR) e o
// painel de programação. Leva a terminação do barramento da pilha.
//
// Programação (prog = 1): a CPU fica parada e o painel usa a própria pilha
// para gravar a RAM: prog_addr vai para as linhas do MAR, prog_data para o
// barramento (por um driver tri-state, como as outras fontes) e prog_we para o
// RI. As placas de RAM não sabem que existe modo de programação.
module sap1_ctrl_board (
    // pilha
    input  logic                    clk,
    input  logic                    rst_n,
    inout  tri   [sap1_pkg::DW-1:0] bus,
    output logic [sap1_pkg::AW-1:0] mar,       // endereço da RAM (MAR ou o do painel)
    output logic                    ri,        // grava na RAM
    output logic                    ro,        // RAM no barramento
    output logic                    ai, ao, bi, eo, su, fi, oi,   // para a placa da ALU
    input  logic                    cf,        // flags, da placa da ALU
    input  logic                    zf,
    // painel
    input  logic                    prog,
    input  logic                    prog_we,
    input  logic [sap1_pkg::AW-1:0] prog_addr,
    input  logic [sap1_pkg::DW-1:0] prog_data,
    output logic                    out_load,  // 1 no ciclo em que a saída é carregada
    output logic                    halted     // 1 depois de um HLT
);
    sap1_pkg::ctrl_t         cw;
    logic [sap1_pkg::DW-1:0] ir;
    logic [sap1_pkg::AW-1:0] pc, mar_q;

    sap1_control u_ctrl (.clk, .rst_n, .run(!prog), .opcode(ir[7:4]), .cf, .zf, .cw);

    sap1_pc                      u_pc  (.clk, .rst_n, .inc(cw.ce), .jump(cw.j), .d(bus[3:0]), .q(pc));
    sap1_reg #(.W(sap1_pkg::AW)) u_mar (.clk, .rst_n, .load(cw.mi), .d(bus[3:0]), .q(mar_q));
    sap1_reg                     u_ir  (.clk, .rst_n, .load(cw.ii), .d(bus), .q(ir));

    // fontes do barramento nesta placa (PC e operando têm 4 bits: os de cima vão a 0)
    sap1_bus_driver u_pc_drv   (.en(cw.co), .d({4'd0, pc}),      .bus);
    sap1_bus_driver u_ir_drv   (.en(cw.io), .d({4'd0, ir[3:0]}), .bus);
    sap1_bus_driver u_prog_drv (.en(prog),  .d(prog_data),       .bus);

    assign mar = prog ? prog_addr : mar_q;
    assign ri  = prog ? prog_we   : cw.ri;
    assign ro  = cw.ro;
    assign ai  = cw.ai;
    assign ao  = cw.ao;
    assign bi  = cw.bi;
    assign eo  = cw.eo;
    assign su  = cw.su;
    assign fi  = cw.fi;
    assign oi  = cw.oi;

    assign out_load = cw.oi;
    assign halted   = cw.hlt;
endmodule
