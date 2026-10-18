`timescale 1ns/1ps
module tb_hier8;
    reg [7:0] a, b; reg ci;
    wire [7:0] s; wire co;
    integer k, fails;
    hier8 dut (.a(a), .b(b), .ci(ci), .s(s), .co(co));
    initial begin
        fails = 0;
        for (k = 0; k < 300; k = k + 1) begin
            a = $random; b = $random; ci = $random; #20;
            if ({co, s} !== a + b + ci) begin
                fails = fails + 1;
                $display("[ERRO] %0d + %0d + %0d = %0d, esperado %0d", a, b, ci, {co, s}, a + b + ci);
            end
        end
        if (fails == 0) $display("PASS"); else $display("FAILED %0d", fails);
        $finish;
    end
endmodule
