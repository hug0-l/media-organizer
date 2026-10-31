from __future__ import annotations

import io
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path

from ..state import State
from .base import HttpClient, ProviderError, TTL_SEARCH

API = "https://api.opensubtitles.com/api/v1"
HOST = "https://www.opensubtitles.com"
CHUNK = 65536


def movie_hash(path: str | Path) -> str:
    """OpenSubtitles hash: size + 64-bit LE word sums of first/last 64 KiB."""
    p = Path(path)
    size = p.stat().st_size
    n = min(CHUNK, size)
    with p.open("rb") as f:
        head = f.read(n)
        f.seek(max(0, size - CHUNK))
        tail = f.read(n)

    def chunk_sum(data: bytes) -> int:
        data = data[: len(data) - (len(data) % 8)]
        total = 0
        for i in range(0, len(data), 8):
            total += int.from_bytes(data[i:i + 8], "little")
        return total & 0xFFFFFFFFFFFFFFFF

    return f"{(size + chunk_sum(head) + chunk_sum(tail)) & 0xFFFFFFFFFFFFFFFF:016x}"


@dataclass
class SubtitleResult:
    provider: str
    file_id: int
    language: str
    release: str
    title: str
    downloads: int
    rating: float
    file_name: str = ""


class OpenSubtitlesProvider:
    name = "opensubtitles"

    def __init__(self, state: State):
        self.state = state
        self.http = HttpClient(state)
        self.key = os.environ.get("MO_OPENSUBTITLES_KEY") or (state.config.get("keys", {}) or {}).get("opensubtitles")
        self.username = os.environ.get("MO_OPENSUBTITLES_USER") or ""
        self.password = os.environ.get("MO_OPENSUBTITLES_PASS") or ""
        self._token: str | None = None
        self._base = HOST

    def _headers(self) -> dict[str, str]:
        h = {"Api-Key": self.key or "", "Accept": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def login(self) -> None:
        if self._token or not self.key or not self.username:
            return
        data = self.http.post_json(
            f"{HOST}/api/v1/login",
            {"username": self.username, "password": self.password},
            headers={"Api-Key": self.key, "Accept": "application/json"},
        )
        token = (data or {}).get("token")
        if token:
            self._token = token
            self._base = (data or {}).get("base_url") or HOST

    def search(self, query: str = "", moviehash: str = "", languages: str = "en") -> list[SubtitleResult]:
        if not self.key:
            raise ProviderError("OpenSubtitles Api-Key missing; set MO_OPENSUBTITLES_KEY")
        self.login()
        params = {"languages": languages}
        if moviehash:
            params["moviehash"] = moviehash
        elif query:
            params["query"] = query
        else:
            return []
        data = self.http.get_json(
            f"{API}/subtitles", params=params, headers=self._headers(), ttl=TTL_SEARCH
        )
        out = []
        for row in (data or {}).get("data", []) or []:
            attrs = row.get("attributes") or {}
            files = attrs.get("files") or []
            fid = files[0].get("file_id") if files else None
            if not fid:
                continue
            out.append(SubtitleResult(
                provider="opensubtitles", file_id=int(fid),
                language=attrs.get("language") or languages,
                release=attrs.get("release") or "",
                title=attrs.get("feature_details", {}).get("title") or "",
                downloads=int(attrs.get("download_count") or 0),
                rating=float(attrs.get("ratings") or 0),
                file_name=files[0].get("file_name") or "",
            ))
        return out

    def download(self, file_id: int) -> bytes:
        if not self.key:
            raise ProviderError("OpenSubtitles Api-Key missing")
        self.login()
        data = self.http.post_json(
            f"{API}/download", {"file_id": int(file_id)},
            headers=self._headers(), ttl=-1,
        )
        link = (data or {}).get("link")
        if not link:
            raise ProviderError(f"OpenSubtitles download did not return a link: {data}")
        raw = self.http.get_bytes(link)
        return _extract_subtitle(raw, (data or {}).get("file_name") or "")


def _extract_subtitle(raw: bytes, name: str = "") -> bytes:
    # gzip
    if raw[:2] == b"\x1f\x8b":
        import gzip
        raw = gzip.decompress(raw)
    # zip
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith((".srt", ".ass", ".ssa", ".vtt", ".sub"))]
            if not names:
                raise ProviderError("downloaded archive contains no subtitle files")
            return zf.read(names[0])
    return raw
