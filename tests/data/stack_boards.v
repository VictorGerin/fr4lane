// Pilha de teste do fr4lane-system: três placas no mesmo barramento de 4 bits
// (stack.v as liga). A de controle decodifica sel, também fala no barramento e
// leva a terminação; as duas de cartão são a mesma placa, sem terminação.
// cartão: põe d no barramento com en e guarda o que leu
module bus_src (input en, input [3:0] d, output [3:0] bus);
    assign bus = en ? d : 4'bz;
endmodule
module card (input clk, input en, input [3:0] d, inout [3:0] bus, output reg [3:0] q);
    bus_src u_s (.en(en), .d(d), .bus(bus));
    always @(posedge clk) q <= bus;
endmodule
// placa de controle: decodifica sel, também fala no barramento e leva a terminação
module ctl (input [1:0] sel, input [3:0] k, inout [3:0] bus, output en_a, en_b);
    assign en_a = sel == 2'd1;
    assign en_b = sel == 2'd2;
    bus_src u_k (.en(sel == 2'd3), .d(k), .bus(bus));
endmodule
