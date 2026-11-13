"""P3 本机 Web 实例启动器的纯函数回归（不起进程、不联网）。"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "p3"))

import local_web  # noqa: E402


class PatchTemplateTests(unittest.TestCase):
    def setUp(self):
        self.text = local_web.PATCH.read_text(encoding="utf-8")

    def test_installs_road_preset_as_default(self):
        self.assertIn("id: preset-road", self.text)
        self.assertIn("name: 道路养护专家", self.text)
        self.assertIn("selectedDefault: road", self.text)

    def test_uses_account_route_and_full_access(self):
        self.assertIn("provider: deepseek-account", self.text)
        self.assertIn("defaultPreset: danger-full-access", self.text)

    def test_has_no_unrendered_placeholder(self):
        self.assertNotIn("{{", self.text)
        self.assertNotIn("}}", self.text)

    def test_does_not_grant_development_tools(self):
        for plugin in ("plugin-manager", "plan-mode", "tool-subagent", "tool-schedule"):
            self.assertNotIn(plugin, self.text)

    def test_shell_tools_are_platform_gated(self):
        # Linux 上要能跑 bash，Windows 上用 pwsh；两者互斥，靠 process.platform 决定
        self.assertIn('name: "@deepseek-ai/dsh-tool-bash"', self.text)
        self.assertIn("disabled: !!js process.platform === 'win32'", self.text)
        self.assertIn('name: "@deepseek-ai/dsh-tool-pwsh"', self.text)
        self.assertIn("disabled: !!js process.platform !== 'win32'", self.text)


class PortTests(unittest.TestCase):
    def test_accepts_project_port(self):
        self.assertEqual(local_web.validate_port(8090), 8090)

    def test_rejects_privileged_out_of_range_and_dev_gui(self):
        for port in (80, 70000, local_web.DEV_GUI_PORT):
            with self.assertRaises(local_web.TrialError):
                local_web.validate_port(port)


class AddressTests(unittest.TestCase):
    def test_lan_ranges(self):
        for value in ("192.168.1.5", "10.0.0.7", "172.16.3.9"):
            self.assertTrue(local_web.is_lan_address(value), value)
        for value in ("127.0.0.1", "100.85.0.30", "172.32.0.1", "169.254.1.1", "abc", "1.2.3"):
            self.assertFalse(local_web.is_lan_address(value), value)

    def test_picks_first_lan_candidate(self):
        candidates = ["127.0.0.1", "100.85.0.30", "192.168.1.5", "10.1.2.3"]
        self.assertEqual(local_web.pick_lan_address(candidates), "192.168.1.5")

    def test_prefers_192_then_172_then_10(self):
        self.assertEqual(local_web.pick_lan_address(["10.10.1.1", "192.168.1.5"]), "192.168.1.5")
        self.assertEqual(local_web.pick_lan_address(["10.10.1.1", "172.20.0.4"]), "172.20.0.4")
        self.assertEqual(local_web.pick_lan_address(["10.10.1.1"]), "10.10.1.1")

    def test_returns_none_without_lan(self):
        self.assertIsNone(local_web.pick_lan_address(["127.0.0.1", "100.85.0.30"]))


class UrlTests(unittest.TestCase):
    LOG = (
        "=== start ===\n"
        "dsh web: listening on 192.168.1.5 over plain HTTP\n"
        "dsh web: http://192.168.1.5:8090/?token=first-token\n"
        "dsh web: http://192.168.1.5:8090/?token=second-token\n"
    )

    def test_parse_finds_every_url(self):
        self.assertEqual(len(local_web.parse_urls(self.LOG)), 2)

    def test_latest_url_wins(self):
        self.assertEqual(local_web.latest_url(self.LOG, 8090),
                         "http://192.168.1.5:8090/?token=second-token")

    def test_port_filter_and_missing(self):
        self.assertIsNone(local_web.latest_url(self.LOG, 9000))
        self.assertIsNone(local_web.latest_url("no url here", 8090))


class LayoutTests(unittest.TestCase):
    def test_default_layout_is_outside_repository(self):
        paths = local_web.layout()
        self.assertEqual(paths["base"].name, local_web.BASE_NAME)
        self.assertFalse(paths["base"].is_relative_to(ROOT))
        self.assertEqual(paths["home"], paths["base"] / "home")
        self.assertEqual(paths["patch"], paths["home"] / "profiles" / "web" / "cordis.patch.yml")

    def test_custom_base(self):
        paths = local_web.layout(Path("D:/tmp/trial"))
        self.assertEqual(paths["log"], paths["base"] / "logs" / "web.log")


if __name__ == "__main__":
    unittest.main()
