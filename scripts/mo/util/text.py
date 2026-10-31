from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_WS = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")

RESOLUTION = {
    "2160p", "1080p", "1080i", "720p", "576p", "480p", "4k", "uhd", "8k",
}
SOURCE = {
    "bluray", "blu-ray", "bdrip", "brrip", "bdremux", "remux", "webrip",
    "web-dl", "webdl", "web", "hdtv", "pdtv", "dvdrip", "dvd", "dvdscr",
    "hdcam", "cam", "ts", "tc", "r5", "screener", "scr", "hdrip", "uhdrip",
}
CODEC = {
    "x264", "x265", "h264", "h265", "hevc", "avc", "xvid", "divx", "vp9",
    "av1", "mpeg2", "mpeg4",
}
AUDIO = {
    "aac", "ac3", "eac3", "dts", "dts-hd", "truehd", "atmos", "ddp", "dd",
    "ddp5", "ddp5.1", "dd5.1", "flac", "mp3", "opus", "vorbis", "5.1", "7.1",
     "2.0",
}
MISC = {
    "hdr", "hdr10", "hdr10+", "dv", "dolby", "vision", "10bit", "8bit",
    "proper", "repack", "rerip", "internal", "limited", "extended", "uncut",
    "remastered", "multi", "dual", "subbed", "dubbed", "sub", "subs", "eng",
    "english", "complete", "season", "saison", "staffel", "temporada",
}
RELEASE_WORDS = RESOLUTION | SOURCE | CODEC | AUDIO | MISC

_SUBTITLE_TAGS = re.compile(
    r"(?i)(?:^|[.\-_ ])(?:en|eng|english|zh|chs|cht|chi|chinese|jpn|japanese|"
    r"kor|korean|fre|french|ger|german|spa|spanish|ita|italian|rus|russian|"
    r"por|portuguese|dut|dutch|swe|swedish|nor|norwegian|dan|danish|fin|finnish|"
    r"pol|polish|tur|turkish|ara|arabic|heb|hebrew|hin|hindi|tha|thai|vie|vietnamese)"
    r"(?:[.\-_ ]|$)"
)


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def normalize_name(s: str) -> str:
    """Normalize a title/name for comparison."""
    if not s:
        return ""
    s = strip_accents(s).lower()
    s = s.replace("&", " and ")
    s = re.sub(r"\bthe\b", " the ", s)
    s = _NON_ALNUM.sub(" ", s)
    return _WS.sub(" ", s).strip()


def tokenize(s: str) -> list[str]:
    return [t for t in normalize_name(s).split(" ") if t]


def similarity(a: str, b: str) -> float:
    """0..1 name similarity with token-aware fallback."""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(na.split()), set(nb.split())
    if ta and tb:
        jaccard = len(ta & tb) / len(ta | tb)
        containment = len(ta & tb) / min(len(ta), len(tb))
        ratio = max(ratio, 0.5 * jaccard + 0.5 * containment)
    return max(0.0, min(1.0, ratio))


def title_similarity(file_stem: str, episode_title: str) -> float:
    """Similarity between the residual filename and an episode title."""
    if not episode_title:
        return 0.0
    ft = set(tokenize(file_stem))
    et = set(tokenize(episode_title))
    if not et or not ft:
        return 0.0
    inter = ft & et
    if not inter:
        return 0.0
    # episode titles are short: containment is more informative than jaccard
    return max(
        len(inter) / len(et),
        SequenceMatcher(None, " ".join(sorted(ft)), " ".join(sorted(et))).ratio(),
    )


def extract_year(s: str) -> int | None:
    m = _YEAR.search(s or "")
    if not m:
        return None
    y = int(m.group(1))
    return y if 1888 <= y <= 2100 else None


def find_years(s: str) -> list[int]:
    return [int(m.group(1)) for m in _YEAR.finditer(s or "")]


def clean_release_words(s: str, keep_year: bool = False) -> str:
    """Remove known release/quality words from a candidate title."""
    tokens = re.split(r"[\s._\-\[\]()]+", s)
    out = []
    for tok in tokens:
        low = tok.lower()
        if not low:
            continue
        if low in RELEASE_WORDS:
            continue
        if not keep_year and _YEAR.fullmatch(low):
            continue
        out.append(tok)
    return " ".join(out).strip()


def has_subtitle_tag(s: str) -> bool:
    return bool(_SUBTITLE_TAGS.search(s or ""))


def subtitle_language_tag(s: str) -> str | None:
    m = _SUBTITLE_TAGS.search(s or "")
    if not m:
        return None
    tag = m.group(1).lower()
    mapping = {
        "eng": "en", "english": "en", "en": "en",
        "chs": "zh", "cht": "zh", "chi": "zh", "chinese": "zh", "zh": "zh",
        "jpn": "ja", "japanese": "ja", "ja": "ja",
        "kor": "ko", "korean": "ko", "ko": "ko",
        "fre": "fr", "french": "fr", "fr": "fr",
        "ger": "de", "german": "de", "de": "de",
        "spa": "es", "spanish": "es", "es": "es",
        "ita": "it", "italian": "it", "it": "it",
        "rus": "ru", "russian": "ru", "ru": "ru",
        "por": "pt", "portuguese": "pt", "pt": "pt",
        "dut": "nl", "dutch": "nl", "nl": "nl",
        "swe": "sv", "swedish": "sv", "sv": "sv",
        "nor": "no", "norwegian": "no", "no": "no",
        "dan": "da", "danish": "da", "da": "da",
        "fin": "fi", "finnish": "fi", "fi": "fi",
        "pol": "pl", "polish": "pl", "pl": "pl",
        "tur": "tr", "turkish": "tr", "tr": "tr",
        "ara": "ar", "arabic": "ar", "ar": "ar",
        "heb": "he", "hebrew": "he", "he": "he",
        "hin": "hi", "hindi": "hi", "hi": "hi",
        "tha": "th", "thai": "th", "th": "th",
        "vie": "vi", "vietnamese": "vi", "vi": "vi",
    }
    return mapping.get(tag, tag)


def truncate(s: str, n: int) -> str:
    if s is None:
        return ""
    return s if len(s) <= n else s[: max(0, n - 1)].rstrip() + "…"
