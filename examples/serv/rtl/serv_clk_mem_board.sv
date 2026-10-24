// serv_clk_mem_board.sv : Placa de Clock e Memórias para o SERV RV32I
//
// Conecta-se ao backplane do processador SERV e fornece:
//   1. Gerador de Clock com divisor, suporte a auto-run e single-step manual;
//   2. Gerador de Reset limpo e sincronizado (Power-On-Reset + botão manual);
//   3. Memória ROM de Instruções (Wishbone ibus) com firmware RISC-V pré-carregado;
//   4. Memória RAM de Dados (Wishbone dbus) com suporte a escrita mascarada por byte;
//   5. Memória SRAM do Banco de Registradores (RF, 512x2 bits serial);
//   6. Periférico de E/S Mapeado em Memória (MMIO) com 8 LEDs de diagnóstico.
//
`default_nettype none

module serv_clk_mem_board #(
   parameter int ROM_WORDS = 16,
   parameter int RAM_WORDS = 16
) (
   // =========================================================================
   // Entradas externas de controle e alimentação da placa
   // =========================================================================
   input  wire        i_raw_clk,      // Clock base do oscilador (ex: 100 kHz a 10 MHz)
   input  wire        i_rst_btn,      // Botão de reset manual (1 = pressionado / reset)
   input  wire        i_step_btn,     // Botão de avanço manual (single-step)
   input  wire        i_auto_mode,    // 1 = oscilação contínua automática, 0 = passo a passo manual

   // =========================================================================
   // Linhas para o Backplane (alimentam o processador SERV)
   // =========================================================================
   output reg         o_clk,          // Clock do sistema entregue ao backplane
   output reg         o_rst,          // Reset síncrono entregue ao backplane

   // =========================================================================
   // Barramento Wishbone e RF (conectado ao serv_system pelo backplane)
   // =========================================================================
   // ibus (Instruções - Leitura de ROM)
   input  wire [31:0] i_ibus_adr,
   input  wire        i_ibus_cyc,
   output reg  [31:0] o_ibus_rdt,
   output reg         o_ibus_ack,

   // dbus (Dados - Leitura e Escrita de RAM e MMIO)
   input  wire [31:0] i_dbus_adr,
   input  wire [31:0] i_dbus_dat,
   input  wire [3:0]  i_dbus_sel,
   input  wire        i_dbus_we,
   input  wire        i_dbus_cyc,
   output reg  [31:0] o_dbus_rdt,
   output reg         o_dbus_ack,

   // rf (SRAM serial de 512x2 bits para o Banco de Registradores)
   input  wire [8:0]  i_rf_waddr,
   input  wire [1:0]  i_rf_wdata,
   input  wire        i_rf_wen,
   input  wire [8:0]  i_rf_raddr,
   input  wire        i_rf_ren,
   output reg  [1:0]  o_rf_rdata,

   // =========================================================================
   // Diagnóstico e Monitoramento na Placa
   // =========================================================================
   output reg  [7:0]  o_debug_leds,   // LEDs acionados pelo endereço MMIO 0x200
   output wire        o_bus_busy      // LED aceso durante atividade de barramento
);

   // =========================================================================
   // 1. GERADOR DE CLOCK E CONTROLE SINGLE-STEP
   // =========================================================================
   reg clk_div;
   reg step_dly;
   wire step_pulse;

   // Detector de borda do botão de passo manual
   always @(posedge i_raw_clk) begin
      step_dly <= i_step_btn;
   end
   assign step_pulse = i_step_btn & ~step_dly;

   // Divisor / comutador de clock
   always @(posedge i_raw_clk or posedge i_rst_btn) begin
      if (i_rst_btn) begin
         clk_div <= 1'b0;
         o_clk   <= 1'b0;
      end else begin
         clk_div <= ~clk_div;
         if (i_auto_mode)
            o_clk <= clk_div;
         else
            o_clk <= step_pulse;
      end
   end

   // =========================================================================
   // 2. GERADOR DE RESET SINCRONIZADO (Power-On-Reset + Botão)
   // =========================================================================
   reg [2:0] rst_pipe = 3'b111;

   always @(posedge o_clk or posedge i_rst_btn) begin
      if (i_rst_btn) begin
         rst_pipe <= 3'b111;
         o_rst    <= 1'b1;
      end else begin
         rst_pipe <= {rst_pipe[1:0], 1'b0};
         o_rst    <= rst_pipe[2];
      end
   end

   // =========================================================================
   // 3. MEMÓRIA ROM DE INSTRUÇÕES (Wishbone ibus)
   // =========================================================================
   // Decodifica endereços na faixa 0x000 a 0x03F (palavras de 32 bits)
   wire rom_sel = (i_ibus_adr[31:6] == 26'd0);
   wire [3:0] rom_addr = i_ibus_adr[5:2];

   always @(posedge o_clk or posedge o_rst) begin
      if (o_rst) begin
         o_ibus_ack <= 1'b0;
         o_ibus_rdt <= 32'h0000_0013; // NOP (addi x0, x0, 0)
      end else begin
         // Resposta de handshake Wishbone em 1 ciclo
         o_ibus_ack <= i_ibus_cyc & ~o_ibus_ack & rom_sel;

         // Programa RISC-V RV32I embutido na ROM:
         //   0x00: addi x1, x0, 40       (x1 = 40)
         //   0x04: addi x2, x0, 2        (x2 = 2)
         //   0x08: add  x1, x1, x2       (x1 = 40 + 2 = 42)
         //   0x0c: sw   x1, 256(x0)      (grava 42 na RAM em 0x100)
         //   0x10: sw   x1, 512(x0)      (grava 42 no MMIO LEDs em 0x200)
         //   0x14: lw   x3, 256(x0)      (lê de volta da RAM para x3)
         //   0x18: jal  x0, -8           (loop de monitoramento)
         case (rom_addr)
            4'h0: o_ibus_rdt <= 32'h0280_0093; // addi x1, x0, 40
            4'h1: o_ibus_rdt <= 32'h0020_0113; // addi x2, x0, 2
            4'h2: o_ibus_rdt <= 32'h0020_80B3; // add  x1, x1, x2
            4'h3: o_ibus_rdt <= 32'h1010_2023; // sw   x1, 256(x0) -> RAM 0x100
            4'h4: o_ibus_rdt <= 32'h2010_2023; // sw   x1, 512(x0) -> MMIO 0x200
            4'h5: o_ibus_rdt <= 32'h1000_2183; // lw   x3, 256(x0)
            4'h6: o_ibus_rdt <= 32'hFF9F_F06F; // jal  x0, -8 (loop para 0x14)
            default: o_ibus_rdt <= 32'h0000_0013; // NOP
         endcase
      end
   end

   // =========================================================================
   // 4. MEMÓRIA RAM DE DADOS (Wishbone dbus)
   // =========================================================================
   // Mapeada no endereço 0x100 (0x100 a 0x13F)
   wire ram_sel = (i_dbus_adr[31:8] == 24'h000001);
   wire [3:0] ram_addr = i_dbus_adr[5:2];

   // Espaço de RAM (16 palavras de 32 bits = 64 bytes)
   reg [31:0] ram_data [0:15];
   integer k;

   // Decodificador de Periférico MMIO (LEDs no endereço 0x200)
   wire mmio_led_sel = (i_dbus_adr[31:8] == 24'h000002) & (i_dbus_adr[7:0] == 8'h00);

   always @(posedge o_clk or posedge o_rst) begin
      if (o_rst) begin
         o_dbus_ack   <= 1'b0;
         o_dbus_rdt   <= 32'd0;
         o_debug_leds <= 8'hAA; // Padrão inicial de power-up nos LEDs
         for (k = 0; k < 16; k = k + 1)
            ram_data[k] <= 32'd0;
      end else begin
         o_dbus_ack <= i_dbus_cyc & ~o_dbus_ack & (ram_sel | mmio_led_sel);

         // Escrita na RAM com máscara de byte (Wishbone SEL)
         if (i_dbus_cyc & ~o_dbus_ack & i_dbus_we) begin
            if (ram_sel) begin
               if (i_dbus_sel[0]) ram_data[ram_addr][7:0]   <= i_dbus_dat[7:0];
               if (i_dbus_sel[1]) ram_data[ram_addr][15:8]  <= i_dbus_dat[15:8];
               if (i_dbus_sel[2]) ram_data[ram_addr][23:16] <= i_dbus_dat[23:16];
               if (i_dbus_sel[3]) ram_data[ram_addr][31:24] <= i_dbus_dat[31:24];
            end else if (mmio_led_sel) begin
               if (i_dbus_sel[0]) o_debug_leds <= i_dbus_dat[7:0];
            end
         end

         // Leitura da RAM ou MMIO
         if (ram_sel)
            o_dbus_rdt <= ram_data[ram_addr];
         else if (mmio_led_sel)
            o_dbus_rdt <= {24'd0, o_debug_leds};
         else
            o_dbus_rdt <= 32'd0;
      end
   end

   // =========================================================================
   // 5. BANCO DE REGISTRADORES SERIAL (SRAM RF: 512 x 2 bits)
   // =========================================================================
   // Implementa fisicamente os 32 registradores de 32 bits do RV32I (1024 bits)
   reg [1:0] rf_mem [0:511];
   integer m;

   always @(posedge o_clk or posedge o_rst) begin
      if (o_rst) begin
         o_rf_rdata <= 2'b00;
         for (m = 0; m < 512; m = m + 1)
            rf_mem[m] <= 2'b00;
      end else begin
         // Escrita síncrona de 2 bits na SRAM serial
         if (i_rf_wen) begin
            rf_mem[i_rf_waddr] <= i_rf_wdata;
         end

         // Leitura síncrona com hardwire do registrador x0 para 0
         if (i_rf_ren) begin
            // Se o endereço apontar para x0 (posições 0 a 15), devolve 00
            if (i_rf_raddr[8:4] == 5'd0)
               o_rf_rdata <= 2'b00;
            else
               o_rf_rdata <= rf_mem[i_rf_raddr];
         end
      end
   end

   // =========================================================================
   // 6. SINALIZAÇÃO DE ATIVIDADE
   // =========================================================================
   assign o_bus_busy = i_ibus_cyc | i_dbus_cyc | i_rf_ren | i_rf_wen;

endmodule
