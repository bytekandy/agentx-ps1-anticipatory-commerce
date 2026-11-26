import contextlib
import io
import sys
import unittest
from pathlib import Path

from tests._server_fixture import LiveServer, require_extras

require_extras()

from server.app import Settings, create_app  # noqa: E402
from server.service import StreamService  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import stream_client  # noqa: E402

SERVICE = StreamService()


class ClientTestCase(unittest.TestCase):
    settings = Settings()

    @classmethod
    def setUpClass(cls):
        cls.live = LiveServer(create_app(SERVICE, cls.settings)).__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.live.__exit__()

    def run_client(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = stream_client.main(["--server", self.live.url, *args])
        return code, out.getvalue()


class ClientTest(ClientTestCase):
    def test_live_mode_sends_words_over_a_websocket(self):
        code, text = self.run_client("--live", "beige Loomsy sneakers size 10 under 3000 please")
        self.assertEqual(code, 0)
        self.assertIn("COMMIT P0081", text)
        self.assertIn("final: P0081", text)
        self.assertEqual(sum(1 for line in text.splitlines() if line[:3].strip().isdigit()), 8)

    def test_rest_mode_is_one_stateless_post_per_word(self):
        code, text = self.run_client("--rest", "beige Loomsy sneakers size 10 under 3000 please")
        self.assertIn("COMMIT P0081", text)
        self.assertIn("final: P0081", text)

    def test_the_two_transports_print_the_same_thing(self):
        live = self.run_client("--live", "navy Urbanyx hoodie size M")[1]
        rest = self.run_client("--rest", "navy Urbanyx hoodie size M")[1]
        self.assertEqual(live.splitlines()[1:], rest.splitlines())      # live also prints the start line

    def test_replay_modes(self):
        _, text = self.run_client("--replay-example", "dev-0004", "--delay", "0")
        self.assertIn("scored: correct=True early_words=2", text)
        _, text = self.run_client("--replay", "navy Nike hoodies size M", "--delay", "0")
        self.assertIn("brand: nike", text)

    def test_errors_are_messages_not_tracebacks(self):
        with self.assertRaises(SystemExit) as ctx:
            self.run_client("--replay-example", "nope", "--delay", "0")
        self.assertIn("unknown_example", str(ctx.exception))
        with self.assertRaises(SystemExit) as ctx:
            self.run_client("--rest", "x" * 101)                 # a word over the 100 character limit
        self.assertIn("bad_word", str(ctx.exception))
        with self.assertRaises(SystemExit) as ctx:
            self.run_client("--replay", "   ", "--delay", "0")
        self.assertIn("bad_request", str(ctx.exception))


class ClientWithKeyTest(ClientTestCase):
    settings = Settings(api_key="k3y")

    def test_a_missing_or_wrong_key_is_reported_for_every_mode(self):
        for mode in (["--rest", "black cap"], ["--live", "black cap"], ["--replay", "black cap", "--delay", "0"]):
            with self.subTest(mode=mode[0]):
                with self.assertRaises(SystemExit) as ctx:
                    self.run_client(*mode)
                self.assertRegex(str(ctx.exception), r"401|403|API key")
                with self.assertRaises(SystemExit):
                    self.run_client(*mode, "--api-key", "wrong")

    def test_the_right_key_works_for_every_mode(self):
        for mode in (["--rest", "black cap"], ["--live", "black cap"], ["--replay", "black cap", "--delay", "0"]):
            with self.subTest(mode=mode[0]):
                code, text = self.run_client(*mode, "--api-key", "k3y")
                self.assertEqual(code, 0)
                self.assertIn("black", text)


if __name__ == "__main__":
    unittest.main()
