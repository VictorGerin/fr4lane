// serv_ctrl.sv : Controle do Program Counter (PC) em SystemVerilog
module serv_ctrl
  #(
    parameter int        PC_WIDTH = 32,
    parameter bit [31:0] RESET_PC = 32'd0
  )
  (
   input  logic        clk,
   input  logic        i_rst,
   // Estado
   input  logic        i_pc_en,
   input  logic        i_cnt12to31,
   input  logic        i_cnt0,
   input  logic        i_cnt1,
   input  logic        i_cnt2,
   // Controle
   input  logic        i_jump,
   input  logic        i_jal_or_jalr,
   input  logic        i_utype,
   input  logic        i_pc_rel,
   // Dados
   input  logic        i_imm,
   input  logic        i_buf,
   output logic        o_rd,
   output logic        o_bad_pc,
   // Barramento de instrução
   output logic [31:0] o_ibus_adr
  );

   logic [PC_WIDTH-1:0] pc_reg;
   logic [4:0]          shift_cnt;

   logic pc_plus_4;
   logic pc_plus_4_cy;
   logic pc_plus_4_cy_r;

   logic pc_plus_offset;
   logic pc_plus_offset_cy;
   logic pc_plus_offset_cy_r;

   logic pc_plus_offset_aligned;
   logic plus_4;
   logic pc;
   logic new_pc;
   logic offset_a;
   logic offset_b;

   assign plus_4 = i_cnt2;
   assign pc     = (shift_cnt < PC_WIDTH) ? pc_reg[0] : 1'b0;
   assign new_pc = i_jump ? pc_plus_offset_aligned : pc_plus_4;

   assign offset_a = i_pc_rel & pc;
   assign offset_b = i_utype ? (i_imm & i_cnt12to31) : i_buf;

   assign o_bad_pc = pc_plus_offset_aligned;

   assign {pc_plus_4_cy, pc_plus_4}           = pc + plus_4 + pc_plus_4_cy_r;
   assign {pc_plus_offset_cy, pc_plus_offset} = offset_a + offset_b + pc_plus_offset_cy_r;

   assign pc_plus_offset_aligned = pc_plus_offset & !i_cnt0;

   assign o_rd = (i_utype & pc_plus_offset_aligned) | (pc_plus_4 & i_jal_or_jalr);

   always_ff @(posedge clk) begin
      pc_plus_4_cy_r      <= i_pc_en & pc_plus_4_cy;
      pc_plus_offset_cy_r <= i_pc_en & pc_plus_offset_cy;

      if (i_rst) begin
         pc_reg    <= RESET_PC[PC_WIDTH-1:0];
         shift_cnt <= 5'd0;
      end else if (i_pc_en) begin
         shift_cnt <= (shift_cnt == 5'd31) ? 5'd0 : shift_cnt + 5'd1;
         if (shift_cnt < PC_WIDTH)
            pc_reg <= {new_pc, pc_reg[PC_WIDTH-1:1]};
      end
   end

   if (PC_WIDTH == 32) begin : gen_pc32
      assign o_ibus_adr = pc_reg;
   end else begin : gen_pc_narrow
      assign o_ibus_adr = { {(32-PC_WIDTH){1'b0}}, pc_reg };
   end

endmodule
