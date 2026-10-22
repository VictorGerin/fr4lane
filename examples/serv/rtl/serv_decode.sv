// serv_decode.sv : Decodificador de instrução em SystemVerilog
module serv_decode (
   input  logic        clk,
   input  logic [31:2] i_wb_rdt,
   input  logic        i_wb_en,
   // Para state
   (* keep *) output logic        o_sh_right,
   output logic        o_bne_or_bge,
   output logic        o_cond_branch,
   output logic        o_e_op,
   output logic        o_ebreak,
   output logic        o_branch_op,
   output logic        o_shift_op,
   output logic        o_rd_op,
   output logic        o_two_stage_op,
   output logic        o_dbus_en,
   // Para bufreg
   output logic        o_bufreg_rs1_en,
   output logic        o_bufreg_imm_en,
   output logic        o_bufreg_clr_lsb,
   output logic        o_bufreg_sh_signed,
   // Para ctrl
   output logic        o_ctrl_jal_or_jalr,
   output logic        o_ctrl_utype,
   output logic        o_ctrl_pc_rel,
   output logic        o_ctrl_mret,
   // Para alu
   output logic        o_alu_sub,
   output logic [1:0]  o_alu_bool_op,
   output logic        o_alu_cmp_eq,
   output logic        o_alu_cmp_sig,
   (* keep *) output logic [2:0]  o_alu_rd_sel,
   // Para mem IF
   output logic        o_mem_signed,
   output logic        o_mem_word,
   output logic        o_mem_half,
   output logic        o_mem_cmd,
   // Para immdec
   output logic [3:0]  o_immdec_ctrl,
   output logic [3:0]  o_immdec_en,
   output logic        o_op_b_source,
   // Para RF IF
   output logic        o_rd_mem_en,
   output logic        o_rd_alu_en
);

   logic [4:0] opcode;
   logic [2:0] funct3;
   logic       op20;
   logic       op21;
   logic       imm30;
   logic       reg_sh_right;

   logic       co_two_stage_op;
   logic       co_shift_op;
   logic       co_branch_op;
   logic       co_dbus_en;
   logic       co_mem_word;
   logic       co_rd_alu_en;
   logic       co_rd_mem_en;
   logic       co_bufreg_rs1_en;
   logic       co_bufreg_imm_en;
   logic       co_bufreg_clr_lsb;
   logic       co_cond_branch;
   logic       co_ctrl_utype;
   logic       co_ctrl_jal_or_jalr;
   logic       co_ctrl_pc_rel;
   logic       co_rd_op;
   (* keep *) logic       co_sh_right;
   logic       co_bne_or_bge;
   logic       co_ebreak;
   logic       co_ctrl_mret;
   logic       co_e_op;
   logic       co_bufreg_sh_signed;
   logic       co_alu_sub;
   logic       co_alu_cmp_eq;
   logic       co_alu_cmp_sig;
   logic       co_mem_cmd;
   logic       co_mem_signed;
   logic       co_mem_half;
   logic [1:0] co_alu_bool_op;
   logic [3:0] co_immdec_ctrl;
   logic [3:0] co_immdec_en;
   (* keep *) logic [2:0] co_alu_rd_sel;
   logic       co_op_b_source;

   assign co_two_stage_op = ~opcode[2] | (funct3[0] & ~funct3[1] & ~opcode[0] & ~opcode[4]) |
                            (funct3[1] & ~funct3[2] & ~opcode[0] & ~opcode[4]);
   assign co_shift_op     = opcode[2] & ~funct3[1];
   assign co_branch_op    = opcode[4];
   assign co_dbus_en      = ~opcode[2] & ~opcode[4];
   assign co_mem_word     = funct3[1];
   assign co_rd_alu_en    = !opcode[0] & opcode[2] & !opcode[4];
   assign co_rd_mem_en    = !opcode[2] & !opcode[0];

   assign co_bufreg_rs1_en  = !opcode[4] | (!opcode[1] & opcode[0]);
   assign co_bufreg_imm_en  = !opcode[2];
   assign co_bufreg_clr_lsb = opcode[4] & ((opcode[1:0] == 2'b00) | (opcode[1:0] == 2'b11));

   assign co_cond_branch      = !opcode[0];
   assign co_ctrl_utype       = !opcode[4] & opcode[2] & opcode[0];
   assign co_ctrl_jal_or_jalr = opcode[4] & opcode[0];

   assign co_ctrl_pc_rel = (opcode[2:0] == 3'b000)  |
                           (opcode[1:0] == 2'b11)   |
                           (opcode[4] & opcode[2] & op20) |
                           (opcode[4:3] == 2'b00);

   assign co_rd_op = (opcode[2] |
                     (!opcode[2] & opcode[4] & opcode[0]) |
                     (!opcode[2] & !opcode[3] & !opcode[0]));

   assign co_sh_right   = ~reg_sh_right;
   assign co_bne_or_bge = funct3[0];
   assign co_ebreak     = op20;
   assign co_ctrl_mret  = opcode[4] & opcode[2] & op21 & !(|funct3);
   assign co_e_op       = opcode[4] & opcode[2] & !op21 & !(|funct3);

   assign co_bufreg_sh_signed = imm30;
   assign co_alu_sub = funct3[1] | funct3[0] | (opcode[3] & imm30) | opcode[4];

   assign co_alu_cmp_eq  = (funct3[2:1] == 2'b00);
   assign co_alu_cmp_sig = ~((funct3[0] & funct3[1]) | (funct3[1] & funct3[2]));

   assign co_mem_cmd    = opcode[3];
   assign co_mem_signed = ~funct3[2];
   assign co_mem_half   = funct3[0];

   assign co_alu_bool_op = funct3[1:0];

   assign co_immdec_ctrl[0] = (opcode[3:0] == 4'b1000);
   assign co_immdec_ctrl[1] = (opcode[1:0] == 2'b00) | (opcode[2:1] == 2'b00);
   assign co_immdec_ctrl[2] = opcode[4] & !opcode[0];
   assign co_immdec_ctrl[3] = opcode[4];

   assign co_immdec_en[3] = opcode[4] | opcode[3] | opcode[2] | !opcode[0];
   assign co_immdec_en[2] = (opcode[4] & opcode[2]) | !opcode[3] | opcode[0];
   assign co_immdec_en[1] = (opcode[2:1] == 2'b01) | (opcode[2] & opcode[0]);
   assign co_immdec_en[0] = ~co_rd_op;

   assign co_alu_rd_sel[0] = (funct3 == 3'b000);
   assign co_alu_rd_sel[1] = (funct3[2:1] == 2'b01);
   assign co_alu_rd_sel[2] = funct3[2];

   assign co_op_b_source = opcode[3];

   always_ff @(posedge clk) begin
      if (i_wb_en) begin
         funct3       <= i_wb_rdt[14:12];
         reg_sh_right <= ~i_wb_rdt[14];
         imm30        <= i_wb_rdt[30];
         opcode <= i_wb_rdt[6:2];
         op20   <= i_wb_rdt[20];
         op21   <= i_wb_rdt[21];
      end
   end

   always_comb begin
      o_sh_right         = co_sh_right;
      o_bne_or_bge       = co_bne_or_bge;
      o_cond_branch      = co_cond_branch;
      o_dbus_en          = co_dbus_en;
      o_two_stage_op     = co_two_stage_op;
      o_e_op             = co_e_op;
      o_ebreak           = co_ebreak;
      o_branch_op        = co_branch_op;
      o_shift_op         = co_shift_op;
      o_rd_op            = co_rd_op;
      o_bufreg_rs1_en    = co_bufreg_rs1_en;
      o_bufreg_imm_en    = co_bufreg_imm_en;
      o_bufreg_clr_lsb   = co_bufreg_clr_lsb;
      o_bufreg_sh_signed = co_bufreg_sh_signed;
      o_ctrl_jal_or_jalr = co_ctrl_jal_or_jalr;
      o_ctrl_utype       = co_ctrl_utype;
      o_ctrl_pc_rel      = co_ctrl_pc_rel;
      o_ctrl_mret        = co_ctrl_mret;
      o_alu_sub          = co_alu_sub;
      o_alu_bool_op      = co_alu_bool_op;
      o_alu_cmp_eq       = co_alu_cmp_eq;
      o_alu_cmp_sig      = co_alu_cmp_sig;
      o_alu_rd_sel       = co_alu_rd_sel;
      o_mem_signed       = co_mem_signed;
      o_mem_word         = co_mem_word;
      o_mem_half         = co_mem_half;
      o_mem_cmd          = co_mem_cmd;
      o_immdec_ctrl      = co_immdec_ctrl;
      o_immdec_en        = co_immdec_en;
      o_op_b_source      = co_op_b_source;
      o_rd_alu_en        = co_rd_alu_en;
      o_rd_mem_en        = co_rd_mem_en;
   end

endmodule
