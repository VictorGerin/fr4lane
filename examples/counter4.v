// Exemplo sequencial para o fr4lane: contador de 4 bits com enable e reset
// assíncrono (mapeia para DFFR) + registrador de atraso sem reset (DFF).
module counter4 (
    input            clk,
    input            rst_n,
    input            en,
    output reg [3:0] count,
    output reg       msb_d      // count[3] atrasado de um ciclo
);
    always @(posedge clk or negedge rst_n)
        if (!rst_n)  count <= 4'd0;
        else if (en) count <= count + 4'd1;

    always @(posedge clk)
        msb_d <= count[3];
endmodule
