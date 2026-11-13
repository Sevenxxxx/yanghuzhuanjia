"""road.py 的配置优先级：--config > ROAD_EXPERT_CONFIG > 仓库示例文件。"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import road  # noqa: E402


class ResolveConfigTests(unittest.TestCase):
    def test_explicit_flag_wins(self):
        with patch.dict(os.environ, {"ROAD_EXPERT_CONFIG": "/etc/road-chat/config.json"}):
            self.assertEqual(road.resolve_config("/tmp/mine.json"), "/tmp/mine.json")

    def test_environment_when_no_flag(self):
        with patch.dict(os.environ, {"ROAD_EXPERT_CONFIG": "/etc/road-chat/config.json"}):
            self.assertEqual(road.resolve_config(None), "/etc/road-chat/config.json")

    def test_none_falls_back_to_repository_example(self):
        env = {key: value for key, value in os.environ.items() if key != "ROAD_EXPERT_CONFIG"}
        with patch.dict(os.environ, env, clear=True):
            self.assertIsNone(road.resolve_config(None))


if __name__ == "__main__":
    unittest.main()
