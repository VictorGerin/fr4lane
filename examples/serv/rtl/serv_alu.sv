// serv_alu.sv : ALU bit-serial de 1 bit do SERV em SystemVerilog moderno
//
// Executa soma/subtração bit a bit, comparações (SLT, SLTU, BEQ/BNE/BLT/BGE)
// e operações booleanas (XOR, OR, AND).
module serv_alu (
   input  logic       clk,
   // Sinais de estado
   input  logic       i_en,
   input  logic       i_cnt0,
   output logic       o_cmp,
   // Sinais de controle
   input  logic       i_sub,
   input  logic [1:0] i_bool_op,
   input  logic       i_cmp_eq,
   input  logic       i_cmp_sig,
   input  logic [2:0] i_rd_sel,
   // Dados seriais
   input  logic       i_rs1,
   input  logic       i_op_b,
   input  logic       i_buf,
   output logic       o_rd
);

   logic result_add;
   logic result_slt;
   logic cmp_r;

   logic add_cy;
   logic add_cy_r;

   // Extensão de sinal para comparações com sinal
   logic rs1_sx;
   logic op_b_sx;
   logic add_b;
   logic result_lt;
   logic result_eq;
   logic result_bool;

   assign rs1_sx  = i_rs1 & i_cmp_sig;
   assign op_b_sx = i_op_b & i_cmp_sig;
   assign add_b   = i_op_b ^ i_sub;

   assign {add_cy, result_add} = i_rs1 + add_b + add_cy_r;

   assign result_lt = rs1_sx + ~op_b_sx + add_cy;
   assign result_eq = !result_add & (cmp_r | i_cnt0);

   assign o_cmp = i_cmp_eq ? result_eq : result_lt;

   // Operações lógicas:
   // 00: XOR, 01: 0 (usado em shifts para passar i_buf), 10: OR, 11: AND
   assign result_bool = ((i_rs1 ^ i_op_b) & ~i_bool_op[0]) | (i_bool_op[1] & i_op_b & i_rs1);

   assign result_slt = cmp_r & i_cnt0;

   assign o_rd = i_buf |
                 (i_rd_sel[0] & result_add) |
                 (i_rd_sel[1] & result_slt) |
                 (i_rd_sel[2] & result_bool);

   always_ff @(posedge clk) begin
      add_cy_r <= i_en ? add_cy : i_sub;
      if (i_en)
         cmp_r <= o_cmp;
   end

endmodule
