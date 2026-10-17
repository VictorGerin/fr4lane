"""Compilação dos laços pesados (busca do roteador, anelamento do placement).

Com o numba instalado (já vem no Anaconda), as funções marcadas com @njit são
compiladas para código de máquina na primeira chamada e guardadas em cache
(__pycache__). Sem ele, @njit não faz nada e as mesmas funções rodam como
Python puro, com o mesmo resultado, só que mais devagar.
"""

try:
    from numba import njit
    COMPILED = True
except ImportError:
    COMPILED = False

    def njit(*args, **kwargs):
        if args and callable(args[0]):
            return args[0]
        return lambda f: f


def views(arrays):
    """O que passar para uma função @njit: os próprios arrays numpy (compilado)
    ou memoryviews deles (Python puro: ler e escrever elemento a elemento num
    memoryview é bem mais rápido que num array numpy, e a memória é a mesma)."""
    return tuple(arrays) if COMPILED else tuple(memoryview(a) for a in arrays)
