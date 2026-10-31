import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from mo.util.paths import (  # noqa: E402
    dangerous_root,
    resolve_destination,
    sanitize_component,
    sanitize_relpath,
    unique_indexed_path,
)


class PathTests(unittest.TestCase):
    def test_invalid_chars(self):
        self.assertEqual(sanitize_component('a:b/c?d*e'), "a - b c d e")

    def test_reserved(self):
        self.assertTrue(sanitize_component("CON").startswith("_"))
        self.assertTrue(sanitize_component("nul.txt").startswith("_"))

    def test_trailing(self):
        self.assertEqual(sanitize_component("name. "), "name")

    def test_traversal(self):
        with self.assertRaises(ValueError):
            sanitize_relpath("a/../../b")

    def test_resolve_inside(self):
        with tempfile.TemporaryDirectory() as d:
            dest = resolve_destination("Show/Season 01/file.mkv", d)
            self.assertTrue(str(dest).startswith(str(Path(d).resolve())))

    def test_absolute_outside_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            outside = str(Path(d).parent / "elsewhere.mkv")
            with self.assertRaises(ValueError):
                resolve_destination(outside, d)

    def test_absolute_inside_allowed(self):
        with tempfile.TemporaryDirectory() as d:
            inside = str(Path(d) / "sub" / "x.mkv")
            self.assertEqual(resolve_destination(inside, d), Path(inside).resolve())

    def test_unique_index(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.mkv"
            p.write_text("x")
            u = unique_indexed_path(p)
            self.assertEqual(u.name, "a.1.mkv")

    def test_dangerous_root(self):
        self.assertTrue(dangerous_root(Path.home()))
        self.assertTrue(dangerous_root(Path("C:/")))


if __name__ == "__main__":
    unittest.main()
