# Troubleshooting

## Start here

```powershell
python $MO doctor --json
python $MO scan "<path>" --json
```

`doctor` shows Python/SQLite, state directory, index counts, keys, and tools.
`scan` is read-only and reveals parse problems before any plan exists.

## "No media files found"

- Check the path and `--recursive`.
- Supported video extensions: mkv, mp4, avi, m4v, mov, wmv, flv, ts, m2ts, mpg,
  mpeg, webm, vob, iso, 3gp.
- The scanner skips dot-directories, `sample`, `extras`, `featurettes`,
  `trailers`, `subs`, and system folders.
- If files are inside a skipped folder, move them or scan the subfolder directly.

## "local index is empty"

Build an index first:

```powershell
python $MO index build --root "<root>" --from "<index.json>"
```

Or set `MO_TMDB_KEY` / `MO_TVDB_KEY` and use `--db tmdb` / `--db tvdb`.

## Everything is `unmatched`

- Use `explain --plan <file> --item N` to see candidate/reasons.
- Try `--non-strict` to see title-only possibilities, then review carefully.
- Try `--q "Exact Show Name"` or `--q "tt1234567"` to force a query.
- Check that the filename contains an episode marker (`S01E02`, `1x02`,
  `Episode 2`, `- 12`, or a date) for TV mode.
- For movies, include a year (`Name.2023.mkv` or `Name (2023)/`).
- Local indexes must contain episode rows for TV matching.

## Low confidence / wrong candidate

- Remakes and regional versions are the usual cause. Use `--q` with the exact
  title, year, or provider id.
- Watch for `The Office` (US/UK/AU), `Battlestar Galactica` (1978/2004),
  `Ghost in the Shell` variants, and anime absolute numbering.
- Do not apply `< 0.60`. Ask the user when `0.60–0.90`.

## "plan hash mismatch"

The plan file changed after creation, or it was hand-edited. Regenerate:

```powershell
python $MO plan ... --plan-out plan.json
```

Do not patch plan JSON manually. Use `--q`, `--format`, or a different index.

## "source size changed" / "source mtime changed"

The files changed after planning (download still running, sync client, etc.).
Wait for the copy to finish, then regenerate the plan. `--force` skips the check
and is only for user-confirmed cases.

## Conflicts

- Default `skip` leaves the source untouched.
- `index`/`auto` picks `.1`, `.2`, ….
- `replace` backs up the existing destination under
  `.media-organizer/backups/<plan_id>/` before moving.
- If a conflict was skipped, the source is still at its original path.

## Access denied / network share

- Run non-elevated. Elevated processes under UAC cannot see mapped drives made
  in the standard user session.
- Prefer UNC paths (`\\server\share\Media`) over drive letters when automation
  runs in a different integrity level.
- Do not scan `C:\Windows`, `Program Files`, drive roots, or the home directory
  root; the safety checks reject these as roots.

## Reserved names / long paths

The formatter sanitizes `<>:"/\|?*`, control characters, trailing dots/spaces,
and Windows device names. Components over 200 characters are truncated. If a
destination has no extension, the source extension is appended.

## Subtitles fail

- `MO_OPENSUBTITLES_KEY` must be set; login is optional but improves quota.
- Hash search may return nothing for newly released or re-encoded files; the
  fallback is a name search.
- Downloaded ASS/SSA is converted to UTF-8 SRT. If the provider returns an
  unsupported container, the item fails and the journal records it.
- Use `--lang zh` / `--lang en` (ISO 639-1) consistently.

## Artwork/NFO

- `--apply nfo` writes `<name>.nfo`.
- `--apply metadata` writes `media-organizer.metadata` as an NTFS ADS/xattr; if
  the filesystem refuses, it falls back to `<name>.<ext>.mo.json`.
- `--apply artwork` currently downloads TMDb movie poster/backdrop images when
  the candidate has `poster_path`/`backdrop_path`. TV artwork is not fetched yet.

## Undo

```powershell
python $MO revert --journal "<journal>" --root "<root>"
```

Revert only acts when the source is absent and the destination exists. It is
idempotent. If a `replace` backup exists, it is restored to the destination after
the new file is moved back.

## Encoding

- CLI output is UTF-8; subtitles are written UTF-8.
- On consoles with legacy code pages, run from Windows Terminal or set
  `PYTHONUTF8=1`.

## Performance

- Local index scans are fast; online lookups are cached and rate-limited.
- Thousands of files are processed in one plan; apply is sequential by design to
  keep the journal deterministic.
- If a run is interrupted, the journal contains all completed operations; rerun
  `apply` with a fresh plan or `revert` the journal.
