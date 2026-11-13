// Unit-clause, unique-literal-clause and per-variable sign-majority statistics of an original (plain DIMACS) CNF.
//
//   cnf_unit_unique FILE.cnf   ->  one JSON line on stdout
//
// Definitions (every occurrence counts, including a literal repeated inside one clause):
//   occ(l)            number of occurrences of the signed literal l in the whole formula
//   unit clause       |C| = 1 (as written in the file)
//   unique clause     non-empty clause in which every literal l has occ(l) = 1; positive and negative literals of a
//                     variable are counted separately, so -x may occur many times elsewhere
//   majority sign     for a variable occurring at least once: + if occ(x) > occ(-x), - if <, tie if equal
// Two passes over the file (counts, then clause tests); CPU time of the whole program is reported.
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <sys/resource.h>

static FILE *in;
static char buf[1 << 20];
static size_t len, pos;
static int next_char (void) {
  if (pos == len) { len = fread (buf, 1, sizeof buf, in); pos = 0; if (!len) return EOF; }
  return buf[pos++];
}
static int64_t maxvar, *occ; // occ[2v] positive, occ[2v+1] negative
static void grow (int64_t v) {
  if (v <= maxvar) return;
  int64_t n = maxvar ? maxvar : 1024;
  while (n < v) n *= 2;
  occ = realloc (occ, sizeof (int64_t) * 2 * (n + 1));
  if (!occ) { fprintf (stderr, "out of memory\n"); exit (2); }
  memset (occ + 2 * (maxvar + 1), 0, sizeof (int64_t) * 2 * (n - maxvar));
  maxvar = n;
}
// Reads the next literal; returns 1 and sets *lit (0 = end of clause) or 0 at end of file.
static int read_lit (int64_t *lit) {
  int c;
  for (;;) {
    c = next_char ();
    if (c == EOF) return 0;
    if (c == 'c' || c == 'p' || c == '%') { while (c != '\n' && c != EOF) c = next_char (); if (c == EOF) return 0; continue; }
    if (c == '-' || (c >= '0' && c <= '9')) break;
  }
  int neg = 0; int64_t v = 0;
  if (c == '-') { neg = 1; c = next_char (); }
  while (c >= '0' && c <= '9') { v = v * 10 + (c - '0'); c = next_char (); }
  *lit = neg ? -v : v;
  return 1;
}
static double cpu (void) {
  struct rusage u; getrusage (RUSAGE_SELF, &u);
  return u.ru_utime.tv_sec + u.ru_stime.tv_sec + 1e-6 * (u.ru_utime.tv_usec + u.ru_stime.tv_usec);
}
static int open_input (const char *path) { in = fopen (path, "rb"); len = pos = 0; return in != NULL; }

int main (int argc, char **argv) {
  if (argc != 2) { fprintf (stderr, "usage: cnf_unit_unique FILE.cnf\n"); return 64; }
  if (!open_input (argv[1])) { perror (argv[1]); return 66; }
  int64_t lit, clauses = 0, literals = 0, size = 0, empty = 0, units = 0, unit_pos = 0, used = 0;
  int64_t first = 0;
  while (read_lit (&lit)) {
    if (!lit) {
      clauses++;
      if (size == 0) empty++;
      else if (size == 1) { units++; if (first > 0) unit_pos++; }
      size = 0; continue;
    }
    int64_t v = lit < 0 ? -lit : lit;
    grow (v);
    if (v > used) used = v;
    occ[2 * v + (lit < 0)]++;
    if (!size) first = lit;
    size++, literals++;
  }
  fclose (in);
  // second pass: unique-literal clauses
  if (!open_input (argv[1])) { perror (argv[1]); return 66; }
  int64_t uniq = 0, uniq_lits = 0, uniq_pos_lits = 0, uniq_allpos = 0, uniq_allneg = 0, uniq_units = 0;
  int64_t cur_pos = 0, cur_neg = 0; int all_once = 1; size = 0;
  while (read_lit (&lit)) {
    if (!lit) {
      if (size > 0 && all_once) {
        uniq++, uniq_lits += size, uniq_pos_lits += cur_pos;
        if (!cur_neg) uniq_allpos++;
        if (!cur_pos) uniq_allneg++;
        if (size == 1) uniq_units++;
      }
      size = 0, cur_pos = cur_neg = 0, all_once = 1; continue;
    }
    int64_t v = lit < 0 ? -lit : lit;
    if (occ[2 * v + (lit < 0)] != 1) all_once = 0;
    if (lit > 0) cur_pos++; else cur_neg++;
    size++;
  }
  fclose (in);
  int64_t vars_occ = 0, maj_pos = 0, maj_neg = 0, ties = 0, lit_once = 0, lits_occ = 0;
  for (int64_t v = 1; v <= used; v++) {
    int64_t p = occ[2 * v], n = occ[2 * v + 1];
    if (p) lits_occ++, lit_once += p == 1;
    if (n) lits_occ++, lit_once += n == 1;
    if (!p && !n) continue;
    vars_occ++;
    if (p > n) maj_pos++; else if (n > p) maj_neg++; else ties++;
  }
  double m = clauses ? (double) clauses : 1, vo = vars_occ ? (double) vars_occ : 1;
  printf ("{\"clauses\":%lld,\"literals\":%lld,\"max_var\":%lld,\"variables_occurring\":%lld,\"empty_clauses\":%lld,"
          "\"unit_count\":%lld,\"unit_pos\":%lld,\"unit_neg\":%lld,\"unit_frac\":%.10g,\"unit_pos_share\":%.10g,"
          "\"unit_per_var\":%.10g,"
          "\"uniq_count\":%lld,\"uniq_frac\":%.10g,\"uniq_lits\":%lld,\"uniq_pos_lits\":%lld,\"uniq_pos_share\":%.10g,"
          "\"uniq_allpos\":%lld,\"uniq_allneg\":%lld,\"uniq_mean_len\":%.10g,\"uniq_units\":%lld,"
          "\"lit_once_frac\":%.10g,"
          "\"maj_pos_frac\":%.10g,\"maj_neg_frac\":%.10g,\"maj_tie_frac\":%.10g,"
          "\"cpu_s\":%.6f}\n",
          (long long) clauses, (long long) literals, (long long) used, (long long) vars_occ, (long long) empty,
          (long long) units, (long long) unit_pos, (long long) (units - unit_pos), units / m,
          units ? (double) unit_pos / units : 0.0, units / vo,
          (long long) uniq, uniq / m, (long long) uniq_lits, (long long) uniq_pos_lits,
          uniq_lits ? (double) uniq_pos_lits / uniq_lits : 0.0, (long long) uniq_allpos, (long long) uniq_allneg,
          uniq ? (double) uniq_lits / uniq : 0.0, (long long) uniq_units,
          lits_occ ? (double) lit_once / lits_occ : 0.0,
          maj_pos / vo, maj_neg / vo, ties / vo, cpu ());
  return 0;
}
