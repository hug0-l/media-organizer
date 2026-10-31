import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from mo.index import Index  # noqa: E402
from mo.state import State  # noqa: E402


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state = State(root=self.root)
        self.idx = Index(self.state)
        data = {
            "series": [{
                "name": "Show Name", "year": 2019, "tmdb_id": 1001,
                "aliases": ["The Show"],
                "episodes": [
                    {"season": 1, "episode": 1, "title": "Pilot", "airdate": "2019-01-01"},
                    {"season": 1, "episode": 2, "title": "Episode Two", "airdate": "2019-01-08"},
                ],
            }],
            "movies": [{"name": "Movie Name", "year": 2023, "tmdb_id": 2002, "aliases": ["The Movie"]}],
        }
        (self.root / "index.json").write_text(json.dumps(data), encoding="utf-8")
        self.idx.build_from(self.root / "index.json")

    def tearDown(self):
        self.state.close()
        self.tmp.cleanup()

    def test_stats(self):
        s = self.idx.stats()
        self.assertEqual(s["series"], 1)
        self.assertEqual(s["episodes"], 2)
        self.assertEqual(s["movies"], 1)

    def test_search_name(self):
        rows = self.idx.search_series("show name")
        self.assertEqual(rows[0].name, "Show Name")

    def test_search_alias(self):
        rows = self.idx.search_series("the show")
        self.assertTrue(rows and rows[0].name == "Show Name")

    def test_episodes(self):
        eps = self.idx.episodes("tmdb:1001")
        self.assertEqual([e.episode for e in eps], [1, 2])
        self.assertEqual(eps[0].title, "Pilot")

    def test_movie(self):
        rows = self.idx.search_movies("the movie", year=2023)
        self.assertTrue(rows and rows[0].name == "Movie Name")


if __name__ == "__main__":
    unittest.main()
