import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from mo.apply import apply_plan, revert_journal  # noqa: E402
from mo.classify import detect_kind  # noqa: E402
from mo.index import Index  # noqa: E402
from mo.match import match_files  # noqa: E402
from mo.plan import PlanOptions, build_plan  # noqa: E402
from mo.providers.local import LocalProvider  # noqa: E402
from mo.scan import scan_paths  # noqa: E402
from mo.state import State  # noqa: E402


class PlanApplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Path(self.tmp.name) / "lib"
        (self.lib / "TV").mkdir(parents=True)
        (self.lib / "Movies").mkdir(parents=True)
        (self.lib / "TV" / "Show.Name.S01E01.1080p.mkv").write_bytes(b"a" * 10)
        (self.lib / "TV" / "Show.Name.S01E02.1080p.mkv").write_bytes(b"b" * 10)
        (self.lib / "TV" / "Show.Name.S01E02.1080p.en.srt").write_bytes(b"c" * 10)
        (self.lib / "Movies" / "Movie.Name.2023.1080p.mkv").write_bytes(b"d" * 10)
        self.state = State(root=self.lib)
        idx = Index(self.state)
        idx.build_from_data({
            "series": [{
                "name": "Show Name", "year": 2019, "tmdb_id": 1001,
                "episodes": [
                    {"season": 1, "episode": 1, "title": "Pilot"},
                    {"season": 1, "episode": 2, "title": "Episode Two"},
                ],
            }],
            "movies": [{"name": "Movie Name", "year": 2023, "tmdb_id": 2002}],
        })
        self.provider = LocalProvider(self.state, idx)

    def tearDown(self):
        self.state.close()
        self.tmp.cleanup()

    def _make_plan(self, files, kind, fmt, out, conflict="skip", action="move"):
        matches = match_files(files, self.provider, kind)
        opts = PlanOptions(action=action, conflict=conflict, format=fmt, output=str(out), kind=kind)
        return build_plan(files, matches, opts, self.lib)

    def test_apply_and_revert(self):
        files = scan_paths([self.lib])
        tv = [f for f in files if detect_kind(f) == "tv"]
        out = self.lib / "Organized"
        plan = self._make_plan(tv, "tv", "{n} - {s00e00} - {t}", out)
        self.assertEqual(plan["summary"]["matched"], 2)
        result = apply_plan(self.state, plan)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["applied"], 2)
        self.assertTrue((out / "Show Name - S01E01 - Pilot.mkv").exists())
        self.assertTrue((out / "Show Name - S01E02 - Episode Two.mkv").exists())
        self.assertTrue((out / "Show Name - S01E02 - Episode Two.en.srt").exists())
        self.assertFalse((self.lib / "TV" / "Show.Name.S01E01.1080p.mkv").exists())

        rev = revert_journal(self.state, result["journal"])
        self.assertEqual(rev["failed"], 0)
        self.assertEqual(rev["reverted"], 3)
        self.assertTrue((self.lib / "TV" / "Show.Name.S01E01.1080p.mkv").exists())
        self.assertTrue((self.lib / "TV" / "Show.Name.S01E02.1080p.en.srt").exists())

    def test_copy_action(self):
        files = [f for f in scan_paths([self.lib]) if "S01E01" in f.path and "Organized" not in f.path]
        out = self.lib / "Copied"
        plan = self._make_plan(files, "tv", "{n} - {s00e00} - {t}", out, action="copy")
        r = apply_plan(self.state, plan)
        self.assertEqual(r["applied"], 1)
        self.assertTrue((self.lib / "TV" / "Show.Name.S01E01.1080p.mkv").exists())
        self.assertTrue((out / "Show Name - S01E01 - Pilot.mkv").exists())
        rev = revert_journal(self.state, r["journal"])
        self.assertEqual(rev["reverted"], 1)
        self.assertTrue((self.lib / "TV" / "Show.Name.S01E01.1080p.mkv").exists())
        self.assertFalse((out / "Show Name - S01E01 - Pilot.mkv").exists())

    def test_test_action_noop(self):
        files = [f for f in scan_paths([self.lib]) if "S01E01" in f.path and "Organized" not in f.path]
        out = self.lib / "Dry"
        plan = self._make_plan(files, "tv", "{n} - {s00e00} - {t}", out, action="test")
        r = apply_plan(self.state, plan)
        self.assertEqual(r["applied"], 1)
        self.assertTrue((self.lib / "TV" / "Show.Name.S01E01.1080p.mkv").exists())
        self.assertFalse((out / "Show Name - S01E01 - Pilot.mkv").exists())

    def test_movie_plan(self):
        files = scan_paths([self.lib / "Movies"])
        plan = self._make_plan(files, "movie", "{n} ({y})", self.lib / "Out")
        self.assertEqual(plan["items"][0]["dst"], str((self.lib / "Out" / "Movie Name (2023).mkv").resolve()))
        r = apply_plan(self.state, plan)
        self.assertEqual(r["applied"], 1)
        self.assertTrue((self.lib / "Out" / "Movie Name (2023).mkv").exists())

    def test_conflict_skip(self):
        out = self.lib / "Organized"
        out.mkdir()
        existing = out / "Show Name - S01E01 - Pilot.mkv"
        existing.write_bytes(b"existing")
        files = [f for f in scan_paths([self.lib]) if "S01E01" in f.path and "Organized" not in f.path]
        plan = self._make_plan(files, "tv", "{n} - {s00e00} - {t}", out, conflict="skip")
        self.assertEqual(plan["items"][0]["status"], "conflict")
        r = apply_plan(self.state, plan)
        self.assertEqual(r["applied"], 0)
        self.assertEqual(r["skipped"], 1)
        self.assertEqual(existing.read_bytes(), b"existing")
        self.assertTrue((self.lib / "TV" / "Show.Name.S01E01.1080p.mkv").exists())

    def test_conflict_index(self):
        out = self.lib / "Organized"
        out.mkdir()
        existing = out / "Show Name - S01E01 - Pilot.mkv"
        existing.write_bytes(b"existing")
        files = [f for f in scan_paths([self.lib]) if "S01E01" in f.path and "Organized" not in f.path]
        plan = self._make_plan(files, "tv", "{n} - {s00e00} - {t}", out, conflict="index")
        self.assertEqual(plan["items"][0]["status"], "indexed")
        self.assertIn(".1.mkv", plan["items"][0]["dst"])
        r = apply_plan(self.state, plan)
        self.assertEqual(r["applied"], 1)
        self.assertTrue((out / "Show Name - S01E01 - Pilot.1.mkv").exists())

    def test_plan_tamper_rejected(self):
        files = [f for f in scan_paths([self.lib]) if "S01E01" in f.path]
        plan = self._make_plan(files, "tv", "{n} - {s00e00} - {t}", self.lib / "Out")
        plan["items"][0]["dst"] = str(self.lib / "hacked.mkv")
        with self.assertRaises(Exception):
            apply_plan(self.state, plan)

    def test_traversal_format_rejected(self):
        files = [f for f in scan_paths([self.lib]) if "S01E01" in f.path]
        plan = self._make_plan(files, "tv", "../{n}", self.lib / "Out")
        self.assertEqual(plan["items"][0]["status"], "error")


if __name__ == "__main__":
    unittest.main()
