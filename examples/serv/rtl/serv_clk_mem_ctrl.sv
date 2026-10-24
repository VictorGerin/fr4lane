// serv_clk_mem_ctrl.sv : Controlador Discreto RTL de Clock, Reset e Barramento de Memória
//
// Módulo em lógica discreta RTL (transistores NPN BC548 + resistores) responsável por:
//   1. Geração de Clock (divisor / comutador auto e single-step);
//   2. Geração de Reset sincronizado (Power-On-Reset + botão manual);
//   3. Decodificação de Endereços Wishbone para os chips de ROM, RAM e RF;
//   4. Geração de sinais de Chip Select (CS) e Handshake ACK;
//   5. Registrador de Diagnóstico MMIO (8 LEDs de status);
//   6. Indicador de atividade de barramento.
//
`default_nettype none

module serv_clk_mem_ctrl (
   // =========================================================================
   // Entradas externas de controle da bancada
   // =========================================================================
   input  wire        i_raw_clk,      // Clock do oscilador base
   input  wire        i_rst_btn,      // Botão de reset manual
   input  wire        i_step_btn,     // Botão de avanço manual (single-step)
   input  wire        i_auto_mode,    // 1 = oscilação contínua automática, 0 = passo a passo

   // =========================================================================
   // Sinais para o Backplane (alimentam a CPU SERV)
   // =========================================================================
   output reg         o_clk,          // Clock entregue ao backplane
   output reg         o_rst,          // Reset limpo entregue ao backplane

   // =========================================================================
   // Linhas de Barramento Wishbone (da CPU)
   // =========================================================================
   input  wire [31:0] i_ibus_adr,     // Endereço de instruções
   input  wire        i_ibus_cyc,     // Ciclo de instruções
   output reg         o_ibus_ack,     // ACK de instrução

   input  wire [31:0] i_dbus_adr,     // Endereço de dados
   input  wire [7:0]  i_dbus_dat,     // Byte de dados (LSB) para MMIO
   input  wire        i_dbus_we,      // Escrita de dados
   input  wire        i_dbus_cyc,     // Ciclo de dados
   output reg         o_dbus_ack,     // ACK de dados

   // =========================================================================
   // Sinais de Habilitação / Chip Select para os chips de memória
   // =========================================================================
   output wire        o_rom_cs,       // Habilita chip de ROM (AT28C256)
   output wire        o_ram_cs,       // Habilita chip de RAM (AS6C62256)
   output wire        o_mmio_cs,      // Habilita periférico MMIO

   // =========================================================================
   // Diagnóstico e Monitoramento
   // =========================================================================
   output reg  [7:0]  o_debug_leds,   // LEDs acionados pelo endereço MMIO 0x200
   output wire        o_bus_busy      // LED de atividade de barramento
);

   // 1. GERADOR DE CLOCK E CONTROLE SINGLE-STEP
   reg clk_div;
   reg step_dly;
   wire step_pulse = i_step_btn & ~step_dly;

   always @(posedge i_raw_clk) begin
      step_dly <= i_step_btn;
   end

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

   // 2. GERADOR DE RESET SINCRONIZADO
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

   // 3. DECODIFICADORES DE ENDEREÇO
   // ROM: faixa 0x000 a 0x03F (endereços com bits superiores zerados)
   assign o_rom_cs = (i_ibus_adr[31:8] == 24'd0);

   // RAM: faixa 0x100 (bits superiores 0x000001)
   assign o_ram_cs = (i_dbus_adr[31:8] == 24'h000001);

   // MMIO LEDs: endereço 0x200 (bits superiores 0x000002)
   assign o_mmio_cs = (i_dbus_adr[31:8] == 24'h000002);

   // 4. HANDSHAKE WISHBONE (ACK)
   always @(posedge o_clk or posedge o_rst) begin
      if (o_rst) begin
         o_ibus_ack <= 1'b0;
         o_dbus_ack <= 1'b0;
      end else begin
         o_ibus_ack <= i_ibus_cyc & ~o_ibus_ack & o_rom_cs;
         o_dbus_ack <= i_dbus_cyc & ~o_dbus_ack & (o_ram_cs | o_mmio_cs);
      end
   end

   // 5. REGISTRADOR MMIO DE DIAGNÓSTICO (LEDs)
   always @(posedge o_clk or posedge o_rst) begin
      if (o_rst) begin
         o_debug_leds <= 8'hAA; // Padrão alternado no boot
      end else begin
         if (i_dbus_cyc & ~o_dbus_ack & i_dbus_we & o_mmio_cs) begin
            o_debug_leds <= i_dbus_dat;
         end
      end
   end

   // 6. INDICADOR DE ATIVIDADE
   assign o_bus_busy = i_ibus_cyc | i_dbus_cyc;

endmodule
