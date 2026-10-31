import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from mo.providers.omdb import OMDbProvider  # noqa: E402
from mo.providers.opensubtitles import OpenSubtitlesProvider  # noqa: E402
from mo.providers.tmdb import TMDbProvider  # noqa: E402
from mo.providers.tvdb import TVDBProvider  # noqa: E402
from mo.providers.tvmaze import TVmazeProvider  # noqa: E402
from mo.state import State  # noqa: E402


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = State(root=Path(self.tmp.name))

    def tearDown(self):
        self.state.close()
        self.tmp.cleanup()

    def test_tmdb(self):
        with patch.dict(os.environ, {"MO_TMDB_KEY": "k"}):
            p = TMDbProvider(self.state)
        calls = []

        def fake(url, params=None, headers=None, ttl=0):
            calls.append(url)
            if url.endswith("/search/tv"):
                return {"results": [{"id": 10, "name": "Show", "original_name": "Show Original", "first_air_date": "2019-01-01", "popularity": 5}]}
            if url.endswith("/search/movie"):
                return {"results": [{"id": 20, "title": "Movie", "original_title": "Movie", "release_date": "2023-05-01", "popularity": 9}]}
            if url.endswith("/tv/10"):
                return {"name": "Show", "first_air_date": "2019-01-01", "seasons": [{"season_number": 1, "episode_count": 2}]}
            if url.endswith("/tv/10/season/1"):
                return {"episodes": [
                    {"season_number": 1, "episode_number": 1, "name": "Pilot", "air_date": "2019-01-01"},
                    {"season_number": 1, "episode_number": 2, "name": "Two", "air_date": "2019-01-08"},
                ]}
            return {}

        p.http.get_json = fake
        series = p.search_series("Show")
        self.assertEqual(series[0].tmdb_id, 10)
        self.assertEqual(series[0].year, 2019)
        eps = p.episodes("tmdb:10")
        self.assertEqual([e.episode for e in eps], [1, 2])
        self.assertEqual(eps[1].title, "Two")
        movies = p.search_movies("Movie", year=2023)
        self.assertEqual(movies[0].year, 2023)

    def test_tvmaze(self):
        p = TVmazeProvider(self.state)

        def fake(url, params=None, headers=None, ttl=0):
            if url.endswith("/search/shows"):
                return [{"score": 9.5, "show": {"id": 7, "name": "Show", "premiered": "2020-02-02"}}]
            if url.endswith("/shows/7"):
                return {"id": 7, "name": "Show", "premiered": "2020-02-02"}
            if url.endswith("/shows/7/episodes"):
                return [{"season": 2, "number": 3, "name": "Ep", "airdate": "2021-03-03"}]
            return {}

        p.http.get_json = fake
        s = p.search_series("Show")
        self.assertEqual(s[0].id, "tvmaze:7")
        eps = p.episodes("tvmaze:7")
        self.assertEqual((eps[0].season, eps[0].episode), (2, 3))

    def test_tvdb(self):
        with patch.dict(os.environ, {"MO_TVDB_KEY": "k"}):
            p = TVDBProvider(self.state)
        p.http.post_json = lambda url, data, headers=None, ttl=-1: {"data": {"token": "t"}}

        def fake(url, params=None, headers=None, ttl=0):
            if url.endswith("/search"):
                return {"data": [{"tvdb_id": 42, "name": "Show", "first_air_time": "2018-01-01"}]}
            if url.endswith("/series/42/extended"):
                return {"data": {"name": "Show", "firstAired": "2018-01-01"}}
            if url.endswith("/series/42/episodes/default"):
                return {"data": {"episodes": [{"seasonNumber": 1, "number": 1, "name": "Pilot", "aired": "2018-01-01"}]}, "links": {}}
            return {}

        p.http.get_json = fake
        s = p.search_series("Show")
        self.assertEqual(s[0].tvdb_id, 42)
        eps = p.episodes("tvdb:42")
        self.assertEqual(eps[0].title, "Pilot")
        self.assertEqual(eps[0].series_year, 2018)

    def test_omdb(self):
        with patch.dict(os.environ, {"MO_OMDB_KEY": "k"}):
            p = OMDbProvider(self.state)
        p.http.get_json = lambda url, params=None, headers=None, ttl=0: {
            "Search": [{"Title": "Movie", "Year": "2023", "imdbID": "tt1234567"}]
        }
        movies = p.search_movies("Movie")
        self.assertEqual(movies[0].imdb_id, "tt1234567")
        self.assertEqual(movies[0].year, 2023)

    def test_opensubtitles_search(self):
        with patch.dict(os.environ, {"MO_OPENSUBTITLES_KEY": "k"}):
            p = OpenSubtitlesProvider(self.state)
        p.http.get_json = lambda url, params=None, headers=None, ttl=0: {
            "data": [{"attributes": {
                "language": "en", "release": "Show.S01E01", "download_count": 10,
                "ratings": 8.0, "files": [{"file_id": 99, "file_name": "a.srt"}],
                "feature_details": {"title": "Show"},
            }}]
        }
        rows = p.search("Show", languages="en")
        self.assertEqual(rows[0].file_id, 99)
        self.assertEqual(rows[0].language, "en")


if __name__ == "__main__":
    unittest.main()
