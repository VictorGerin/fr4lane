// Placa de RAM: um banco de 4 bytes. A mesma placa é montada 4 vezes; os
// jumpers bank[1:0] dizem qual banco ela é, e ela só grava e responde quando
// os 2 bits de cima do endereço (mar[3:2]) são o número dela.
module sap1_ram_board (
    // pilha
    input  logic                    clk,
    inout  tri   [sap1_pkg::DW-1:0] bus,
    input  logic [sap1_pkg::AW-1:0] mar,       // endereço
    input  logic                    ri,        // grava o barramento no endereço
    input  logic                    ro,        // põe o byte do endereço no barramento
    // jumpers
    input  logic [1:0]              bank
);
    localparam int N = 4;                      // bytes por placa

    logic                    mine;
    logic [sap1_pkg::DW-1:0] q [N];

    assign mine = (mar[3:2] == bank);

    for (genvar i = 0; i < N; i++) begin : g_byte
        sap1_byte u_byte (.clk, .we(ri && mine && mar[1:0] == 2'(i)), .d(bus), .q(q[i]));
    end

    sap1_bus_driver u_drv (.en(ro && mine), .d(q[mar[1:0]]), .bus);
endmodule
