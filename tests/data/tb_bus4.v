`timescale 1ns/1ps
// Com uma fonte habilitada, o barramento tem o valor dela e o registrador o lê.
// Sem fonte, o barramento fica solto (z no RTL, 1 pela terminação na placa) e o
// registrador guarda o valor.
module tb_bus4;
    reg        clk = 0;
    reg  [1:0] sel = 0;
    reg  [3:0] a = 0, b = 0, c = 0;
    wire [3:0] bus, q;
    reg  [3:0] want, held;
    integer    i, errors = 0;

    bus4 uut (.clk(clk), .sel(sel), .a(a), .b(b), .c(c), .bus(bus), .q(q));

    always #50 clk = ~clk;

    initial begin
        held = 4'bx;
        for (i = 0; i < 200; i = i + 1) begin
            @(negedge clk);
            sel = $random; a = $random; b = $random; c = $random;
            want = sel == 1 ? a : sel == 2 ? b : c;
            #20;
            if (sel != 0 && bus !== want) begin
                $display("[ERRO] ciclo %0d: sel=%0d bus=%b esperado=%b", i, sel, bus, want);
                errors = errors + 1;
            end
            // solto: z no RTL e no gate-level; 1111 na placa, pela terminação
            if (sel == 0 && bus !== 4'bzzzz && bus !== 4'b1111) begin
                $display("[ERRO] ciclo %0d: barramento solto = %b", i, bus);
                errors = errors + 1;
            end
            @(posedge clk); #5;
            if (sel != 0) held = want;
            if (i > 0 && held !== 4'bx && q !== held) begin
                $display("[ERRO] ciclo %0d: q=%b esperado=%b", i, q, held);
                errors = errors + 1;
            end
        end
        if (errors == 0) $display("--- bus4: barramento confere ---");
        else $display("[ERRO] bus4: %0d erro(s)", errors);
        $finish;
    end
endmodule
