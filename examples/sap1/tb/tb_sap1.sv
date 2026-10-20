`timescale 1ns/1ps
// Testbench do SAP-1: grava cada programa pela porta de programação, roda até
// o HLT e confere a sequência de valores na saída.
//
// Só usa as portas do sap1, porque o pcbflow roda o mesmo testbench contra o
// netlist de portas e o de componentes, que não têm o sap1_pkg. Por isso os
// opcodes são repetidos aqui.
module tb_sap1;
    typedef enum logic [3:0] {
        NOP = 4'b0000, LDA = 4'b0001, ADD = 4'b0010, SUB = 4'b0011,
        STA = 4'b0100, LDI = 4'b0101, JMP = 4'b0110, JC  = 4'b0111,
        JZ  = 4'b1000, OUT = 4'b1110, HLT = 4'b1111
    } opcode_t;

    localparam int MAX_CYCLES = 2000;

    logic       clk = 0, rst_n = 0, prog = 0, prog_we = 0;
    logic [3:0] prog_addr = '0;
    logic [7:0] prog_data = '0;
    logic [7:0] out;
    logic       out_load, halted;

    logic [7:0] mem [16];       // programa a gravar
    logic [7:0] expected [$];   // saídas esperadas, em ordem
    int         errors = 0;

    sap1 uut (.clk, .rst_n, .prog, .prog_we, .prog_addr, .prog_data, .out, .out_load, .halted);

    always #50 clk = ~clk;

    function automatic logic [7:0] op(opcode_t code, logic [3:0] arg = '0);
        return {code, arg};
    endfunction

    task automatic new_program();
        foreach (mem[i]) mem[i] = '0;
        expected.delete();
    endtask

    // Grava o programa com a CPU em reset e solta o reset no fim.
    task automatic load_program();
        @(negedge clk);
        rst_n = 0;
        prog  = 1;
        for (int i = 0; i < 16; i++) begin
            @(negedge clk);
            prog_addr = 4'(i);
            prog_data = mem[i];
            prog_we   = 1;
        end
        @(negedge clk);
        prog_we = 0;
        prog    = 0;
        @(negedge clk);
        rst_n = 1;
    endtask

    // Roda até o HLT, conferindo cada valor que vai para a saída.
    task automatic run_program(string name);
        int n_out = 0, cycles = 0;
        load_program();
        while (!halted && cycles < MAX_CYCLES) begin
            if (out_load) begin
                @(posedge clk); #5;
                if (n_out >= expected.size()) begin
                    $display("[ERRO] %s: saída extra %0d", name, out);
                    errors++;
                end else if (out !== expected[n_out]) begin
                    $display("[ERRO] %s: saída %0d = %0d, esperado %0d", name, n_out, out, expected[n_out]);
                    errors++;
                end
                n_out++;
            end
            @(negedge clk);
            cycles++;
        end
        if (!halted) begin
            $display("[ERRO] %s: não chegou ao HLT em %0d ciclos", name, MAX_CYCLES);
            errors++;
        end else if (n_out != expected.size()) begin
            $display("[ERRO] %s: %0d saída(s), esperado %0d", name, n_out, expected.size());
            errors++;
        end else
            $display("%s: %0d saída(s) conferem, HLT em %0d ciclos", name, n_out, cycles);
        // parado: nada mais acontece
        repeat (10) @(negedge clk);
        if (!halted || out_load) begin
            $display("[ERRO] %s: a CPU não ficou parada depois do HLT", name);
            errors++;
        end
    endtask

    initial begin
        // 1. Soma (o primeiro programa do Ben Eater): 28 + 14 = 42.
        new_program();
        mem[0]  = op(LDA, 14);
        mem[1]  = op(ADD, 15);
        mem[2]  = op(OUT);
        mem[3]  = op(HLT);
        mem[14] = 28;
        mem[15] = 14;
        expected = '{42};
        run_program("soma");

        // 2. Multiplicação por somas sucessivas: 7 x 6 = 42.
        //    Usa STA, SUB, JZ (não tomado e tomado) e JMP.
        new_program();
        mem[0]  = op(LDA, 14);    // laço: produto
        mem[1]  = op(ADD, 13);    //   + x
        mem[2]  = op(STA, 14);
        mem[3]  = op(LDA, 15);    //   y
        mem[4]  = op(SUB, 12);    //   - 1
        mem[5]  = op(STA, 15);
        mem[6]  = op(JZ,  8);
        mem[7]  = op(JMP, 0);
        mem[8]  = op(LDA, 14);
        mem[9]  = op(OUT);
        mem[10] = op(HLT);
        mem[12] = 1;
        mem[13] = 7;              // x
        mem[14] = 0;              // produto
        mem[15] = 6;              // y
        expected = '{42};
        run_program("multiplica");

        // 3. Conta de 51 em 51 até estourar 8 bits: LDI, ADD com carry, JC.
        new_program();
        mem[0]  = op(LDI, 0);
        mem[1]  = op(OUT);        // laço
        mem[2]  = op(ADD, 15);
        mem[3]  = op(JC,  5);
        mem[4]  = op(JMP, 1);
        mem[5]  = op(OUT);        // 255 + 51 = 306 -> 50, com carry
        mem[6]  = op(HLT);
        mem[15] = 51;
        expected = '{0, 51, 102, 153, 204, 255, 50};
        run_program("conta");

        // 4. Contagem regressiva: na subtração, carry = 1 enquanto não há
        //    empréstimo (A >= operando); 0 - 1 zera o carry e sai do laço.
        new_program();
        mem[0]  = op(LDI, 5);
        mem[1]  = op(OUT);        // laço
        mem[2]  = op(SUB, 15);
        mem[3]  = op(JC,  1);
        mem[4]  = op(NOP);
        mem[5]  = op(HLT);
        mem[15] = 1;
        expected = '{5, 4, 3, 2, 1, 0};
        run_program("regressiva");

        if (errors == 0) begin
            $display("--- sap1: todos os programas conferem ---");
            $finish(0);
        end else begin
            $display("[ERRO] sap1: %0d erro(s)", errors);
            $finish(1);
        end
    end
endmodule
