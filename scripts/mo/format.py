from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from .models import EpisodeRef, MovieRef, MusicRef
from .parse import ParsedMedia
from .util.text import extract_year


class FormatError(ValueError):
    pass


# ---------------------------------------------------------------------------
# tokenizer / parser for the safe expression subset
# ---------------------------------------------------------------------------

@dataclass
class Token:
    kind: str
    value: str
    pos: int


_OPS = [
    "==", "!=", "<=", ">=", "&&", "||",
    "+", "-", "*", "/", "%", "!", "<", ">", "?", ":", ".", ",", "(", ")", "[", "]",
]
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _tokenize(src: str) -> list[Token]:
    out: list[Token] = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
            continue
        if c in "'\"":
            quote = c
            j = i + 1
            buf = []
            while j < n:
                if src[j] == "\\" and j + 1 < n:
                    esc = src[j + 1]
                    buf.append({"n": "\n", "t": "\t", "r": "\r"}.get(esc, esc))
                    j += 2
                    continue
                if src[j] == quote:
                    break
                buf.append(src[j])
                j += 1
            if j >= n:
                raise FormatError("unterminated string")
            out.append(Token("STRING", "".join(buf), i))
            i = j + 1
            continue
        m = _NUMBER.match(src, i)
        if m:
            out.append(Token("NUMBER", m.group(0), i))
            i = m.end()
            continue
        m = _IDENT.match(src, i)
        if m:
            out.append(Token("IDENT", m.group(0), i))
            i = m.end()
            continue
        for op in _OPS:
            if src.startswith(op, i):
                out.append(Token("OP", op, i))
                i += len(op)
                break
        else:
            raise FormatError(f"unexpected character {c!r} at {i}")
    out.append(Token("EOF", "", n))
    return out


class _Parser:
    def __init__(self, src: str):
        self.src = src
        self.toks = _tokenize(src)
        self.i = 0

    def peek(self, value: str | None = None) -> Token:
        t = self.toks[self.i]
        if value is None or t.value == value:
            return t
        return Token("", "", -1)

    def take(self, value: str | None = None) -> Token:
        t = self.toks[self.i]
        if value is not None and t.value != value:
            raise FormatError(f"expected {value!r} at {t.pos}, got {t.value!r}")
        self.i += 1
        return t

    def parse(self):
        node = self.ternary()
        if self.peek().kind != "EOF":
            raise FormatError(f"unexpected token {self.peek().value!r}")
        return node

    def ternary(self):
        cond = self.or_expr()
        if self.peek("?").value == "?":
            self.take("?")
            a = self.ternary()
            self.take(":")
            b = self.ternary()
            return ("ternary", cond, a, b)
        return cond

    def or_expr(self):
        node = self.and_expr()
        while self.peek("||").value == "||":
            self.take("||")
            node = ("or", node, self.and_expr())
        return node

    def and_expr(self):
        node = self.eq_expr()
        while self.peek("&&").value == "&&":
            self.take("&&")
            node = ("and", node, self.eq_expr())
        return node

    def eq_expr(self):
        node = self.rel_expr()
        while self.peek().value in {"==", "!="}:
            op = self.take().value
            node = ("bin", op, node, self.rel_expr())
        return node

    def rel_expr(self):
        node = self.add_expr()
        while self.peek().value in {"<", ">", "<=", ">="}:
            op = self.take().value
            node = ("bin", op, node, self.add_expr())
        return node

    def add_expr(self):
        node = self.mul_expr()
        while self.peek().value in {"+", "-"}:
            op = self.take().value
            node = ("bin", op, node, self.mul_expr())
        return node

    def mul_expr(self):
        node = self.unary()
        while self.peek().value in {"*", "/", "%"}:
            op = self.take().value
            node = ("bin", op, node, self.unary())
        return node

    def unary(self):
        if self.peek().value in {"!", "-"}:
            op = self.take().value
            return ("unary", op, self.unary())
        return self.postfix()

    def postfix(self):
        node = self.primary()
        while True:
            if self.peek(".").value == ".":
                self.take(".")
                name = self.take()
                if name.kind != "IDENT":
                    raise FormatError("expected attribute name")
                if self.peek("(").value == "(":
                    args = self.args()
                    node = ("method", node, name.value, args)
                else:
                    node = ("attr", node, name.value)
            elif self.peek("(").value == "(":
                args = self.args()
                node = ("call", node, args)
            else:
                break
        return node

    def args(self) -> list:
        self.take("(")
        out = []
        if self.peek(")").value != ")":
            out.append(self.ternary())
            while self.peek(",").value == ",":
                self.take(",")
                out.append(self.ternary())
        self.take(")")
        return out

    def primary(self):
        t = self.peek()
        if t.kind == "NUMBER":
            self.take()
            return ("num", float(t.value) if "." in t.value else int(t.value))
        if t.kind == "STRING":
            self.take()
            return ("str", t.value)
        if t.kind == "IDENT":
            self.take()
            return ("var", t.value)
        if t.value == "(":
            self.take("(")
            node = self.ternary()
            self.take(")")
            return node
        if t.value == "[":
            self.take("[")
            items = []
            if self.peek("]").value != "]":
                items.append(self.ternary())
                while self.peek(",").value == ",":
                    self.take(",")
                    items.append(self.ternary())
            self.take("]")
            return ("list", items)
        raise FormatError(f"unexpected token {t.value!r} at {t.pos}")


@lru_cache(maxsize=512)
def parse_expression(src: str):
    return _Parser(src).parse()


class _Undefined:
    def __repr__(self):
        return "<undefined>"


UNDEFINED = _Undefined()


def _truthy(v: Any) -> bool:
    if v is None or v is UNDEFINED:
        return False
    if isinstance(v, (str, list, tuple, dict)):
        return len(v) > 0
    return bool(v)


def _attr(obj: Any, name: str) -> Any:
    if obj is None or obj is UNDEFINED:
        return UNDEFINED
    if isinstance(obj, dict):
        return obj.get(name, UNDEFINED)
    if hasattr(obj, name):
        return getattr(obj, name)
    return UNDEFINED


def _call_method(obj: Any, name: str, args: list) -> Any:
    lname = name.lower()
    if lname in {"upper", "lower", "title", "strip", "trim"}:
        return _fn("strip" if lname == "trim" else lname, [obj, *args])
    if lname in {"replace", "replaceall", "match", "contains", "startswith", "endswith", "split"}:
        return _fn(lname, [obj, *args])
    if lname == "join" and isinstance(obj, (list, tuple)):
        return str(args[0] if args else "").join(str(x) for x in obj)
    if lname == "format":
        return _fn("date", [obj, *args])
    v = _attr(obj, name)
    if callable(v):
        return v(*args)
    return v


def _fn(name: str, args: list) -> Any:
    name = name.lower()
    a = args
    if name == "upper":
        return str(a[0]).upper() if a else ""
    if name == "lower":
        return str(a[0]).lower() if a else ""
    if name == "title":
        return str(a[0]).title() if a else ""
    if name in {"strip", "trim"}:
        return str(a[0]).strip() if a else ""
    if name == "replace":
        return str(a[0]).replace(str(a[1]), str(a[2])) if len(a) >= 3 else (str(a[0]) if a else "")
    if name == "replaceall":
        if len(a) < 3:
            return str(a[0]) if a else ""
        try:
            return re.sub(str(a[1]), str(a[2]), str(a[0]))
        except re.error as e:
            raise FormatError(f"invalid regex: {e}") from e
    if name in {"match", "matches"}:
        try:
            return bool(re.search(str(a[1]), str(a[0]))) if len(a) >= 2 else False
        except re.error as e:
            raise FormatError(f"invalid regex: {e}") from e
    if name == "contains":
        return str(a[1]) in str(a[0]) if len(a) >= 2 else False
    if name == "startswith":
        return str(a[0]).startswith(str(a[1])) if len(a) >= 2 else False
    if name == "endswith":
        return str(a[0]).endswith(str(a[1])) if len(a) >= 2 else False
    if name == "split":
        return str(a[0]).split(str(a[1])) if len(a) >= 2 else [str(a[0])]
    if name == "join":
        seq, sep = (a[0], a[1]) if len(a) >= 2 else (a[0] if a else [], "")
        return str(sep).join(str(x) for x in seq)
    if name == "pad":
        v = a[0] if a else ""
        width = int(a[1]) if len(a) > 1 else 2
        ch = str(a[2]) if len(a) > 2 else "0"
        s = str(v)
        return s.rjust(width, ch)
    if name == "default":
        v = a[0] if a else UNDEFINED
        return a[1] if (v is UNDEFINED or v is None or v == "") and len(a) > 1 else v
    if name == "coalesce":
        for v in a:
            if v is not UNDEFINED and v is not None and v != "":
                return v
        return UNDEFINED
    if name == "len":
        return len(a[0]) if a else 0
    if name == "int":
        try:
            return int(float(a[0])) if a else 0
        except (TypeError, ValueError):
            return 0
    if name == "str":
        return "" if not a or a[0] is UNDEFINED else str(a[0])
    if name == "abs":
        return abs(float(a[0])) if a else 0
    if name == "round":
        return round(float(a[0])) if a else 0
    if name == "exists":
        return a and a[0] is not UNDEFINED and a[0] is not None and a[0] != ""
    if name == "basename":
        return Path(str(a[0])).name if a else ""
    if name == "dirname":
        return str(Path(str(a[0])).parent) if a else ""
    if name == "ext":
        return Path(str(a[0])).suffix.lstrip(".") if a else ""
    if name in {"date", "datetime"}:
        if not a:
            return ""
        val, fmt = a[0], str(a[1]) if len(a) > 1 else "%Y-%m-%d"
        if isinstance(val, (date, datetime)):
            return val.strftime(fmt)
        s = str(val)
        for f in ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d"):
            try:
                return datetime.strptime(s[:10], f).strftime(fmt)
            except ValueError:
                pass
        return s
    if name == "now":
        fmt = str(a[0]) if a else "%Y-%m-%d"
        return datetime.now(timezone.utc).strftime(fmt)
    if name == "lowercase":
        return str(a[0]).lower() if a else ""
    if name == "list":
        return list(a)
    raise FormatError(f"unknown function {name!r}")


def _eval(node, env: dict[str, Any]) -> Any:
    kind = node[0]
    if kind == "num" or kind == "str":
        return node[1]
    if kind == "list":
        return [_eval(x, env) for x in node[1]]
    if kind == "var":
        name = node[1]
        if name in env:
            return env[name]
        if name in {"true", "True"}:
            return True
        if name in {"false", "False"}:
            return False
        if name in {"null", "none", "None"}:
            return None
        return UNDEFINED
    if kind == "attr":
        return _attr(_eval(node[1], env), node[2])
    if kind == "call":
        args = [_eval(x, env) for x in node[2]]
        if node[1][0] == "var":
            return _fn(node[1][1], args)
        target = _eval(node[1], env)
        if callable(target):
            return target(*args)
        return UNDEFINED
    if kind == "method":
        obj = _eval(node[1], env)
        args = [_eval(x, env) for x in node[3]]
        return _call_method(obj, node[2], args)
    if kind == "unary":
        v = _eval(node[2], env)
        if node[1] == "!":
            return not _truthy(v)
        try:
            return -float(v)
        except (TypeError, ValueError):
            return 0
    if kind == "bin":
        op = node[1]
        a = _eval(node[2], env)
        b = _eval(node[3], env)
        if op == "+":
            if isinstance(a, str) or isinstance(b, str):
                return _str(a) + _str(b)
            try:
                return a + b
            except TypeError:
                return _str(a) + _str(b)
        if op == "-":
            return _num(a) - _num(b)
        if op == "*":
            return _num(a) * _num(b)
        if op == "/":
            return _num(a) / _num(b) if _num(b) else 0
        if op == "%":
            return _num(a) % _num(b) if _num(b) else 0
        if op in {"==", "!="}:
            eq = _norm_cmp(a) == _norm_cmp(b)
            return eq if op == "==" else not eq
        if op in {"<", ">", "<=", ">="}:
            try:
                if op == "<":
                    return a < b
                if op == ">":
                    return a > b
                if op == "<=":
                    return a <= b
                return a >= b
            except TypeError:
                sa, sb = _str(a), _str(b)
                return {"<": sa < sb, ">": sa > sb, "<=": sa <= sb, ">=": sa >= sb}[op]
    if kind == "and":
        return _eval(node[1], env) if not _truthy(_eval(node[1], env)) else _eval(node[2], env)
    if kind == "or":
        v = _eval(node[1], env)
        return v if _truthy(v) else _eval(node[2], env)
    if kind == "ternary":
        return _eval(node[2], env) if _truthy(_eval(node[1], env)) else _eval(node[3], env)
    raise FormatError(f"bad AST node {kind}")


def _num(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _str(v: Any) -> str:
    if v is None or v is UNDEFINED:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _norm_cmp(v: Any) -> Any:
    if isinstance(v, str):
        return v.casefold().strip()
    return v


# ---------------------------------------------------------------------------
# template rendering
# ---------------------------------------------------------------------------

def split_template(template: str) -> list[tuple[str, str]]:
    """Return [('literal', text) | ('expr', source)]."""
    out: list[tuple[str, str]] = []
    buf: list[str] = []
    depth = 0
    for c in template:
        if c == "{":
            if depth == 0:
                if buf:
                    out.append(("literal", "".join(buf)))
                    buf = []
            else:
                buf.append(c)
            depth += 1
        elif c == "}":
            if depth == 1:
                out.append(("expr", "".join(buf)))
                buf = []
            elif depth > 1:
                buf.append(c)
            else:
                raise FormatError("unexpected '}'")
            depth -= 1
        else:
            buf.append(c)
    if depth != 0:
        raise FormatError("missing '}'")
    if buf:
        out.append(("literal", "".join(buf)))
    return out


def render(template: str, bindings: dict[str, Any]) -> str:
    parts = split_template(template)
    if not any(k == "expr" for k, _ in parts):
        raise FormatError("format has no expression; wrap fields in { ... }")
    out: list[str] = []
    for kind, text in parts:
        if kind == "literal":
            out.append(text)
            continue
        src = text.strip()
        if not src:
            raise FormatError("empty expression")
        try:
            node = parse_expression(src)
            val = _eval(node, bindings)
        except FormatError:
            raise
        except Exception as e:
            raise FormatError(f"expression failed: {src!r}: {e}") from e
        if val is UNDEFINED:
            raise FormatError(f"undefined binding in expression: {src!r}")
        out.append(_str(val))
    return "".join(out)


# ---------------------------------------------------------------------------
# bindings
# ---------------------------------------------------------------------------

def _pad2(v: int | None) -> str:
    return f"{v:02d}" if v is not None else ""


def _multi_sxe(season: int | None, episodes: list[int]) -> str:
    if not episodes:
        return ""
    if len(episodes) == 1:
        return f"S{_pad2(season)}E{_pad2(episodes[0])}"
    return f"S{_pad2(season)}E{_pad2(episodes[0])}-E{_pad2(episodes[-1])}"


def build_bindings(
    candidate: Any,
    file_path: str | Path,
    parsed: ParsedMedia | None = None,
    output: str | Path | None = None,
    kind: str = "tv",
    is_anime: bool = False,
) -> dict[str, Any]:
    p = Path(file_path)
    tags = parsed.tags if parsed else {}
    ep: EpisodeRef | None = candidate if isinstance(candidate, EpisodeRef) else None
    mv: MovieRef | None = candidate if isinstance(candidate, MovieRef) else None
    mu: MusicRef | None = candidate if isinstance(candidate, MusicRef) else None

    if ep is not None:
        series_name = ep.series_name
        season, episode, title = ep.season, ep.episode, ep.title
        year = ep.series_year or (extract_year(ep.airdate.isoformat()) if ep.airdate else None)
        raw_eps = ep.raw.get("episodes") if isinstance(ep.raw, dict) else None
        episodes = [int(x) for x in raw_eps] if raw_eps else ([episode] if episode is not None else [])
        absolute = ep.absolute
        airdate = ep.airdate.isoformat() if ep.airdate else ""
        db_id = ep.series_id
        tmdb_id = tvdb_id = imdb_id = ""
    elif mu is not None:
        series_name = mu.album_artist or mu.artist
        season = episode = None
        title = mu.title
        year = mu.year
        episodes = []
        absolute = None
        airdate = ""
        db_id = mu.id
        tmdb_id = tvdb_id = imdb_id = ""
    elif mv is not None:
        series_name = mv.name
        season = episode = None
        title = mv.name
        year = mv.year
        episodes = []
        absolute = None
        airdate = ""
        db_id = mv.id
        tmdb_id = mv.tmdb_id or ""
        tvdb_id = imdb_id = ""
        imdb_id = mv.imdb_id or ""
    else:
        series_name = getattr(candidate, "name", "") if candidate is not None else ""
        season = episode = None
        title = series_name
        year = getattr(candidate, "year", None) if candidate is not None else None
        episodes = []
        absolute = None
        airdate = ""
        db_id = getattr(candidate, "id", "") if candidate is not None else ""
        tmdb_id = getattr(candidate, "tmdb_id", "") if candidate is not None else ""
        tvdb_id = getattr(candidate, "tvdb_id", "") if candidate is not None else ""
        imdb_id = getattr(candidate, "imdb_id", "") if candidate is not None else ""

    ext = p.suffix.lstrip(".")
    name_year = f"{series_name} ({year})" if year else series_name
    sxe = _multi_sxe(season, episodes)
    s00 = _pad2(season)
    e00 = "-".join(_pad2(x) for x in episodes) if episodes else ""
    season_name = f"Season {_pad2(season)}" if season is not None else ""

    b: dict[str, Any] = {
        "n": series_name,
        "y": year or "",
        "ny": name_year,
        "s": season if season is not None else "",
        "sn": season_name,
        "e": episode if episode is not None else "",
        "es": episodes,
        "s00": s00,
        "e00": e00,
        "sxe": sxe,
        "s00e00": sxe,
        "t": title,
        "d": airdate,
        "airdate": airdate,
        "absolute": absolute or "",
        "special": ep.special if ep and ep.special is not None else "",
        "series": series_name,
        "id": db_id,
        "tmdbid": tmdb_id,
        "tvdbid": tvdb_id,
        "imdbid": imdb_id,
        "db": "tmdb" if tmdb_id else ("tvdb" if tvdb_id else ""),
        "type": kind,
        "anime": is_anime,
        "regular": not is_anime,
        "ext": ext,
        "fn": p.name,
        "f": str(p),
        "mediaFile": str(p),
        "mediaFileName": p.name,
        "folder": str(p.parent),
        "root": str(p.anchor or p.parent),
        "drive": str(p.drive or ""),
        "home": str(Path.home()),
        "output": str(output or ""),
        "bytes": p.stat().st_size if p.exists() else 0,
        "megabytes": round((p.stat().st_size / 1_000_000), 1) if p.exists() else 0,
        "gigabytes": round((p.stat().st_size / 1_000_000_000), 2) if p.exists() else 0,
        "today": date.today().isoformat(),
        "vf": tags.get("resolution", ""),
        "resolution": tags.get("resolution", ""),
        "vc": tags.get("codec", ""),
        "ac": tags.get("audio", ""),
        "hdr": tags.get("hdr", ""),
        "bitdepth": tags.get("bit_depth", ""),
        "group": (parsed.group if parsed and parsed.group else tags.get("group", "")),
        "source": tags.get("source", ""),
        "vs": tags.get("source", ""),
        "edition": tags.get("edition", ""),
        "lang": "",
        "languages": [],
        "az": (series_name[:1].upper() if series_name else ""),
        "decade": (int(year) // 10 * 10 if year else ""),
        "artist": mu.artist if mu else "",
        "albumArtist": (mu.album_artist or mu.artist) if mu else "",
        "album": mu.album if mu else "",
        "track": (f"{mu.track:02d}" if mu and mu.track is not None else ""),
    }
    b["plex"] = preset_path("plex", kind, b, is_anime)
    b["kodi"] = preset_path("kodi", kind, b, is_anime)
    b["emby"] = preset_path("emby", kind, b, is_anime)
    b["jellyfin"] = preset_path("jellyfin", kind, b, is_anime)
    return b


def preset_path(style: str, kind: str, b: dict[str, Any], is_anime: bool = False) -> str:
    name = str(b.get("n") or "")
    year = b.get("y")
    name_year = f"{name} ({year})" if year else name
    if kind in {"tv", "anime"}:
        series = name
        season = b.get("s")
        if season == "" or season is None:
            season_dir = "Specials" if b.get("special") not in {"", None} else ""
        else:
            pad = f"{int(season):02d}" if style in {"plex", "emby", "jellyfin"} else str(int(season))
            season_dir = f"Season {pad}"
        ep = str(b.get("s00e00") or "")
        title = str(b.get("t") or "")
        file_name = f"{series} - {ep}" + (f" - {title}" if title else "")
        category = "Anime" if is_anime else "TV Shows"
        parts = [category, series, season_dir, file_name]
        if style in {"kodi", "emby", "jellyfin"} and b.get("tmdbid"):
            tag = {"kodi": f" {{tmdb-{b['tmdbid']}}}", "emby": f" [tmdbid={b['tmdbid']}]", "jellyfin": f" [tmdbid-{b['tmdbid']}]"}[style]
            parts[-1] += tag
        return "/".join(x for x in parts if x)
    if kind == "music":
        artist = str(b.get("albumArtist") or b.get("artist") or "")
        album = str(b.get("album") or "")
        track = str(b.get("track") or "")
        title = str(b.get("t") or "")
        file_name = f"{track} - {title}" if track else title
        return "/".join(x for x in ["Music", artist, album, file_name] if x)
    # movie
    parts = ["Movies", name_year, name_year]
    if style in {"kodi", "emby", "jellyfin"} and b.get("tmdbid"):
        tag = {"kodi": f" {{tmdb-{b['tmdbid']}}}", "emby": f" [tmdbid={b['tmdbid']}]", "jellyfin": f" [tmdbid-{b['tmdbid']}]"}[style]
        parts[-1] += tag
    return "/".join(parts)
