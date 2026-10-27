"""Goal v11 semantic checks (docs/BROAD_SCOPE_PROTOCOL_V11.md section 3.3): a SAT model is decoded into the
problem's own terms (cover, schedule, plan, factors, Latin square, colouring) and checked against the problem
description stored by the generator -- independent of the CNF clauses. brute() solves tiny instances by
enumeration (generator tests only). Standard library only.
"""
import itertools


def model_set(lits):
    return {l for l in lits if l > 0}


def check(family, sem, true):
    """True / False: does the model (set of true variables) decode to a valid solution of the problem."""
    return CHECK[family](sem, true)


def ck_vcover(sem, true):
    cover = {v for v in range(sem["n"]) if v + 1 in true}
    return len(cover) <= sem["K"] and all(u in cover or v in cover for u, v in sem["edges"])


def jssp_starts(sem, true):
    var = {}
    for j, k, t, v in sem["var"]:
        var.setdefault((j, k), []).append((t, v))
    starts = {}
    for o, tv in var.items():
        tv.sort()
        if sem["enc"] == "order":
            hit = [t for t, v in tv if v in true]
            starts[o] = hit[0] if hit else tv[-1][0] + 1  # all false -> s_o = lst_o
        else:
            hit = [t for t, v in tv if v in true]
            if len(hit) != 1:
                return None
            starts[o] = hit[0]
    for j, job in enumerate(sem["jobs"]):  # operations without variables (fixed domain): est = lst
        for k in range(len(job)):
            if (j, k) not in starts:
                starts[(j, k)] = sum(d for _, d in job[:k])
    return starts


def ck_jssp(sem, true):
    s = jssp_starts(sem, true)
    if s is None:
        return False
    jobs, T = sem["jobs"], sem["T"]
    for j, job in enumerate(jobs):
        for k, (_, d) in enumerate(job):
            if s[(j, k)] < 0 or s[(j, k)] + d > T:
                return False
            if k and s[(j, k - 1)] + job[k - 1][1] > s[(j, k)]:
                return False
    by_m = {}
    for j, job in enumerate(jobs):
        for k, (m, d) in enumerate(job):
            by_m.setdefault(m, []).append((s[(j, k)], d))
    for iv in by_m.values():
        iv.sort()
        for (a, d), (b, _) in zip(iv, iv[1:]):
            if a + d > b:
                return False
    return True


def ck_bwplan(sem, true):
    state = {int(k): v for k, v in sem["init"].items()}
    goal = {int(k): v for k, v in sem["goal"].items()}
    steps = {}
    for b, x, y, t, a in sem["mv"]:
        if a in true:
            if t in steps:
                return False  # sequential plans: one action per step
            steps[t] = (b, x, y)
    for t in sorted(steps):
        b, x, y = steps[t]
        clear = lambda z: all(state[c] != z for c in state)  # noqa: E731
        if state[b] != x or not clear(b) or (y and not clear(y)) or y == b:
            return False
        state[b] = y
    return state == goal


def ck_factor(sem, true):
    p = sum(1 << i for i, v in enumerate(sem["P"]) if v in true)
    q = sum(1 << i for i, v in enumerate(sem["Q"]) if v in true)
    return p >= 2 and q >= 2 and p * q == int(sem["N"])


def ck_qcp(sem, true):
    n = sem["n"]
    sq = {}
    for r in range(n):
        for c in range(n):
            vals = [v for v in range(n) if r * n * n + c * n + v + 1 in true]
            if not vals:
                return False
            if len(vals) != 1:  # implied by both encodings (counting argument for 'minimal')
                return False
            sq[(r, c)] = vals[0]
    for r, c, v in sem["pre"]:
        if sq[(r, c)] != v:
            return False
    return all(len({sq[(r, c)] for c in range(n)}) == n for r in range(n)) and \
        all(len({sq[(r, c)] for r in range(n)}) == n for c in range(n))


def ck_col3log(sem, true):
    col = {}
    for v in range(sem["n"]):
        a, b = 2 * v + 1 in true, 2 * v + 2 in true
        if a and b:
            return False
        col[v] = 2 * a + b
    return all(col[u] != col[v] for u, v in sem["edges"])


def ck_col3direct(sem, true):
    """CNFgen kcolor: variable x(v, c) = v * 3 + c + 1 (vertex-major, as CNFgen 0.9.6 numbers them; checked in
    tests) -- at least one colour per vertex; any chosen colour per vertex must differ from the neighbours'."""
    cols = {v: {c for c in range(3) if v * 3 + c + 1 in true} for v in range(sem["n"])}
    if any(not c for c in cols.values()):
        return False
    pick = {v: min(c) for v, c in cols.items()}
    return all(pick[u] != pick[v] for u, v in sem["edges"])


CHECK = {"vcover": ck_vcover, "jssp": ck_jssp, "bwplan": ck_bwplan, "factor": ck_factor, "qcp": ck_qcp,
         "col3log": ck_col3log, "col3": ck_col3direct}


# ------------------------------------------------------------------ brute force (tiny instances; tests only)

def brute(family, sem):
    return BRUTE[family](sem)


def br_vcover(sem):
    n, K = sem["n"], sem["K"]
    for k in range(K + 1):
        for S in itertools.combinations(range(n), k):
            s = set(S)
            if all(u in s or v in s for u, v in sem["edges"]):
                return True
    return False


def br_jssp(sem):
    jobs, T = sem["jobs"], sem["T"]
    n_m = 1 + max(m for job in jobs for m, _ in job)
    ops_on = {m: [(j, k) for j, job in enumerate(jobs) for k, (mm, _) in enumerate(job) if mm == m] for m in range(n_m)}
    for orders in itertools.product(*[list(itertools.permutations(ops_on[m])) for m in range(n_m)]):
        # semi-active schedule for these machine orders (fixed point of longest paths), None if cyclic
        prev = {}
        for m, order in enumerate(orders):
            for a, b in zip(order, order[1:]):
                prev.setdefault(b, []).append(a)
        for j, job in enumerate(jobs):
            for k in range(1, len(job)):
                prev.setdefault((j, k), []).append((j, k - 1))
        dur = {(j, k): d for j, job in enumerate(jobs) for k, (_, d) in enumerate(job)}
        start, ok = {}, True
        pending = set(dur)
        while pending and ok:
            ready = [o for o in pending if all(p in start for p in prev.get(o, []))]
            if not ready:
                ok = False
                break
            for o in ready:
                start[o] = max([start[p] + dur[p] for p in prev.get(o, [])] + [0])
                pending.discard(o)
        if ok and max(start[o] + dur[o] for o in dur) <= T:
            return True
    return False


def br_bwplan(sem):
    init = tuple(sorted((int(k), v) for k, v in sem["init"].items()))
    goal = tuple(sorted((int(k), v) for k, v in sem["goal"].items()))
    frontier, seen = [init], {init}
    for _ in range(sem["T"]):  # after the loop, seen holds the states reachable in <= T steps
        if goal in seen:
            return True
        nxt = []
        for st in frontier:
            s = dict(st)
            clear = [b for b in s if all(s[c] != b for c in s)]
            for b in clear:
                for y in [0] + [c for c in clear if c != b]:
                    if y != s[b]:
                        t = dict(s)
                        t[b] = y
                        key = tuple(sorted(t.items()))
                        if key not in seen:
                            seen.add(key)
                            nxt.append(key)
        frontier = nxt
    return goal in seen


def br_factor(sem):
    N, b = int(sem["N"]), sem["b"]
    return any(N % p == 0 and 2 <= N // p < (1 << b) for p in range(2, 1 << b))


def br_qcp(sem):
    n = sem["n"]
    sq = {(r, c): v for r, c, v in sem["pre"]}
    cells = [(r, c) for r in range(n) for c in range(n) if (r, c) not in sq]

    def ok(r, c, v):
        return all(sq.get((r, cc)) != v for cc in range(n)) and all(sq.get((rr, c)) != v for rr in range(n))

    def rec(i):
        if i == len(cells):
            return True
        r, c = cells[i]
        for v in range(n):
            if ok(r, c, v):
                sq[(r, c)] = v
                if rec(i + 1):
                    return True
                del sq[(r, c)]
        return False
    return rec(0)


def br_col3(sem):
    n = sem["n"]
    for col in itertools.product(range(3), repeat=n):
        if all(col[u] != col[v] for u, v in sem["edges"]):
            return True
    return False


BRUTE = {"vcover": br_vcover, "jssp": br_jssp, "bwplan": br_bwplan, "factor": br_factor, "qcp": br_qcp,
         "col3log": br_col3, "col3": br_col3}
