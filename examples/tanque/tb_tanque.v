`timescale 1ns/1ps
module tb_tanque;
    localparam [1:0] VAZIO      = 2'b00,
                     ENCHENDO   = 2'b01,
                     CHEIO      = 2'b10,
                     ESVAZIANDO = 2'b11;

    reg        clk = 0, rst_n = 0;
    reg        nivel_baixo = 0, nivel_alto = 0;
    wire [1:0] estado;
    wire       bomba;
    integer    ciclo;

    tanque uut (
        .clk(clk),
        .rst_n(rst_n),
        .nivel_baixo(nivel_baixo),
        .nivel_alto(nivel_alto),
        .estado(estado),
        .bomba(bomba)
    );

    always #10 clk = ~clk;

    task check(input [1:0] exp_est, input exp_bomba, input [127:0] etapa);
        begin
            if (estado !== exp_est || bomba !== exp_bomba) begin
                $display("[ERRO] %0s: estado=%b (esp %b), bomba=%b (esp %b)",
                         etapa, estado, exp_est, bomba, exp_bomba);
                $finish(1);
            end
        end
    endtask

    initial begin
        #25;
        check(VAZIO, 1'b0, "reset inicial");
        rst_n = 1;

        for (ciclo = 0; ciclo < 3; ciclo = ciclo + 1) begin
            // 1. VAZIO -> ENCHENDO (sensor baixo em 0)
            @(negedge clk); nivel_baixo = 0; nivel_alto = 0;
            @(posedge clk); #2;
            check(ENCHENDO, 1'b1, "iniciou enchimento");

            // 2. Continua ENCHENDO quando passa pelo sensor de nível baixo
            @(negedge clk); nivel_baixo = 1; nivel_alto = 0;
            @(posedge clk); #2;
            check(ENCHENDO, 1'b1, "meio tanque subindo");

            // 3. Atingiu o topo (nivel_alto = 1) -> CHEIO (desliga a bomba)
            @(negedge clk); nivel_baixo = 1; nivel_alto = 1;
            @(posedge clk); #2;
            check(CHEIO, 1'b0, "tanque cheio");

            // Permanece CHEIO enquanto nivel_alto = 1
            @(negedge clk);
            @(posedge clk); #2;
            check(CHEIO, 1'b0, "mantem cheio");

            // 4. Nível começou a descer (nivel_alto = 0, nivel_baixo = 1) -> ESVAZIANDO
            @(negedge clk); nivel_baixo = 1; nivel_alto = 0;
            @(posedge clk); #2;
            check(ESVAZIANDO, 1'b0, "esvaziando meio tanque");

            // Continua ESVAZIANDO enquanto ainda há água acima de nivel_baixo
            @(negedge clk);
            @(posedge clk); #2;
            check(ESVAZIANDO, 1'b0, "continua esvaziando");

            // 5. Esvaziou abaixo do sensor inferior (nivel_baixo = 0) -> VAZIO
            @(negedge clk); nivel_baixo = 0; nivel_alto = 0;
            @(posedge clk); #2;
            check(VAZIO, 1'b0, "voltou para vazio");
        end

        $display("--- tanque: todos os ciclos da maquina de estados conferem ---");
        $finish(0);
    end
endmodule
