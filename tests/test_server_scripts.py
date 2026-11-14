"""部署脚本的结构性约束：PowerShell 必须带 BOM，否则 5.1 按 GBK 解码会解析失败。"""
import unittest
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1] / "scripts" / "p3" / "server"


class PowerShellEncodingTests(unittest.TestCase):
    def test_every_script_starts_with_utf8_bom(self):
        scripts = sorted(SERVER_DIR.glob("*.ps1"))
        self.assertTrue(scripts, "没有找到任何 .ps1")
        for path in scripts:
            with self.subTest(script=path.name):
                self.assertEqual(
                    path.read_bytes()[:3],
                    b"\xef\xbb\xbf",
                    f"{path.name} 缺少 UTF-8 BOM；用记事本另存为「UTF-8 带 BOM」",
                )

    def test_scripts_are_not_empty(self):
        for path in sorted(SERVER_DIR.glob("*.ps1")):
            with self.subTest(script=path.name):
                self.assertGreater(len(path.read_text(encoding="utf-8-sig")), 200)


if __name__ == "__main__":
    unittest.main()
