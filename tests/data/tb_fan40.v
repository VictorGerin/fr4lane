`timescale 1ns/1ps
module tb_fan40;
    reg clk = 0, d = 0;
    reg [39:0] x = 0, r_m = 0;
    wire [39:0] q;
    integer k, fails = 0;
    fan40 dut (.clk(clk), .d(d), .x(x), .q(q));
    initial begin
        for (k = 0; k < 120; k = k + 1) begin
            x = {$random, $random}; d = $random;
            #20 clk = 1; r_m = x & {40{d}};
            #20 clk = 0;
            x = {$random, $random};                 // muda x depois da borda: q usa o r guardado
            #20;
            if (q !== (r_m ^ {40{^x[3:0]}})) begin
                fails = fails + 1;
                $display("[ERRO] k=%0d q=%h esperado=%h", k, q, r_m ^ {40{^x[3:0]}});
            end
        end
        if (fails == 0) $display("PASS"); else $display("FAILED %0d", fails);
        $finish;
    end
endmodule
