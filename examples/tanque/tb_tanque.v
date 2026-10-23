`timescale 1ns/1ps
module tb_tanque;
    localparam [1:0] VAZIO      = 2'b00,
                     ENCHENDO   = 2'b01,
                     CHEIO      = 2'b10,
                     ESVAZIANDO = 2'b11;

    reg     clk = 0, rst_n = 0;
    reg     nivel_baixo = 0, nivel_alto = 0;
    wire    motor;
    integer ciclo;

    tanque uut (
        .clk(clk),
        .rst_n(rst_n),
        .nivel_baixo(nivel_baixo),
        .nivel_alto(nivel_alto),
        .motor(motor)
    );

    always #10 clk = ~clk;

    task check(input exp_motor, input [127:0] etapa);
        begin
            if (motor !== exp_motor) begin
                $display("[ERRO] %0s: motor=%b (esperado %b)",
                         etapa, motor, exp_motor);
                $finish(1);
            end
        end
    endtask

    initial begin
        #25;
        // No reset inicial (VAZIO), o motor deve estar ligado para encher
        check(1'b1, "reset inicial (tanque vazio)");
        rst_n = 1;

        for (ciclo = 0; ciclo < 3; ciclo = ciclo + 1) begin
            // 1. VAZIO -> ENCHENDO (sensor baixo em 0): motor continua ligado
            @(negedge clk); nivel_baixo = 0; nivel_alto = 0;
            @(posedge clk); #2;
            check(1'b1, "iniciou enchimento (motor ligado)");

            // 2. Continua ENCHENDO quando passa pelo sensor de nível baixo: motor ligado
            @(negedge clk); nivel_baixo = 1; nivel_alto = 0;
            @(posedge clk); #2;
            check(1'b1, "meio tanque subindo (motor ligado)");

            // 3. Atingiu o topo (nivel_alto = 1) -> CHEIO (desliga o motor)
            @(negedge clk); nivel_baixo = 1; nivel_alto = 1;
            @(posedge clk); #2;
            check(1'b0, "tanque cheio (motor desligado)");

            // Permanece CHEIO enquanto nivel_alto = 1: motor desligado
            @(negedge clk);
            @(posedge clk); #2;
            check(1'b0, "mantem cheio (motor desligado)");

            // 4. Nível começou a descer (nivel_alto = 0, nivel_baixo = 1) -> ESVAZIANDO: motor desligado
            @(negedge clk); nivel_baixo = 1; nivel_alto = 0;
            @(posedge clk); #2;
            check(1'b0, "esvaziando meio tanque (motor desligado)");

            // Continua ESVAZIANDO enquanto ainda há água acima de nivel_baixo: motor desligado
            @(negedge clk);
            @(posedge clk); #2;
            check(1'b0, "continua esvaziando (motor desligado)");

            // 5. Esvaziou abaixo do sensor inferior (nivel_baixo = 0) -> VAZIO: motor religa
            @(negedge clk); nivel_baixo = 0; nivel_alto = 0;
            @(posedge clk); #2;
            check(1'b1, "voltou para vazio (motor religa)");
        end

        $display("--- tanque: todos os ciclos da maquina de estados conferem ---");
        $finish(0);
    end
endmodule
