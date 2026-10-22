// EXPECTED: 50
// Testa escrita e leitura na memoria RAM (LOAD e STORE)

int arr[5];

int main(void) {
    // Escreve no array global
    arr[0] = 5;
    arr[1] = 10;
    arr[2] = 15;
    arr[3] = 20;

    int sum = 0;
    for (int i = 0; i < 4; i++) {
        sum += arr[i]; // 5 + 10 + 15 + 20 = 50
    }

    return sum;
}
