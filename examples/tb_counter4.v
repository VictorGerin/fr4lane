`timescale 1ns/1ps
module tb_counter4;
    reg clk = 0, rst_n = 0, en = 0;
    wire [3:0] count;
    wire msb_d;
    reg  [3:0] model;
    reg  prev_msb;
    integer i;

    counter4 uut (.clk(clk), .rst_n(rst_n), .en(en), .count(count), .msb_d(msb_d));

    always #10 clk = ~clk;

    initial begin
        #25;
        if (count !== 4'd0) begin $display("[ERRO] reset: count=%b", count); $finish(1); end
        rst_n = 1;
        model = 0;
        for (i = 0; i < 40; i = i + 1) begin
            @(negedge clk);
            en = (i % 5) != 3;           // alguns ciclos sem enable
            prev_msb = model[3];
            @(posedge clk); #2;
            if (en) model = model + 1;
            if (count !== model) begin
                $display("[ERRO] ciclo %0d: count=%b esperado=%b", i, count, model);
                $finish(1);
            end
            if (i > 0 && msb_d !== prev_msb) begin
                $display("[ERRO] ciclo %0d: msb_d=%b esperado=%b", i, msb_d, prev_msb);
                $finish(1);
            end
        end
        rst_n = 0; #1;
        if (count !== 4'd0) begin $display("[ERRO] reset assincrono falhou"); $finish(1); end
        $display("--- counter4: todos os ciclos conferem ---");
        $finish(0);
    end
endmodule
