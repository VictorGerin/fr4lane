// tb_serv_system.sv : testbench do sistema multi-placa do SERV na pilha do fr4lane
//
// Modela fora da placa a memória de programa/dados (Wishbone, ack em 1 ciclo)
// e a SRAM de 512 x 2 bits do banco de registradores, e roda o programa que
// calcula 40 + 2 = 42 e grava o resultado no endereço 0x100:
//
//   0x00  addi x1, x0, 40      # x1 = 40
//   0x04  addi x2, x0, 2       # x2 = 2
//   0x08  add  x1, x1, x2      # x1 = 40 + 2 = 42
//   0x0c  sw   x1, 256(x0)     # mem[0x100] = 42
//   0x10  jal  x0, 0           # halt
`timescale 1ns/1ps
module tb_serv_system;
   reg clk = 1'b0;
   reg rst = 1'b1;
   always #50 clk = ~clk;

   serv_pkg::sys_req_t sys_req;
   serv_pkg::sys_rsp_t sys_rsp;

   serv_system dut
     (.clk   (clk),
      .i_rst (rst),
      .o_sys (sys_req),
      .i_sys (sys_rsp));

   // memória de programa e dados: 256 palavras de 32 bits
   reg [31:0] mem [0:255];
   integer i;
   initial begin
      sys_rsp = '0;
      for (i = 0; i < 256; i = i + 1) mem[i] = 32'h0000_0013;   // nop
      mem[0] = 32'h0280_0093;                                   // addi x1, x0, 40
      mem[1] = 32'h0020_0113;                                   // addi x2, x0, 2
      mem[2] = 32'h0020_80B3;                                   // add  x1, x1, x2
      mem[3] = 32'h1010_2023;                                   // sw   x1, 256(x0)
      mem[4] = 32'h0000_006F;                                   // jal  x0, 0
      mem[64] = 32'h0000_0000;                                  // 0x100
   end

   // SRAM do banco de registradores (512x2 bits)
   reg [1:0] rf [0:511];
   initial for (i = 0; i < 512; i = i + 1) rf[i] = 2'b00;

   always @(posedge clk) begin
      // Wishbone Instrução
      sys_rsp.ibus.ack <= #5 (sys_req.ibus.cyc & !sys_rsp.ibus.ack);
      sys_rsp.ibus.rdt <= #5 mem[sys_req.ibus.adr[9:2]];

      // Wishbone Dados
      sys_rsp.dbus.ack <= #5 (sys_req.dbus.cyc & !sys_rsp.dbus.ack);
      sys_rsp.dbus.rdt <= #5 mem[sys_req.dbus.adr[9:2]];
      if (sys_req.dbus.cyc & !sys_rsp.dbus.ack & sys_req.dbus.we) begin
         if (sys_req.dbus.sel[0]) mem[sys_req.dbus.adr[9:2]][7:0]   <= #5 sys_req.dbus.dat[7:0];
         if (sys_req.dbus.sel[1]) mem[sys_req.dbus.adr[9:2]][15:8]  <= #5 sys_req.dbus.dat[15:8];
         if (sys_req.dbus.sel[2]) mem[sys_req.dbus.adr[9:2]][23:16] <= #5 sys_req.dbus.dat[23:16];
         if (sys_req.dbus.sel[3]) mem[sys_req.dbus.adr[9:2]][31:24] <= #5 sys_req.dbus.dat[31:24];
      end

      // SRAM RF
      if (sys_req.rf.wen) rf[sys_req.rf.waddr] <= #5 sys_req.rf.wdata;
      sys_rsp.rf.rdata <= #5 rf[sys_req.rf.raddr] & ~{2{(sys_req.rf.raddr[8:4] == 5'd0)}};
   end

   integer cyc = 0;
   initial begin
      repeat (5) @(posedge clk);
      @(negedge clk);
      rst <= 1'b0;
      while (!(sys_req.dbus.cyc & sys_req.dbus.we & sys_rsp.dbus.ack) && cyc < 1000) begin
         @(posedge clk);
         cyc = cyc + 1;
      end
      @(posedge clk);
      if (mem[64] !== 32'd42) begin
         $display("FALHOU: mem[0x100] = %0d (esperado 42) após %0d ciclos", mem[64], cyc);
         $finish(1);
      end
      $display("OK: serv_system: 40 + 2 = %0d em %0d ciclos de clock", mem[64], cyc);
      $finish(0);
   end
endmodule
