// Bounded static CNF analysis for goal v10 (family A, docs/CROSS_SCALE_PROTOCOL_V10.md).
//
//   static10 [--work-cap N] <cnf>
//
// Prints one JSON object {"status", "features", "work", "cpu"} with the 20
// registered features ('st_*').  Features 1-18 are counts over the clauses as
// given (one pass plus one pass over the variables).  Features 19-20 describe
// the variable interaction graph (VIG: two variables are adjacent if they
// occur in a common clause) on a fixed, evenly spaced sample of at most 256
// occurring variables; their work (literal visits) is bounded by --work-cap
// (default 5e7).  When the cap is reached the graph features are null and the
// status is "graph_cap"; the counts are still reported.  Unparsable input:
// status "error", exit code 2.  Deterministic: no randomness, no timing in the
// features.  Standard C only.

#include <ctype.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>

#define NUM_FEATURES 20
#define SAMPLE 256

static const char *names[NUM_FEATURES] = {
    "st_log_vars",     "st_log_clauses", "st_cv_ratio",      "st_mean_len",
    "st_bin_frac",     "st_long_frac",   "st_pos_frac",      "st_horn_frac",
    "st_antihorn_frac", "st_allneg_frac", "st_allpos_frac",   "st_deg_log_mean",
    "st_deg_cv",       "st_pol_imbalance", "st_pure_frac",    "st_jw_pos",
    "st_lowdeg_frac",  "st_bin_var_frac", "st_vig_deg_log",  "st_vig_clust"};

static double cpu_time (void) {
  struct rusage u;
  getrusage (RUSAGE_SELF, &u);
  return u.ru_utime.tv_sec + 1e-6 * u.ru_utime.tv_usec + u.ru_stime.tv_sec +
         1e-6 * u.ru_stime.tv_usec;
}

static double ratio (double a, double b) { return b > 0 ? a / b : NAN; }

static void fail (const char *msg) {
  printf ("{\"status\":\"error\",\"error\":\"%s\",\"cpu\":%.6f}\n", msg,
          cpu_time ());
  exit (2);
}

typedef struct {
  long n, cap;
  int *a;
} Vec;

static void push (Vec *v, int x) {
  if (v->n == v->cap) {
    v->cap = v->cap ? 2 * v->cap : 1024;
    v->a = realloc (v->a, v->cap * sizeof *v->a);
    if (!v->a)
      fail ("out of memory");
  }
  v->a[v->n++] = x;
}

int main (int argc, char **argv) {
  double work_cap = 5e7;
  const char *path = 0;
  for (int i = 1; i < argc; i++) {
    if (!strcmp (argv[i], "--work-cap") && i + 1 < argc)
      work_cap = atof (argv[++i]);
    else
      path = argv[i];
  }
  if (!path)
    fail ("usage: static10 [--work-cap N] <cnf>");
  FILE *f = fopen (path, "r");
  if (!f)
    fail ("can not read input");
  long hv = -1, hc = -1;
  int ch;
  for (;;) {
    ch = getc (f);
    if (ch == 'c') {
      while ((ch = getc (f)) != '\n' && ch != EOF)
        ;
      continue;
    }
    if (ch == 'p')
      break;
    if (ch == EOF || !isspace (ch))
      fail ("missing header");
  }
  if (fscanf (f, " cnf %ld %ld", &hv, &hc) != 2 || hv < 0 || hc < 0)
    fail ("invalid header");
  Vec lits = {0, 0, 0}, start = {0, 0, 0};
  push (&start, 0);
  long lit;
  for (;;) {
    ch = getc (f);
    if (ch == EOF)
      break;
    if (isspace (ch))
      continue;
    if (ch == 'c' || ch == '%') {
      if (ch == '%')
        break;
      while ((ch = getc (f)) != '\n' && ch != EOF)
        ;
      continue;
    }
    ungetc (ch, f);
    if (fscanf (f, "%ld", &lit) != 1)
      fail ("parse error");
    if (labs (lit) > hv)
      fail ("literal exceeds header");
    if (lit)
      push (&lits, (int) lit);
    else
      push (&start, (int) lits.n);
  }
  fclose (f);
  const long C = start.n - 1, V = hv;
  long *pos = calloc (V + 1, sizeof (long)), *neg = calloc (V + 1, sizeof (long));
  unsigned char *inbin = calloc (V + 1, 1);
  if (!pos || !neg || !inbin)
    fail ("out of memory");
  long L = 0, P = 0, bin = 0, lng = 0, horn = 0, ahorn = 0, allneg = 0,
       allpos = 0;
  double jw_pos = 0, jw_all = 0;
  for (long c = 0; c < C; c++) {
    long s = start.a[c], e = start.a[c + 1], n = e - s, np = 0;
    double w = ldexp (1.0, -(int) (n < 60 ? n : 60));
    for (long k = s; k < e; k++) {
      int l = lits.a[k];
      if (l > 0)
        np++, pos[l]++, jw_pos += w;
      else
        neg[-l]++;
      jw_all += w;
      if (n == 2)
        inbin[abs (l)] = 1;
    }
    L += n, P += np;
    bin += (n == 2), lng += (n >= 4);
    horn += (np <= 1), ahorn += (n - np <= 1);
    allneg += (n > 0 && np == 0), allpos += (n > 0 && np == n);
  }
  long occ_vars = 0, pure = 0, lowdeg = 0, binv = 0;
  double dsum = 0, dsq = 0, imb = 0;
  for (long v = 1; v <= V; v++) {
    long d = pos[v] + neg[v];
    if (!d)
      continue;
    occ_vars++;
    dsum += d, dsq += (double) d * d;
    imb += fabs ((double) (pos[v] - neg[v])) / d;
    pure += (pos[v] == 0 || neg[v] == 0);
    lowdeg += (d <= 3);
    binv += inbin[v];
  }
  double feat[NUM_FEATURES];
  for (int i = 0; i < NUM_FEATURES; i++)
    feat[i] = NAN;
  double dmean = ratio (dsum, occ_vars);
  feat[0] = log10 (1.0 + occ_vars);
  feat[1] = log10 (1.0 + C);
  feat[2] = ratio (C, occ_vars);
  feat[3] = ratio (L, C);
  feat[4] = ratio (bin, C);
  feat[5] = ratio (lng, C);
  feat[6] = ratio (P, L);
  feat[7] = ratio (horn, C);
  feat[8] = ratio (ahorn, C);
  feat[9] = ratio (allneg, C);
  feat[10] = ratio (allpos, C);
  feat[11] = occ_vars ? log10 (dmean) : NAN;
  feat[12] = occ_vars ? sqrt (fmax (0.0, dsq / occ_vars - dmean * dmean)) / dmean : NAN;
  feat[13] = ratio (imb, occ_vars);
  feat[14] = ratio (pure, occ_vars);
  feat[15] = ratio (jw_pos, jw_all);
  feat[16] = ratio (lowdeg, occ_vars);
  feat[17] = ratio (binv, occ_vars);

  // VIG on a fixed sample: occurrence lists (CSR), neighbour marks.
  const char *status = "ok";
  double work = 0;
  long *ostart = calloc (V + 2, sizeof (long));
  if (!ostart)
    fail ("out of memory");
  for (long v = 1; v <= V; v++)
    ostart[v + 1] = ostart[v] + pos[v] + neg[v];
  long *ofill = calloc (V + 2, sizeof (long));
  int *occ = malloc ((L ? L : 1) * sizeof (int));
  int *mark = calloc (V + 1, sizeof (int)), *mark2 = calloc (V + 1, sizeof (int));
  int *nb = malloc ((V + 1) * sizeof (int));
  if (!ofill || !occ || !mark || !mark2 || !nb)
    fail ("out of memory");
  for (long c = 0; c < C; c++)
    for (long k = start.a[c]; k < start.a[c + 1]; k++) {
      int v = abs (lits.a[k]);
      occ[ostart[v] + ofill[v]++] = (int) c;
    }
  work += L;
  long nsample = occ_vars < SAMPLE ? occ_vars : SAMPLE;
  double deg_sum = 0, clust_sum = 0;
  long clust_n = 0, done = 0, seen_occ = 0, stamp = 0, stamp2 = 0;
  long step = nsample ? occ_vars / nsample : 1, next = 0;
  for (long v = 1; v <= V && done < nsample && work <= work_cap; v++) {
    if (!(pos[v] + neg[v]))
      continue;
    if (seen_occ++ != next)
      continue;
    next += step;
    done++;
    // neighbour set of v
    stamp++;
    long nn = 0;
    for (long o = ostart[v]; o < ostart[v + 1]; o++) {
      long c = occ[o];
      for (long k = start.a[c]; k < start.a[c + 1]; k++) {
        int u = abs (lits.a[k]);
        if (u != v && mark[u] != stamp)
          mark[u] = (int) stamp, nb[nn++] = u;
      }
      work += start.a[c + 1] - start.a[c];
    }
    deg_sum += nn;
    if (nn < 2)
      continue;
    // edges among the neighbours: for each neighbour u, distinct neighbours of u inside N(v)
    double links = 0;
    for (long j = 0; j < nn && work <= work_cap; j++) {
      int u = nb[j];
      stamp2++;
      for (long o = ostart[u]; o < ostart[u + 1]; o++) {
        long c = occ[o];
        for (long k = start.a[c]; k < start.a[c + 1]; k++) {
          int w = abs (lits.a[k]);
          if (w != u && w != v && mark[w] == stamp && mark2[w] != stamp2)
            mark2[w] = (int) stamp2, links += 1;
        }
        work += start.a[c + 1] - start.a[c];
      }
    }
    clust_sum += links / ((double) nn * (nn - 1));
    clust_n++;
  }
  if (work > work_cap)
    status = "graph_cap";
  else {
    feat[18] = done ? log10 (1.0 + deg_sum / done) : NAN;
    feat[19] = clust_n ? clust_sum / clust_n : (done ? 0.0 : NAN);
  }
  printf ("{\"status\":\"%s\",\"vars\":%ld,\"clauses\":%ld,\"sample\":%ld,"
          "\"work\":%.0f,\"work_cap\":%.0f,\"features\":{",
          status, occ_vars, C, done, work, work_cap);
  for (int i = 0; i < NUM_FEATURES; i++) {
    if (isnan (feat[i]))
      printf ("%s\"%s\":null", i ? "," : "", names[i]);
    else
      printf ("%s\"%s\":%.6g", i ? "," : "", names[i], feat[i]);
  }
  printf ("},\"cpu\":%.6f}\n", cpu_time ());
  return 0;
}
