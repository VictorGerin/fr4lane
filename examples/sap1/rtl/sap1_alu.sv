// ALU: A + B ou A - B (complemento de 2), com carry e zero.
// Na subtração, carry = 1 quando não há empréstimo (A >= B).
module sap1_alu (
    input  logic [sap1_pkg::DW-1:0] a,
    input  logic [sap1_pkg::DW-1:0] b,
    input  logic                    sub,
    output logic [sap1_pkg::DW-1:0] y,
    output logic                    carry,
    output logic                    zero
);
    // A concatenação fixa ~b em 8 bits: sem ela, b seria estendido para os 9
    // bits da soma antes da inversão, e o carry sairia errado.
    always_comb begin
        {carry, y} = {1'b0, a} + {1'b0, sub ? ~b : b} + sub;
        zero       = (y == '0);
    end
endmodule
