# media-organizer

A pure-Python, agent-first media library organizer. It is a clean-room
implementation of common media-library workflows: parse media filenames,
resolve identities against metadata providers or a local index, match files to
episodes/movies, render Plex/Kodi/Emby/Jellyfin-style destination paths, and
apply renames with dry-run plans and undo journals.

- No proprietary organizer runtime, license, code, assets, API keys, or index
  data is used.
- Standard library only at runtime (Python 3.11+).
- Windows-first path safety, cross-platform where possible.

## Install

The skill lives at:

```
%USERPROFILE%\.config\opencode\skills\media-organizer\
```

No dependencies are required. Optional:

- `TMDb` / `TVDB` / `OMDb` / `OpenSubtitles` API keys (environment variables).
- `fpcalc` (Chromaprint) for AcoustID music enrichment.
- `ffprobe` for future media probing.

## Quick start

```powershell
$MO = "$env:USERPROFILE\.config\opencode\skills\media-organizer\scripts\mo.py"

python $MO doctor --json
python $MO scan "D:\Media\TV" --json
python $MO plan "D:\Media\TV" --mode tv --db local `
  --format "{n} - {s00e00} - {t}" `
  --plan-out "D:\Media\tv.json"
python $MO apply --plan "D:\Media\tv.json" --yes
python $MO revert --journal "<journal path>" --root "D:\Media\TV"
```

Offline demo (local index):

```powershell
python $MO index build --root "D:\Media" --from "D:\Media\index.json"
python $MO plan "D:\Media" --mode auto --db local --output "D:\Media\Organized"
```

## Commands

| Command | Purpose |
|---|---|
| `doctor` | environment, state, keys, tools, index stats |
| `scan` | read-only inventory with parsed identity |
| `plan` | build a hash-verified dry-run plan |
| `apply` | execute a plan with journal/backup |
| `revert` | undo a journal |
| `subs` | build a subtitle download plan |
| `index build/stats/search` | local offline metadata index |
| `explain` | inspect one plan item |

## Design

```
scan → parse → classify → resolve (index/providers) → match → format → plan
     → apply (journal) → post-process (nfo/metadata/artwork) → revert
```

- Plans are content-addressed (`sha256`), so edits are detected.
- State defaults to one global directory; a `.media-organizer` marker in any
  ancestor (or `--state-dir`) opts a library into its own database.
- Apply re-checks source size/mtime, destination bounds, and conflicts.
- `move`/`copy`/`hardlink`/`symlink` are supported; `replace` backs up first.
- Subtitle downloads are converted to UTF-8 SRT (ASS/SSA supported).

## Tests

```powershell
cd "$env:USERPROFILE\.config\opencode\skills\media-organizer\tests"
python -m unittest discover -v
```

54 tests cover parsing, formatting, path safety, index search, plan/apply/revert,
provider response mapping, subtitles, and ID3.

## Limitations

- Expression support is a safe subset, not full Groovy. Unknown bindings fail
  loudly instead of silently rendering wrong paths.
- Matching uses a compact multi-metric cascade (season/episode, airdate, title,
  series name, year) rather than a full 20-metric list. XEM scene mapping is not
  implemented.
- AniDB live search is not implemented; import AniDB-shaped data into the local
  index or use TMDb/TVmaze.
- Artwork downloads currently use TMDb movie poster/backdrop paths.
- No GUI.
