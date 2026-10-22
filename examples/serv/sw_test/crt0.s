.section .init, "ax"
.global _start
.type _start, @function

_start:
    /* Inicializa Stack Pointer */
    la sp, _stack_top

    /* Limpa a seção .bss */
    la t0, _bss_start
    la t1, _bss_end
bss_clear_loop:
    bge t0, t1, bss_clear_done
    sw zero, 0(t0)
    addi t0, t0, 4
    j bss_clear_loop
bss_clear_done:

    /* Chama main */
    call main

    /* Grava retorno de main (a0) no endereço 0x2000 */
    li t0, 0x00002000
    sw a0, 0(t0)

    /* Grava sinal de fim (1) no endereço 0x2004 */
    li t1, 1
    sw t1, 4(t0)

halt:
    j halt

.size _start, . - _start
