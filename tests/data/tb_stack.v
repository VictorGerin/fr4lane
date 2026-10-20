`timescale 1ns/1ps
// Quem a placa de controle põe no barramento chega aos dois cartões.
module tb_stack;
    reg clk = 0; reg [1:0] sel = 0; reg [3:0] a = 0, b = 0, k = 0;
    wire [3:0] qa, qb, bus; reg [3:0] want; integer i, errors = 0;
    stack uut (.clk(clk), .sel(sel), .a(a), .b(b), .k(k), .qa(qa), .qb(qb), .bus(bus));
    always #50 clk = ~clk;
    initial begin
        for (i = 0; i < 100; i = i + 1) begin
            @(negedge clk); sel = $random; a = $random; b = $random; k = $random;
            want = sel == 1 ? a : sel == 2 ? b : sel == 3 ? k : 4'b1111;
            @(posedge clk); #5;
            if (sel != 0 && (qa !== want || qb !== want)) begin
                $display("[ERRO] ciclo %0d: sel=%0d qa=%b qb=%b esperado=%b", i, sel, qa, qb, want); errors = errors + 1; end
        end
        if (errors == 0) $display("--- pilha confere ---");
        $finish;
    end
endmodule
