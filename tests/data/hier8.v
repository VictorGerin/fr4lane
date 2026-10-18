// Somador de 8 bits hierárquico para os testes do fluxo com macros:
// hier8 = 2 x add4, add4 = 4 x fa
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

module hier8 (input [7:0] a, b, input ci, output [7:0] s, output co);
    wire c4;
    add4 lo (.a(a[3:0]), .b(b[3:0]), .ci(ci), .s(s[3:0]), .co(c4));
    add4 hi (.a(a[7:4]), .b(b[7:4]), .ci(c4), .s(s[7:4]), .co(co));
endmodule
