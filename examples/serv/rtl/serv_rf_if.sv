// serv_rf_if.sv : Interface do banco de registradores em SystemVerilog
module serv_rf_if #(
   parameter int WREG = 5
) (
   input  logic            i_cnt_en,
   output logic [WREG-1:0] o_wreg0,
   output logic [WREG-1:0] o_wreg1,
   output logic            o_wen0,
   output logic            o_wen1,
   output logic            o_wdata0,
   output logic            o_wdata1,
   output logic [WREG-1:0] o_rreg0,
   output logic [WREG-1:0] o_rreg1,
   input  logic            i_rdata0,
   input  logic            i_rdata1,
   // Escrita em RD
   input  logic            i_rd_wen,
   input  logic [WREG-1:0] i_rd_waddr,
   input  logic            i_ctrl_rd,
   input  logic            i_alu_rd,
   input  logic            i_rd_alu_en,
   input  logic            i_mem_rd,
   input  logic            i_rd_mem_en,
   // Leitura de RS1 e RS2
   input  logic [WREG-1:0] i_rs1_raddr,
   output logic            o_rs1,
   input  logic [WREG-1:0] i_rs2_raddr,
   output logic            o_rs2
);

   logic rd_wen;
   logic rd;

   assign rd_wen = i_rd_wen & (|i_rd_waddr);

   assign rd = (i_ctrl_rd) |
               (i_alu_rd & i_rd_alu_en) |
               (i_mem_rd & i_rd_mem_en);

   assign o_wdata0 = rd;
   assign o_wdata1 = 1'b0;

   assign o_wreg0 = i_rd_waddr;
   assign o_wreg1 = '0;

   assign o_wen0 = i_cnt_en & rd_wen;
   assign o_wen1 = 1'b0;

   assign o_rreg0 = i_rs1_raddr;
   assign o_rreg1 = i_rs2_raddr;

   assign o_rs1 = i_rdata0;
   assign o_rs2 = i_rdata1;

endmodule
