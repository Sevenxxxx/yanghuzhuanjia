"""P3 模型代理的本地行为：/models 本地应答、未允许路径 404（不连上游）。"""
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "p3" / "proxy"))

import model_proxy  # noqa: E402


class LocalModelListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), model_proxy.Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def test_models_answers_locally(self):
        with urllib.request.urlopen(self.url("/models"), timeout=5) as response:
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["object"], "list")
        self.assertEqual([item["id"] for item in payload["data"]], ["deepseek-chat"])

    def test_models_with_query_string_still_answers_locally(self):
        with urllib.request.urlopen(self.url("/models?v=1"), timeout=5) as response:
            self.assertEqual(response.status, 200)

    def test_unknown_path_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.url("/not-allowed"), timeout=5)
        self.assertEqual(caught.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
