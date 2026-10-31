import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from mo.format import FormatError, build_bindings, render  # noqa: E402
from mo.models import EpisodeRef, MovieRef, MusicRef  # noqa: E402


class FormatTests(unittest.TestCase):
    def setUp(self):
        self.ep = EpisodeRef(
            series_id="tmdb:1", series_name="Show Name", season=1,
            episode=2, title="Episode Title", series_year=2019,
        )
        self.b = build_bindings(self.ep, r"C:\Media\Show.Name.S01E02.1080p.mkv", kind="tv")

    def test_tokens(self):
        self.assertEqual(render("{n} - {s00e00} - {t}", self.b), "Show Name - S01E02 - Episode Title")

    def test_pad_and_functions(self):
        self.assertEqual(render("{pad(e,2)}", self.b), "02")
        self.assertEqual(render("{n.upper()}", self.b), "SHOW NAME")
        self.assertEqual(render('{n.replaceAll(" ", "_")}', self.b), "Show_Name")

    def test_ternary(self):
        self.assertEqual(render('{s == 1 ? "S01" : "x"}', self.b), "S01")

    def test_plex(self):
        self.assertEqual(
            render("{plex}", self.b),
            "TV Shows/Show Name/Season 01/Show Name - S01E02 - Episode Title",
        )

    def test_movie(self):
        mv = MovieRef(id="tmdb:2", name="Movie Name", year=2023)
        b = build_bindings(mv, r"C:\Media\Movie.Name.2023.mkv", kind="movie")
        self.assertEqual(render("{n} ({y})", b), "Movie Name (2023)")
        self.assertEqual(render("{plex}", b), "Movies/Movie Name (2023)/Movie Name (2023)")

    def test_multi_episode(self):
        ep = EpisodeRef(
            series_id="x", series_name="Multi Show", season=1, episode=1,
            title="Part One", raw={"episodes": [1, 2]},
        )
        b = build_bindings(ep, r"C:\Media\Multi.S01E01-E02.mkv", kind="tv")
        self.assertEqual(render("{s00e00}", b), "S01E01-E02")

    def test_music(self):
        mu = MusicRef(id="m1", artist="Artist", album_artist="Album Artist", album="Album", title="Song", track=3)
        b = build_bindings(mu, r"C:\Music\03 - Song.mp3", kind="music")
        self.assertEqual(render("{albumArtist}/{album}/{track} - {t}", b), "Album Artist/Album/03 - Song")

    def test_undefined_binding(self):
        with self.assertRaises(FormatError):
            render("{does_not_exist}", self.b)

    def test_unbalanced_braces(self):
        with self.assertRaises(FormatError):
            render("{n", self.b)

    def test_constant_rejected(self):
        with self.assertRaises(FormatError):
            render("plain text", self.b)


if __name__ == "__main__":
    unittest.main()
