import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from mo.providers.opensubtitles import movie_hash  # noqa: E402
from mo.subs import ass_to_srt, ensure_srt  # noqa: E402

ASS = """[Script Info]
Title: test

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.50,Default,,0,0,0,,Hello {\\b1}world{\\b0}\\NSecond line
Dialogue: 0,0:00:04.00,0:00:06.00,Default,,0,0,0,,Next
"""


class SubtitleTests(unittest.TestCase):
    def test_ass_to_srt(self):
        srt = ass_to_srt(ASS)
        self.assertIn("00:00:01,000 --> 00:00:03,500", srt)
        self.assertIn("Hello world\nSecond line", srt)
        self.assertIn("00:00:04,000 --> 00:00:06,000", srt)

    def test_ensure_srt(self):
        out = ensure_srt(ASS.encode("utf-8"))
        self.assertIn(b"00:00:01,000 --> 00:00:03,500", out)
        self.assertNotIn(b"[Script Info]", out)

    def test_movie_hash(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "f.bin"
            data = bytes(range(100))
            p.write_bytes(data)
            h = movie_hash(p)
            self.assertEqual(len(h), 16)
            import struct
            words = [int.from_bytes(data[i:i + 8], "little") for i in range(0, 96, 8)]
            expected = (100 + sum(words) + sum(words)) & 0xFFFFFFFFFFFFFFFF
            self.assertEqual(h, f"{expected:016x}")


if __name__ == "__main__":
    unittest.main()
