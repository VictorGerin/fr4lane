// Placa da ALU: registradores A e B, ALU de soma e subtração, flags de carry
// e zero e o registrador de saída (display).
module sap1_alu_board (
    // pilha
    input  logic                    clk,
    input  logic                    rst_n,
    inout  tri   [sap1_pkg::DW-1:0] bus,
    input  logic                    ai,        // carrega A
    input  logic                    ao,        // A no barramento
    input  logic                    bi,        // carrega B
    input  logic                    eo,        // ALU no barramento
    input  logic                    su,        // ALU subtrai
    input  logic                    fi,        // carrega as flags
    input  logic                    oi,        // carrega a saída
    output logic                    cf,        // flags, para a placa de controle
    output logic                    zf,
    // display
    output logic [sap1_pkg::DW-1:0] out
);
    logic [sap1_pkg::DW-1:0] a, b, alu;
    logic                    carry, zero;

    sap1_reg          u_a   (.clk, .rst_n, .load(ai), .d(bus), .q(a));
    sap1_reg          u_b   (.clk, .rst_n, .load(bi), .d(bus), .q(b));
    sap1_reg          u_out (.clk, .rst_n, .load(oi), .d(bus), .q(out));
    sap1_reg #(.W(2)) u_flg (.clk, .rst_n, .load(fi), .d({carry, zero}), .q({cf, zf}));

    sap1_alu u_alu (.a, .b, .sub(su), .y(alu), .carry, .zero);

    sap1_bus_driver u_a_drv   (.en(ao), .d(a),   .bus);
    sap1_bus_driver u_alu_drv (.en(eo), .d(alu), .bus);
endmodule
