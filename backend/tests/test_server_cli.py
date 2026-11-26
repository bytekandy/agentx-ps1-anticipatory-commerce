import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests._server_fixture import require_extras

require_extras()

import httpx  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]


class ServerProcessTest(unittest.TestCase):
    """`python -m server` as a person would run it."""

    def start(self, *args, env=None):
        process = subprocess.Popen([sys.executable, "-W", "ignore", "-m", "server", "--port", "0", *args],
                                   cwd=BACKEND, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, env=dict(os.environ, **(env or {})))
        line = process.stdout.readline()
        self.assertIn("stream server on http://", line, process.stderr.read() if process.poll() else "")
        return process, line.split("http://")[1].split()[0], line

    def stop(self, process):
        process.terminate()
        process.wait(timeout=15)
        process.stdout.close()
        process.stderr.close()

    def test_it_starts_serves_and_stops(self):
        process, address, line = self.start()
        try:
            self.assertIn("no API key, local only", line)
            self.assertEqual(httpx.get(f"http://{address}/api/info").json()["products"], 1074)
            self.assertEqual(httpx.get(f"http://{address}/docs").status_code, 200)
        finally:
            self.stop(process)

    def test_the_real_process_answers_keep_alive_calls_quickly(self):
        """The launcher binds its own socket; without IPPROTO_TCP every call took about 40 ms."""
        import statistics
        import time
        process, address, _ = self.start()
        try:
            with httpx.Client(base_url=f"http://{address}") as client:
                client.get("/api/health")
                timings = []
                for _ in range(30):
                    started = time.perf_counter()
                    client.get("/api/health")
                    timings.append(1000 * (time.perf_counter() - started))
            self.assertLess(statistics.median(timings), 10.0, f"median {statistics.median(timings):.1f} ms")
        finally:
            self.stop(process)

    def test_it_can_serve_a_folder_next_to_the_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "index.html").write_text("<p>ui</p>")
            process, address, _ = self.start("--static", tmp)
            try:
                self.assertEqual(httpx.get(f"http://{address}/").text, "<p>ui</p>")
                self.assertEqual(httpx.get(f"http://{address}/api/health").status_code, 200)
            finally:
                self.stop(process)

    def test_the_key_comes_from_a_flag_or_the_environment(self):
        for args, env in ((("--api-key", "k1"), None), ((), {"STREAM_API_KEY": "k1"})):
            process, address, line = self.start(*args, env=env)
            try:
                self.assertIn("API key required", line)
                self.assertEqual(httpx.get(f"http://{address}/api/info").status_code, 401)
                self.assertEqual(httpx.get(f"http://{address}/api/info", headers={"X-API-Key": "k1"}).status_code, 200)
            finally:
                self.stop(process)

    def run_server(self, *args):
        return subprocess.run([sys.executable, "-W", "ignore", "-m", "server", *args], cwd=BACKEND,
                              capture_output=True, text=True, timeout=30,
                              env={k: v for k, v in os.environ.items() if k != "STREAM_API_KEY"})

    def test_it_refuses_to_listen_beyond_this_machine_without_a_key(self):
        for host in ("0.0.0.0", "::", "192.168.1.5"):
            result = self.run_server("--host", host, "--port", "0")
            self.assertNotEqual(result.returncode, 0, host)
            self.assertIn("without an API key", result.stderr)

    def test_with_a_key_it_may_listen_on_all_addresses(self):
        process, address, line = self.start("--host", "0.0.0.0", "--api-key", "k")
        try:
            port = address.rsplit(":", 1)[1]
            self.assertEqual(httpx.get(f"http://127.0.0.1:{port}/api/info", headers={"X-API-Key": "k"}).status_code, 200)
        finally:
            self.stop(process)

    def test_a_missing_static_folder_is_reported(self):
        result = self.run_server("--static", "/no/such/folder")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is not a folder", result.stderr)

    def test_help(self):
        result = self.run_server("--help")
        self.assertEqual(result.returncode, 0)
        for flag in ("--port", "--api-key", "--cors-origin", "--static"):
            self.assertIn(flag, result.stdout)


if __name__ == "__main__":
    unittest.main()
