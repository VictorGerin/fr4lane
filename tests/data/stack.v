// Sistema de teste: só liga as placas de stack_boards.v (um arquivo só para ele).
module stack (input clk, input [1:0] sel, input [3:0] a, b, k, output [3:0] qa, qb, inout [3:0] bus);
    wire en_a, en_b;
    ctl  u_ctl (.sel(sel), .k(k), .bus(bus), .en_a(en_a), .en_b(en_b));
    card u_a   (.clk(clk), .en(en_a), .d(a), .bus(bus), .q(qa));
    card u_b   (.clk(clk), .en(en_b), .d(b), .bus(bus), .q(qb));
endmodule
