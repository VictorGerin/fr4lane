// Um byte da RAM: flip-flops com escrita, sem reset. É o bloco repetido da
// RAM, candidato natural a macro no pcbflow (--macro sap1_byte).
module sap1_byte (
    input  logic                    clk,
    input  logic                    we,
    input  logic [sap1_pkg::DW-1:0] d,
    output logic [sap1_pkg::DW-1:0] q
);
    always_ff @(posedge clk)
        if (we) q <= d;
endmodule
