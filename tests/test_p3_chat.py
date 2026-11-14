"""P3 纯聊天前端的纯函数回归：patch 生成与事件取文（不起进程、不联网）。"""
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "p3" / "chat"))

import app  # noqa: E402


WEB_PATCH = (ROOT / "scripts" / "p3" / "road_expert.patch.yml").read_text(encoding="utf-8")


class PatchSplitTests(unittest.TestCase):
    def test_splits_top_level_blocks(self):
        blocks = app.split_patch("- id: a\n  config: {}\n- id: b\n  config: {}\n")
        self.assertEqual(len(blocks), 2)
        self.assertTrue(blocks[0].startswith("- id: a"))
        self.assertTrue(blocks[1].startswith("- id: b"))

    def test_ignores_leading_blank_text(self):
        self.assertEqual(app.split_patch("\n\n"), [])


class SdkPatchTests(unittest.TestCase):
    def setUp(self):
        self.text = app.sdk_patch_text(WEB_PATCH)

    def test_carries_persona_and_permissions(self):
        self.assertIn("personaPrefix: |", self.text)
        self.assertIn("你是道路养护技术咨询专家助手", self.text)
        self.assertIn("defaultPreset: danger-full-access", self.text)

    def test_does_not_shadow_web_preset(self):
        # SDK 根 agent 不走 preset；搬过来只会 pending 等 Web 端的 agentPresets 服务
        self.assertNotIn("preset-road", self.text)
        self.assertNotIn("agent-preset-registry", self.text)

    def test_drops_web_only_rows(self):
        for row in ("dsh-client-locale", "id: connection", "deepseek-account"):
            self.assertNotIn(row, self.text)

    def test_restricts_development_tools(self):
        for row in ("tool-plugin-manager", "tool-subagent", "plan-mode"):
            self.assertIn(f"- id: {row}\n  disabled: true", self.text)

    def test_persona_is_dedented(self):
        lines = app.persona_text(WEB_PATCH)
        self.assertTrue(lines[0].startswith("你是道路养护"))
        self.assertTrue(all(not line.startswith("    ") for line in lines if line.strip()))

    def test_missing_persona_is_reported(self):
        with self.assertRaises(app.ChatError):
            app.sdk_patch_text("- id: permission\n  config: {}\n")


class AssistantTextTests(unittest.TestCase):
    def test_reads_text_blocks_in_order(self):
        event = {"type": "assistant/message", "data": {"message": {"content": [
            {"type": "text", "text": "甲"},
            {"type": "image", "attachment": "sha256:x"},
            {"type": "text", "text": "乙"},
        ]}}}
        self.assertEqual(app.assistant_text(event), "甲乙")

    def test_tolerates_flat_data_and_garbage(self):
        self.assertEqual(app.assistant_text({"data": {"content": [{"type": "text", "text": "x"}]}}), "x")
        self.assertEqual(app.assistant_text({}), "")
        self.assertEqual(app.assistant_text({"data": {"content": "nope"}}), "")


class ApiKeyTests(unittest.TestCase):
    def test_environment_wins(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-env"}):
            self.assertEqual(app.read_api_key(Path("nowhere")), "sk-env")

    def test_reads_marker_home_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home / ".credentials.yaml").write_text(
                "version: 1\nrefs:\n  DEEPSEEK_API_KEY: sk-file\n", encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if k != "DEEPSEEK_API_KEY"}
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(app.read_api_key(home), "sk-file")


class PasswordTests(unittest.TestCase):
    def test_environment_wins_over_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text('{"password": "from-file"}', encoding="utf-8")
            self.assertEqual(app.resolve_password(path, "from-env"), "from-env")

    def test_empty_environment_disables_the_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text('{"password": "from-file"}', encoding="utf-8")
            self.assertEqual(app.resolve_password(path, ""), "")

    def test_file_value_is_used_and_empty_disables(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text('{"password": "yhg2"}', encoding="utf-8")
            self.assertEqual(app.resolve_password(path, None), "yhg2")
            path.write_text('{"password": ""}', encoding="utf-8")
            self.assertEqual(app.resolve_password(path, None), "")

    def test_deploy_shaped_config_reads_only_password(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "deploy.json"
            path.write_text(
                '{"_说明":"提示","password":"deploy-pass","api_key":"sk-x","chat_port":8091,'
                '"paths":{"app":"C:/road/app"}}',
                encoding="utf-8",
            )
            self.assertEqual(app.resolve_password(path, None), "deploy-pass")

    def test_utf8_bom_file_is_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text('{"password": ""}', encoding="utf-8-sig")
            self.assertEqual(app.resolve_password(path, None), "")

    def test_missing_or_broken_file_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "missing.json"
            self.assertEqual(app.resolve_password(path, None), app.DEFAULT_PASSWORD)
            broken = Path(folder) / "broken.json"
            broken.write_text("{not json", encoding="utf-8")
            self.assertEqual(app.resolve_password(broken, None), app.DEFAULT_PASSWORD)


class AuthCookieTests(unittest.TestCase):
    def test_roundtrip(self):
        cookie = app.make_auth_cookie("secret", now=1000)
        self.assertTrue(app.check_auth_cookie(cookie, "secret", now=1001))

    def test_expired_is_rejected(self):
        cookie = app.make_auth_cookie("secret", now=1000, ttl=10)
        self.assertFalse(app.check_auth_cookie(cookie, "secret", now=2000))

    def test_tampered_or_foreign_cookie_is_rejected(self):
        cookie = app.make_auth_cookie("secret", now=1000)
        expires, _, signature = cookie.partition(".")
        self.assertFalse(app.check_auth_cookie(f"{expires}.{signature[:-1]}0", "secret", now=1001))
        self.assertFalse(app.check_auth_cookie(cookie, "other", now=1001))
        self.assertFalse(app.check_auth_cookie("", "secret", now=1001))
        self.assertFalse(app.check_auth_cookie("garbage", "secret", now=1001))

    def test_signature_change_tracks_expiry(self):
        self.assertNotEqual(app._sign("secret", 1), app._sign("secret", 2))


class FakeRuntime:
    def __init__(self):
        self.requests = {}
        self.request_sessions = {}
        self.answers = []
        self.killed = 0
        self.alive = True

    def respond(self, jsonrpc_id, result):
        self.answers.append((jsonrpc_id, result))

    def kill(self):
        self.killed += 1
        self.alive = False


def make_visitor():
    """只测纯逻辑：构造一个不真正起进程的 Visitor。"""
    visitor = app.Visitor.__new__(app.Visitor)
    visitor.id = "a" * 32
    visitor._guard = threading.Lock()
    visitor._locks = {}
    visitor._active = {}
    visitor.sessions = 0
    visitor.runtime = FakeRuntime()
    visitor.ready = True
    visitor.error = None
    visitor.restarts = []
    visitor.restart = lambda resume_session=None: visitor.restarts.append(resume_session)
    return visitor


class VisitorTests(unittest.TestCase):
    def test_new_session_ids_are_unique_and_opaque(self):
        visitor = make_visitor()
        first, second = visitor.new_session(), visitor.new_session()
        self.assertNotEqual(first, second)
        self.assertRegex(first, r"^web-[0-9a-f]{12}$")

    def test_lock_is_per_session(self):
        visitor = make_visitor()
        self.assertIs(visitor.lock_for("web-a"), visitor.lock_for("web-a"))
        self.assertIsNot(visitor.lock_for("web-a"), visitor.lock_for("web-b"))

    def test_new_session_abandons_running_turn(self):
        visitor = make_visitor()
        turn = app.Turn("web-a")
        visitor._active["web-a"] = turn
        visitor.new_session()
        self.assertTrue(turn.abandoned.is_set())

    def test_abandon_cancels_pending_question_of_that_session_only(self):
        visitor = make_visitor()
        visitor._active["web-a"] = app.Turn("web-a")
        visitor.runtime.requests = {"q1": 11, "q2": 12}
        visitor.runtime.request_sessions = {"q1": "web-a", "q2": "web-b"}
        visitor.abandon_all()
        self.assertEqual(visitor.runtime.answers, [(11, {"cancelled": True})])
        self.assertEqual(visitor.runtime.requests, {"q2": 12})
        self.assertEqual(visitor.runtime.request_sessions, {"q2": "web-b"})

    def test_stop_only_touches_its_own_turn(self):
        visitor = make_visitor()
        mine, other = app.Turn("web-a"), app.Turn("web-b")
        visitor._active = {"web-a": mine, "web-b": other}
        visitor.runtime.requests = {"q1": 11}
        visitor.runtime.request_sessions = {"q1": "web-a"}
        self.assertTrue(visitor.stop("web-a"))
        self.assertTrue(mine.abandoned.is_set())
        self.assertFalse(other.abandoned.is_set())
        self.assertEqual(visitor.runtime.answers, [(11, {"cancelled": True})])
        self.assertFalse(visitor.stop("missing"))

    def test_stop_restarts_only_this_visitor(self):
        visitor = make_visitor()
        visitor._active = {"web-a": app.Turn("web-a")}
        visitor.stop("web-a")
        deadline = time.time() + 2
        while not visitor.restarts and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(visitor.restarts, ["web-a"])

    def test_rebuild_after_many_new_sessions(self):
        visitor = make_visitor()
        visitor.sessions = app.REBUILD_AFTER
        visitor.new_session()
        deadline = time.time() + 2
        while not visitor.restarts and time.time() < deadline:
            time.sleep(0.01)
        self.assertEqual(visitor.restarts, [None])
        self.assertEqual(visitor.sessions, 1)

    def test_no_rebuild_while_a_turn_is_running(self):
        visitor = make_visitor()
        visitor.sessions = app.REBUILD_AFTER
        visitor._active = {"web-a": app.Turn("web-a")}
        visitor.new_session()
        time.sleep(0.05)
        self.assertEqual(visitor.restarts, [])


class PoolTests(unittest.TestCase):
    def test_same_id_reuses_visitor_and_different_ids_do_not(self):
        service = app.ChatService(Path("."), "sk-test")
        first = service.visitor("a" * 32)
        self.assertIs(first, service.visitor("a" * 32))
        self.assertIsNot(first, service.visitor("b" * 32))

    def test_health_reports_pool_size(self):
        service = app.ChatService(Path("."), "sk-test")
        service.visitor("a" * 32)
        service.visitor("b" * 32)
        self.assertEqual(service.health()["visitors"], 2)


class TranslateEventTests(unittest.TestCase):
    """0.4.0 把会话事件翻译抽成了方法，这里锁住它的输出与返回值。"""

    def make(self):
        visitor = app.Visitor.__new__(app.Visitor)
        visitor.emitted = []
        visitor.emit = lambda name, data: visitor.emitted.append((name, data))
        return visitor

    def test_assistant_message_emits_text_and_reports_produced(self):
        visitor = self.make()
        produced = visitor._translate_event({
            "type": "assistant/message",
            "data": {"message": {"content": [{"type": "text", "text": "结论"}]}},
        }, visitor.emit)
        self.assertTrue(produced)

    def test_tool_call_becomes_trace_without_produced(self):
        visitor = self.make()
        produced = visitor._translate_event({
            "type": "tool/call",
            "data": {"callId": "c1", "name": "pwsh", "arguments": {"command": "road.py"}},
        }, visitor.emit)
        self.assertFalse(produced)

    def test_injected_context_becomes_trace(self):
        visitor = self.make()
        produced = visitor._translate_event({
            "type": "user/message",
            "data": {"source": {"kind": "agent-instructions", "path": "AGENTS.md"}},
        }, visitor.emit)
        self.assertFalse(produced)

    def test_plain_user_message_emits_nothing(self):
        visitor = self.make()
        produced = visitor._translate_event({
            "type": "user/message",
            "data": {"source": {"kind": "user"}},
        }, visitor.emit)
        self.assertFalse(produced)

    def test_unknown_event_is_ignored(self):
        visitor = self.make()
        self.assertFalse(visitor._translate_event({"type": "something/else"}, visitor.emit))


class TraceTests(unittest.TestCase):
    def test_assistant_blocks_split_thinking_and_answer(self):
        event = {"data": {"message": {"content": [
            {"type": "reasoning", "text": "先看规范"},
            {"type": "tool-call", "name": "read", "arguments": "{}"},
            {"type": "text", "text": "答案"},
        ]}}}
        thinking, answer = app.assistant_blocks(event)
        self.assertEqual(thinking, ["先看规范"])
        self.assertEqual(answer, "答案")

    def test_trace_label_maps_tools_and_targets(self):
        self.assertEqual(app.trace_label("pwsh", '{"command": "ls"}'), ("运行命令", "ls"))
        self.assertEqual(app.trace_label("skill", '{"name": "road-diagnosis"}'), ("加载技能", "road-diagnosis"))
        self.assertEqual(app.trace_label("read", '{"file_path": "a/b.md"}'), ("读取", "a/b.md"))
        self.assertEqual(app.trace_label("mystery", "{}"), ("mystery", ""))
        self.assertEqual(app.trace_label("pwsh", "not json"), ("运行命令", ""))

    def test_context_label_names_instruction_files(self):
        source = {"kind": "agent-instructions",
                  "changes": [{"path": "C:\\repo\\AGENTS.md"}, {"scope": ".\x00CLAUDE.md"}]}
        self.assertEqual(app.context_label(source), "上下文注入 · AGENTS.md、CLAUDE.md")

    def test_context_label_for_plain_snapshot(self):
        self.assertEqual(app.context_label({"kind": "runtime-context"}),
                         "上下文注入 · runtime-context")


class StateFileTests(unittest.TestCase):
    def test_marker_sits_beside_home(self):
        path = app.state_path(Path("C:/work/dsh-roads/home"))
        self.assertEqual(path.name, "chat-url.txt")
        self.assertEqual(path.parent.name, "dsh-roads")
        self.assertFalse(str(path).startswith(str(Path("C:/work/dsh-roads/home"))))


if __name__ == "__main__":
    unittest.main()
