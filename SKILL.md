---
name: media-organizer
description: >
  Media library organizer: scan movies/TV/anime/music, parse filenames, match
  TMDb/TVDB/TVmaze/OMDb or a local offline index, render Plex/Kodi/Emby/
  Jellyfin-style formats (including {plex}, {kodi}, {emby}, {jellyfin}), fetch
  subtitles/artwork/NFO, and apply renames with dry-run plans and undo journals.
  MUST USE when the user points at media folders or downloads and asks to
  rename, organize, sort, scrape, fetch subtitles, or organize a media library.
  Triggers: 整理媒体库, 重命名美剧, 电影改名, 剧集整理, 刮削, 字幕下载, 自动改名,
  rename TV shows, organize movies, media library, episode matching.
  NOT for generic batch rename without media metadata, plain copying, or
  license/paywall circumvention.
---

# Media Organizer

A pure-Python media organizer. It does **not** call any proprietary organizer,
does not need a third-party license, and does not reuse third-party code,
assets, API keys, or index data.

## When to use

- The user has a folder of movies / TV episodes / anime / music and wants correct
  names, season folders, or Plex/Kodi/Emby/Jellyfin layouts.
- The user wants to preview renames, then apply them, with an undo path.
- The user wants subtitles or NFO/artwork/metadata sidecars.
- The user references common media-renamer formats such as `{n}`, `{s00e00}`,
  `{t}`, `{plex}`.

## When not to use

- Generic file renames that have nothing to do with media identity.
- Pure copy/backup jobs with no matching step.
- Bypassing licenses or paywalls. This skill never does that.
- Modifying system folders, drive roots, or the user's home directory root.

## Hard rules

1. **Dry-run first.** Always `scan` → `plan` → show summary → `apply`.
   Never mutate files before the user has seen the plan.
2. **Never hand-write `mv` / `Move-Item` / `os.rename`.** All mutations go
   through `scripts/mo.py`. This is what makes plans hash-verified and undoable.
3. **Default is safe.** `--action move`, `--conflict skip`, no overwrite,
   no delete. `replace` and bulk runs over 50 files require explicit confirmation.
4. **Stay inside the root.** Destinations must remain under the scanned root or
   an explicit `--output`. Absolute paths outside those roots are rejected.
5. **No surprise network calls.** Offline mode (`--db local`) is the default when
   no TMDb key is configured. Only use online providers when keys exist and the
   task needs them.
6. **Never print API keys.** Reports and logs must not include key values.
7. **Report outcomes.** Say how many files matched, were skipped, failed, and
   where the plan/journal live. Offer `revert` on any doubt.

## Setup

Resolve the skill directory once:

```powershell
$MO = "$env:USERPROFILE\.config\opencode\skills\media-organizer\scripts\mo.py"
python $MO doctor --json
```

`doctor` reports Python/SQLite, state directory, index counts, provider keys, and
optional tools (`fpcalc`, `ffprobe`). Missing online keys are not fatal.

State defaults to `%LOCALAPPDATA%\media-organizer` so indexes and plans work
across subfolders. A library is self-contained if `<root>\.media-organizer`
exists (or if every command gets the same `--state-dir`). Plans record their
state directory, so `apply` uses the same database automatically.

## Standard workflow

### 1. Scan (read-only)

```powershell
python $MO scan "D:\Media\TV" --recursive --json
```

Look for the summary (`files`, `by_kind`, `sidecars`, `warnings`). Do not proceed
if the target is a drive root, the home directory root, or a system directory.

### 2. Plan (dry-run, no mutation)

```powershell
python $MO plan "D:\Media\TV" --mode tv --db auto `
  --format "{n} - {s00e00} - {t}" `
  --action move --conflict skip `
  --output "D:\Media\Organized" `
  --plan-out "D:\Media\plans\tv.json"
```

Notes:

- `--mode auto` handles mixed libraries (TV + movies + music) and uses the
  default format per kind.
- `--db auto` uses TMDb when `MO_TMDB_KEY` is set, otherwise the local index.
- `--format "{plex}"` produces a full Plex path; do not also add folders by hand.
- `--non-strict` enables title-only matching. Prefer strict for first passes.

### 3. Review the plan

Print the summary and the first rows. Pay attention to:

| Status | Meaning | Action |
|---|---|---|
| `ok` | unique match, destination free | safe to apply |
| `indexed` | destination exists, `.1` name chosen | safe if intended |
| `replace` | destination exists and would be replaced | require explicit confirmation |
| `conflict` | destination exists, skipped | leave as-is or switch to `index` |
| `unmatched` | no confident candidate | do not guess; ask user / use `--q` |
| `error` | parse/format/path problem | fix input or format |

Confidence guidance:

- `>= 0.90`: usually safe.
- `0.60–0.90`: explain the candidate; ask if the library has remakes, regional
  versions, or multiple shows with similar names.
- `< 0.60`: do not apply. Re-run with `--q "Exact Name"`, `--mode`, or a better
  index.

Use `explain` for one item:

```powershell
python $MO explain --plan "D:\Media\plans\tv.json" --item 3 --json
```

### 4. Apply (only after confirmation)

```powershell
python $MO apply --plan "D:\Media\plans\tv.json" --yes
```

`apply` re-verifies the plan hash, source size/mtime, destination bounds, and
conflicts. It writes one journal line per file before/after each operation.

- Add `--dry-run` to validate a plan without touching anything.
- Add `--force` only if the user confirms the source files changed after planning.
- `--action test` plans are safe to "apply" (no-op).

### 5. Verify and offer undo

Check the applied count, failures, and the journal path. If anything looks wrong:

```powershell
python $MO revert --journal "<journal path>" --root "D:\Media\TV"
```

Revert is idempotent: it only moves back when the source is absent and the
destination exists.

## Other commands

```powershell
# Local/offline index (JSON or CSV; see references/providers.md)
python $MO index build --root "D:\Media" --from "D:\Media\index.json"
python $MO index stats --root "D:\Media"
python $MO index search --root "D:\Media" --series "show name"

# Subtitle plan; apply with the same apply command
python $MO subs "D:\Media\TV" --lang zh --plan-out "D:\Media\plans\subs.json"
python $MO apply --plan "D:\Media\plans\subs.json" --yes

# Post-processing while renaming
python $MO plan ... --apply nfo --apply metadata --apply artwork
```

## Output contract to the user

Report:

1. Plan id and plan file path.
2. Counts: total, matched, unmatched, conflicts, errors, sidecars.
3. Up to 10 representative `source -> destination` lines.
4. Any `unmatched` / low-confidence items and the exact next command.
5. After apply: applied/skipped/failed counts and the journal path.

Use `--json` for machine-readable output; keep the human summary short.

## Safety rules (Windows specifics)

- Run **non-elevated**. Elevated processes cannot see the user's mapped network
  drives under UAC. If the media lives on a mapped drive, launch the agent from a
  normal shell or use the UNC path.
- Reserved names (`CON`, `PRN`, `AUX`, `NUL`, `COM1`…), trailing dots/spaces,
  and `<>:"/\|?*` are sanitized automatically. Do not disable this.
- Case-insensitive collisions are detected on Windows.
- Symlinks may require Developer Mode or elevation; prefer `move`/`copy` unless
  the user asks for links.
- Long paths are allowed by modern Python, but keep destination components under
  200 characters.

## References

- `references/formats.md` — all bindings, expression syntax, presets, examples.
- `references/matching.md` — parsing rules, strictness, confidence, conflicts.
- `references/providers.md` — offline index schema, keys, endpoints, caching.
- `references/troubleshooting.md` — common failures and fixes.
