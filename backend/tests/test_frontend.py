"""The page must stay consistent with the API it calls and the HTML it fills in."""
import re
import unittest
from pathlib import Path

from tests._server_fixture import require_extras

require_extras()

from server.app import create_app  # noqa: E402
from server.service import StreamService  # noqa: E402

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
JS = (FRONTEND / "app.js").read_text(encoding="utf-8")
HTML = (FRONTEND / "index.html").read_text(encoding="utf-8")
CSS = (FRONTEND / "style.css").read_text(encoding="utf-8")


class PageConsistencyTest(unittest.TestCase):
    def test_every_element_the_script_looks_up_exists_in_the_page(self):
        ids = set(re.findall(r'id="([\w-]+)"', HTML))
        used = set(re.findall(r'\$\("([\w-]+)"\)', JS))
        self.assertEqual({u for u in used if u not in ids}, set())

    def test_every_api_path_the_script_calls_exists(self):
        paths = set(create_app(StreamService()).openapi()["paths"])
        called = set(re.findall(r'"(/api/[\w/]+)"', JS))
        self.assertIn("/api/ws", called)
        missing = {p for p in called if p != "/api/ws"
                   and not any(q == p or q.startswith(p.rstrip("/") + "/") for q in paths)}
        self.assertEqual(missing, set())

    def test_it_is_self_contained_and_dash_free(self):
        for name, text in (("index.html", HTML), ("app.js", JS), ("style.css", CSS)):
            external = [u for u in re.findall(r"https?://[^\s\"')]+", text) if "127.0.0.1" not in u]
            self.assertEqual(external, [], name)
            self.assertNotRegex(text, "[" + chr(0x2013) + chr(0x2014) + "]")


if __name__ == "__main__":
    unittest.main()
