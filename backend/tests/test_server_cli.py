import json
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


class ServerProcessTest(unittest.TestCase):
    """`python -m server` as a person would run it."""

    def start(self, *args):
        process = subprocess.Popen([sys.executable, "-m", "server", "--port", "0", *args],
                                   cwd=BACKEND, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True)
        line = process.stdout.readline()
        self.assertIn("stream server on http://127.0.0.1:", line, process.stderr.read() if process.poll() else "")
        return process, line.split("http://")[1].split()[0]

    def stop(self, process):
        process.terminate()
        process.wait(timeout=10)
        process.stdout.close()
        process.stderr.close()

    def test_it_starts_serves_and_stops(self):
        process, address = self.start()
        try:
            with urllib.request.urlopen(f"http://{address}/api/info") as response:
                self.assertEqual(json.loads(response.read())["products"], 1074)
        finally:
            self.stop(process)

    def test_it_can_serve_a_folder_next_to_the_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "index.html").write_text("<p>ui</p>")
            process, address = self.start("--static", tmp)
            try:
                with urllib.request.urlopen(f"http://{address}/") as response:
                    self.assertEqual(response.read(), b"<p>ui</p>")
                with urllib.request.urlopen(f"http://{address}/api/health") as response:
                    self.assertEqual(response.status, 200)
            finally:
                self.stop(process)

    def test_a_missing_static_folder_is_reported(self):
        result = subprocess.run([sys.executable, "-m", "server", "--static", "/no/such/folder"],
                                cwd=BACKEND, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("is not a folder", result.stderr)

    def test_help(self):
        result = subprocess.run([sys.executable, "-m", "server", "--help"], cwd=BACKEND,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0)
        self.assertIn("--port", result.stdout)


if __name__ == "__main__":
    unittest.main()
