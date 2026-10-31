import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from mo.parse import parse_media  # noqa: E402


class ParseTests(unittest.TestCase):
    def test_sxxeyy(self):
        p = parse_media(r"C:\TV\Show.Name.S01E02.1080p.WEB-DL.DDP5.1.x264-GROUP.mkv")
        self.assertEqual(p.kind, "tv")
        self.assertEqual(p.title, "Show Name")
        self.assertEqual((p.season, p.episodes), (1, [2]))
        self.assertEqual(p.group, "GROUP")
        self.assertEqual(p.tags.get("resolution"), "1080p")

    def test_multi(self):
        p = parse_media("Multi.S01E01-E02.720p.mkv")
        self.assertEqual(p.title, "Multi")
        self.assertEqual(p.episodes, [1, 2])
        self.assertTrue(p.is_multi)

    def test_multi_compact(self):
        p = parse_media("Show.S01E01E02.720p.mkv")
        self.assertEqual(p.episodes, [1, 2])

    def test_nxnn(self):
        p = parse_media("Show Name - 1x02 - Episode Title.mkv")
        self.assertEqual(p.title, "Show Name")
        self.assertEqual((p.season, p.episodes), (1, [2]))

    def test_movie_year(self):
        p = parse_media("Movie.Name.2023.2160p.HDR.mkv")
        self.assertEqual(p.kind, "movie")
        self.assertEqual(p.title, "Movie Name")
        self.assertEqual(p.year, 2023)

    def test_movie_folder_year(self):
        p = parse_media("Name (2020)/Name.2020.mkv")
        self.assertEqual(p.kind, "movie")
        self.assertEqual((p.title, p.year), ("Name", 2020))

    def test_anime_bracket(self):
        p = parse_media("[SubsPlease] Anime - 12 (1080p) [ABCD1234].mkv")
        self.assertEqual(p.kind, "tv")
        self.assertEqual(p.title, "Anime")
        self.assertEqual(p.absolute, 12)
        self.assertEqual(p.group, "SubsPlease")

    def test_season_folder(self):
        p = parse_media("Series/Season 02/02.mkv")
        self.assertEqual(p.kind, "tv")
        self.assertEqual(p.title, "Series")
        self.assertEqual((p.season, p.episodes), (2, [2]))

    def test_season_episode_words(self):
        p = parse_media("Show Name Season 1 Episode 2.mkv")
        self.assertEqual((p.season, p.episodes), (1, [2]))

    def test_quality_is_not_episode(self):
        p = parse_media("Show.Name.S01E02.1080p.mkv")
        self.assertEqual(p.episodes, [2])


if __name__ == "__main__":
    unittest.main()
