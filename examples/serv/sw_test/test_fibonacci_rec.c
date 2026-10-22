// EXPECTED: 13
// Teste de recursao: valida pilha (stack pointer SP), chamadas aninhadas (JAL/JALR)
// salvando endereço de retorno (RA) e registradores salvos (S0) na memória RAM.

int fib_rec(int n) {
    if (n <= 0)
        return 0;
    if (n == 1)
        return 1;
    return fib_rec(n - 1) + fib_rec(n - 2);
}

volatile int n_rec = 7;

int main(void) {
    return fib_rec(n_rec);
}
