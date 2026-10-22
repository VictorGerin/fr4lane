// serv_bufreg2.sv : Segundo registrador de buffer em SystemVerilog
module serv_bufreg2 (
   input  logic        i_clk,
   // Estado
   input  logic        i_en,
   input  logic        i_init,
   input  logic        i_cnt7,
   input  logic        i_cnt_done,
   input  logic        i_sh_right,
   input  logic [1:0]  i_lsb,
   input  logic [1:0]  i_bytecnt,
   output logic        o_sh_done,
   // Controle
   input  logic        i_op_b_sel,
   input  logic        i_shift_op,
   // Dados
   input  logic        i_rs2,
   input  logic        i_imm,
   output logic        o_op_b,
   output logic        o_q,
   // Externo
   output logic [31:0] o_dat,
   input  logic        i_load,
   input  logic [31:0] i_dat
);

   logic [7:0]  dhi;
   logic [23:0] dlo;
   logic        byte_valid;
   logic        shift_en;
   logic        cnt_en;
   logic [7:0]  cnt_next;
   logic [7:0]  dat_shamt;

   assign byte_valid = (!i_lsb[0] & !i_lsb[1])         |
                       (!i_bytecnt[0] & !i_bytecnt[1]) |
                       (!i_bytecnt[1] & !i_lsb[1])     |
                       (!i_bytecnt[1] & !i_lsb[0])     |
                       (!i_bytecnt[0] & !i_lsb[1]);

   assign o_op_b = i_op_b_sel ? i_rs2 : i_imm;

   assign shift_en = i_shift_op ? (i_en & i_init & (i_bytecnt == 2'b00)) : (i_en & byte_valid);
   assign cnt_en   = (i_shift_op & (!i_init | (i_cnt_done & i_sh_right)));

   assign cnt_next  = {o_op_b, dhi[7], dhi[5:0] - 6'd1};
   assign dat_shamt = cnt_en ? cnt_next : {o_op_b, dhi[7:1]};

   assign o_sh_done = dat_shamt[5];

   assign o_q = ((i_lsb == 2'd3) & o_dat[24]) |
                ((i_lsb == 2'd2) & o_dat[16]) |
                ((i_lsb == 2'd1) & o_dat[8])  |
                ((i_lsb == 2'd0) & o_dat[0]);

   assign o_dat = {dhi, dlo};

   always_ff @(posedge i_clk) begin
      if (shift_en | cnt_en | i_load)
         dhi <= i_load ? i_dat[31:24] : (dat_shamt & {2'b11, !(i_shift_op & i_cnt7 & !cnt_en), 5'b11111});
      if (shift_en | i_load)
         dlo <= i_load ? i_dat[23:0] : {dhi[0], dlo[23:1]};
   end

endmodule
