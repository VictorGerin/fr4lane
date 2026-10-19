// Exemplo com vários módulos para o pcbflow: um somador de 8 bits feito de
// dois add4 (cada um com 4 somadores completos), um contador e um registrador.
// Os blocos não compartilham fios: cada um ganha a sua área na placa, o que
// deixa o floorplan e os macros fáceis de ver.
module fa (input a, b, ci, output s, co);
    assign s  = a ^ b ^ ci;
    assign co = (a & b) | (ci & (a ^ b));
endmodule

module add4 (input [3:0] a, b, input ci, output [3:0] s, output co);
    wire c1, c2, c3;
    fa f0 (.a(a[0]), .b(b[0]), .ci(ci), .s(s[0]), .co(c1));
    fa f1 (.a(a[1]), .b(b[1]), .ci(c1), .s(s[1]), .co(c2));
    fa f2 (.a(a[2]), .b(b[2]), .ci(c2), .s(s[2]), .co(c3));
    fa f3 (.a(a[3]), .b(b[3]), .ci(c3), .s(s[3]), .co(co));
endmodule

module add8 (input [7:0] a, b, input ci, output [7:0] s, output co);
    wire c4;
    add4 lo (.a(a[3:0]), .b(b[3:0]), .ci(ci), .s(s[3:0]), .co(c4));
    add4 hi (.a(a[7:4]), .b(b[7:4]), .ci(c4), .s(s[7:4]), .co(co));
endmodule

module counter4 (input clk, rst_n, en, output reg [3:0] count);
    always @(posedge clk or negedge rst_n)
        if (!rst_n)  count <= 4'd0;
        else if (en) count <= count + 4'd1;
endmodule

module reg4 (input clk, we, input [3:0] d, output reg [3:0] q);
    always @(posedge clk)
        if (we) q <= d;
endmodule

module demo_top (
    input  [7:0] a, b,
    input        ci,
    output [7:0] s,
    output       co,
    input        clk, rst_n, en, we,
    input  [3:0] d,
    output [3:0] count,
    output [3:0] q
);
    add8     u_add (.a(a), .b(b), .ci(ci), .s(s), .co(co));
    counter4 u_cnt (.clk(clk), .rst_n(rst_n), .en(en), .count(count));
    reg4     u_reg (.clk(clk), .we(we), .d(d), .q(q));
endmodule
