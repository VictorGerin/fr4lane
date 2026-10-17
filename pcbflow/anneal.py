"""Anelamento simulado do placement, compilado com numba (jit.py).

Mesmo algoritmo de place.py, com as estruturas em arrays:
  - fileiras: um array achatado rows[k * cap + i] (cap = número de blocos) e
    cnt[k] blocos em cada uma; pos[v] é o índice do bloco v na sua fileira;
  - nets (reais e virtuais) e listas por bloco em formato CSR (ptr + idx);
  - o sorteio usa um gerador próprio (combinado de L'Ecuyer, 1988), exato em
    inteiros de 64 bits: dá a mesma sequência compilado ou em Python puro. Ele não reproduz o random.Random
    do Python: a solução difere da versão anterior, com a mesma qualidade.

Cada movimento troca dois blocos que podem ocupar os mesmos trechos ou leva um
bloco para outra posição de um trecho permitido; o custo é o HPWL das nets
afetadas mais o excesso das fileiras, e a aceitação é a de Metropolis.
"""

import math

import numpy as np

from .jit import njit, views

# gerador combinado de L'Ecuyer (1988): dois MINSTD com módulos primos
# diferentes; período ~2,3e18 e sem a correlação entre sorteios seguidos de
# um MINSTD só. Os produtos cabem em int64.
_M1, _A1 = 2147483563, 40014
_M2, _A2 = 2147483399, 40692
_EPS = 1e-9                # variação de custo (mm) tratada como zero


@njit(cache=True)
def _rand(st):
    """Número em (0, 1); st = [s1, s2]."""
    s1 = (st[0] * _A1) % _M1
    s2 = (st[1] * _A2) % _M2
    st[0] = s1
    st[1] = s2
    z = s1 - s2
    if z < 1:
        z += _M1 - 1
    return z / _M1


@njit(cache=True)
def _randrange(st, n):
    r = int(_rand(st) * n)
    return n - 1 if r >= n else r


@njit(cache=True)
def _layout_row(k, rows, cnt, cap, row_of, pos, px, py, width, sx, sy, scap, spread, row_len, g):
    """Posição dos blocos da fileira k; com ocupação-alvo < 1, a sobra é
    repartida entre os blocos (meio vão em cada ponta), em múltiplos da grade."""
    base = k * cap
    c = cnt[k]
    tot = 0.0
    for i in range(c):
        tot += width[rows[base + i]]
    x = sx[k]
    gap = 0.0
    if spread[k] and c > 0:
        free = scap[k] - tot
        if free > 0:
            gap = math.floor(free / c / g) * g
            x += math.floor(gap / 2 / g) * g
    for i in range(c):
        v = rows[base + i]
        px[v] = x + width[v] / 2
        py[v] = sy[k]
        row_of[v] = k
        pos[v] = i
        x += width[v] + gap
    row_len[k] = tot


@njit(cache=True)
def _hpwl(e, mem_ptr, mem_idx, fbox, hasfb, weight, px, py):
    if hasfb[e]:
        xmin, xmax = fbox[4 * e], fbox[4 * e + 1]
        ymin, ymax = fbox[4 * e + 2], fbox[4 * e + 3]
    else:
        xmin = ymin = math.inf
        xmax = ymax = -math.inf
    for j in range(mem_ptr[e], mem_ptr[e + 1]):
        v = mem_idx[j]
        x, y = px[v], py[v]
        if x < xmin:
            xmin = x
        if x > xmax:
            xmax = x
        if y < ymin:
            ymin = y
        if y > ymax:
            ymax = y
    if xmax < xmin:
        return 0.0
    return ((xmax - xmin) + (ymax - ymin)) * weight[e]


@njit(cache=True)
def _overflow(k, row_len, scap, target, dw):
    x = max(0.0, row_len[k] - scap[k])
    # acima da ocupação-alvo: custo mais brando, que espalha sem forçar
    t = max(0.0, row_len[k] - target[k]) if target[k] < scap[k] - 1e-6 else 0.0
    return x * x * 2.0 + x * 10.0 + (t * t * 0.5 + t * 2.0) * dw


@njit(cache=True)
def _insert(rows, cnt, cap, k, i, v):
    base = k * cap
    for j in range(cnt[k], i, -1):
        rows[base + j] = rows[base + j - 1]
    rows[base + i] = v
    cnt[k] += 1


@njit(cache=True)
def _pop(rows, cnt, cap, k, i):
    base = k * cap
    v = rows[base + i]
    for j in range(i, cnt[k] - 1):
        rows[base + j] = rows[base + j + 1]
    cnt[k] -= 1
    return v


@njit(cache=True)
def run(nmoves, sample, temp, st, rows, cnt, cap, row_of, pos, px, py, width,
        sx, sy, scap, target, spread, row_len, g, dw,
        al_ptr, al_idx, cls_of, cl_ptr, cl_idx, nb_ptr, nb_idx,
        mem_ptr, mem_idx, fbox, hasfb, weight, net_cost, emark, ebuf, cbuf, stamp_box):
    """nmoves movimentos. sample=True: só mede (desfaz todos) e devolve a soma
    de |variação de custo|; senão aceita/recusa à temperatura temp e devolve 0."""
    n = len(width)
    ssum = 0.0
    for _ in range(nmoves):
        a = _randrange(st, n)
        ra = row_of[a]
        ia = pos[a]
        c = cls_of[a]
        csize = cl_ptr[c + 1] - cl_ptr[c]
        swap = False
        if _rand(st) < 0.5 and csize > 1:
            # troca com outro bloco que pode ocupar os mesmos trechos
            b = cl_idx[cl_ptr[c] + _randrange(st, csize)]
            rb = row_of[b]
            ib = pos[b]
            rows[ra * cap + ia] = b
            rows[rb * cap + ib] = a
            swap = True
        else:
            # leva o bloco para uma posição de um trecho permitido
            rb = al_idx[al_ptr[a] + _randrange(st, al_ptr[a + 1] - al_ptr[a])]
            _pop(rows, cnt, cap, ra, ia)
            ib = _randrange(st, cnt[rb] + 1)
            _insert(rows, cnt, cap, rb, ib, a)

        # nets afetadas: as dos blocos das duas fileiras (sem repetir)
        stamp_box[0] += 1
        stamp = stamp_box[0]
        ne = 0
        for t in range(2):
            k = ra if t == 0 else rb
            if t == 1 and rb == ra:
                break
            base = k * cap
            for i in range(cnt[k]):
                v = rows[base + i]
                for j in range(nb_ptr[v], nb_ptr[v + 1]):
                    e = nb_idx[j]
                    if emark[e] != stamp:
                        emark[e] = stamp
                        ebuf[ne] = e
                        ne += 1
        old = 0.0
        for i in range(ne):
            old += net_cost[ebuf[i]]
        old += _overflow(ra, row_len, scap, target, dw)
        if rb != ra:
            old += _overflow(rb, row_len, scap, target, dw)
        _layout_row(ra, rows, cnt, cap, row_of, pos, px, py, width, sx, sy, scap, spread, row_len, g)
        if rb != ra:
            _layout_row(rb, rows, cnt, cap, row_of, pos, px, py, width, sx, sy, scap, spread, row_len, g)
        new = 0.0
        for i in range(ne):
            cbuf[i] = _hpwl(ebuf[i], mem_ptr, mem_idx, fbox, hasfb, weight, px, py)
            new += cbuf[i]
        new += _overflow(ra, row_len, scap, target, dw)
        if rb != ra:
            new += _overflow(rb, row_len, scap, target, dw)
        d = new - old

        if sample:
            ssum += abs(d)
            accept = False
        else:
            # |d| abaixo de _EPS é arredondamento (custo igual somado em outra
            # ordem): conta como 0, senão o sorteio extra desalinharia a sequência
            accept = d <= _EPS or _rand(st) < math.exp(-d / temp)
        if accept:
            for i in range(ne):
                net_cost[ebuf[i]] = cbuf[i]
        else:
            if swap:
                t2 = rows[ra * cap + ia]
                rows[ra * cap + ia] = rows[rb * cap + ib]
                rows[rb * cap + ib] = t2
            else:
                v = _pop(rows, cnt, cap, rb, ib)
                _insert(rows, cnt, cap, ra, ia, v)
            _layout_row(ra, rows, cnt, cap, row_of, pos, px, py, width, sx, sy, scap, spread, row_len, g)
            if rb != ra:
                _layout_row(rb, rows, cnt, cap, row_of, pos, px, py, width, sx, sy, scap, spread, row_len, g)
    return ssum


def _csr(lists, dtype=np.int64):
    ptr = np.zeros(len(lists) + 1, np.int64)
    for i, lst in enumerate(lists):
        ptr[i + 1] = ptr[i] + len(lst)
    idx = np.fromiter((x for lst in lists for x in lst), dtype, int(ptr[-1]))
    return ptr, idx


class Annealer:
    """Monta os arrays a partir das estruturas do place.py, roda os movimentos
    e devolve o resultado para elas (rows, px, py, row_of, row_len, net_cost)."""

    def __init__(self, seed, rows, slots, width, allowed, nets_of_block, members, fixed_box,
                 weight, net_cost, target, spread, g, dw):
        n, nr = len(width), len(slots)
        self.n, self.nr, self.cap = n, nr, max(1, n)
        self.rows = np.full(nr * self.cap, -1, np.int64)
        self.cnt = np.zeros(nr, np.int64)
        for k, row in enumerate(rows):
            self.rows[k * self.cap:k * self.cap + len(row)] = row
            self.cnt[k] = len(row)
        self.row_of = np.zeros(n, np.int64)
        self.pos = np.zeros(n, np.int64)
        self.px = np.zeros(n, np.float64)
        self.py = np.zeros(n, np.float64)
        self.width = np.asarray(width, np.float64)
        self.sx = np.array([s[0] for s in slots], np.float64)
        self.sy = np.array([s[1] for s in slots], np.float64)
        self.scap = np.array([s[2] for s in slots], np.float64)
        # target é lista (automático) ou {fileira: meta} (floorplan declarado)
        self.target = np.array([target[k] for k in range(nr)], np.float64)
        self.spread = np.asarray(spread, np.bool_)
        self.row_len = np.zeros(nr, np.float64)
        self.al_ptr, self.al_idx = _csr(allowed)
        # blocos com a mesma lista de trechos permitidos podem trocar de lugar
        classes, cls_of = {}, np.zeros(n, np.int64)
        for v in range(n):
            cls_of[v] = classes.setdefault(id(allowed[v]), len(classes))
        members_of_class = [[] for _ in classes]
        for v in range(n):
            members_of_class[cls_of[v]].append(v)
        self.cls_of = cls_of
        self.cl_ptr, self.cl_idx = _csr(members_of_class)
        self.nb_ptr, self.nb_idx = _csr(nets_of_block)
        self.mem_ptr, self.mem_idx = _csr(members)
        ne = len(members)
        self.fbox = np.zeros(4 * ne, np.float64)
        self.hasfb = np.zeros(ne, np.bool_)
        for e, fb in enumerate(fixed_box):
            if fb:
                self.fbox[4 * e:4 * e + 4] = fb
                self.hasfb[e] = True
        self.weight = np.asarray(weight, np.float64)
        self.net_cost = np.asarray(net_cost, np.float64)
        self.emark = np.zeros(ne, np.int64)
        self.ebuf = np.zeros(ne, np.int64)
        self.cbuf = np.zeros(ne, np.float64)
        self.stamp = np.zeros(1, np.int64)
        seed = int(seed)
        self.st = np.array([(seed * 7919 + 12345) % (_M1 - 1) + 1,
                            (seed * 104729 + 54321) % (_M2 - 1) + 1], np.int64)
        self.g, self.dw = float(g), float(dw)
        self._v = views((self.st, self.rows, self.cnt, self.row_of, self.pos, self.px, self.py,
                         self.width, self.sx, self.sy, self.scap, self.target, self.spread,
                         self.row_len, self.al_ptr, self.al_idx, self.cls_of, self.cl_ptr,
                         self.cl_idx, self.nb_ptr, self.nb_idx, self.mem_ptr, self.mem_idx,
                         self.fbox, self.hasfb, self.weight, self.net_cost, self.emark,
                         self.ebuf, self.cbuf, self.stamp))
        (st, rows_, cnt, row_of, pos, px, py, width_, sx, sy, scap, target_, spread_, row_len, *_) = self._v
        for k in range(nr):
            _layout_row(k, rows_, cnt, self.cap, row_of, pos, px, py, width_, sx, sy, scap, spread_,
                        row_len, self.g)

    def moves(self, nmoves, temp=1.0, sample=False):
        (st, rows, cnt, row_of, pos, px, py, width, sx, sy, scap, target, spread, row_len,
         al_ptr, al_idx, cls_of, cl_ptr, cl_idx, nb_ptr, nb_idx, mem_ptr, mem_idx,
         fbox, hasfb, weight, net_cost, emark, ebuf, cbuf, stamp) = self._v
        return run(nmoves, sample, float(temp), st, rows, cnt, self.cap, row_of, pos, px, py, width,
                   sx, sy, scap, target, spread, row_len, self.g, self.dw,
                   al_ptr, al_idx, cls_of, cl_ptr, cl_idx, nb_ptr, nb_idx,
                   mem_ptr, mem_idx, fbox, hasfb, weight, net_cost, emark, ebuf, cbuf, stamp)

    def hpwl(self, n_real):
        return float(self.net_cost[:n_real].sum())

    def write_back(self, rows, px, py, row_of, row_len, net_cost):
        """Devolve o resultado às listas do place.py (no lugar: as funções
        internas de place() continuam vendo os mesmos objetos)."""
        for k in range(self.nr):
            rows[k][:] = self.rows[k * self.cap:k * self.cap + self.cnt[k]].tolist()
        px[:] = self.px.tolist()
        py[:] = self.py.tolist()
        row_of[:] = self.row_of.tolist()
        row_len[:] = self.row_len.tolist()
        net_cost[:] = self.net_cost.tolist()
