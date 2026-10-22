// serv_mem_if.sv : Interface de memória em SystemVerilog
module serv_mem_if (
   input  logic       i_clk,
   // Estado
   input  logic [1:0] i_bytecnt,
   input  logic [1:0] i_lsb,
   output logic       o_misalign,
   // Controle
   input  logic       i_signed,
   input  logic       i_word,
   input  logic       i_half,
   // Dados
   input  logic       i_bufreg2_q,
   output logic       o_rd,
   // Interface Wishbone
   output logic [3:0] o_wb_sel
);

   logic signbit;
   logic dat_valid;

   assign dat_valid = i_word | (i_bytecnt == 2'b00) | (i_half & !i_bytecnt[1]);

   assign o_rd = dat_valid ? i_bufreg2_q : (i_signed & signbit);

   assign o_wb_sel[3] = (i_lsb == 2'b11) | i_word | (i_half & i_lsb[1]);
   assign o_wb_sel[2] = (i_lsb == 2'b10) | i_word;
   assign o_wb_sel[1] = (i_lsb == 2'b01) | i_word | (i_half & !i_lsb[1]);
   assign o_wb_sel[0] = (i_lsb == 2'b00);

   always_ff @(posedge i_clk) begin
      if (dat_valid)
         signbit <= i_bufreg2_q;
   end

   assign o_misalign = 1'b0;

endmodule
