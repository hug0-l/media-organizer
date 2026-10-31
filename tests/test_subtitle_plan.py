import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from mo.providers.opensubtitles import SubtitleResult  # noqa: E402
from mo.scan import scan_paths  # noqa: E402
from mo.state import State  # noqa: E402
from mo.subs import build_subtitle_plan  # noqa: E402


class FakeProvider:
    name = "fake"
    key = "test"

    def search(self, query="", moviehash="", languages="en"):
        return [SubtitleResult(
            provider="fake", file_id=123, language=languages,
            release="Show.S01E01", title="Show", downloads=10, rating=8.0,
        )]


class SubtitlePlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "Show.S01E01.1080p.mkv").write_bytes(b"x" * 100)
        self.state = State(root=self.root)

    def tearDown(self):
        self.state.close()
        self.tmp.cleanup()

    def test_plan(self):
        files = scan_paths([self.root])
        plan = build_subtitle_plan(files, "zh", self.state, provider=FakeProvider())
        self.assertEqual(plan["kind"], "subtitle")
        self.assertEqual(plan["summary"]["matched"], 1)
        item = plan["items"][0]
        self.assertEqual(item["subtitle"]["file_id"], 123)
        self.assertTrue(item["dst"].endswith("Show.S01E01.1080p.zh.srt"))


if __name__ == "__main__":
    unittest.main()
