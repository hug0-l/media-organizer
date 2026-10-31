# Format expressions

The formatter is a **safe expression subset**. It is not a general-purpose
language and it never executes arbitrary code.

## Syntax

A format is literal text plus `{ expression }` blocks:

```
{n} - {s00e00} - {t}
{ny}/{ny}
{plex}
```

- Braces nest: `{s == 1 ? "S01" : "S02"}`.
- A format with no `{...}` block is rejected (prevents accidental constant names).
- Unknown bindings throw an error; they never render as empty silently.

## Expressions

Supported operators, highest priority first:

| Operator | Meaning |
|---|---|
| `()` `[]` `.` | grouping, list, attribute/method |
| `!` `-` | not, negation |
| `*` `/` `%` | arithmetic |
| `+` `-` | add/subtract (string concat with `+`) |
| `<` `>` `<=` `>=` | comparison |
| `==` `!=` | equality (case-insensitive for strings) |
| `&&` `||` | boolean |
| `? :` | ternary |

Literals: `'text'`, `"text"`, integers, decimals, `true`, `false`, `null`.

Functions:

`upper`, `lower`, `title`, `trim`/`strip`, `replace(s, a, b)`,
`replaceall(s, regex, repl)`, `match(s, regex)`, `contains`, `startswith`,
`endswith`, `split`, `join`, `pad(value, width, char)`, `default(value, fallback)`,
`coalesce(...)`, `len`, `int`, `str`, `abs`, `round`, `exists`, `basename`,
`dirname`, `ext`, `date(value, fmt)`, `now(fmt)`, `list(...)`.

Methods on strings: `.upper()`, `.lower()`, `.title()`, `.strip()`,
`.replace(a, b)`, `.replaceAll(regex, repl)`, `.startswith()`, `.endswith()`,
`.split()`.

Regex literals (`/.../`) are **not** supported. Pass a regex as a string:

```
{replaceall(n, "[!?.]+$", "")}
```

## Bindings

### Identity / episode

| Token | Meaning |
|---|---|
| `{n}` | series or movie name |
| `{y}` | year |
| `{ny}` | `Name (Year)` |
| `{s}` `{e}` | season / episode number |
| `{es}` | list of episode numbers |
| `{s00}` `{e00}` | zero-padded season / episode |
| `{s00e00}` `{sxe}` | `S01E02` (multi: `S01E01-E02`) |
| `{sn}` | `Season 01` |
| `{t}` | episode or movie title |
| `{d}` `{airdate}` | air date (`YYYY-MM-DD`) |
| `{absolute}` | absolute episode number |
| `{special}` | special number |
| `{series}` | series name |
| `{id}` `{tmdbid}` `{tvdbid}` `{imdbid}` `{db}` | identifiers |
| `{episode}` `{episodes}` `{movie}` `{music}` | candidate objects |
| `{type}` | `tv` / `anime` / `movie` / `music` |
| `{anime}` `{regular}` | anime / regular flags |
| `{primaryTitle}` | reserved (title) |
| `{alias}` | reserved (aliases) |
| `{order}` `{localize}` | reserved (sort/localized objects) |
| `{historic}` `{info}` | reserved metadata objects |

### Release / technical

| Token | Meaning |
|---|---|
| `{vf}` `{resolution}` | `1080p`, `2160p`… |
| `{vc}` | video codec (`x264`, `hevc`…) |
| `{ac}` | audio codec |
| `{hdr}` | HDR tag |
| `{bitdepth}` | `10bit` |
| `{group}` | release group |
| `{source}` `{vs}` | `WEB-DL`, `BluRay`… |
| `{edition}` | `extended`, `uncut`… |
| `{lang}` `{languages}` | reserved language bindings |

### File / path

| Token | Meaning |
|---|---|
| `{f}` `{mediaFile}` | absolute source path |
| `{fn}` `{mediaFileName}` | source filename |
| `{ext}` | extension without dot |
| `{folder}` | source parent |
| `{root}` `{drive}` | root / drive |
| `{home}` `{output}` | home / output folder |
| `{bytes}` `{megabytes}` `{gigabytes}` | file size |
| `{today}` | today's date |
| `{az}` `{decade}` | initial / decade |
| `{defines}` `{label}` | reserved user variables |

### Naming presets

| Token | Result |
|---|---|
| `{plex}` | `TV Shows/Series/Season 01/Series - S01E02 - Title` or `Movies/Name (Year)/Name (Year)` |
| `{kodi}` | `Season 1` (no zero padding), multi-episode `S01E01-E02`, IDs ` {tmdb-123}` |
| `{emby}` | IDs ` [tmdbid=123]` |
| `{jellyfin}` | IDs ` [tmdbid-123]` |

For music: `{albumArtist}`, `{artist}`, `{album}`, `{track}`, `{t}`.

## Presets / examples

```text
# TV, flat
{n} - {s00e00} - {t}

# TV, library folders
{n}/Season {s00}/{n} - {s00e00} - {t}

# TV, Plex
{plex}

# Movies
{n} ({y})/{n} ({y})

# Movies with collection
{n} ({y})/{n} ({y})

# Anime absolute numbering
{n} - {absolute} - {t}

# Music
{albumArtist}/{album}/{track} - {t}

# Conditional edition
{n} ({y}){edition == "" ? "" : " - " + edition}
```

## Sanitization

After rendering, each path component is cleaned:

- Windows-invalid characters `<>:"/\|?*` and control characters → space.
- `:` becomes ` - ` for readability.
- Trailing dots/spaces removed.
- Reserved device names get a `_` prefix.
- Components longer than 200 characters are truncated.
- `..` path segments are rejected.

Use `--unixfs` only on filesystems that allow special characters; it does not
disable `..` protection.
