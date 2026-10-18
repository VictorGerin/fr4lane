// Fan-out alto para os testes de buffers: o clock e a entrada d alimentam 40
// cargas cada, e a net interna t (paridade de 4 bits) também alimenta 40
module fan40 (input clk, input d, input [39:0] x, output [39:0] q);
    reg [39:0] r;
    wire t = ^x[3:0];
    always @(posedge clk) r <= x & {40{d}};
    assign q = r ^ {40{t}};
endmodule
