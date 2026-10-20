// Contador de programa: incrementa com CE e salta com J.
module sap1_pc (
    input  logic                    clk,
    input  logic                    rst_n,
    input  logic                    inc,
    input  logic                    jump,
    input  logic [sap1_pkg::AW-1:0] d,
    output logic [sap1_pkg::AW-1:0] q
);
    always_ff @(posedge clk or negedge rst_n)
        if (!rst_n)    q <= '0;
        else if (jump) q <= d;
        else if (inc)  q <= q + 1'b1;
endmodule
