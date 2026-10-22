// Static CNF profile for the three-way (D / F+ / F-) selection study.
//
//   cnfprofile <cnf>
//
// One pass over a plain or compressed DIMACS file (fast buffered parser);
// prints one JSON object with structural and polarity features plus the CPU
// time of this process and its decompression child (charged to the static
// selector, docs/THREE_WAY_PROTOCOL.md).  Clauses are counted as given
// (duplicate literals and tautologies are not removed); 'vars' are the
// distinct variables that occur.  Superset of tools/cnffeatures.c, which is
// kept unchanged for round-1 reproducibility.

#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>

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
  char *buf = malloc (strlen (cmd) + n + 8);
  sprintf (buf, "%s '%s'", cmd, path);
  *pipe = 1;
  FILE *f = popen (buf, "r");
  free (buf);
  return f;
}

static double cpu_time (void) {
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

// buffered reader
static FILE *in;
static unsigned char buf[1 << 20];
static size_t pos, len;
static int next (void) {
  if (pos == len) {
    len = fread (buf, 1, sizeof buf, in);
    pos = 0;
    if (!len)
      return EOF;
  }
  return buf[pos++];
}

static double ratio (double a, double b) { return b > 0 ? a / b : NAN; }
static int first = 1;
static void print (const char *name, double x) {
  printf (first ? "" : ",");
  first = 0;
  if (isnan (x) || isinf (x))
    printf ("\"%s\":null", name);
  else
    printf ("\"%s\":%.6g", name, x);
}

static void die (const char *msg) {
  fprintf (stderr, "cnfprofile: %s\n", msg);
  exit (2);
}

int main (int argc, char **argv) {
  if (argc != 2) {
    fprintf (stderr, "usage: cnfprofile <cnf>\n");
    return 2;
  }
  int is_pipe;
  in = open_input (argv[1], &is_pipe);
  if (!in)
    die ("can not read input");
  int ch;
  long header_vars = -1, header_clauses = -1;
  for (;;) { // skip comments, find header
    ch = next ();
    if (ch == 'c') {
      while ((ch = next ()) != '\n' && ch != EOF)
        ;
      continue;
    }
    if (ch == 'p')
      break;
    if (ch == EOF)
      die ("missing header");
    if (ch != ' ' && ch != '\n' && ch != '\t' && ch != '\r')
      die ("missing header");
  }
  { // " cnf V C"
    char line[256];
    int i = 0;
    while ((ch = next ()) != '\n' && ch != EOF && i < 255)
      line[i++] = ch;
    line[i] = 0;
    if (sscanf (line, " cnf %ld %ld", &header_vars, &header_clauses) != 2)
      die ("invalid header");
  }
  uint32_t *posocc = calloc (header_vars + 1, sizeof *posocc);
  uint32_t *negocc = calloc (header_vars + 1, sizeof *negocc);
  if (!posocc || !negocc)
    die ("out of memory");
  long clauses = 0, lits = 0, plits = 0, unit = 0, bin = 0, ter = 0,
       len4p = 0, len10p = 0, horn = 0, antihorn = 0, allpos = 0,
       allneg = 0, binneg = 0, binpos = 0, maxlen = 0, empty = 0;
  double sumsq = 0;
  long size = 0, cpos = 0;
  for (;;) {
    ch = next ();
    if (ch == EOF)
      break;
    if (ch == ' ' || ch == '\n' || ch == '\t' || ch == '\r')
      continue;
    if (ch == 'c') {
      while ((ch = next ()) != '\n' && ch != EOF)
        ;
      continue;
    }
    int sign = 1;
    if (ch == '-') {
      sign = -1;
      ch = next ();
    }
    if (ch < '0' || ch > '9')
      die ("parse error");
    long v = ch - '0';
    while ((ch = next ()) >= '0' && ch <= '9')
      v = 10 * v + (ch - '0');
    if (v) {
      if (v > header_vars)
        die ("literal exceeds header");
      size++;
      if (sign > 0)
        cpos++, posocc[v]++;
      else
        negocc[v]++;
    } else {
      clauses++, lits += size, plits += cpos;
      sumsq += (double) size * size;
      if (size > maxlen)
        maxlen = size;
      empty += (size == 0);
      unit += (size == 1), bin += (size == 2), ter += (size == 3);
      len4p += (size >= 4), len10p += (size >= 10);
      horn += (cpos <= 1), antihorn += (size - cpos <= 1);
      if (size > 0) {
        allpos += (cpos == size), allneg += (cpos == 0);
      }
      if (size == 2)
        binpos += (cpos == 2), binneg += (cpos == 0);
      size = cpos = 0;
    }
    if (ch == EOF)
      break;
  }
  if (is_pipe)
    pclose (in);
  else
    fclose (in);

  // per-variable polarity balance b = (p - n) / (p + n)
  long vars = 0, purepos = 0, pureneg = 0, posmaj = 0, negmaj = 0,
       maxocc = 0;
  double sb = 0, sb2 = 0, sab = 0, socc = 0, socc2 = 0;
  for (long v = 1; v <= header_vars; v++) {
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
  double mlen = ratio (lits, clauses);
  double mb = ratio (sb, vars), mocc = ratio (socc, vars);
  printf ("{");
  print ("header_vars", header_vars);
  print ("header_clauses", header_clauses);
  print ("vars", vars);
  print ("clauses", clauses);
  print ("p_log_vars", log10 (1.0 + vars));
  print ("p_log_clauses", log10 (1.0 + clauses));
  print ("p_cv_ratio", ratio (clauses, vars));
  print ("p_len_mean", mlen);
  print ("p_len_std", clauses ? sqrt (fmax (0, sumsq / clauses - mlen * mlen)) : NAN);
  print ("p_len_max", maxlen);
  print ("p_empty_frac", ratio (empty, clauses));
  print ("p_unit_frac", ratio (unit, clauses));
  print ("p_bin_frac", ratio (bin, clauses));
  print ("p_ter_frac", ratio (ter, clauses));
  print ("p_len4p_frac", ratio (len4p, clauses));
  print ("p_len10p_frac", ratio (len10p, clauses));
  print ("p_pos_lit_frac", ratio (plits, lits));
  print ("p_horn_frac", ratio (horn, clauses));
  print ("p_antihorn_frac", ratio (antihorn, clauses));
  print ("p_allpos_cls_frac", ratio (allpos, clauses));
  print ("p_allneg_cls_frac", ratio (allneg, clauses));
  print ("p_binpos_frac", ratio (binpos, bin));
  print ("p_binneg_frac", ratio (binneg, bin));
  print ("p_var_bal_mean", mb);
  print ("p_var_bal_std", vars ? sqrt (fmax (0, sb2 / vars - mb * mb)) : NAN);
  print ("p_var_absbal_mean", ratio (sab, vars));
  print ("p_var_purepos_frac", ratio (purepos, vars));
  print ("p_var_pureneg_frac", ratio (pureneg, vars));
  print ("p_var_posmaj_frac", ratio (posmaj, vars));
  print ("p_var_negmaj_frac", ratio (negmaj, vars));
  print ("p_occ_mean", mocc);
  print ("p_occ_cv", vars && mocc > 0 ? sqrt (fmax (0, socc2 / vars - mocc * mocc)) / mocc : NAN);
  print ("p_occ_max_rel", ratio (maxocc, mocc));
  print ("cpu_time", cpu_time ());
  printf ("}\n");
  return 0;
}
