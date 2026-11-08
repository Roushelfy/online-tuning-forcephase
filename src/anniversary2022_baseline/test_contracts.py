import gzip
import hashlib
import lzma
import tempfile
import unittest
from pathlib import Path
from .common import ACTIONS, check_model, parse_stats, sha, shard_rows, validate_spec, write
from .export_results import export
from .stage_inputs import stage
from .filter_manifest import exclude, score_status


class ScientificContracts(unittest.TestCase):
    def test_external_filter_preserves_missing_coverage_and_any_solve(self):
        self.assertTrue(exclude([False,False,False]))
        self.assertFalse(exclude([False,None,False]))
        self.assertFalse(exclude([False,True,False]))
        self.assertFalse(exclude([False,False]))

    def test_official_scores_use_penalty_not_nominal_cutoff(self):
        self.assertFalse(score_status(["10000","10000"],5000))
        self.assertTrue(score_status(["2000","1004.301"],1000))
        self.assertIsNone(score_status(["10000","missing"],5000))
        self.assertIsNone(score_status(["nan"],5000))

    def test_missing_statistics_are_not_zero(self):
        self.assertIsNone(parse_stats("s UNKNOWN\n")["conflicts"])
        self.assertEqual(parse_stats("c conflicts: 0 0 per second\n")["conflicts"], 0)
        self.assertEqual(parse_stats("c conflicts: 3\nc conflicts: 9\n")["conflicts"], 9)

    def test_draft_cannot_launch(self):
        with self.assertRaisesRegex(ValueError, "only frozen"):
            validate_spec({"status": "DRAFT_NOT_LAUNCHABLE"}, "/not/a/manifest")

    def test_model_is_checked_against_cnf_not_status(self):
        with tempfile.TemporaryDirectory() as d:
            cnf, log = Path(d)/"x.cnf", Path(d)/"x.log"
            cnf.write_text("p cnf 1 1\n1 0\n")
            log.write_text("s SATISFIABLE\nv -1 0\n")
            self.assertFalse(check_model(cnf, log))
            log.write_text("s SATISFIABLE\nv 1 0\n")
            self.assertTrue(check_model(cnf, log))
            cnf.write_text("p cnf 1 2\n1 0\n0\n")
            self.assertFalse(check_model(cnf, log))

    def test_compression_and_cache_identity(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); data=b"c input fixture\np cnf 1 1\n1 0\n"
            for name, content in [("plain",data),("gzip",gzip.compress(data)),("xz",lzma.compress(data))]:
                source=base/(name+".data");source.write_bytes(content)
                row={"instance_key":name,"url":source.as_uri(),"expected_sha256_cnf":hashlib.sha256(data).hexdigest()}
                out=base/(name+"_root");out.mkdir()
                r=stage(row,out,{"disk_reserve_bytes":1024,"download_wall_s":5})
                self.assertEqual(Path(r["path"]).read_bytes(),data)
                self.assertEqual(stage(row,out,{"disk_reserve_bytes":1024})["input_sha256"],r["input_sha256"])
                Path(r["path"]).write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError,"cached input changed"):
                    stage(row,out,{"disk_reserve_bytes":1024})

    def test_wrong_public_sha_blocks_readiness(self):
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/"source.cnf";source.write_text("p cnf 1 1\n1 0\n")
            out=Path(d)/"out";out.mkdir()
            with self.assertRaisesRegex(ValueError,"SHA mismatch"):
                stage({"instance_key":"bad","url":source.as_uri(),"expected_sha256_cnf":"0"*64},out,{"disk_reserve_bytes":1024})
            self.assertFalse((out/"input_receipts/bad.json").exists())

    def test_partial_export_cannot_claim_complete(self):
        with tempfile.TemporaryDirectory() as d:
            write(Path(d)/"progress.json",{"status":"PARTIAL"})
            with self.assertRaisesRegex(ValueError,"incomplete or invalid"):
                export(d,Path(d)/"result.tar.gz",True)

    def test_indented_sub_statistics_are_not_top_level_counts(self):
        # Shape of the CaDiCaL 3.0.1 statistics block seen on the cluster (warmup sub-entry after the main one).
        text = ("c chronological:            222697         2.03 %  of conflicts\n"
                "c conflicts:              10967737     18286.93    per second\n"
                "c   backtracked:          11183701       101.97 %  of conflicts\n"
                "c decisions:              10994830     18332.10    per second\n"
                "c restarts:                   1076     10193.06    interval\n"
                "c   conflicts:                   0         0.00    per warmup\n"
                "c   decisions:                   0         0.00    per warmup\n")
        s = parse_stats(text)
        self.assertEqual((s["conflicts"], s["decisions"], s["restarts"]), (10967737, 10994830, 1076))

    def test_shards_partition_the_cohort(self):
        rows = [{"instance_key": str(i)} for i in range(10)]
        parts = [shard_rows(rows, {"shard": {"index": i, "count": 3}}) for i in range(3)]
        keys = [r["instance_key"] for part in parts for r in part]
        self.assertEqual(sorted(keys), sorted(r["instance_key"] for r in rows))
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(shard_rows(rows, {}), rows)

    def test_invalid_shard_or_relative_proof_dir_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            manifest = Path(d)/"m.csv"
            manifest.write_text("instance_key,url,role\na,file:///a,qualification\nb,file:///b,qualification\n")
            spec = {"status": "QUALIFICATION", "expected_inputs": 2, "manifest_sha256": sha(manifest), "actions": ACTIONS,
                    "seeds": [0], "cutoff_s": 2, "wall_watchdog_s": 10, "max_physical_cpu_hours": 0.05,
                    "memory_bytes": 1 << 29, "proof_limit_bytes": 1 << 27, "checker_cpu_s": 20, "checker_wall_s": 30,
                    "workers": 2}
            self.assertEqual(len(validate_spec(spec, manifest, tools=False)), 2)
            self.assertEqual(len(validate_spec({**spec, "shard": {"index": 1, "count": 2}, "proof_dir": "/tmp/p"}, manifest, tools=False)), 2)
            for bad in [{"index": 2, "count": 2}, {"index": -1, "count": 2}, {"index": 0, "count": 3}, {"index": 0}]:
                with self.assertRaisesRegex(ValueError, "invalid shard"):
                    validate_spec({**spec, "shard": bad}, manifest, tools=False)
            with self.assertRaisesRegex(ValueError, "absolute"):
                validate_spec({**spec, "proof_dir": "relative/dir"}, manifest, tools=False)


if __name__=="__main__":unittest.main()
