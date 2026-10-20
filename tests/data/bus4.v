// Barramento de 4 bits com três fontes tri-state em submódulos diferentes e um
// registrador que lê dele: na família RTL, cada fonte vira drivers de coletor
// aberto (TBUF) e cada linha ganha um pull-up (PULLUP).
module bus_src (input en, input [3:0] d, output [3:0] bus);
    assign bus = en ? d : 4'bz;
endmodule

module bus4 (
    input            clk,
    input      [1:0] sel,      // 0: ninguém no barramento; 1..3: a, b ou c
    input      [3:0] a, b, c,
    output     [3:0] bus,
    output reg [3:0] q         // último valor lido do barramento
);
    bus_src u_a (.en(sel == 2'd1), .d(a), .bus(bus));
    bus_src u_b (.en(sel == 2'd2), .d(b), .bus(bus));
    bus_src u_c (.en(sel == 2'd3), .d(c), .bus(bus));

    always @(posedge clk)
        if (sel != 2'd0) q <= bus;
endmodule
