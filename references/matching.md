# Matching and parsing

## Filename parsing

Order is specific → generic. The first successful pattern wins.

| Pattern | Example | Result |
|---|---|---|
| `SxxEyy`, `SxxEyy-Ezz`, `SxxEyyEzz` | `Show.S01E02-E03.mkv` | season 1, episodes 2–3 |
| `1x02`, `1x02-1x03` | `Show - 1x02.mkv` | season 1, episode 2 |
| `Season 1 Episode 2` | `Show Season 1 Episode 2.mkv` | season 1, episode 2 |
| `Episode 12`, `Ep12`, `E12` | `Show.E12.mkv` | absolute 12 |
| `- 12`, `[12]` | `[Group] Anime - 12.mkv` | absolute 12 |
| `1.02` | `Show.1.02.mkv` | season 1, episode 2 |
| Date | `Show.2024.05.01.mkv` | airdate |
| `Name (Year)` / `Name.Year` | `Movie.2023.mkv` | movie, 2023 |
| `Season 02/02.mkv` | folder + bare number | season 2, episode 2 |

Sanity filters reject absurd values (season > 300, episode > 3000) and quality
tokens such as `1080p`, `5.1`, `x265`.

Titles are the text before the first episode marker; dots/underscores become
spaces; leading `[Group]` and trailing release groups are separated. A trailing
year is stripped for series queries (`Show 2019 S01E02` → `Show`).

## Classification

- audio extension → music
- episode marker → TV (anime if bracket group / `Anime` folder / absolute only)
- `Name (Year)` without episode → movie
- otherwise unknown (left unmatched)

`--mode tv|movie|anime|music` overrides detection.

## Strict vs non-strict

- **Strict (default)**: TV requires an exact season/episode, absolute number, or
  airdate in the episode list. Movies require a name match and, when a year is
  present, the exact year. Ambiguous ties (within 0.04) are left unmatched.
- **Non-strict (`--non-strict`)**: title-only matches and best-effort fallbacks
  are allowed, with lower confidence. Always review non-strict plans.

## Confidence

TV:

```
exact episode: 0.82 + 0.10 * title + 0.05 * series   (capped 0.99)
title-only:    0.55 + 0.15 * title + 0.08 * series
date-only:     0.75
```

Movies:

```
0.50 + 0.30 * name + 0.10 (exact year)
```

Guidance: `>= 0.90` auto; `0.60–0.90` ask; `< 0.60` do not guess.

## Series selection

1. Search the provider/index with the parsed title (or `--q`).
2. Score name + aliases; add a small bonus for exact/adjacent year.
3. Pick the top result if it is clearly ahead; otherwise leave unmatched and
   suggest `--q "Exact Name"`.

## Episode assignment

Candidate episodes are restricted by SxxEyy/absolute/airdate. Remaining pairs are
claimed greedily by score, one file per episode and one episode per file. This
mirrors the usual "unique match first, then fall back" behavior without an
assignment solver.

Multi-episode files (`S01E01-E02`) are matched only when all requested episodes
exist in the same season and are collapsed into a single candidate
(`S01E01-E02` in formats).

Anime absolute numbering matches `{absolute}` or season-1 episode numbers when
the provider has no absolute field.

## Sidecars

Files in the same folder whose stem starts with the video stem are treated as
sidecars:

- subtitles: `.srt`, `.ass`, `.ssa`, `.sub`, `.vtt`, `.smi`, `.idx`, `.sup`
- metadata: `.nfo`, `.txt`, `.xml`, `.json`
- images: `.jpg`, `.jpeg`, `.png`, `.webp`

Their destination is the renamed video stem plus the original suffix, e.g.
`Show.S01E02.en.srt` → `Show - S01E02 - Title.en.srt`.

## Conflicts

| Mode | Behavior |
|---|---|
| `skip` (default) | leave source in place, mark `conflict` |
| `index` / `auto` | choose `name.1.ext`, `name.2.ext`, … |
| `replace` | move the existing destination to `.media-organizer/backups/<plan>/` first |
| `fail` | mark as failed and do not touch it |

Apply re-checks conflicts even though the plan already resolved them.
