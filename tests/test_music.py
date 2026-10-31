import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from mo.match import match_music  # noqa: E402
from mo.models import MediaFile  # noqa: E402
from mo.parse import parse_media  # noqa: E402
from mo.music import read_tags  # noqa: E402


def _frame(fid: bytes, text: str) -> bytes:
    payload = b"\x03" + text.encode("utf-8")
    return fid + struct.pack(">I", len(payload)) + b"\x00\x00" + payload


def _syncsafe(n: int) -> bytes:
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


class MusicTests(unittest.TestCase):
    def test_id3v23(self):
        frames = (
            _frame(b"TIT2", "Song Title")
            + _frame(b"TPE1", "Artist")
            + _frame(b"TPE2", "Album Artist")
            + _frame(b"TALB", "Album")
            + _frame(b"TRCK", "3/12")
            + _frame(b"TYER", "2020")
        )
        data = b"ID3\x03\x00\x00" + _syncsafe(len(frames)) + frames
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "track.mp3"
            p.write_bytes(data)
            tags = read_tags(p)
        self.assertEqual(tags["title"], "Song Title")
        self.assertEqual(tags["artist"], "Artist")
        self.assertEqual(tags["album_artist"], "Album Artist")
        self.assertEqual(tags["album"], "Album")
        self.assertEqual(tags["track"], "3/12")
        self.assertEqual(tags["year"], "2020")

    def test_id3v1_fallback(self):
        tag = b"TAG" + b"Title".ljust(30, b"\x00") + b"Artist".ljust(30, b"\x00") + b"Album".ljust(30, b"\x00") + b"1999"
        tag = tag.ljust(128, b"\x00")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "track.mp3"
            p.write_bytes(b"\x00" * 10 + tag)
            tags = read_tags(p)
        self.assertEqual(tags["title"], "Title")
        self.assertEqual(tags["year"], "1999")

    def test_match_music(self):
        frames = _frame(b"TIT2", "Song") + _frame(b"TPE1", "Artist") + _frame(b"TRCK", "3/12")
        data = b"ID3\x03\x00\x00" + _syncsafe(len(frames)) + frames
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "track.mp3"
            p.write_bytes(data)
            mf = MediaFile(path=str(p), size=len(data), media_kind="audio")
            mf.parsed = parse_media(p)
            out = match_music([mf])
        self.assertEqual(len(out.matches), 1)
        self.assertEqual(out.matches[0].candidate.title, "Song")
        self.assertEqual(out.matches[0].candidate.track, 3)


if __name__ == "__main__":
    unittest.main()
