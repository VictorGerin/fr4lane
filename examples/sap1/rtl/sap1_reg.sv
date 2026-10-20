// Registrador com carga e reset assíncrono: A, B, saída, instrução, endereço
// da memória e flags.
module sap1_reg #(parameter int W = sap1_pkg::DW) (
    input  logic         clk,
    input  logic         rst_n,
    input  logic         load,
    input  logic [W-1:0] d,
    output logic [W-1:0] q
);
    always_ff @(posedge clk or negedge rst_n)
        if (!rst_n)    q <= '0;
        else if (load) q <= d;
endmodule
