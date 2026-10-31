from __future__ import annotations

from dataclasses import dataclass, field

from .models import EpisodeRef, MatchResult, MediaFile, MovieRef, MusicRef, SeriesRef
from .parse import ParsedMedia
from .providers.base import Provider, ProviderError
from .util.text import normalize_name, similarity, title_similarity


@dataclass
class MatchOutput:
    matches: list[MatchResult] = field(default_factory=list)
    unmatched: list[MediaFile] = field(default_factory=list)
    unresolved_series: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _series_score(query: str, parsed: ParsedMedia | None, s: SeriesRef) -> float:
    names = [s.name, *s.aliases]
    sim = max((similarity(query, n) for n in names if n), default=0.0)
    if normalize_name(query) == normalize_name(s.name):
        sim = max(sim, 1.0)
    if parsed and parsed.year and s.year:
        if parsed.year == s.year:
            sim += 0.08
        elif abs(parsed.year - s.year) <= 1:
            sim += 0.03
    return min(1.0, sim)


def choose_series(
    query: str,
    parsed: ParsedMedia | None,
    candidates: list[SeriesRef],
    strict: bool = True,
) -> tuple[SeriesRef | None, str | None]:
    if not candidates:
        return None, "no series candidates"
    ranked = sorted(
        ((_series_score(query, parsed, s), s) for s in candidates),
        key=lambda x: (x[0], x[1].popularity, x[1].year or 0),
        reverse=True,
    )
    top_score, top = ranked[0]
    if top_score < 0.45:
        return None, f"low series similarity ({top_score:.2f})"
    if strict and len(ranked) > 1 and abs(top_score - ranked[1][0]) < 0.04:
        return None, f"ambiguous series: {top.name} / {ranked[1][1].name}"
    return top, None


def _episode_key(ep: EpisodeRef) -> str:
    return f"{ep.series_id}:{ep.season}:{ep.episode}"


def _episode_numbers(ep: EpisodeRef) -> list[int]:
    raw_eps = ep.raw.get("episodes") if isinstance(ep.raw, dict) else None
    if raw_eps:
        return [int(x) for x in raw_eps]
    return [ep.episode] if ep.episode is not None else []


def _score_episode(parsed: ParsedMedia, ep: EpisodeRef) -> tuple[float, list[str]]:
    reasons: list[str] = []
    exact = False
    eps = _episode_numbers(ep)

    if parsed.season is not None and parsed.episodes:
        if ep.season == parsed.season and set(parsed.episodes).issubset(set(eps)):
            exact = True
            reasons.append("season/episode exact")
    elif parsed.absolute is not None:
        if ep.absolute == parsed.absolute or (ep.season in (None, 1) and ep.episode == parsed.absolute):
            exact = True
            reasons.append("absolute episode exact")
    elif parsed.air_date and ep.airdate == parsed.air_date:
        exact = True
        reasons.append("airdate exact")

    title_sim = title_similarity(parsed.raw, ep.title) if ep.title else 0.0
    if title_sim >= 0.35:
        reasons.append(f"title {title_sim:.2f}")
    series_sim = similarity(parsed.title, ep.series_name)
    if series_sim >= 0.6:
        reasons.append(f"series name {series_sim:.2f}")

    if exact:
        conf = 0.82 + 0.1 * title_sim + 0.05 * series_sim
        if title_sim < 0.2:
            conf -= 0.04
        return min(0.99, conf), reasons
    if title_sim >= 0.55 and series_sim >= 0.5:
        return min(0.79, 0.55 + 0.15 * title_sim + 0.08 * series_sim), reasons + ["title-only"]
    if parsed.air_date and ep.airdate and parsed.air_date == ep.airdate:
        return 0.75, reasons + ["date-only"]
    return 0.0, reasons


def _combine_multi(parsed: ParsedMedia, eps: list[EpisodeRef]) -> EpisodeRef:
    base = eps[0]
    numbers = sorted({e.episode for e in eps if e.episode is not None})
    return EpisodeRef(
        series_id=base.series_id, series_name=base.series_name,
        season=base.season, episode=numbers[0] if numbers else None,
        title=" / ".join(e.title for e in eps if e.title),
        airdate=base.airdate, absolute=base.absolute,
        special=base.special, series_year=base.series_year, source=base.source,
        raw={**base.raw, "episodes": numbers, "episode_refs": eps},
    )


def match_tv(
    files: list[MediaFile],
    provider: Provider,
    query: str | None = None,
    strict: bool = True,
) -> MatchOutput:
    out = MatchOutput()
    groups: dict[str, list[MediaFile]] = {}
    for mf in files:
        parsed = mf.parsed
        if parsed is None or parsed.kind != "tv":
            out.unmatched.append(mf)
            continue
        key = normalize_name(query or parsed.title or "") or "__all__"
        groups.setdefault(key, []).append(mf)

    episode_cache: dict[str, list[EpisodeRef]] = {}
    for key, group in groups.items():
        title = query or group[0].parsed.title
        candidates = provider.search_series(title, year=group[0].parsed.year)
        series, why = choose_series(title, group[0].parsed, candidates, strict=strict)
        if series is None:
            out.unresolved_series.append(f"{title}: {why}")
            out.unmatched.extend(group)
            continue
        if series.id not in episode_cache:
            episode_cache[series.id] = provider.episodes(series.id)
        episodes = episode_cache[series.id]
        if not episodes:
            out.unresolved_series.append(f"{series.name}: provider returned no episodes")
            out.unmatched.extend(group)
            continue

        # candidate generation
        pairs: list[tuple[float, MediaFile, EpisodeRef, list[str]]] = []
        for mf in group:
            parsed = mf.parsed
            possible: list[EpisodeRef] = []
            if parsed.season is not None and parsed.episodes:
                if len(parsed.episodes) > 1:
                    by_num = {e.episode: e for e in episodes if e.season == parsed.season}
                    if all(n in by_num for n in parsed.episodes):
                        possible = [_combine_multi(parsed, [by_num[n] for n in parsed.episodes])]
                else:
                    possible = [
                        e for e in episodes
                        if e.season == parsed.season and e.episode == parsed.episodes[0]
                    ]
            elif parsed.absolute is not None:
                possible = [
                    e for e in episodes
                    if e.absolute == parsed.absolute
                    or (e.season in (None, 1) and e.episode == parsed.absolute)
                ]
            if not possible and parsed.air_date:
                possible = [e for e in episodes if e.airdate == parsed.air_date]
            if not possible and not strict:
                possible = episodes[:50]
            for ep in possible:
                score, reasons = _score_episode(parsed, ep)
                if score > 0:
                    pairs.append((score, mf, ep, reasons))

        pairs.sort(key=lambda x: (x[0], x[2].season or 0, x[2].episode or 0), reverse=True)
        used_files: set[str] = set()
        used_candidates: set[str] = set()
        assigned: dict[str, MatchResult] = {}
        for score, mf, ep, reasons in pairs:
            if mf.path in used_files:
                continue
            k = _episode_key(ep)
            if k in used_candidates:
                continue
            used_files.add(mf.path)
            used_candidates.add(k)
            assigned[mf.path] = MatchResult(
                file=mf, candidate=ep, confidence=score, reasons=reasons, kind="tv"
            )

        for mf in group:
            if mf.path in assigned:
                out.matches.append(assigned[mf.path])
            elif not strict:
                # last-resort unique candidate
                remaining = [e for e in episodes if _episode_key(e) not in used_candidates]
                if remaining:
                    out.matches.append(MatchResult(
                        file=mf, candidate=remaining[0], confidence=0.35,
                        reasons=["non-strict fallback"], kind="tv",
                    ))
                    used_candidates.add(_episode_key(remaining[0]))
                else:
                    out.unmatched.append(mf)
            else:
                out.unmatched.append(mf)

    return out


def _movie_score(parsed: ParsedMedia, movie: MovieRef) -> float:
    sim = max((similarity(parsed.title, n) for n in [movie.name, *movie.aliases] if n), default=0.0)
    if parsed.year and movie.year:
        if parsed.year == movie.year:
            sim += 0.2
        elif abs(parsed.year - movie.year) <= 1:
            sim += 0.05
    return min(1.0, sim)


def match_movies(
    files: list[MediaFile],
    provider: Provider,
    query: str | None = None,
    strict: bool = True,
) -> MatchOutput:
    out = MatchOutput()
    for mf in files:
        parsed = mf.parsed
        if parsed is None or parsed.kind != "movie":
            out.unmatched.append(mf)
            continue
        q = query or parsed.title
        candidates = provider.search_movies(q, year=parsed.year)
        if not candidates:
            out.unmatched.append(mf)
            continue
        ranked = sorted(
            ((_movie_score(parsed, m), m) for m in candidates),
            key=lambda x: (x[0], x[1].popularity, x[1].year or 0),
            reverse=True,
        )
        top_score, top = ranked[0]
        if strict:
            year_ok = (not parsed.year) or (top.year == parsed.year)
            if top_score < 0.6 or not year_ok:
                out.unmatched.append(mf)
                continue
            if len(ranked) > 1 and abs(top_score - ranked[1][0]) < 0.04:
                out.unmatched.append(mf)
                continue
        if top_score < 0.35:
            out.unmatched.append(mf)
            continue
        confidence = min(0.99, 0.5 + 0.3 * top_score + (0.1 if parsed.year and top.year == parsed.year else 0))
        reasons = [f"name {similarity(parsed.title, top.name):.2f}"]
        if parsed.year and top.year == parsed.year:
            reasons.append("year exact")
        out.matches.append(MatchResult(file=mf, candidate=top, confidence=confidence, reasons=reasons, kind="movie"))
    return out


def match_music(files: list[MediaFile], state=None) -> MatchOutput:
    from .acoustid import enrich_tags
    from .music import read_tags

    out = MatchOutput()
    for mf in files:
        tags = read_tags(mf.path)
        if state is not None:
            try:
                tags = enrich_tags(tags, mf.path, state)
            except Exception:
                pass
        if not tags:
            out.unmatched.append(mf)
            continue
        track_raw = str(tags.get("track", "")).split("/")[0].strip()
        year_raw = str(tags.get("year", "")).strip()[:4]
        ref = MusicRef(
            id=f"local:{normalize_name(tags.get('artist', ''))}:{normalize_name(tags.get('album', ''))}:{tags.get('track', '')}",
            artist=tags.get("artist", ""), album_artist=tags.get("album_artist", ""),
            album=tags.get("album", ""), title=tags.get("title", ""),
            track=int(track_raw) if track_raw.isdigit() else None,
            year=int(year_raw) if year_raw.isdigit() else None,
            source="tags",
        )
        out.matches.append(MatchResult(file=mf, candidate=ref, confidence=0.8, reasons=["id3 tags"], kind="music"))
    return out


def match_files(
    files: list[MediaFile],
    provider: Provider,
    kind: str,
    query: str | None = None,
    strict: bool = True,
) -> MatchOutput:
    if kind in {"tv", "anime"}:
        return match_tv(files, provider, query=query, strict=strict)
    if kind == "movie":
        return match_movies(files, provider, query=query, strict=strict)
    if kind == "music":
        return match_music(files)
    raise ProviderError(f"unsupported match kind: {kind}")
