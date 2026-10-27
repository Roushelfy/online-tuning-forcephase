"""Goal v11 problem families beyond the v9/v10 bridge generators (docs/BROAD_SCOPE_PROTOCOL_V11.md section 3).

Every generator is deterministic in (size, seed, params, encoding) and returns
  (cmd, (nv, clauses), params, semantic)
where `semantic` is the decoded problem (graph, jobs, states, N, partial square) that scripts/broad_scope_v11/semantic.py
uses to check a SAT model against the problem itself, independently of the CNF. Encodings are written here (only
PySAT's CardEnc, pinned in configs/stratified_v8/gen-requirements.txt, is used for the vertex-cover counter).

Families and encodings:
  vcover   vertex cover of G(n, m = round(d n / 2)) with at most K = floor(alpha n) vertices;
           enc 'seqcounter' (Sinz) [primary] or 'totalizer' (Bailleux-Boufkhad) for the bound
  jssp     job-shop decision: n jobs x n machines, random machine order, durations U{1..dmax}, makespan <= T =
           ceil(beta LB); enc 'order' (order encoding of start times, ordering variables per machine pair)
           [primary] or 'time' (time-indexed start variables, pairwise at-most-one per machine and time)
  bwplan   blocks world with n blocks, random initial / goal states, sequential plans of at most T =
           ceil(gamma L) steps (L = blocks not well placed); explanatory frame axioms, ladder at-most-one action
           per step [single encoding]
  factor   array multiplier p * q = N with p, q of b bits each and p, q >= 2; task fixed by seed parity:
           even -> N = product of two random b-bit primes (satisfiable), odd -> N a random 2b-bit prime
           (unsatisfiable) [single encoding]
  qcp      quasigroup (Latin square) completion of order n with round(f n^2) cells pre-assigned by random
           consistent sequential assignment; enc 'minimal' (cell >= 1 value, value <= 1 per row / column)
           [primary] or 'extended' (adds cell <= 1 value and value >= 1 per row / column)
  col3log  log (binary) encoding of the col3 graph (2 bits per vertex, value 3 forbidden) -- alternative
           encoding of the bridge family col3 (primary: CNFgen kcolor, direct)
"""
import math
import random


class Builder:
    def __init__(self):
        self.nv = 0
        self.clauses = []

    def new(self):
        self.nv += 1
        return self.nv

    def add(self, c):
        self.clauses.append(list(c))

    def amo_pairwise(self, lits):
        for i in range(len(lits)):
            for j in range(i + 1, len(lits)):
                self.add([-lits[i], -lits[j]])

    def amo_ladder(self, lits):
        """Sequential (ladder) at-most-one: s_i <-> some of x_1..x_i is true (one direction suffices)."""
        if len(lits) <= 4:
            return self.amo_pairwise(lits)
        prev = None
        for i, x in enumerate(lits):
            if i == len(lits) - 1:
                if prev is not None:
                    self.add([-x, -prev])
                break
            s = self.new()
            self.add([-x, s])
            if prev is not None:
                self.add([-prev, s])
                self.add([-x, -prev])
            prev = s


def sample_gnm(n, m, rng):
    edges = set()
    while len(edges) < m:
        u, v = rng.sample(range(n), 2)
        edges.add((min(u, v), max(u, v)))
    return sorted(edges)


# ------------------------------------------------------------------ vertex cover (cardinality)

def vcover(n, seed, prm, enc="seqcounter"):
    from pysat.card import CardEnc, EncType
    d, alpha = prm["avg_degree"], prm["budget_frac"]
    m = round(d * n / 2)
    edges = sample_gnm(n, m, random.Random(seed))
    K = int(math.floor(alpha * n))
    clauses = [[u + 1, v + 1] for u, v in edges]
    card = CardEnc.atmost(list(range(1, n + 1)), bound=K, top_id=n, encoding=getattr(EncType, enc))
    nv = max(n, card.nv)
    clauses += [list(c) for c in card.clauses]
    cmd = ["families.py:vcover", f"n={n}", f"seed={seed}", f"avg_degree={d}", f"budget_frac={alpha}", f"enc={enc}"]
    return cmd, (nv, clauses), {"n": n, "m": m, "K": K, "enc": enc}, {"n": n, "edges": edges, "K": K, "var": "x_v = v + 1"}


# ------------------------------------------------------------------ job shop

def jssp_instance(n, seed, prm):
    rng = random.Random(seed)
    dmax = prm["dmax"]
    jobs = []
    for _ in range(n):
        order = list(range(n))
        rng.shuffle(order)
        jobs.append([(mc, rng.randint(1, dmax)) for mc in order])
    lb = max(max(sum(d for _, d in j) for j in jobs),
             max(sum(d for j in jobs for mc, d in j if mc == m) for m in range(n)))
    T = int(math.ceil(prm["beta"] * lb))
    return jobs, lb, T


def jssp(n, seed, prm, enc="order"):
    jobs, lb, T = jssp_instance(n, seed, prm)
    B = Builder()
    ops = [(j, k) for j in range(len(jobs)) for k in range(len(jobs[j]))]
    dur = {(j, k): jobs[j][k][1] for j, k in ops}
    mach = {(j, k): jobs[j][k][0] for j, k in ops}
    est = {(j, k): sum(jobs[j][i][1] for i in range(k)) for j, k in ops}
    lst = {(j, k): T - sum(jobs[j][i][1] for i in range(k, len(jobs[j]))) for j, k in ops}
    on_m = {m: [o for o in ops if mach[o] == m] for m in range(n)}
    var = {}
    if enc == "order":
        for o in ops:
            for t in range(est[o], lst[o]):
                var[(o, t)] = B.new()  # s_o <= t
        for o in ops:
            for t in range(est[o], lst[o] - 1):
                B.add([-var[(o, t)], var[(o, t + 1)]])

        def le(o, t):  # literal for s_o <= t, or True / False
            if t >= lst[o]:
                return True
            if t < est[o]:
                return False
            return var[(o, t)]

        def before(o, o2, guard):  # guard -> s_o + d_o <= s_o2
            for t in range(est[o2], lst[o2] + 1):
                a, b = le(o2, t), le(o, t - dur[o])
                if a is False or b is True:
                    continue
                c = list(guard)
                if a is not True:
                    c.append(-a)
                if b is not False:
                    c.append(b)
                B.add(c)
        for j in range(len(jobs)):
            for k in range(len(jobs[j]) - 1):
                before((j, k), (j, k + 1), [])
        order_vars = {}
        for m in range(n):
            L = on_m[m]
            for i in range(len(L)):
                for i2 in range(i + 1, len(L)):
                    p = B.new()
                    order_vars[(L[i], L[i2])] = p
                    before(L[i], L[i2], [-p])
                    before(L[i2], L[i], [p])
        decode = "order: s_o = least t with var(o, t) true, else lst_o"
    elif enc == "time":
        for o in ops:
            for t in range(est[o], lst[o] + 1):
                var[(o, t)] = B.new()  # s_o = t
        for o in ops:
            lits = [var[(o, t)] for t in range(est[o], lst[o] + 1)]
            B.add(lits)
            B.amo_pairwise(lits)
        for j in range(len(jobs)):
            for k in range(len(jobs[j]) - 1):
                o, o2 = (j, k), (j, k + 1)
                for t in range(est[o2], lst[o2] + 1):
                    B.add([-var[(o2, t)]] + [var[(o, t1)] for t1 in range(est[o], min(lst[o], t - dur[o]) + 1)])
        for m in range(n):
            for t in range(T):
                cov = [(o, t1) for o in on_m[m] for t1 in range(max(est[o], t - dur[o] + 1), min(lst[o], t) + 1)]
                for i in range(len(cov)):
                    for i2 in range(i + 1, len(cov)):
                        if cov[i][0] != cov[i2][0]:
                            B.add([-var[cov[i]], -var[cov[i2]]])
        decode = "time: s_o = the t with var(o, t) true"
    else:
        raise ValueError(enc)
    cmd = ["families.py:jssp", f"n={n}", f"seed={seed}", f"dmax={prm['dmax']}", f"beta={prm['beta']}", f"enc={enc}"]
    sem = {"jobs": jobs, "T": T, "lb": lb, "enc": enc, "decode": decode,
           "var": [[j, k, t, v] for ((j, k), t), v in sorted(var.items())]}
    return cmd, (B.nv, B.clauses), {"n": n, "lb": lb, "T": T, "enc": enc}, sem


# ------------------------------------------------------------------ blocks world planning

def bw_state(n, rng):
    """Random state: random permutation of the blocks cut into towers at each gap with probability 1/2.
    Returns support[b] in {0 (table)} U blocks (1-based)."""
    perm = list(range(1, n + 1))
    rng.shuffle(perm)
    sup = {}
    below = 0
    for i, b in enumerate(perm):
        if i > 0 and rng.random() < 0.5:
            below = 0
        sup[b] = below
        below = b
    return sup


def bw_lower_bound(init, goal):
    """Blocks that are not well placed (a block is well placed if it sits on its goal support and that support
    is the table or a well-placed block); each of them must move at least once."""
    memo = {}

    def wp(b):
        if b not in memo:
            memo[b] = init[b] == goal[b] and (goal[b] == 0 or wp(goal[b]))
        return memo[b]
    return sum(1 for b in init if not wp(b))


def bwplan(n, seed, prm, enc="seq"):
    rng = random.Random(seed)
    init = bw_state(n, rng)
    goal = bw_state(n, rng)
    L = bw_lower_bound(init, goal)
    T = max(1, int(math.ceil(prm["gamma"] * L)))
    blocks = list(range(1, n + 1))
    B = Builder()
    on, clear, mv = {}, {}, {}
    for t in range(T + 1):
        for b in blocks:
            for x in [0] + [c for c in blocks if c != b]:
                on[(b, x, t)] = B.new()
        for x in blocks:
            clear[(x, t)] = B.new()
    for t in range(T):
        for b in blocks:
            for x in [0] + [c for c in blocks if c != b]:
                for y in [0] + [c for c in blocks if c != b]:
                    if x != y:
                        mv[(b, x, y, t)] = B.new()
    for b in blocks:  # initial and goal states (complete)
        for x in [0] + [c for c in blocks if c != b]:
            B.add([on[(b, x, 0)] if init[b] == x else -on[(b, x, 0)]])
        B.add([on[(b, goal[b], T)]])
    for t in range(T + 1):
        for x in blocks:
            for b in blocks:
                if b != x:
                    B.add([-clear[(x, t)], -on[(b, x, t)]])
    for t in range(T):
        acts = []
        for (b, x, y, tt), a in mv.items():
            if tt != t:
                continue
            acts.append(a)
            B.add([-a, on[(b, x, t)]])
            B.add([-a, clear[(b, t)]])
            if y:
                B.add([-a, clear[(y, t)]])
            B.add([-a, on[(b, y, t + 1)]])
            B.add([-a, -on[(b, x, t + 1)]])
        B.amo_ladder(acts)
        for b in blocks:
            sup = [0] + [c for c in blocks if c != b]
            for x in sup:
                B.add([-on[(b, x, t)], on[(b, x, t + 1)]] + [mv[(b, x, y, t)] for y in sup if y != x])
                B.add([on[(b, x, t)], -on[(b, x, t + 1)]] + [mv[(b, z, x, t)] for z in sup if z != x])
    cmd = ["families.py:bwplan", f"n={n}", f"seed={seed}", f"gamma={prm['gamma']}"]
    sem = {"n": n, "init": {str(k): v for k, v in init.items()}, "goal": {str(k): v for k, v in goal.items()},
           "T": T, "L": L, "mv": [[b, x, y, t, a] for (b, x, y, t), a in sorted(mv.items())]}
    return cmd, (B.nv, B.clauses), {"n": n, "L": L, "T": T}, sem


# ------------------------------------------------------------------ factoring (array multiplier)

_MR_BASES = (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37)


def is_prime(N):
    """Deterministic Miller-Rabin for N < 3.3e24 (bases 2..37)."""
    if N < 2:
        return False
    for p in _MR_BASES:
        if N % p == 0:
            return N == p
    d, s = N - 1, 0
    while d % 2 == 0:
        d //= 2
        s += 1
    for a in _MR_BASES:
        x = pow(a, d, N)
        if x in (1, N - 1):
            continue
        for _ in range(s - 1):
            x = x * x % N
            if x == N - 1:
                break
        else:
            return False
    return True


def rand_prime(bits, rng):
    while True:
        x = rng.getrandbits(bits) | (1 << (bits - 1)) | 1
        if is_prime(x):
            return x


def factor_target(b, seed):
    rng = random.Random(seed)
    if seed % 2 == 0:
        p, q = rand_prime(b, rng), rand_prime(b, rng)
        return p * q, "semiprime", (min(p, q), max(p, q))
    return rand_prime(2 * b, rng), "prime", None


def factor(b, seed, prm=None, enc="array"):
    N, task, pq = factor_target(b, seed)
    B = Builder()
    P = [B.new() for _ in range(b)]
    Q = [B.new() for _ in range(b)]

    def AND(x, y):
        z = B.new()
        B.add([-z, x])
        B.add([-z, y])
        B.add([z, -x, -y])
        return z

    def XOR(x, y):
        z = B.new()
        B.add([-z, x, y])
        B.add([-z, -x, -y])
        B.add([z, -x, y])
        B.add([z, x, -y])
        return z

    def full_add(x, y, c):  # sum, carry (Tseitin of two half adders)
        s1 = XOR(x, y)
        s = XOR(s1, c)
        c1, c2 = AND(x, y), AND(s1, c)
        co = B.new()
        B.add([-co, c1, c2])
        B.add([co, -c1])
        B.add([co, -c2])
        return s, co

    def half_add(x, y):
        return XOR(x, y), AND(x, y)
    # rows of partial products, accumulated with ripple-carry adders
    acc = [AND(P[i], Q[0]) for i in range(b)]  # weight i
    out = [acc[0]]
    acc = acc[1:]  # weights 1..b-1 relative to the next row
    for j in range(1, b):
        row = [AND(P[i], Q[j]) for i in range(b)]  # weights j..j+b-1
        new, carry = [], None
        for i in range(b):
            x = row[i]
            y = acc[i] if i < len(acc) else None
            if y is None:
                if carry is None:
                    s, c = x, None
                else:
                    s, c = half_add(x, carry)
            elif carry is None:
                s, c = half_add(x, y)
            else:
                s, c = full_add(x, y, carry)
            new.append(s)
            carry = c
        if carry is not None:
            new.append(carry)
        out.append(new[0])
        acc = new[1:]
    out += acc
    for i, o in enumerate(out):  # product bits, fixed to N (higher bits of N are zero)
        B.add([o] if (N >> i) & 1 else [-o])
    if N >> len(out):
        B.add([])  # N does not fit: unsatisfiable by construction (never happens for 2b-bit N)
    B.add(P[1:])  # p >= 2
    B.add(Q[1:])  # q >= 2
    cmd = ["families.py:factor", f"b={b}", f"seed={seed}", "enc=array"]
    sem = {"b": b, "N": str(N), "task": task, "P": P, "Q": Q, "expected": "SAT" if task == "semiprime" else "UNSAT",
           "factors": None if pq is None else [str(pq[0]), str(pq[1])]}
    return cmd, (B.nv, B.clauses), {"b": b, "N_bits": N.bit_length(), "task": task}, sem


# ------------------------------------------------------------------ quasigroup completion

def qcp_partial(n, seed, f):
    rng = random.Random(seed)
    cells = [(r, c) for r in range(n) for c in range(n)]
    rng.shuffle(cells)
    want = int(round(f * n * n))
    rows, cols, pre = [set() for _ in range(n)], [set() for _ in range(n)], {}
    for r, c in cells:
        if len(pre) >= want:
            break
        free = [v for v in range(n) if v not in rows[r] and v not in cols[c]]
        if not free:
            continue
        v = rng.choice(free)
        pre[(r, c)] = v
        rows[r].add(v)
        cols[c].add(v)
    return pre


def qcp(n, seed, prm, enc="minimal"):
    pre = qcp_partial(n, seed, prm["preassign_frac"])
    x = lambda r, c, v: r * n * n + c * n + v + 1  # noqa: E731
    B = Builder()
    B.nv = n * n * n
    for r in range(n):
        for c in range(n):
            B.add([x(r, c, v) for v in range(n)])
    for v in range(n):
        for r in range(n):
            B.amo_pairwise([x(r, c, v) for c in range(n)])
        for c in range(n):
            B.amo_pairwise([x(r, c, v) for r in range(n)])
    if enc == "extended":
        for r in range(n):
            for c in range(n):
                B.amo_pairwise([x(r, c, v) for v in range(n)])
        for v in range(n):
            for r in range(n):
                B.add([x(r, c, v) for c in range(n)])
            for c in range(n):
                B.add([x(r, c, v) for r in range(n)])
    elif enc != "minimal":
        raise ValueError(enc)
    for (r, c), v in sorted(pre.items()):
        B.add([x(r, c, v)])
    cmd = ["families.py:qcp", f"n={n}", f"seed={seed}", f"preassign_frac={prm['preassign_frac']}", f"enc={enc}"]
    sem = {"n": n, "pre": [[r, c, v] for (r, c), v in sorted(pre.items())], "var": "x(r,c,v) = r n^2 + c n + v + 1"}
    return cmd, (B.nv, B.clauses), {"n": n, "preassigned": len(pre), "enc": enc}, sem


# ------------------------------------------------------------------ col3: log encoding of the bridge graph

def col3_log(n, edges):
    """2 bits per vertex (value = 2 a + b in {0, 1, 2}); value 3 forbidden; adjacent vertices differ."""
    a = lambda v: 2 * v + 1  # noqa: E731
    b = lambda v: 2 * v + 2  # noqa: E731
    clauses = [[-a(v), -b(v)] for v in range(n)]
    for u, v in edges:
        for col in range(3):
            lits = []
            for bit, f in ((1, a), (0, b)):
                one = (col >> bit) & 1
                lits += [-f(u) if one else f(u), -f(v) if one else f(v)]
            clauses.append(lits)
    return (2 * n, clauses)


FAMILIES = {"vcover": vcover, "jssp": jssp, "bwplan": bwplan, "factor": factor, "qcp": qcp}
