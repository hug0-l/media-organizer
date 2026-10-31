# Index and providers

## Local index (offline-first)

The local index is a SQLite database in the state directory. Build it from JSON
or CSV; no network is required at match time.

```powershell
python $MO index build --root "D:\Media" --from "D:\Media\index.json"
python $MO index stats --root "D:\Media"
```

### JSON schema

```json
{
  "series": [
    {
      "name": "Show Name",
      "year": 2019,
      "tmdb_id": 1001,
      "tvdb_id": 81189,
      "imdb_id": "tt0903747",
      "aliases": ["Show", "The Show"],
      "popularity": 10,
      "episodes": [
        {"season": 1, "episode": 1, "title": "Pilot", "airdate": "2019-01-01"},
        {"season": 1, "episode": 2, "title": "Episode Two", "airdate": "2019-01-08"}
      ]
    }
  ],
  "movies": [
    {
      "name": "Movie Name",
      "year": 2023,
      "tmdb_id": 2002,
      "imdb_id": "tt1234567",
      "aliases": ["The Movie"],
      "popularity": 5
    }
  ]
}
```

`id` is optional. If omitted, the builder uses `tmdb:<tmdb_id>` or a normalized
`local:<name>:<year>` key. Episode rows are required for TV matching; a series
without episodes can be searched but will not produce matches.

### CSV schema

Header-based, one row per series or movie:

```csv
type,name,year,tmdb_id,tvdb_id,imdb_id,aliases,episodes
series,Show Name,2019,1001,,,Show|The Show,"[{""season"":1,""episode"":1,""title"":""Pilot""}]"
movie,Movie Name,2023,2002,,tt1234567,The Movie,
```

`type` defaults to `series`; aliases are `|`-separated; `episodes` is a JSON array.

### Where the index lives

The CLI uses one state directory so indexes, plans, and journals work across
subfolders:

1. `--state-dir <path>` if provided.
2. The nearest ancestor containing `.media-organizer\` (per-library opt-in).
3. Otherwise the global directory:
   - Windows: `%LOCALAPPDATA%\media-organizer\`
   - Unix: `$XDG_DATA_HOME/media-organizer/` or `~/.media-organizer/`

To make a library self-contained, create `<root>\.media-organizer\` before the
first command, or pass `--state-dir "<root>\.media-organizer"` consistently.
Plans record their state directory, so `apply` finds the same database.
`doctor <root>` shows the actual path.

## Online providers

Keys are read from environment variables or `config.json` (`{"keys": {...}}`)
in the state directory. No keys are bundled.

| Provider | Key env | Notes |
|---|---|---|
| TMDb | `MO_TMDB_KEY` | default when a key is present; movies + TV |
| TVDB | `MO_TVDB_KEY` | v4 API; login token cached per process |
| TVmaze | none | TV only; no key |
| OMDb | `MO_OMDB_KEY` | movies; exact-title fallback |
| OpenSubtitles | `MO_OPENSUBTITLES_KEY` | subtitles; optional `MO_OPENSUBTITLES_USER` / `_PASS` |
| AcoustID | `MO_ACOUSTID_KEY` | optional music enrichment; needs `fpcalc` |

`--db local|tmdb|tvdb|tvmaze|omdb` selects explicitly. `--db auto` uses TMDb if
its key is present, otherwise the local index.

### Endpoints

| Provider | Base |
|---|---|
| TMDb | `https://api.themoviedb.org/3/` |
| TVDB v4 | `https://api4.thetvdb.com/v4/` |
| TVmaze | `https://api.tvmaze.com/` |
| OMDb | `https://www.omdbapi.com/` |
| OpenSubtitles REST | `https://www.opensubtitles.com/api/v1/` |
| AcoustID | `https://api.acoustid.org/v2/lookup` |
| TMDb images | `https://image.tmdb.org/t/p/original` |

### Cache and limits

- HTTP responses are cached in SQLite `provider_cache`.
- TTL: search 7 days, details/episodes 30 days, subtitles 7 days.
- One request at a time per host with a small delay; 429/5xx retried twice with
  backoff.
- No telemetry, no background sync, no automatic index downloads.

### OpenSubtitles

- Search first by OpenSubtitles hash, then by parsed name.
- Hash = file size + 64-bit little-endian word sums of first/last 64 KiB.
- Downloads may be gzip/zip; the subtitle is extracted and converted to UTF-8
  SRT when it is ASS/SSA.
- Respect the provider's quota and terms; anonymous downloads may be limited.

### Music

- ID3v2.3/v2.4 and ID3v1 tags are read with the standard library.
- If tags are incomplete, `fpcalc` + AcoustID can fill title/artist/album when
  `MO_ACOUSTID_KEY` and `fpcalc` are available.

## Legal / terms

- Each provider has its own terms of service and attribution requirements.
  Obtain your own credentials; do not reuse another application's embedded keys.
- The local index is your data. Do not redistribute third-party metadata without
  permission.
- This skill is an independent implementation; it does not include third-party
  application code, assets, index data, or license bypass logic.
