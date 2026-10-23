// Observation profiler for goal v5 (docs/OBSERVATION_PROTOCOL_V5.md).
//
//   obsprofile [--sections=LIST] [--cap=SEC] [--seccap=NAME:SEC,...]
//              [--seed=N] <cnf>
//
// Parses a plain or compressed DIMACS file once and computes, section by
// section, the static / propagation / structure observations of the v5
// registry (configs/observations_v5/registry.json).  Prints one JSON object:
//
//   {"sections":{"parse":{"status":"ok","cpu":..}, ...},
//    "features":{"p_...":.., "a01_...":.., ...}, "cpu_total":..}
//
// Sections (in this order; LIST selects a subset, default all):
//   s28    the 28 v4 static features (identical to tools/cnfprofile.c)
//   polar  A01 A02 A03 A04 A05 A07 A09 A10 on the original clauses
//   resid  root unit propagation; B01, C01/C02 residual profile, A04/A11
//          on the residual (the search-entry formula of the pinned
//          CaDiCaL default: no preprocessing rounds, light preprocessing
//          off, so only root propagation changes the clause set)
//   bilat  B02-B05 two-sided bounded BCP of 32 sampled variables, B07/B10
//          uniform-sign greedy paths (needs resid)
//   graph  D01/D02/C04 binary implication graph, D03 components, D07 hubs
//          (needs resid)
//   comm   D04 label-propagation communities, A12, D05 signed pair types,
//          D10 sign-aware WL colours (needs resid)
//   ls     G01-G04/G06 probSAT from all-0 / all-1 / random starts
//          (needs resid; features only, never an answer)
//
// Every section has its own CPU cap (--seccap); a section that hits it is
// reported with status "cap" and contributes no features.  --cap bounds the
// total CPU of the process (parsing included); when it is hit, the running
// and all later sections are "cap"/"skipped".  CPU is process CPU time
// (plus a decompression child, if any).  Duplicate literals are removed and
// tautologies dropped for all sections except s28 (which counts clauses as
// given, like cnfprofile).  Exit code 0 unless the input is unreadable.

#define _GNU_SOURCE
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <time.h>

/*------------------------------------------------------------------------*/
// timing and caps

static double cpu_now (void) {
  struct rusage u;
  double res = 0;
  getrusage (RUSAGE_SELF, &u);
  res += u.ru_utime.tv_sec + 1e-6 * u.ru_utime.tv_usec;
  res += u.ru_stime.tv_sec + 1e-6 * u.ru_stime.tv_usec;
  getrusage (RUSAGE_CHILDREN, &u);
  res += u.ru_utime.tv_sec + 1e-6 * u.ru_utime.tv_usec;
  res += u.ru_stime.tv_sec + 1e-6 * u.ru_stime.tv_usec;
  return res;
}

static double fast_cpu (void) {
  struct timespec ts;
  clock_gettime (CLOCK_PROCESS_CPUTIME_ID, &ts);
  return ts.tv_sec + 1e-9 * ts.tv_nsec;
}

static double total_cap = 1e9, sec_start = 0, sec_cap = 1e9;
static int capped = 0;  // current section hit its cap
static int gcapped = 0; // the global cap was hit
static unsigned tick_counter = 0;

// Cheap periodic check; returns 1 when the running section must stop.
static inline int over (void) {
  if (capped)
    return 1;
  if (++tick_counter & 1023)
    return 0;
  double t = fast_cpu ();
  if (t - sec_start > sec_cap)
    capped = 1;
  if (t > total_cap)
    capped = gcapped = 1;
  return capped;
}

/*------------------------------------------------------------------------*/
// output

typedef struct {
  char name[48];
  double value;
} Feat;
static Feat *feats;
static int nfeats, cfeats;
static int sec_feat_begin;

static void put (const char *name, double x) {
  if (nfeats == cfeats) {
    cfeats = cfeats ? 2 * cfeats : 256;
    feats = realloc (feats, cfeats * sizeof *feats);
  }
  snprintf (feats[nfeats].name, sizeof feats[nfeats].name, "%s", name);
  feats[nfeats++].value = x;
}

static double ratio (double a, double b) { return b > 0 ? a / b : NAN; }
static double lg10p (double x) { return log10 (1.0 + (x > 0 ? x : 0)); }

#define MAXSEC 8
static const char *sec_names[MAXSEC] = {"parse", "s28",   "polar", "resid",
                                        "bilat", "graph", "comm",  "ls"};
static const char *sec_status[MAXSEC];
static double sec_cpu[MAXSEC];
static double sec_caps[MAXSEC] = {1e9, 1e9, 0.5, 0.5, 0.5, 0.5, 1.0, 0.6};
static int sec_wanted[MAXSEC] = {1, 1, 1, 1, 1, 1, 1, 1};

static int sec_index (const char *name, size_t n) {
  for (int i = 0; i < MAXSEC; i++)
    if (strlen (sec_names[i]) == n && !strncmp (sec_names[i], name, n))
      return i;
  return -1;
}

static void begin (int s) {
  capped = 0;
  sec_start = fast_cpu ();
  sec_cap = sec_caps[s];
  sec_feat_begin = nfeats;
}

static void end (int s, const char *status_if_ok) {
  sec_cpu[s] = fast_cpu () - sec_start;
  if (capped) {
    sec_status[s] = "cap";
    nfeats = sec_feat_begin; // a capped section contributes no features
  } else
    sec_status[s] = status_if_ok;
}

static void print_json (double cpu_total) {
  printf ("{\"sections\":{");
  for (int i = 0; i < MAXSEC; i++)
    printf ("%s\"%s\":{\"status\":\"%s\",\"cpu\":%.6f}", i ? "," : "",
            sec_names[i], sec_status[i] ? sec_status[i] : "skipped",
            sec_cpu[i]);
  printf ("},\"features\":{");
  for (int i = 0; i < nfeats; i++) {
    double x = feats[i].value;
    if (isnan (x) || isinf (x))
      printf ("%s\"%s\":null", i ? "," : "", feats[i].name);
    else
      printf ("%s\"%s\":%.6g", i ? "," : "", feats[i].name, x);
  }
  printf ("},\"cpu_total\":%.6f}\n", cpu_total);
}

static void die (const char *msg) {
  fprintf (stderr, "obsprofile: %s\n", msg);
  exit (2);
}

/*------------------------------------------------------------------------*/
// random numbers (splitmix64; never shared with any solver)

static uint64_t rng_state;
static uint64_t rnd (void) {
  uint64_t z = (rng_state += 0x9e3779b97f4a7c15ull);
  z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ull;
  z = (z ^ (z >> 27)) * 0x94d049bb133111ebull;
  return z ^ (z >> 31);
}
static double rnd01 (void) { return (rnd () >> 11) * (1.0 / 9007199254740992.0); }

/*------------------------------------------------------------------------*/
// formula: literal code L = 2*v + neg, NOT(L) = L ^ 1

static long nv;              // header variables
static int64_t nc;           // stored clauses (deduplicated, no tautologies)
static int *cl;              // literal codes, flattened
static int64_t *cs;          // clause starts, nc + 1
static int64_t nlits, ccap, lcap;
static long n_taut, n_empty_in;
static int64_t *ostart;      // occurrence CSR over literal codes
static int64_t *occ;         // clause ids
static double *pw;           // 2^-len lookup

#define VAR(L) ((L) >> 1)
#define NEG(L) ((L) &1)
#define LEN(c) ((int) (cs[(c) + 1] - cs[c]))

// s28 accumulators (raw clauses, as cnfprofile)
static long clauses28, lits28, plits28, unit28, bin28, ter28, len4p28,
    len10p28, horn28, antihorn28, allpos28, allneg28, binneg28, binpos28,
    maxlen28, empty28;
static double sumsq28;
static uint32_t *posocc, *negocc; // raw occurrence counts

static FILE *in;
static int in_pipe;
static unsigned char buf[1 << 20];
static size_t bpos, blen;
static int parse_capped;

static int next_ch (void) {
  if (bpos == blen) {
    if (fast_cpu () > total_cap) {
      parse_capped = 1;
      return EOF;
    }
    blen = fread (buf, 1, sizeof buf, in);
    bpos = 0;
    if (!blen)
      return EOF;
  }
  return buf[bpos++];
}

static FILE *open_input (const char *path, int *pipe) {
  const char *cmd = 0;
  size_t n = strlen (path);
  if (n > 3 && !strcmp (path + n - 3, ".xz"))
    cmd = "xz -dc";
  else if (n > 3 && !strcmp (path + n - 3, ".gz"))
    cmd = "gzip -dc";
  else if (n > 4 && !strcmp (path + n - 4, ".bz2"))
    cmd = "bzip2 -dc";
  if (!cmd) {
    *pipe = 0;
    return fopen (path, "r");
  }
  char *b = malloc (strlen (cmd) + n + 8);
  sprintf (b, "%s '%s'", cmd, path);
  *pipe = 1;
  FILE *f = popen (b, "r");
  free (b);
  return f;
}

static void push_lit (int L) {
  if (nlits == lcap) {
    lcap = lcap ? 2 * lcap : (1 << 20);
    cl = realloc (cl, lcap * sizeof *cl);
    if (!cl)
      die ("out of memory");
  }
  cl[nlits++] = L;
}

static void push_clause_start (void) {
  if (nc + 1 >= ccap) {
    ccap = ccap ? 2 * ccap : (1 << 16);
    cs = realloc (cs, ccap * sizeof *cs);
    if (!cs)
      die ("out of memory");
  }
}

// returns 0 on success, 1 when the global cap stopped parsing
static int parse (const char *path) {
  in = open_input (path, &in_pipe);
  if (!in)
    die ("can not read input");
  int ch;
  long header_clauses = -1;
  for (;;) {
    ch = next_ch ();
    if (ch == 'c') {
      while ((ch = next_ch ()) != '\n' && ch != EOF)
        ;
      continue;
    }
    if (ch == 'p')
      break;
    if (ch == EOF)
      return parse_capped ? 1 : (die ("missing header"), 2);
    if (ch != ' ' && ch != '\n' && ch != '\t' && ch != '\r')
      die ("missing header");
  }
  {
    char line[256];
    int i = 0;
    while ((ch = next_ch ()) != '\n' && ch != EOF && i < 255)
      line[i++] = ch;
    line[i] = 0;
    if (sscanf (line, " cnf %ld %ld", &nv, &header_clauses) != 2)
      die ("invalid header");
  }
  posocc = calloc (nv + 1, sizeof *posocc);
  negocc = calloc (nv + 1, sizeof *negocc);
  int *mark = calloc (nv + 1, sizeof *mark); // +1 pos, -1 neg in clause
  if (!posocc || !negocc || !mark)
    die ("out of memory");
  push_clause_start ();
  cs[0] = 0;
  long size = 0, cpos = 0;
  int taut = 0;
  int64_t cstart = 0;
  for (;;) {
    ch = next_ch ();
    if (ch == EOF)
      break;
    if (ch == ' ' || ch == '\n' || ch == '\t' || ch == '\r')
      continue;
    if (ch == 'c') {
      while ((ch = next_ch ()) != '\n' && ch != EOF)
        ;
      continue;
    }
    int sign = 1;
    if (ch == '-') {
      sign = -1;
      ch = next_ch ();
    }
    if (ch < '0' || ch > '9')
      die ("parse error");
    long v = ch - '0';
    while ((ch = next_ch ()) >= '0' && ch <= '9')
      v = 10 * v + (ch - '0');
    if (v) {
      if (v > nv)
        die ("literal exceeds header");
      size++;
      if (sign > 0)
        cpos++, posocc[v]++;
      else
        negocc[v]++;
      if (mark[v] == sign)
        ; // duplicate literal
      else if (mark[v] == -sign)
        taut = 1;
      else {
        mark[v] = sign;
        push_lit (2 * (int) v + (sign < 0));
      }
    } else {
      clauses28++, lits28 += size, plits28 += cpos;
      sumsq28 += (double) size * size;
      if (size > maxlen28)
        maxlen28 = size;
      empty28 += (size == 0);
      unit28 += (size == 1), bin28 += (size == 2), ter28 += (size == 3);
      len4p28 += (size >= 4), len10p28 += (size >= 10);
      horn28 += (cpos <= 1), antihorn28 += (size - cpos <= 1);
      if (size > 0)
        allpos28 += (cpos == size), allneg28 += (cpos == 0);
      if (size == 2)
        binpos28 += (cpos == 2), binneg28 += (cpos == 0);
      for (int64_t k = cstart; k < nlits; k++)
        mark[VAR (cl[k])] = 0;
      if (taut) {
        n_taut++;
        nlits = cstart;
      } else if (nlits == cstart) {
        n_empty_in++;
      } else {
        nc++;
        push_clause_start ();
        cs[nc] = nlits;
      }
      cstart = nlits;
      size = cpos = 0;
      taut = 0;
    }
    if (ch == EOF)
      break;
  }
  free (mark);
  if (in_pipe)
    pclose (in);
  else
    fclose (in);
  nlits = cstart; // drop an unterminated last clause
  return parse_capped ? 1 : 0;
}

static void build_occ (void) {
  ostart = calloc (2 * nv + 3, sizeof *ostart);
  if (!ostart)
    die ("out of memory");
  for (int64_t k = 0; k < nlits; k++)
    ostart[cl[k] + 1]++;
  for (long L = 0; L < 2 * nv + 2; L++)
    ostart[L + 1] += ostart[L];
  occ = malloc ((nlits + 1) * sizeof *occ);
  int64_t *fill = malloc ((2 * nv + 2) * sizeof *fill);
  if (!occ || !fill)
    die ("out of memory");
  memcpy (fill, ostart, (2 * nv + 2) * sizeof *fill);
  for (int64_t c = 0; c < nc; c++)
    for (int64_t k = cs[c]; k < cs[c + 1]; k++)
      occ[fill[cl[k]]++] = c;
  free (fill);
  pw = malloc (66 * sizeof *pw);
  for (int i = 0; i < 66; i++)
    pw[i] = ldexp (1.0, -i);
}

static inline double pw2 (int len) { return len < 65 ? pw[len] : 0.0; }

/*------------------------------------------------------------------------*/
// s28 (exact copy of cnfprofile's feature definitions)

static void sec_s28 (void) {
  long vars = 0, purepos = 0, pureneg = 0, posmaj = 0, negmaj = 0,
       maxocc = 0;
  double sb = 0, sb2 = 0, sab = 0, socc = 0, socc2 = 0;
  for (long v = 1; v <= nv; v++) {
    long p = posocc[v], n = negocc[v], o = p + n;
    if (!o)
      continue;
    vars++;
    double b = (double) (p - n) / o;
    sb += b, sb2 += b * b, sab += fabs (b);
    purepos += (n == 0), pureneg += (p == 0);
    posmaj += (p > n), negmaj += (n > p);
    socc += o, socc2 += (double) o * o;
    if (o > maxocc)
      maxocc = o;
  }
  double mlen = ratio (lits28, clauses28);
  double mb = ratio (sb, vars), mocc = ratio (socc, vars);
  put ("vars", vars);
  put ("clauses", clauses28);
  put ("p_log_vars", log10 (1.0 + vars));
  put ("p_log_clauses", log10 (1.0 + clauses28));
  put ("p_cv_ratio", ratio (clauses28, vars));
  put ("p_len_mean", mlen);
  put ("p_len_std", clauses28 ? sqrt (fmax (0, sumsq28 / clauses28 - mlen * mlen)) : NAN);
  put ("p_len_max", maxlen28);
  put ("p_empty_frac", ratio (empty28, clauses28));
  put ("p_unit_frac", ratio (unit28, clauses28));
  put ("p_bin_frac", ratio (bin28, clauses28));
  put ("p_ter_frac", ratio (ter28, clauses28));
  put ("p_len4p_frac", ratio (len4p28, clauses28));
  put ("p_len10p_frac", ratio (len10p28, clauses28));
  put ("p_pos_lit_frac", ratio (plits28, lits28));
  put ("p_horn_frac", ratio (horn28, clauses28));
  put ("p_antihorn_frac", ratio (antihorn28, clauses28));
  put ("p_allpos_cls_frac", ratio (allpos28, clauses28));
  put ("p_allneg_cls_frac", ratio (allneg28, clauses28));
  put ("p_binpos_frac", ratio (binpos28, bin28));
  put ("p_binneg_frac", ratio (binneg28, bin28));
  put ("p_var_bal_mean", mb);
  put ("p_var_bal_std", vars ? sqrt (fmax (0, sb2 / vars - mb * mb)) : NAN);
  put ("p_var_absbal_mean", ratio (sab, vars));
  put ("p_var_purepos_frac", ratio (purepos, vars));
  put ("p_var_pureneg_frac", ratio (pureneg, vars));
  put ("p_var_posmaj_frac", ratio (posmaj, vars));
  put ("p_var_negmaj_frac", ratio (negmaj, vars));
  put ("p_occ_mean", mocc);
  put ("p_occ_cv", vars && mocc > 0 ? sqrt (fmax (0, socc2 / vars - mocc * mocc)) / mocc : NAN);
  put ("p_occ_max_rel", ratio (maxocc, mocc));
  put ("n_tautologies", n_taut);
}

/*------------------------------------------------------------------------*/
// helpers on a clause subset (original or residual)

static int cmp_double (const void *a, const void *b) {
  double x = *(const double *) a, y = *(const double *) b;
  return x < y ? -1 : x > y;
}

static double quantile_sorted (const double *a, long n, double q) {
  if (n <= 0)
    return NAN;
  double pos = q * (n - 1);
  long i = (long) pos;
  double f = pos - i;
  return i + 1 < n ? a[i] * (1 - f) + a[i + 1] * f : a[i];
}

/*------------------------------------------------------------------------*/
// polar: A01 A02 A03 A04 A05 A07 A09 A10 on the original clauses

typedef struct {
  uint64_t *keys;
  uint64_t mask;
  int64_t count;
} Set64;

static uint64_t mix64 (uint64_t z) {
  z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ull;
  z = (z ^ (z >> 27)) * 0x94d049bb133111ebull;
  return z ^ (z >> 31);
}

static void set_init (Set64 *s, int64_t n) {
  uint64_t cap = 16;
  while (cap < (uint64_t) (2 * n + 16))
    cap <<= 1;
  s->keys = calloc (cap, sizeof *s->keys);
  if (!s->keys)
    die ("out of memory");
  s->mask = cap - 1;
  s->count = 0;
}

static void set_add (Set64 *s, uint64_t k) { // k != 0
  uint64_t h = mix64 (k) & s->mask;
  while (s->keys[h] && s->keys[h] != k)
    h = (h + 1) & s->mask;
  if (!s->keys[h])
    s->keys[h] = k, s->count++;
}

static int set_has (const Set64 *s, uint64_t k) {
  uint64_t h = mix64 (k) & s->mask;
  while (s->keys[h]) {
    if (s->keys[h] == k)
      return 1;
    h = (h + 1) & s->mask;
  }
  return 0;
}

static inline uint64_t pair_key (int a, int b) {
  if (a > b) {
    int t = a;
    a = b, b = t;
  }
  return ((uint64_t) (uint32_t) (a + 1) << 32) | (uint32_t) (b + 1);
}

static void sec_polar (void) {
  // A01 short-clause weighted pressure, A04 weighted endpoint violation
  double wp = 0, wn = 0, wall = 0, viol0 = 0, viol1 = 0;
  long sp = 0, sn = 0;
  // A05 Bernoulli(p) violation: histogram of (pos, neg) counts
  enum { H = 24 };
  static double hist[H][H];
  memset (hist, 0, sizeof hist);
  double *jp = calloc (nv + 1, sizeof *jp), *jn = calloc (nv + 1, sizeof *jn);
  long *deg2 = calloc (nv + 1, sizeof *deg2), *degs = calloc (nv + 1, sizeof *degs);
  if (!jp || !jn || !deg2 || !degs)
    die ("out of memory");
  int64_t nbin = 0;
  for (int64_t c = 0; c < nc; c++) {
    if (over ())
      goto done;
    int len = LEN (c), pos = 0;
    double w = pw2 (len);
    for (int64_t k = cs[c]; k < cs[c + 1]; k++) {
      int L = cl[k];
      if (NEG (L))
        wn += w, jn[VAR (L)] += w;
      else
        wp += w, pos++, jp[VAR (L)] += w;
      if (len == 2)
        deg2[VAR (L)]++;
      if (len <= 3)
        degs[VAR (L)]++;
    }
    if (len <= 3)
      sp += pos, sn += len - pos;
    wall += w;
    if (pos == len)
      viol0 += w;
    if (pos == 0)
      viol1 += w;
    nbin += (len == 2);
    hist[pos < H ? pos : H - 1][len - pos < H ? len - pos : H - 1] += 1;
  }
  put ("a01_wpos_frac", ratio (wp, wp + wn));
  put ("a01_short_pos_frac", ratio (sp, sp + sn));
  put ("a04_viol0_w", ratio (viol0, wall));
  put ("a04_viol1_w", ratio (viol1, wall));
  put ("a04_viol_w_lr", log2 ((viol0 / wall + 1e-6) / (viol1 / wall + 1e-6)));
  {
    static const double ps[] = {0.1, 0.3, 0.5, 0.7, 0.9};
    double best = INFINITY, argbest = NAN, e3 = 0, e7 = 0;
    for (int g = 1; g < 20; g++) {
      double p = 0.05 * g, e = 0;
      for (int i = 0; i < H; i++)
        for (int j = 0; j < H; j++)
          if (hist[i][j] > 0)
            e += hist[i][j] * pow (1 - p, i) * pow (p, j);
      e /= nc > 0 ? nc : 1;
      if (e < best)
        best = e, argbest = p;
      if (g == 6)
        e3 = e;
      if (g == 14)
        e7 = e;
    }
    for (int g = 0; g < 5; g++) {
      double p = ps[g], e = 0;
      for (int i = 0; i < H; i++)
        for (int j = 0; j < H; j++)
          if (hist[i][j] > 0)
            e += hist[i][j] * pow (1 - p, i) * pow (p, j);
      e /= nc > 0 ? nc : 1;
      char name[32];
      snprintf (name, sizeof name, "a05_logE_p%02d", (int) (100 * p + 0.5));
      put (name, log10 (e + 1e-12));
    }
    put ("a05_argmin_p", argbest);
    put ("a05_asym_30_70", log10 (e3 + 1e-12) - log10 (e7 + 1e-12));
  }
  // A02 per-variable JW direction, A09 balance distribution, A03 top
  // occurrence variables, A10 key-variable weighted balance
  {
    long nvar = 0;
    double *d = malloc ((nv + 1) * sizeof *d), *bal = malloc ((nv + 1) * sizeof *bal);
    long *occn = malloc ((nv + 1) * sizeof *occn);
    double wsum = 0, wdir = 0, wabs = 0, w2 = 0, b2 = 0, ws = 0, bs = 0;
    long posd = 0, negd = 0, mixd = 0, extreme = 0, hb[10] = {0};
    for (long v = 1; v <= nv; v++) {
      long o = ostart[2 * v + 2] - ostart[2 * v];
      if (!o)
        continue;
      double J = jp[v] + jn[v];
      double dv = J > 0 ? (jp[v] - jn[v]) / J : 0;
      long p = ostart[2 * v + 1] - ostart[2 * v], n = o - p;
      double b = (double) (p - n) / o;
      d[nvar] = dv, bal[nvar] = b, occn[nvar] = o;
      nvar++;
      wsum += J, wdir += J * dv, wabs += J * fabs (dv);
      posd += dv > 0.1, negd += dv < -0.1, mixd += fabs (dv) <= 0.1;
      extreme += fabs (b) > 0.8;
      int bin = (int) ((b + 1) * 5);
      hb[bin > 9 ? 9 : bin < 0 ? 0 : bin]++;
      w2 += deg2[v], b2 += deg2[v] * b;
      ws += degs[v], bs += degs[v] * b;
    }
    put ("a02_jw_dir_wmean", ratio (wdir, wsum));
    put ("a02_jw_absdir_wmean", ratio (wabs, wsum));
    put ("a02_jw_pos_frac", ratio (posd, nvar));
    put ("a02_jw_neg_frac", ratio (negd, nvar));
    put ("a02_jw_mixed_frac", ratio (mixd, nvar));
    double *tmp = malloc ((nvar + 1) * sizeof *tmp);
    memcpy (tmp, d, nvar * sizeof *tmp);
    qsort (tmp, nvar, sizeof *tmp, cmp_double);
    put ("a02_jw_dir_q10", quantile_sorted (tmp, nvar, 0.1));
    put ("a02_jw_dir_q50", quantile_sorted (tmp, nvar, 0.5));
    put ("a02_jw_dir_q90", quantile_sorted (tmp, nvar, 0.9));
    memcpy (tmp, bal, nvar * sizeof *tmp);
    qsort (tmp, nvar, sizeof *tmp, cmp_double);
    put ("a09_bal_q10", quantile_sorted (tmp, nvar, 0.1));
    put ("a09_bal_q90", quantile_sorted (tmp, nvar, 0.9));
    put ("a09_bal_extreme_frac", ratio (extreme, nvar));
    double ent = 0;
    for (int i = 0; i < 10; i++)
      if (hb[i] && nvar)
        ent -= (double) hb[i] / nvar * log ((double) hb[i] / nvar);
    put ("a09_bal_entropy", ent / log (10.0));
    // A03: top 10% by occurrence (at least 1 variable)
    {
      double thr_occ;
      for (long i = 0; i < nvar; i++)
        tmp[i] = (double) occn[i];
      qsort (tmp, nvar, sizeof *tmp, cmp_double);
      long k = nvar / 10 > 0 ? nvar / 10 : (nvar > 0);
      thr_occ = nvar ? tmp[nvar - k] : 0;
      double sbt = 0, sball = 0;
      long nt = 0, pm = 0;
      for (long i = 0; i < nvar; i++) {
        sball += bal[i];
        if (occn[i] >= thr_occ)
          sbt += bal[i], nt++, pm += bal[i] > 0;
      }
      put ("a03_top_bal_mean", ratio (sbt, nt));
      put ("a03_top_minus_all_bal", ratio (sbt, nt) - ratio (sball, nvar));
      put ("a03_top_posmaj_frac", ratio (pm, nt));
    }
    put ("a10_bindeg_w_bal", ratio (b2, w2));
    put ("a10_shortdeg_w_bal", ratio (bs, ws));
    free (tmp);
    free (d), free (bal), free (occn);
  }
  // A07 exactly-one fingerprints: all-positive clause (ALO) whose literal
  // pairs all have a binary at-most-one clause (-a v -b): "one-hot"; the
  // mirror (all-negative clause + positive binaries): "one-cold".
  {
    Set64 bins;
    set_init (&bins, nbin);
    for (int64_t c = 0; c < nc; c++)
      if (LEN (c) == 2)
        set_add (&bins, pair_key (cl[cs[c]], cl[cs[c] + 1]));
    char *hot = calloc (nv + 1, 1), *cold = calloc (nv + 1, 1);
    long ghot = 0, gcold = 0, binneg_total = 0, binpos_total = 0;
    int64_t work = 0;
    for (int64_t c = 0; c < nc && !over (); c++) {
      int len = LEN (c);
      if (len < 3 || len > 64)
        continue;
      int pos = 0;
      for (int64_t k = cs[c]; k < cs[c + 1]; k++)
        pos += !NEG (cl[k]);
      if (pos != len && pos != 0)
        continue;
      int ok = 1;
      for (int64_t i = cs[c]; ok && i < cs[c + 1]; i++)
        for (int64_t j = i + 1; ok && j < cs[c + 1]; j++) {
          work++;
          if (!set_has (&bins, pair_key (cl[i] ^ 1, cl[j] ^ 1)))
            ok = 0;
        }
      if (!ok)
        continue;
      if (pos == len) {
        ghot++;
        for (int64_t k = cs[c]; k < cs[c + 1]; k++)
          hot[VAR (cl[k])] = 1;
      } else {
        gcold++;
        for (int64_t k = cs[c]; k < cs[c + 1]; k++)
          cold[VAR (cl[k])] = 1;
      }
    }
    long nh = 0, nco = 0, nvar = 0;
    for (long v = 1; v <= nv; v++) {
      if (ostart[2 * v + 2] == ostart[2 * v])
        continue;
      nvar++, nh += hot[v], nco += cold[v];
    }
    for (int64_t c = 0; c < nc; c++)
      if (LEN (c) == 2) {
        int a = cl[cs[c]], b = cl[cs[c] + 1];
        binneg_total += NEG (a) && NEG (b);
        binpos_total += !NEG (a) && !NEG (b);
      }
    put ("a07_onehot_var_frac", ratio (nh, nvar));
    put ("a07_onecold_var_frac", ratio (nco, nvar));
    put ("a07_onehot_groups_log", lg10p (ghot));
    put ("a07_onecold_groups_log", lg10p (gcold));
    put ("a07_eo_dir", ratio (nh - nco, nh + nco));
    free (hot), free (cold), free (bins.keys);
    (void) binneg_total, (void) binpos_total, (void) work;
  }
done:
  free (jp), free (jn), free (deg2), free (degs);
}

/*------------------------------------------------------------------------*/
// propagation engine (two watched literals) used by resid / bilat / graph

static signed char *val;     // per literal code: 1 true, -1 false, 0 unassigned
static int *trail;
static long trail_n, prop_head;
static int64_t **watches;    // per literal: clause ids watching it
static int *wn, *wcap;
static int root_conflict;
static char *rootsat;        // clause satisfied at root
static int *reslen;          // residual length at root (unassigned literals)
static int *layer;           // per trail position (bilat)
static int64_t prop_work;    // watch visits (bounded by callers)

static void watch_push (int L, int64_t c) {
  if (wn[L] == wcap[L]) {
    wcap[L] = wcap[L] ? 2 * wcap[L] : 4;
    watches[L] = realloc (watches[L], wcap[L] * sizeof **watches);
    if (!watches[L])
      die ("out of memory");
  }
  watches[L][wn[L]++] = c;
}

static inline void assign_lit (int L) {
  val[L] = 1, val[L ^ 1] = -1;
  trail[trail_n++] = L;
}

// Propagate from prop_head; returns 1 on conflict.  Stops early (returning
// 0 with prop_head < trail_n) when 'limit' trail literals exist.
static int propagate (long limit) {
  while (prop_head < trail_n) {
    if (trail_n >= limit)
      return 0;
    if (over ())
      return 0;
    const int L = trail[prop_head];
    const int lay = layer ? layer[prop_head] : 0;
    prop_head++;
    const int F = L ^ 1; // literal that became false
    int64_t *ws = watches[F];
    int i = 0, j = 0, n = wn[F];
    int conflict = 0;
    for (; i < n; i++) {
      int64_t c = ws[i];
      prop_work++;
      if (conflict) {
        ws[j++] = c;
        continue;
      }
      int *lits = cl + cs[c];
      int len = LEN (c);
      // keep the false literal at position 1
      if (lits[0] == F)
        lits[0] = lits[1], lits[1] = F;
      if (val[lits[0]] > 0) {
        ws[j++] = c;
        continue;
      }
      int k, found = 0;
      for (k = 2; k < len; k++)
        if (val[lits[k]] >= 0) {
          found = 1;
          break;
        }
      if (found) {
        int nl = lits[k];
        lits[k] = F, lits[1] = nl;
        watch_push (nl, c);
        continue; // dropped from ws
      }
      ws[j++] = c;
      if (val[lits[0]] < 0)
        conflict = 1;
      else {
        if (layer)
          layer[trail_n] = lay + 1;
        assign_lit (lits[0]);
      }
    }
    wn[F] = j;
    if (conflict)
      return 1;
  }
  return 0;
}

static void backtrack_to (long n) {
  while (trail_n > n) {
    int L = trail[--trail_n];
    val[L] = val[L ^ 1] = 0;
  }
  prop_head = n;
}

/*------------------------------------------------------------------------*/
// resid: root propagation, residual profile (B01 C01 C02 A04 A11)

static long nres_vars;       // unassigned variables occurring in the residual
static int *resvars;         // their indices
static long *resocc;         // residual occurrence count per variable
static int resid_ok;

// original-side summary values used for deltas
static double o_pos_frac, o_wpos_frac, o_horn, o_bal_mean, o_bin_frac;
static long o_vars;

static void sec_resid (void) {
  val = calloc (2 * nv + 2, 1);
  trail = malloc ((nv + 1) * sizeof *trail);
  watches = calloc (2 * nv + 2, sizeof *watches);
  wn = calloc (2 * nv + 2, sizeof *wn);
  wcap = calloc (2 * nv + 2, sizeof *wcap);
  rootsat = calloc (nc + 1, 1);
  reslen = calloc (nc + 1, sizeof *reslen);
  if (!val || !trail || !watches || !wn || !wcap || !rootsat || !reslen)
    die ("out of memory");
  // original-side summaries (deduplicated clauses)
  {
    double wp = 0, wn_ = 0;
    long lits = 0, plits = 0, horn = 0, bin = 0;
    for (int64_t c = 0; c < nc; c++) {
      int len = LEN (c), pos = 0;
      for (int64_t k = cs[c]; k < cs[c + 1]; k++)
        pos += !NEG (cl[k]);
      lits += len, plits += pos;
      horn += pos <= 1, bin += len == 2;
      wp += pos * pw2 (len), wn_ += (len - pos) * pw2 (len);
    }
    o_pos_frac = ratio (plits, lits);
    o_wpos_frac = ratio (wp, wp + wn_);
    o_horn = ratio (horn, nc);
    o_bin_frac = ratio (bin, nc);
    double sb = 0;
    long nvar = 0;
    for (long v = 1; v <= nv; v++) {
      long o = ostart[2 * v + 2] - ostart[2 * v];
      if (!o)
        continue;
      long p = ostart[2 * v + 1] - ostart[2 * v];
      sb += (double) (2 * p - o) / o, nvar++;
    }
    o_bal_mean = ratio (sb, nvar);
    o_vars = nvar;
  }
  // units first, then watches
  root_conflict = n_empty_in > 0;
  for (int64_t c = 0; c < nc && !root_conflict; c++) {
    if (LEN (c) == 1) {
      int L = cl[cs[c]];
      if (val[L] < 0)
        root_conflict = 1;
      else if (!val[L])
        assign_lit (L);
    } else {
      watch_push (cl[cs[c]], c);
      watch_push (cl[cs[c] + 1], c);
    }
    if (over ())
      return;
  }
  if (!root_conflict && propagate (1L << 62))
    root_conflict = 1;
  if (capped)
    return;
  put ("c01_root_conflict", root_conflict);
  long fixed = trail_n, fixed_pos = 0;
  for (long i = 0; i < trail_n; i++)
    fixed_pos += !NEG (trail[i]);
  put ("b01_fixed_frac", ratio (fixed, o_vars));
  put ("b01_fixed_pos_frac", ratio (fixed_pos, fixed));
  if (root_conflict)
    return;
  // residual clauses
  resocc = calloc (nv + 1, sizeof *resocc);
  long *rpos = calloc (nv + 1, sizeof *rpos);
  int64_t nres = 0, rlits = 0, rplits = 0, rbin = 0, rter = 0, rhorn = 0,
          ranti = 0, rallpos = 0, rallneg = 0, shortened = 0;
  double wp = 0, wn_ = 0, wall = 0, v0 = 0, v1 = 0;
  for (int64_t c = 0; c < nc; c++) {
    if (over ())
      return;
    int len = 0, pos = 0, sat = 0;
    for (int64_t k = cs[c]; k < cs[c + 1]; k++) {
      int L = cl[k];
      if (val[L] > 0) {
        sat = 1;
        break;
      }
      if (!val[L])
        len++, pos += !NEG (L);
    }
    if (sat) {
      rootsat[c] = 1;
      continue;
    }
    reslen[c] = len;
    nres++;
    shortened += len < LEN (c);
    rlits += len, rplits += pos;
    rbin += len == 2, rter += len == 3;
    rhorn += pos <= 1, ranti += len - pos <= 1;
    rallpos += pos == len, rallneg += pos == 0;
    double w = pw2 (len);
    wp += pos * w, wn_ += (len - pos) * w, wall += w;
    if (pos == len)
      v0 += w;
    if (pos == 0)
      v1 += w;
    for (int64_t k = cs[c]; k < cs[c + 1]; k++) {
      int L = cl[k];
      if (!val[L])
        resocc[VAR (L)]++, rpos[VAR (L)] += !NEG (L);
    }
  }
  resvars = malloc ((nv + 1) * sizeof *resvars);
  nres_vars = 0;
  double sb = 0, sab = 0, msb = 0, msab = 0;
  long pure = 0, mixed = 0;
  for (long v = 1; v <= nv; v++) {
    if (!resocc[v])
      continue;
    resvars[nres_vars++] = (int) v;
    double b = (double) (2 * rpos[v] - resocc[v]) / resocc[v];
    sb += b, sab += fabs (b);
    if (rpos[v] == 0 || rpos[v] == resocc[v])
      pure++;
    else
      mixed++, msb += b, msab += fabs (b);
  }
  free (rpos);
  put ("c01_res_vars_log", lg10p (nres_vars));
  put ("c01_res_clauses_log", lg10p (nres));
  put ("c01_res_cv_ratio", ratio (nres, nres_vars));
  put ("c01_res_len_mean", ratio (rlits, nres));
  put ("c01_res_bin_frac", ratio (rbin, nres));
  put ("c01_res_ter_frac", ratio (rter, nres));
  put ("c01_res_pos_frac", ratio (rplits, rlits));
  put ("c01_res_wpos_frac", ratio (wp, wp + wn_));
  put ("c01_res_horn_frac", ratio (rhorn, nres));
  put ("c01_res_antihorn_frac", ratio (ranti, nres));
  put ("c01_res_allpos_frac", ratio (rallpos, nres));
  put ("c01_res_allneg_frac", ratio (rallneg, nres));
  put ("c01_res_bal_mean", ratio (sb, nres_vars));
  put ("c01_res_absbal_mean", ratio (sab, nres_vars));
  put ("c01_res_pure_frac", ratio (pure, nres_vars));
  put ("a04_res_viol0_w", ratio (v0, wall));
  put ("a04_res_viol1_w", ratio (v1, wall));
  put ("a11_mixed_bal_mean", ratio (msb, mixed));
  put ("a11_mixed_absbal_mean", ratio (msab, mixed));
  put ("c02_vars_ratio", ratio (nres_vars, o_vars));
  put ("c02_clauses_ratio", ratio (nres, nc));
  put ("c02_shortened_frac", ratio (shortened, nres));
  put ("c02_pos_frac_delta", ratio (rplits, rlits) - o_pos_frac);
  put ("c02_wpos_frac_delta", ratio (wp, wp + wn_) - o_wpos_frac);
  put ("c02_horn_delta", ratio (rhorn, nres) - o_horn);
  put ("c02_bin_delta", ratio (rbin, nres) - o_bin_frac);
  put ("c02_bal_delta", ratio (sb, nres_vars) - o_bal_mean);
  resid_ok = 1;
}

/*------------------------------------------------------------------------*/
// variable sample shared by bilat and graph: 16 highest residual
// occurrence + 16 uniformly random others (fixed seed)

static int sample_vars[32];
static int nsample;

static int cmp_occ_desc (const void *a, const void *b) {
  int x = *(const int *) a, y = *(const int *) b;
  if (resocc[x] != resocc[y])
    return resocc[x] > resocc[y] ? -1 : 1;
  return x < y ? -1 : x > y;
}

static int *occ_order; // residual variables by decreasing occurrence

static uint64_t base_seed;

static void make_sample (void) {
  if (nsample || !nres_vars)
    return;
  rng_state = base_seed; // same sample whichever sections run
  occ_order = malloc (nres_vars * sizeof *occ_order);
  memcpy (occ_order, resvars, nres_vars * sizeof *occ_order);
  qsort (occ_order, nres_vars, sizeof *occ_order, cmp_occ_desc);
  if (nres_vars <= 32) {
    for (long i = 0; i < nres_vars; i++)
      sample_vars[nsample++] = occ_order[i];
    return;
  }
  for (int i = 0; i < 16; i++)
    sample_vars[nsample++] = occ_order[i];
  // random others: positions 16.. of occ_order, without repetition
  for (int tries = 0; nsample < 32 && tries < 10000; tries++) {
    long p = 16 + (long) (rnd () % (uint64_t) (nres_vars - 16));
    int v = occ_order[p], dup = 0;
    for (int i = 16; i < nsample; i++)
      dup |= sample_vars[i] == v;
    if (!dup)
      sample_vars[nsample++] = v;
  }
}

/*------------------------------------------------------------------------*/
// bilat: two-sided bounded BCP (B02-B05) and greedy uniform-sign paths
// (B07, B10)

#define BL_PROP_LIMIT 20000
#define BL_OCC_LIMIT 4000000

typedef struct {
  int failed, layers;
  long props;
  double sat, newbin, wred;
  int truncated;
} Side;

static int *falsecnt;
static int64_t *satstamp;
static int64_t epoch;
static int64_t *touched;
static int64_t ntouched, ctouched;

static void touch (int64_t c) {
  if (ntouched == ctouched) {
    ctouched = ctouched ? 2 * ctouched : 1024;
    touched = realloc (touched, ctouched * sizeof *touched);
  }
  touched[ntouched++] = c;
}

static Side probe_side (int L) {
  Side s = {0};
  long root = trail_n;
  layer[trail_n] = 0;
  assign_lit (L);
  s.failed = propagate (root + BL_PROP_LIMIT);
  s.truncated = prop_head < trail_n && !s.failed;
  s.props = trail_n - root - 1;
  int maxl = 0;
  for (long i = root; i < trail_n; i++)
    if (layer[i] > maxl)
      maxl = layer[i];
  s.layers = maxl;
  if (!s.failed) {
    epoch++;
    ntouched = 0;
    int64_t work = 0;
    for (long i = root; i < trail_n && work < BL_OCC_LIMIT; i++) {
      int T = trail[i];
      for (int64_t k = ostart[T]; k < ostart[T + 1]; k++, work++) {
        int64_t c = occ[k];
        if (rootsat[c] || satstamp[c] == epoch)
          continue;
        satstamp[c] = epoch;
        s.sat += 1;
      }
      int F = T ^ 1;
      for (int64_t k = ostart[F]; k < ostart[F + 1]; k++, work++) {
        int64_t c = occ[k];
        if (rootsat[c])
          continue;
        if (!falsecnt[c])
          touch (c);
        falsecnt[c]++;
      }
    }
    if (work >= BL_OCC_LIMIT)
      s.truncated = 1;
    for (int64_t t = 0; t < ntouched; t++) {
      int64_t c = touched[t];
      if (satstamp[c] != epoch) {
        int rem = reslen[c] - falsecnt[c];
        if (rem == 2)
          s.newbin += 1;
        s.wred += pw2 (rem) - pw2 (reslen[c]);
      }
      falsecnt[c] = 0;
    }
  }
  backtrack_to (root);
  return s;
}

static void sec_bilat (void) {
  layer = malloc ((nv + 2) * sizeof *layer);
  falsecnt = calloc (nc + 1, sizeof *falsecnt);
  satstamp = calloc (nc + 1, sizeof *satstamp);
  if (!layer || !falsecnt || !satstamp)
    die ("out of memory");
  make_sample ();
  long n = 0, failp = 0, failn = 0, failany = 0, both_ok = 0, posgt = 0,
       trunc = 0;
  double lr = 0, alr = 0, ldiff = 0, plog = 0, satlr = 0, binlr = 0,
         wredlr = 0, lr_top = 0;
  long n_top = 0;
  for (int i = 0; i < nsample && !capped; i++) {
    int v = sample_vars[i];
    Side P = probe_side (2 * v), N = probe_side (2 * v + 1);
    if (capped)
      break;
    n++;
    failp += P.failed, failn += N.failed, failany += P.failed || N.failed;
    trunc += P.truncated + N.truncated;
    plog += lg10p (P.props) + lg10p (N.props);
    if (!P.failed && !N.failed) {
      both_ok++;
      double r = log2 ((1.0 + P.props) / (1.0 + N.props));
      lr += r, alr += fabs (r), posgt += P.props > N.props;
      ldiff += P.layers - N.layers;
      satlr += log2 ((1.0 + P.sat) / (1.0 + N.sat));
      binlr += log2 ((1.0 + P.newbin) / (1.0 + N.newbin));
      wredlr += log2 ((1e-3 + P.wred) / (1e-3 + N.wred));
      if (i < 16)
        lr_top += r, n_top++;
    }
  }
  if (capped)
    return;
  put ("b02_n_sampled", n);
  put ("b02_fail_pos_frac", ratio (failp, n));
  put ("b02_fail_neg_frac", ratio (failn, n));
  put ("b02_fail_any_frac", ratio (failany, n));
  put ("b03_props_lr_mean", ratio (lr, both_ok));
  put ("b03_props_lr_absmean", ratio (alr, both_ok));
  put ("b03_props_pos_gt_frac", ratio (posgt, both_ok));
  put ("b03_props_lr_top16", ratio (lr_top, n_top));
  put ("b03_layers_diff_mean", ratio (ldiff, both_ok));
  put ("b03_props_log_mean", ratio (plog, 2 * n));
  put ("b05_sat_lr_mean", ratio (satlr, both_ok));
  put ("b05_newbin_lr_mean", ratio (binlr, both_ok));
  put ("b05_wred_lr_mean", ratio (wredlr, both_ok));
  put ("b02_truncated_frac", ratio (trunc, 2 * n));
  // B07 / B10: greedy uniform-sign paths along decreasing occurrence
  for (int sgn = 0; sgn < 2 && !capped; sgn++) {
    long root = trail_n, d = 0, conf_depth = -1, opp = 0, implied = 0;
    double a4 = NAN, a16 = NAN, a64 = NAN, af_last = 0;
    long idx = 0;
    while (d < 64 && !capped) {
      while (idx < nres_vars && val[2 * occ_order[idx]])
        idx++;
      if (idx >= nres_vars)
        break;
      int L = 2 * occ_order[idx] + sgn;
      long before = trail_n;
      layer[trail_n] = 0;
      assign_lit (L);
      d++;
      int conf = propagate (1L << 62);
      for (long i = before + 1; i < trail_n; i++)
        implied++, opp += NEG (trail[i]) != sgn;
      if (conf) {
        conf_depth = d;
        break;
      }
      double af = ratio (trail_n - root, nres_vars);
      af_last = af;
      if (d == 4)
        a4 = af;
      if (d == 16)
        a16 = af;
      if (d == 64)
        a64 = af;
    }
    if (!capped && (conf_depth > 0 || idx >= nres_vars)) {
      // the path stopped early (conflict, or nothing left to decide): the
      // later depths keep the coverage reached before stopping
      if (isnan (a4))
        a4 = af_last;
      if (isnan (a16))
        a16 = af_last;
      if (isnan (a64))
        a64 = af_last;
    }
    backtrack_to (root);
    if (capped)
      break;
    const char *s = sgn ? "neg" : "pos";
    char name[48];
    snprintf (name, sizeof name, "b07_confdepth_%s_log2", s);
    put (name, log2 (conf_depth > 0 ? (double) conf_depth : 65.0));
    snprintf (name, sizeof name, "b07_asg4_%s", s);
    put (name, a4);
    snprintf (name, sizeof name, "b07_asg16_%s", s);
    put (name, a16);
    snprintf (name, sizeof name, "b07_asg64_%s", s);
    put (name, a64);
    snprintf (name, sizeof name, "b10_opp_frac_%s", s);
    put (name, ratio (opp, implied));
  }
}

/*------------------------------------------------------------------------*/
// graph: binary implication graph of the residual (D01 D02 C04), variable
// components (D03), hub polarity (D07)

static int64_t *bstart, *badj; // CSR over literal codes

static void sec_graph (void) {
  make_sample ();
  long NL = 2 * nv + 2;
  bstart = calloc (NL + 1, sizeof *bstart);
  int64_t nedges = 0;
  for (int64_t c = 0; c < nc; c++) {
    if (rootsat[c] || reslen[c] != 2)
      continue;
    int a = -1, b = -1;
    for (int64_t k = cs[c]; k < cs[c + 1]; k++)
      if (!val[cl[k]]) {
        if (a < 0)
          a = cl[k];
        else
          b = cl[k];
      }
    bstart[(a ^ 1) + 1]++, bstart[(b ^ 1) + 1]++;
    nedges += 2;
    if (over ())
      return;
  }
  for (long L = 0; L < NL; L++)
    bstart[L + 1] += bstart[L];
  badj = malloc ((nedges + 1) * sizeof *badj);
  int64_t *fill = malloc ((NL + 1) * sizeof *fill);
  memcpy (fill, bstart, (NL + 1) * sizeof *fill);
  long pos_edges = 0;
  for (int64_t c = 0; c < nc; c++) {
    if (rootsat[c] || reslen[c] != 2)
      continue;
    int a = -1, b = -1;
    for (int64_t k = cs[c]; k < cs[c + 1]; k++)
      if (!val[cl[k]]) {
        if (a < 0)
          a = cl[k];
        else
          b = cl[k];
      }
    badj[fill[a ^ 1]++] = b, badj[fill[b ^ 1]++] = a;
    pos_edges += !NEG (a) + !NEG (b);
  }
  free (fill);
  put ("d01_big_edges_per_var", ratio (nedges, nres_vars));
  put ("d01_big_pos_target_frac", ratio (pos_edges, nedges));
  // D01: bounded BFS reach from both literals of the sampled variables
  {
    int *seen = calloc (NL, sizeof *seen), *queue = malloc (5001 * sizeof *queue);
    int stamp = 0;
    double rl = 0, rlr = 0;
    long n = 0, posgt = 0, fail = 0, sides = 0;
    for (int i = 0; i < nsample && !over (); i++) {
      long reach[2];
      for (int s = 0; s < 2; s++) {
        int L = 2 * sample_vars[i] + s;
        stamp++;
        long qh = 0, qt = 0;
        queue[qt++] = L;
        seen[L] = stamp;
        int contra = 0;
        while (qh < qt && qt < 5000) {
          int x = queue[qh++];
          for (int64_t k = bstart[x]; k < bstart[x + 1] && qt < 5000; k++) {
            int y = (int) badj[k];
            if (seen[y] == stamp)
              continue;
            seen[y] = stamp;
            queue[qt++] = y;
            if (y == (L ^ 1))
              contra = 1;
          }
        }
        reach[s] = qt - 1;
        fail += contra, sides++;
      }
      n++;
      rl += lg10p (reach[0]) + lg10p (reach[1]);
      rlr += log2 ((1.0 + reach[0]) / (1.0 + reach[1]));
      posgt += reach[0] > reach[1];
    }
    free (seen), free (queue);
    if (capped)
      return;
    put ("d01_reach_log_mean", ratio (rl, 2 * n));
    put ("d01_reach_lr_mean", ratio (rlr, n));
    put ("d01_reach_pos_gt_frac", ratio (posgt, n));
    put ("d01_big_fail_frac", ratio (fail, sides));
  }
  // D02 / C04: Tarjan SCC (iterative) over literal nodes
  {
    int *index = malloc (NL * sizeof *index), *low = malloc (NL * sizeof *low);
    int *stack = malloc (NL * sizeof *stack), *comp = malloc (NL * sizeof *comp);
    char *onst = calloc (NL, 1);
    int64_t *iter = malloc (NL * sizeof *iter);
    int *cstack = malloc (NL * sizeof *cstack);
    for (long L = 0; L < NL; L++)
      index[L] = -1, comp[L] = -1;
    int idx = 0, sp = 0, ncomp = 0;
    long nontriv_lits = 0, maxscc = 0, mixed = 0, members = 0;
    int contra = 0;
    int *csize = NULL;
    for (long r = 2; r < NL && !capped; r++) {
      if (index[r] >= 0 || bstart[r] == bstart[r + 1])
        continue;
      int csp = 0;
      cstack[csp++] = (int) r;
      index[r] = low[r] = idx++;
      iter[r] = bstart[r];
      stack[sp++] = (int) r, onst[r] = 1;
      while (csp > 0) {
        if (over ())
          break;
        int x = cstack[csp - 1];
        if (iter[x] < bstart[x + 1]) {
          int y = (int) badj[iter[x]++];
          if (index[y] < 0) {
            index[y] = low[y] = idx++;
            iter[y] = bstart[y];
            stack[sp++] = y, onst[y] = 1;
            cstack[csp++] = y;
          } else if (onst[y] && index[y] < low[x])
            low[x] = index[y];
        } else {
          csp--;
          if (csp > 0) {
            int p = cstack[csp - 1];
            if (low[x] < low[p])
              low[p] = low[x];
          }
          if (low[x] == index[x]) {
            long size = 0, pos = 0;
            int y;
            do {
              y = stack[--sp];
              onst[y] = 0;
              comp[y] = ncomp;
              size++, pos += !NEG (y);
            } while (y != x);
            if (size > 1) {
              nontriv_lits += size;
              mixed += pos < size - pos ? pos : size - pos;
              members += size;
            }
            if (size > maxscc)
              maxscc = size;
            ncomp++;
          }
        }
      }
    }
    if (!capped)
      for (long v = 1; v <= nv; v++)
        if (comp[2 * v] >= 0 && comp[2 * v] == comp[2 * v + 1])
          contra = 1;
    free (index), free (low), free (stack), free (comp), free (onst),
        free (iter), free (cstack), free (csize);
    if (capped)
      return;
    put ("d02_scc_nontriv_lit_frac", ratio (nontriv_lits, 2.0 * nres_vars));
    put ("d02_scc_max_frac", ratio (maxscc, 2.0 * nres_vars));
    put ("d02_contradiction", contra);
    put ("c04_equiv_var_frac", ratio (nontriv_lits / 2.0, nres_vars));
    put ("c04_inverse_share", ratio (mixed, members));
  }
  // D03: components of the residual variable-clause graph (union-find)
  {
    int *parent = malloc ((nv + 1) * sizeof *parent);
    for (long v = 0; v <= nv; v++)
      parent[v] = (int) v;
#define FIND(x)                                                              \
  ({                                                                         \
    int _x = (x);                                                            \
    while (parent[_x] != _x)                                                 \
      parent[_x] = parent[parent[_x]], _x = parent[_x];                      \
    _x;                                                                      \
  })
    for (int64_t c = 0; c < nc && !over (); c++) {
      if (rootsat[c])
        continue;
      int first = -1;
      for (int64_t k = cs[c]; k < cs[c + 1]; k++) {
        if (val[cl[k]])
          continue;
        int v = VAR (cl[k]);
        if (first < 0)
          first = FIND (v);
        else {
          int r = FIND (v);
          if (r != first)
            parent[r] = first;
        }
      }
    }
    if (capped) {
      free (parent);
      return;
    }
    long *csz = calloc (nv + 1, sizeof *csz);
    double *cbal = calloc (nv + 1, sizeof *cbal), *cocc = calloc (nv + 1, sizeof *cocc);
    long npos_all = 0, nocc_all = 0;
    for (long i = 0; i < nres_vars; i++) {
      int v = resvars[i], r = FIND (v);
      csz[r]++;
      long p = 0;
      for (int64_t k = ostart[2 * v]; k < ostart[2 * v + 1]; k++)
        p += !rootsat[occ[k]];
      long o = resocc[v];
      cbal[r] += 2 * p - o, cocc[r] += o;
      npos_all += p, nocc_all += o;
    }
    long ncomp = 0, maxc = 0, small = 0, oppo = 0;
    double gbal = ratio (2.0 * npos_all - nocc_all, nocc_all), wsum = 0, wb = 0, wb2 = 0;
    for (long v = 1; v <= nv; v++) {
      if (!csz[v])
        continue;
      ncomp++;
      if (csz[v] > maxc)
        maxc = csz[v];
      if (csz[v] < 10)
        small += csz[v];
      double b = cbal[v] / cocc[v];
      wsum += cocc[v], wb += cocc[v] * b, wb2 += cocc[v] * b * b;
      if (fabs (b) > 0.05 && fabs (gbal) > 0.05 && (b > 0) != (gbal > 0))
        oppo += csz[v];
    }
    double m = ratio (wb, wsum);
    put ("d03_ncomp_log", lg10p (ncomp));
    put ("d03_maxcomp_frac", ratio (maxc, nres_vars));
    put ("d03_small_comp_var_frac", ratio (small, nres_vars));
    put ("d03_comp_bal_wstd", wsum > 0 ? sqrt (fmax (0, wb2 / wsum - m * m)) : NAN);
    put ("d03_comp_oppo_var_frac", ratio (oppo, nres_vars));
    free (csz), free (cbal), free (cocc), free (parent);
  }
  // D07: polarity of BIG hubs (top 1% by implication degree, >= 10)
  {
    long n = nres_vars;
    double *deg = malloc ((n + 1) * sizeof *deg), *tmp = malloc ((n + 1) * sizeof *tmp);
    for (long i = 0; i < n; i++) {
      int v = resvars[i];
      deg[i] = (double) (bstart[2 * v + 1] - bstart[2 * v] + bstart[2 * v + 2] - bstart[2 * v + 1]);
      tmp[i] = deg[i];
    }
    qsort (tmp, n, sizeof *tmp, cmp_double);
    long k = n / 100 > 10 ? n / 100 : (n < 10 ? n : 10);
    double thr = n ? tmp[n - k] : 0;
    double hb = 0, ab = 0;
    long nh = 0;
    for (long i = 0; i < n; i++) {
      int v = resvars[i];
      long p = 0;
      for (int64_t q = ostart[2 * v]; q < ostart[2 * v + 1]; q++)
        p += !rootsat[occ[q]];
      double b = (double) (2 * p - resocc[v]) / resocc[v];
      ab += b;
      if (deg[i] >= thr && deg[i] > 0)
        hb += b, nh++;
    }
    put ("d07_hub_bal_mean", ratio (hb, nh));
    put ("d07_hub_minus_all_bal", ratio (hb, nh) - ratio (ab, n));
    free (deg), free (tmp);
  }
}

/*------------------------------------------------------------------------*/
// comm: label propagation communities (D04, A12), signed pair types
// (D05), sign-aware WL colours (D10) on the residual

#define COMM_MAXLEN 8

static int cmp_u64 (const void *a, const void *b) {
  uint64_t x = *(const uint64_t *) a, y = *(const uint64_t *) b;
  return x < y ? -1 : x > y;
}

static void sec_comm (void) {
  int *label = malloc ((nv + 1) * sizeof *label);
  for (long v = 0; v <= nv; v++)
    label[v] = (int) v;
  double *cnt = calloc (nv + 1, sizeof *cnt);
  int *cand = malloc ((nv + 1) * sizeof *cand);
  int64_t short_cls = 0, all_cls = 0;
  for (int64_t c = 0; c < nc; c++)
    if (!rootsat[c]) {
      all_cls++;
      short_cls += reslen[c] <= COMM_MAXLEN;
    }
  for (int round = 0; round < 3 && !capped; round++) {
    for (long i = 0; i < nres_vars && !over (); i++) {
      int v = resvars[i], nc_ = 0;
      for (int s = 0; s < 2; s++) {
        int L = 2 * v + s;
        for (int64_t k = ostart[L]; k < ostart[L + 1]; k++) {
          int64_t c = occ[k];
          if (rootsat[c] || reslen[c] > COMM_MAXLEN)
            continue;
          for (int64_t q = cs[c]; q < cs[c + 1]; q++) {
            int u = VAR (cl[q]);
            if (u == v || val[cl[q]])
              continue;
            int lab = label[u];
            if (cnt[lab] == 0)
              cand[nc_++] = lab;
            cnt[lab] += 1.0;
          }
        }
      }
      int best = label[v];
      double bc = nc_ ? cnt[best] : 0;
      for (int j = 0; j < nc_; j++) {
        int lab = cand[j];
        if (cnt[lab] > bc || (cnt[lab] == bc && lab < best))
          best = lab, bc = cnt[lab];
      }
      for (int j = 0; j < nc_; j++)
        cnt[cand[j]] = 0;
      label[v] = best;
    }
  }
  free (cand);
  if (capped) {
    free (label), free (cnt);
    return;
  }
  // community sizes and polarity
  long *csz = calloc (nv + 1, sizeof *csz);
  double *cb = calloc (nv + 1, sizeof *cb), *co = calloc (nv + 1, sizeof *co);
  long npos_all = 0, nocc_all = 0;
  for (long i = 0; i < nres_vars; i++) {
    int v = resvars[i], r = label[v];
    long p = 0;
    for (int64_t q = ostart[2 * v]; q < ostart[2 * v + 1]; q++)
      p += !rootsat[occ[q]];
    csz[r]++;
    cb[r] += 2 * p - resocc[v], co[r] += resocc[v];
    npos_all += p, nocc_all += resocc[v];
  }
  double gbal = ratio (2.0 * npos_all - nocc_all, nocc_all);
  long ncomm = 0, maxc = 0, oppo = 0;
  double wabs = 0, wsum = 0;
  for (long v = 1; v <= nv; v++) {
    if (!csz[v])
      continue;
    ncomm++;
    if (csz[v] > maxc)
      maxc = csz[v];
    double b = cb[v] / co[v];
    wabs += co[v] * fabs (b), wsum += co[v];
    if (fabs (b) > 0.1 && fabs (gbal) > 0.05 && (b > 0) != (gbal > 0))
      oppo += csz[v];
  }
  // intra-community short clauses, signed pair types (D05)
  long intra = 0;
  double pp = 0, pn = 0, nn = 0, xpp = 0, xpn = 0, xnn = 0;
  for (int64_t c = 0; c < nc && !over (); c++) {
    if (rootsat[c] || reslen[c] > COMM_MAXLEN)
      continue;
    int lab = -1, same = 1;
    int lits[COMM_MAXLEN], k = 0;
    for (int64_t q = cs[c]; q < cs[c + 1]; q++) {
      if (val[cl[q]])
        continue;
      lits[k++] = cl[q];
      int l = label[VAR (cl[q])];
      if (lab < 0)
        lab = l;
      else if (l != lab)
        same = 0;
    }
    intra += same;
    for (int i = 0; i < k; i++)
      for (int j = i + 1; j < k; j++) {
        int a = NEG (lits[i]), b = NEG (lits[j]);
        int cross = label[VAR (lits[i])] != label[VAR (lits[j])];
        if (!a && !b)
          cross ? (xpp += 1) : (pp += 1);
        else if (a && b)
          cross ? (xnn += 1) : (nn += 1);
        else
          cross ? (xpn += 1) : (pn += 1);
      }
  }
  if (capped) {
    free (label), free (cnt), free (csz), free (cb), free (co);
    return;
  }
  put ("d04_comm_coverage", ratio (short_cls, all_cls));
  put ("d04_ncomm_rel_log", log10 (ratio (ncomm, nres_vars) + 1e-9));
  put ("d04_maxcomm_frac", ratio (maxc, nres_vars));
  put ("d04_intra_clause_frac", ratio (intra, short_cls));
  put ("a12_comm_absbal_wmean", ratio (wabs, wsum));
  put ("a12_comm_minus_global_absbal", ratio (wabs, wsum) - fabs (gbal));
  put ("a12_comm_oppo_var_frac", ratio (oppo, nres_vars));
  {
    double tot = pp + pn + nn + xpp + xpn + xnn;
    double p = ratio (2 * (pp + xpp) + pn + xpn, 2 * tot);
    double e = p * p + (1 - p) * (1 - p);
    double same = ratio (pp + nn + xpp + xnn, tot);
    put ("d05_assort", ratio (same - e, 1 - e));
    put ("d05_pp_excess", ratio (pp + xpp, tot) - p * p);
    double tin = pp + pn + nn, tx = xpp + xpn + xnn;
    put ("d05_assort_intra_minus_cross", ratio (pp + nn, tin) - ratio (xpp + xnn, tx));
  }
  free (csz), free (cb), free (co), free (cnt), free (label);
  // D10: sign-aware WL on the residual variable-clause graph, computed for
  // the formula and its global sign flip in parallel
  {
    uint64_t *vc = malloc ((nv + 1) * sizeof *vc), *vf = malloc ((nv + 1) * sizeof *vf);
    uint64_t *cc = malloc ((nc + 1) * sizeof *cc), *cf = malloc ((nc + 1) * sizeof *cf);
    uint64_t *nvc = malloc ((nv + 1) * sizeof *nvc), *nvf = malloc ((nv + 1) * sizeof *nvf);
    for (long v = 0; v <= nv; v++)
      vc[v] = vf[v] = 1;
    for (int64_t c = 0; c < nc; c++)
      cc[c] = cf[c] = mix64 (0x1234 + (uint64_t) reslen[c]);
    double sym1 = NAN, sym2 = NAN, dist2 = NAN, ent2 = NAN;
    for (int round = 1; round <= 2 && !capped; round++) {
      // variables from clauses
      for (long i = 0; i < nres_vars && !over (); i++) {
        int v = resvars[i];
        uint64_t sc = 0, sf = 0;
        for (int s = 0; s < 2; s++) {
          int L = 2 * v + s;
          for (int64_t k = ostart[L]; k < ostart[L + 1]; k++) {
            int64_t c = occ[k];
            if (rootsat[c])
              continue;
            sc += mix64 (cc[c] * 2 + (uint64_t) s);
            sf += mix64 (cf[c] * 2 + (uint64_t) (1 - s));
          }
        }
        nvc[v] = mix64 (vc[v] ^ mix64 (sc + 0x51));
        nvf[v] = mix64 (vf[v] ^ mix64 (sf + 0x51));
      }
      if (capped)
        break;
      long same = 0;
      for (long i = 0; i < nres_vars; i++) {
        int v = resvars[i];
        vc[v] = nvc[v], vf[v] = nvf[v];
        same += vc[v] == vf[v];
      }
      if (round == 1)
        sym1 = ratio (same, nres_vars);
      else
        sym2 = ratio (same, nres_vars);
      if (round == 2)
        break;
      // clauses from variables
      for (int64_t c = 0; c < nc && !over (); c++) {
        if (rootsat[c])
          continue;
        uint64_t sc = 0, sf = 0;
        for (int64_t q = cs[c]; q < cs[c + 1]; q++) {
          int L = cl[q];
          if (val[L])
            continue;
          sc += mix64 (vc[VAR (L)] * 2 + (uint64_t) NEG (L));
          sf += mix64 (vf[VAR (L)] * 2 + (uint64_t) (1 - NEG (L)));
        }
        cc[c] = mix64 (cc[c] ^ mix64 (sc + 0x77));
        cf[c] = mix64 (cf[c] ^ mix64 (sf + 0x77));
      }
    }
    if (!capped) {
      uint64_t *tmp = malloc ((nres_vars + 1) * sizeof *tmp);
      for (long i = 0; i < nres_vars; i++)
        tmp[i] = vc[resvars[i]];
      qsort (tmp, nres_vars, sizeof *tmp, cmp_u64);
      long distinct = 0, run = 0;
      double ent = 0;
      for (long i = 0; i < nres_vars; i++) {
        run++;
        if (i + 1 == nres_vars || tmp[i + 1] != tmp[i]) {
          distinct++;
          double p = (double) run / nres_vars;
          ent -= p * log (p);
          run = 0;
        }
      }
      dist2 = ratio (distinct, nres_vars);
      ent2 = nres_vars > 1 ? ent / log ((double) nres_vars) : NAN;
      free (tmp);
      put ("d10_wl1_sign_sym_frac", sym1);
      put ("d10_wl2_sign_sym_frac", sym2);
      put ("d10_wl2_distinct_frac", dist2);
      put ("d10_wl2_entropy_norm", ent2);
    }
    free (vc), free (vf), free (cc), free (cf), free (nvc), free (nvf);
  }
}

/*------------------------------------------------------------------------*/
// ls: probSAT (break-only, polynomial) on the residual from three starts

#define LS_FLIPS 200000
#define LS_START_CAP 0.2

static void sec_ls (void) {
  // compact residual formula
  long n = nres_vars;
  int *vmap = malloc ((nv + 1) * sizeof *vmap);
  for (long i = 0; i < n; i++)
    vmap[resvars[i]] = (int) i;
  int64_t m = 0, nl = 0;
  for (int64_t c = 0; c < nc; c++)
    if (!rootsat[c])
      m++, nl += reslen[c];
  int *lits = malloc ((nl + 1) * sizeof *lits);
  int64_t *st = malloc ((m + 1) * sizeof *st);
  char *allpos = malloc (m + 1);
  int64_t j = 0, k = 0;
  for (int64_t c = 0; c < nc; c++) {
    if (rootsat[c])
      continue;
    st[j] = k;
    int pos = 0, len = 0;
    for (int64_t q = cs[c]; q < cs[c + 1]; q++)
      if (!val[cl[q]]) {
        lits[k++] = 2 * vmap[VAR (cl[q])] + NEG (cl[q]);
        pos += !NEG (cl[q]), len++;
      }
    allpos[j] = pos == len ? 1 : pos == 0 ? 2 : 0;
    j++;
  }
  st[m] = k;
  int64_t *os = calloc (2 * n + 2, sizeof *os), *oc = malloc ((nl + 1) * sizeof *oc);
  for (int64_t q = 0; q < nl; q++)
    os[lits[q] + 1]++;
  for (long L = 0; L < 2 * n + 1; L++)
    os[L + 1] += os[L];
  int64_t *fill = malloc ((2 * n + 2) * sizeof *fill);
  memcpy (fill, os, (2 * n + 2) * sizeof *fill);
  for (int64_t c = 0; c < m; c++)
    for (int64_t q = st[c]; q < st[c + 1]; q++)
      oc[fill[lits[q]]++] = c;
  free (fill);
  int *ntrue = malloc ((m + 1) * sizeof *ntrue);
  int64_t *ulist = malloc ((m + 1) * sizeof *ulist), *upos = malloc ((m + 1) * sizeof *upos);
  char *a = malloc (n + 1);
  char *fin[3];
  double cb = 2.3, probs[256];
  for (int b = 0; b < 256; b++)
    probs[b] = pow (1.0 + b, -cb);
  double best_log[3], d1k[3], dens[3], stall[3];
  rng_state = mix64 (base_seed + 7); // independent of the other sections
  long unsat_pos = 0, unsat_neg = 0, unsat_tot = 0, unsat_len = 0;
  int solved = 0;
  for (int s = 0; s < 3 && !capped; s++) {
    double t0 = fast_cpu ();
    for (long v = 0; v < n; v++)
      a[v] = s == 0 ? 0 : s == 1 ? 1 : (char) (rnd () & 1);
    int64_t nu = 0;
    for (int64_t c = 0; c < m; c++) {
      int t = 0;
      for (int64_t q = st[c]; q < st[c + 1]; q++) {
        int L = lits[q];
        t += a[L >> 1] != (L & 1);
      }
      ntrue[c] = t;
      if (!t)
        upos[c] = nu, ulist[nu++] = c;
    }
    int64_t u0 = nu, best = nu, best_flip = 0, at1k = -1;
    long f;
    int stop = 0;
    for (f = 0; f < LS_FLIPS && nu > 0 && !stop; f++) {
      if (!(f & 255)) {
        double t = fast_cpu ();
        if (t - t0 > LS_START_CAP)
          stop = 1;
        if (t - sec_start > sec_cap || t > total_cap)
          capped = 1, stop = 1;
        if (stop)
          break;
      }
      int64_t c = ulist[rnd () % (uint64_t) nu];
      int len = (int) (st[c + 1] - st[c]);
      double sum = 0, pr[64];
      int cand = len < 64 ? len : 64;
      for (int i = 0; i < cand; i++) {
        int L = lits[st[c] + i], v = L >> 1;
        int TL = 2 * v + (a[v] ? 0 : 1); // currently true literal of v
        long br = 0;
        for (int64_t q = os[TL]; q < os[TL + 1]; q++)
          br += ntrue[oc[q]] == 1;
        pr[i] = probs[br < 255 ? br : 255];
        sum += pr[i];
      }
      double r = rnd01 () * sum;
      int pick = cand - 1;
      for (int i = 0; i < cand; i++) {
        r -= pr[i];
        if (r <= 0) {
          pick = i;
          break;
        }
      }
      int v = lits[st[c] + pick] >> 1;
      int TL = 2 * v + (a[v] ? 0 : 1), FL = TL ^ 1;
      a[v] = !a[v];
      for (int64_t q = os[TL]; q < os[TL + 1]; q++) {
        int64_t d = oc[q];
        if (--ntrue[d] == 0)
          upos[d] = nu, ulist[nu++] = d;
      }
      for (int64_t q = os[FL]; q < os[FL + 1]; q++) {
        int64_t d = oc[q];
        if (ntrue[d]++ == 0) {
          int64_t last = ulist[--nu];
          ulist[upos[d]] = last, upos[last] = upos[d];
        }
      }
      if (nu < best)
        best = nu, best_flip = f + 1;
      if (f + 1 == 1000)
        at1k = nu;
    }
    if (capped)
      break;
    solved |= best == 0;
    best_log[s] = log10 (1.0 + (double) best);
    d1k[s] = u0 == 0 ? NAN : at1k >= 0 ? 1.0 - (double) at1k / u0 : nu == 0 ? 1.0 : NAN;
    stall[s] = f > 0 ? 1.0 - (double) best_flip / f : NAN;
    long ones = 0;
    for (long v = 0; v < n; v++)
      ones += a[v];
    dens[s] = ratio (ones, n);
    for (int64_t i = 0; i < nu; i++) {
      int64_t c = ulist[i];
      unsat_tot++;
      unsat_pos += allpos[c] == 1, unsat_neg += allpos[c] == 2;
      unsat_len += st[c + 1] - st[c];
    }
    fin[s] = malloc (n + 1);
    memcpy (fin[s], a, n);
  }
  if (!capped) {
    put ("g01_best_zero_log", best_log[0]);
    put ("g01_best_one_log", best_log[1]);
    put ("g01_best_rand_log", best_log[2]);
    put ("g01_zero_minus_one_log", best_log[0] - best_log[1]);
    put ("g02_descent1k_zero", d1k[0]);
    put ("g02_descent1k_one", d1k[1]);
    put ("g02_descent1k_rand", d1k[2]);
    put ("g02_stall_mean", (stall[0] + stall[1] + stall[2]) / 3);
    put ("g03_density_zero", dens[0]);
    put ("g03_density_one", dens[1]);
    put ("g03_density_rand", dens[2]);
    long agree01 = 0, agree3 = 0;
    for (long v = 0; v < n; v++) {
      agree01 += fin[0][v] == fin[1][v];
      agree3 += fin[0][v] == fin[1][v] && fin[1][v] == fin[2][v];
    }
    put ("g04_agree_zero_one", ratio (agree01, n));
    put ("g04_agree_all3", ratio (agree3, n));
    put ("g06_unsat_allpos_frac", ratio (unsat_pos, unsat_tot));
    put ("g06_unsat_allneg_frac", ratio (unsat_neg, unsat_tot));
    put ("g06_unsat_len_mean", ratio (unsat_len, unsat_tot));
    put ("g_found_model", solved);
    for (int s = 0; s < 3; s++)
      free (fin[s]);
  }
  free (vmap), free (lits), free (st), free (allpos), free (os), free (oc),
      free (ntrue), free (ulist), free (upos), free (a);
}

/*------------------------------------------------------------------------*/

int main (int argc, char **argv) {
  const char *path = 0;
  uint64_t seed = 20261023;
  for (int i = 1; i < argc; i++) {
    const char *a = argv[i];
    if (!strncmp (a, "--sections=", 11)) {
      for (int s = 2; s < MAXSEC; s++)
        sec_wanted[s] = 0;
      const char *p = a + 11;
      while (*p) {
        const char *q = strchr (p, ',');
        size_t n = q ? (size_t) (q - p) : strlen (p);
        int s = sec_index (p, n);
        if (s < 0)
          die ("unknown section");
        sec_wanted[s] = 1;
        p += n + (q ? 1 : 0);
      }
    } else if (!strncmp (a, "--cap=", 6))
      total_cap = atof (a + 6);
    else if (!strncmp (a, "--seed=", 7))
      seed = strtoull (a + 7, 0, 10);
    else if (!strncmp (a, "--seccap=", 9)) {
      const char *p = a + 9;
      while (*p) {
        const char *colon = strchr (p, ':');
        if (!colon)
          die ("bad --seccap");
        int s = sec_index (p, (size_t) (colon - p));
        if (s < 0)
          die ("unknown section in --seccap");
        sec_caps[s] = atof (colon + 1);
        const char *q = strchr (colon, ',');
        p = q ? q + 1 : colon + strlen (colon);
      }
    } else if (a[0] == '-')
      die ("unknown option");
    else
      path = a;
  }
  if (!path)
    die ("usage: obsprofile [--sections=LIST] [--cap=SEC] [--seccap=N:S,..] [--seed=N] <cnf>");
  rng_state = base_seed = seed;
  for (int s = 1; s < MAXSEC; s++)
    if (!sec_wanted[s])
      sec_status[s] = "off";
  // dependencies: bilat/graph/comm/ls need resid
  if (sec_wanted[4] || sec_wanted[5] || sec_wanted[6] || sec_wanted[7])
    sec_wanted[3] = 1;
  begin (0);
  int pc = parse (path);
  if (pc) {
    capped = gcapped = 1;
    end (0, "ok");
    print_json (cpu_now ());
    return 0;
  }
  build_occ ();
  end (0, "ok");
  for (int s = 1; s < MAXSEC; s++) {
    if (!sec_wanted[s])
      continue;
    if (gcapped) {
      sec_status[s] = "skipped";
      continue;
    }
    if (s >= 4 && !resid_ok) {
      sec_status[s] = sec_status[3] && !strcmp (sec_status[3], "ok") ? "n/a" : "skipped";
      continue; // root conflict, or resid capped
    }
    begin (s);
    switch (s) {
    case 1: sec_s28 (); break;
    case 2: sec_polar (); break;
    case 3: sec_resid (); break;
    case 4: sec_bilat (); break;
    case 5: sec_graph (); break;
    case 6: sec_comm (); break;
    case 7: sec_ls (); break;
    }
    end (s, "ok");
  }
  print_json (cpu_now ());
  return 0;
}
