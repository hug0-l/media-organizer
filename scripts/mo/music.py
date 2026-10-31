from __future__ import annotations

import os
import struct
from pathlib import Path

_FRAME_MAP = {
    "TIT2": "title", "TT2": "title",
    "TPE1": "artist", "TP1": "artist",
    "TPE2": "album_artist", "TP2": "album_artist",
    "TALB": "album", "TAL": "album",
    "TRCK": "track", "TRK": "track",
    "TDRC": "year", "TYER": "year", "TYE": "year",
    "TCON": "genre", "TCO": "genre",
    "TCOM": "composer",
    "TPOS": "disc", "TPA": "disc",
    "TSSE": "encoder",
}


def _syncsafe(b: bytes) -> int:
    return (b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]


def _decode_text(data: bytes) -> str:
    if not data:
        return ""
    enc = data[0]
    payload = data[1:]
    try:
        if enc == 0:
            return payload.split(b"\x00", 1)[0].decode("latin-1", "replace")
        if enc == 1:
            return payload.split(b"\x00\x00", 1)[0].decode("utf-16", "replace").strip("\x00")
        if enc == 2:
            return payload.split(b"\x00\x00", 1)[0].decode("utf-16-be", "replace").strip("\x00")
        if enc == 3:
            return payload.split(b"\x00", 1)[0].decode("utf-8", "replace")
    except Exception:
        return ""
    return ""


def _read_id3v2(path: Path) -> dict[str, str]:
    with path.open("rb") as f:
        header = f.read(10)
        if len(header) < 10 or header[:3] != b"ID3":
            return {}
        ver = header[3]
        size = _syncsafe(header[6:10])
        body = f.read(size)
    tags: dict[str, str] = {}
    pos = 0
    frame_header = 6 if ver >= 3 else 6
    while pos + frame_header <= len(body):
        fid = body[pos:pos + (4 if ver >= 3 else 3)].decode("latin-1", "replace")
        if not fid.strip("\x00") or fid.startswith("\x00"):
            break
        if ver >= 3:
            if pos + 10 > len(body):
                break
            raw_size = body[pos + 4:pos + 8]
            fsize = _syncsafe(raw_size) if ver >= 4 else struct.unpack(">I", raw_size)[0]
            pos += 10
        else:
            fsize = int.from_bytes(body[pos + 3:pos + 6], "big")
            pos += 6
        if fsize <= 0 or pos + fsize > len(body):
            break
        data = body[pos:pos + fsize]
        pos += fsize
        key = _FRAME_MAP.get(fid)
        if key and key not in tags:
            val = _decode_text(data)
            if val:
                tags[key] = val
    return tags


def _read_id3v1(path: Path) -> dict[str, str]:
    try:
        with path.open("rb") as f:
            f.seek(-128, os.SEEK_END)
            tag = f.read(128)
    except OSError:
        return {}
    if len(tag) < 128 or tag[:3] != b"TAG":
        return {}
    def s(a, b):
        return tag[a:b].split(b"\x00", 1)[0].decode("latin-1", "replace").strip()
    out = {"title": s(3, 33), "artist": s(33, 63), "album": s(63, 93)}
    year = s(93, 97)
    if year.isdigit():
        out["year"] = year
    return {k: v for k, v in out.items() if v}


def read_tags(path: str | Path) -> dict[str, str]:
    p = Path(path)
    try:
        tags = _read_id3v2(p)
    except Exception:
        tags = {}
    if not tags:
        tags = _read_id3v1(p)
    return tags
