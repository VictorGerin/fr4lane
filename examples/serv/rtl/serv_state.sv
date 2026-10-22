// serv_state.sv : Máquina de estados principal do SERV em SystemVerilog
module serv_state (
   input  logic       i_clk,
   input  logic       i_rst,
   // Sinais de estado
   input  logic       i_new_irq,
   input  logic       i_alu_cmp,
   output logic       o_init,
   output logic       o_cnt_en,
   output logic       o_cnt0to3,
   output logic       o_cnt12to31,
   output logic       o_cnt0,
   output logic       o_cnt1,
   output logic       o_cnt2,
   output logic       o_cnt3,
   output logic       o_cnt7,
   output logic       o_cnt11,
   output logic       o_cnt12,
   output logic       o_cnt_done,
   output logic       o_bufreg_en,
   output logic       o_ctrl_pc_en,
   output logic       o_ctrl_jump,
   output logic       o_ctrl_trap,
   input  logic       i_ctrl_misalign,
   input  logic       i_sh_done,
   output logic [1:0] o_mem_bytecnt,
   input  logic       i_mem_misalign,
   // Sinais de controle
   input  logic       i_bne_or_bge,
   input  logic       i_cond_branch,
   input  logic       i_dbus_en,
   input  logic       i_two_stage_op,
   input  logic       i_branch_op,
   input  logic       i_shift_op,
   input  logic       i_sh_right,
   input  logic       i_alu_rd_sel1,
   input  logic       i_rd_alu_en,
   input  logic       i_e_op,
   input  logic       i_rd_op,
   // Barramentos externos
   output logic       o_dbus_cyc,
   input  logic       i_dbus_ack,
   output logic       o_ibus_cyc,
   input  logic       i_ibus_ack,
   // Interface do RF
   output logic       o_rf_rreq,
   output logic       o_rf_wreq,
   input  logic       i_rf_ready,
   output logic       o_rf_rd_en
);

   logic       init_done;
   logic [4:2] o_cnt;
   logic [3:0] cnt_r;
   logic       ibus_cyc;
   logic       take_branch;
   logic       last_init;
   logic [3:0] cnt_lsb;

   assign o_ctrl_pc_en  = o_cnt_en & !o_init;
   assign o_mem_bytecnt = o_cnt[4:3];

   assign o_cnt0to3   = (o_cnt[4:2] == 3'd0);
   assign o_cnt12to31 = (o_cnt[4] | (o_cnt[3:2] == 2'b11));
   assign o_cnt0      = (o_cnt[4:2] == 3'd0) & cnt_r[0];
   assign o_cnt1      = (o_cnt[4:2] == 3'd0) & cnt_r[1];
   assign o_cnt2      = (o_cnt[4:2] == 3'd0) & cnt_r[2];
   assign o_cnt3      = (o_cnt[4:2] == 3'd0) & cnt_r[3];
   assign o_cnt7      = (o_cnt[4:2] == 3'd1) & cnt_r[3];
   assign o_cnt11     = (o_cnt[4:2] == 3'd2) & cnt_r[3];
   assign o_cnt12     = (o_cnt[4:2] == 3'd3) & cnt_r[0];

   assign take_branch = i_branch_op & (!i_cond_branch | (i_alu_cmp ^ i_bne_or_bge));
   assign last_init   = o_cnt_done & o_init;

   assign o_rf_wreq = (i_shift_op & (i_sh_right ? (i_sh_done & (last_init | (!o_cnt_en & init_done))) : last_init)) |
                      i_dbus_ack |
                      (i_branch_op & last_init) |
                      (i_rd_alu_en & i_alu_rd_sel1 & last_init);

   assign o_dbus_cyc  = !o_cnt_en & init_done & i_dbus_en;
   assign o_rf_rreq   = i_ibus_ack;
   assign o_rf_rd_en  = i_rd_op & !o_init;

   assign o_bufreg_en = (o_cnt_en & (o_init | (i_branch_op & i_two_stage_op))) |
                        (i_shift_op & init_done & (i_sh_right | i_sh_done));

   assign o_ibus_cyc  = ibus_cyc & !i_rst;
   assign o_init      = i_two_stage_op & !init_done;
   assign o_cnt_done  = (o_cnt[4:2] == 3'b111) & cnt_r[3];

   always_ff @(posedge i_clk) begin
      if (i_ibus_ack | o_cnt_done | i_rst)
         ibus_cyc <= o_ctrl_pc_en | i_rst;

      if (o_cnt_done) begin
         init_done   <= o_init & !init_done;
         o_ctrl_jump <= o_init & take_branch;
      end

      if (i_rst) begin
         init_done   <= 1'b0;
         o_ctrl_jump <= 1'b0;
      end
   end

   always_ff @(posedge i_clk) begin
      o_cnt   <= o_cnt + {2'd0, cnt_r[3]};
      cnt_lsb <= {cnt_lsb[2:0], (cnt_lsb[3] & !o_cnt_done) | i_rf_ready};
      if (i_rst) begin
         o_cnt   <= 3'd0;
         cnt_lsb <= 4'b0000;
      end
   end

   assign cnt_r    = cnt_lsb;
   assign o_cnt_en = |cnt_lsb;

   assign o_ctrl_trap = 1'b0;

endmodule
