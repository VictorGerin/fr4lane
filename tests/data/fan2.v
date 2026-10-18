// Duas instâncias do fan40 (macro): o clock e d alimentam 80 cargas no topo,
// e cada instância tem as suas nets internas com fan-out alto
module fan2 (input clk, input d, input [39:0] x, y, output [39:0] q, p);
    fan40 u0 (.clk(clk), .d(d), .x(x), .q(q));
    fan40 u1 (.clk(clk), .d(d), .x(y), .q(p));
endmodule
