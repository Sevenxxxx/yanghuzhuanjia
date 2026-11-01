"""Synthetic interaction, recovery and Windows merged-storage regressions."""
import os
from pathlib import Path
from unittest.mock import patch

from test_workflow import Isolated
from roadexpert.storage import RoadError, local_store_path
from roadexpert.service import App


class TrialFlowTests(Isolated):
    def ask(self, session, fields=None):
        result = self.request(session, "question-ask", fields=fields or ["traffic"])
        return self.app.store.read(session["id"]), result["questions"]

    def reply(self, session, q, reply="不清楚", state="unknown", **kwargs):
        return self.request(session, "turn", text=reply, question_responses=[{
            "question_id": q["id"], "text": reply, "state": state, "submitted": True, **kwargs}])["session"]

    def test_pending_survives_restart_without_inventing_facts(self):
        s, questions = self.ask(self.start())
        restored = App(self.project, self.base / "records", self.config).dispatch({"op": "resume", "session_id": s["id"]})
        self.assertEqual(restored["resume_summary"]["pending_questions"][0]["id"], questions[0]["id"])
        self.assertEqual(restored["briefing"]["next_questions"], [])
        self.assertEqual(len(restored["session"]["turns"]), 1)
        self.assertEqual(restored["session"]["facts"], [])
        with self.assertRaises(RoadError):
            self.ask(s, ["location"])

    def test_unsubmitted_and_unknown_as_known_are_rejected_without_write(self):
        s, qs = self.ask(self.start())
        for args in ({"submitted": False}, {"state": "known"}):
            with self.assertRaises(RoadError):
                self.reply(s, qs[0], **args)
            self.assertEqual(self.app.store.read(s["id"]), s)

    def test_unknown_free_text_and_duplicate_submission(self):
        s, qs = self.ask(self.start())
        s = self.reply(s, qs[0])
        self.assertEqual(s["facts"][-1]["state"], "unknown")
        self.assertEqual(s["question_log"][-1]["status"], "answered")
        self.assertNotIn("traffic", [q["field"] for q in self.app.briefing(s)["next_questions"]])
        with self.assertRaises(RoadError):
            self.reply(s, qs[0])
        s, qs = self.ask(s, ["location"])
        s = self.reply(s, qs[0], "在路肩靠近旧沟槽处，具体边界不清楚", "known")
        self.assertEqual(s["facts"][-1]["value"], "在路肩靠近旧沟槽处，具体边界不清楚")

    def test_close_and_late_reply_keep_no_reply_distinct_from_unknown(self):
        s, qs = self.ask(self.start())
        result = self.request(s, "question-close", question_ids=[qs[0]["id"]], reason="合成模拟关闭弹窗")
        self.assertEqual(result["facts_added"], 0)
        s = self.app.store.read(s["id"])
        self.assertEqual(s["facts"], [])
        self.assertEqual(len(s["turns"]), 1)
        self.assertEqual(self.app.resume_summary(s)["unanswered_questions"][0]["id"], qs[0]["id"])
        s = self.reply(s, qs[0])
        self.assertEqual(len(s["facts"]), 1)

    def test_other_session_reply_and_stale_revision_fail(self):
        first, qs = self.ask(self.start())
        second = self.start()
        with self.assertRaises(RoadError):
            self.reply(second, qs[0])
        current = self.request(first, "turn", text="补充合成原话")["session"]
        with self.assertRaises(RoadError):
            self.reply(first, qs[0])
        self.assertEqual(self.app.store.read(first["id"]), current)

    def test_direct_chat_reply_resolves_pending_and_correction_keeps_history(self):
        s, qs = self.ask(self.start())
        s = self.request(s, "turn", text="已经停止通行", facts=[{
            "field": "traffic", "value": "已经停止通行", "state": "known"}])["session"]
        self.assertEqual(s["question_log"][0]["status"], "answered_in_turn")
        old = s["facts"][0]["id"]
        s = self.request(s, "turn", text="更正：仍有车辆通行", user_correction=True, correction_reason="合成用户纠正",
                         facts=[{"field": "traffic", "value": "仍有车辆通行", "supersedes": [old]}])["session"]
        self.assertEqual(self.app.resume_summary(s)["corrected_facts"][0]["id"], old)
        self.assertEqual(self.app.active_facts(s)[0]["value"], "仍有车辆通行")

    def test_resume_stale_information_and_saved_opinion_changes(self):
        s = self.start()
        first_answer = self.answer_data()
        self.request(s, "answer", answer=first_answer)
        s = self.app.store.read(s["id"])
        s = self.request(s, "turn", text="合成补充：位置在桥头", facts=[{
            "field": "location", "value": "位置在桥头"}])["session"]
        summary = self.app.resume_summary(s)
        self.assertTrue(summary["latest_opinion"]["stale"])
        self.assertEqual(summary["new_information"][0]["text"], "合成补充：位置在桥头")
        self.assertEqual(summary["follow_up_checks"], first_answer["next_checks"])
        answer = self.answer_data()
        answer["summary"] = "新增位置资料后，需先核对构造物过渡部位。"
        self.request(s, "answer", answer=answer)
        summary = self.app.dispatch({"op": "resume", "session_id": s["id"]})["resume_summary"]
        self.assertFalse(summary["latest_opinion"]["stale"])
        self.assertEqual(summary["new_information"], [])
        self.assertTrue(summary["opinion_changes"]["summary_changed"])
        self.assertEqual(summary["opinion_changes"]["previous_summary"], first_answer["summary"])

    def test_restricted_summaries_questions_and_titles_do_not_leak(self):
        s = self.start(privacy={"level": "restricted", "external_model_allowed": False})
        self.request(s, "save", user_requested=True, basis="合成保存受限记录")
        result = self.app.dispatch({"op": "resume", "session_id": s["id"]})
        self.assertIsNone(result["resume_summary"])
        self.assertNotIn("title", self.app.dispatch({"op": "sessions"})[0])
        with self.assertRaises(RoadError):
            self.ask(s)

    def test_unknown_reply_does_not_import_question_wording_as_observation(self):
        s, qs = self.ask(self.start(text="合成问题，信息不详。"), ["progression"])
        before = s["observations"]
        s = self.reply(s, qs[0])
        self.assertEqual(s["observations"], before)
        self.assertEqual(s["turns"][-1]["text"], "不清楚")
        self.assertNotEqual(s["risk"]["status"], "attention")

    def test_pending_and_summary_are_hidden_after_permission_revocation(self):
        s, qs = self.ask(self.start())
        self.request(s, "permission", action="revoke", basis="合成撤销")
        latest = self.app.store.read(s["id"])
        self.request(latest, "save", user_requested=True, basis="合成保存受限记录")
        historical = self.app.dispatch({"op": "show", "session_id": s["id"], "revision": s["revision"]})
        self.assertIsNone(historical["resume_summary"])
        self.assertIsNone(historical["briefing"])
        self.assertNotIn("title", self.app.dispatch({"op": "sessions"})[0])

    def test_legacy_question_is_visible_without_rewriting_history(self):
        s = self.start()
        answer = self.answer_data()
        answer["questions"] = [{"field": "location", "question": "具体位置？", "purpose": "明确部位"}]
        self.request(s, "answer", answer=answer)
        s = self.app.store.read(s["id"])
        summary = self.app.resume_summary(s)
        self.assertEqual(summary["unanswered_questions"][0]["status"], "legacy_unanswered")
        self.assertNotIn("status", self.app.store.read(s["id"])["question_log"][0])
        s = self.request(s, "turn", text="位置不清楚", facts=[{"field": "location", "value": "位置不清楚", "state": "unknown"}])["session"]
        self.assertEqual(self.app.resume_summary(s)["unanswered_questions"], [])

    def test_profile_requires_reasoning_discrimination_and_branches(self):
        s = self.start()
        answer = self.answer_data()
        answer.update(analysis_profile="pavement-subsidence-v1", hypotheses=[{
            "label": "合成待核查方向", "support_fact_ids": [], "against_fact_ids": [],
            "uncertainties": ["尚无确认资料"]}])
        with self.assertRaises(RoadError):
            self.request(s, "answer", answer=answer)
        answer["hypotheses"][0].update(reasoning="尚无直接证据，不能仅凭时间关联确定原因", discriminator="对照空间位置与既有调查资料")
        with self.assertRaises(RoadError):
            self.request(s, "answer", answer=answer)
        answer["next_checks"][0]["different_results"] = "资料显示有变化则补充专业调查；记录不足则保留未知"
        self.request(s, "answer", answer=answer)
        report = self.app.render_report(self.app.store.read(s["id"]))
        self.assertIn(answer["hypotheses"][0]["reasoning"], report)
        self.assertIn(answer["hypotheses"][0]["discriminator"], report)
        self.assertIn(answer["next_checks"][0]["different_results"], report)


class MergedStorageTests(Isolated):
    def test_local_paths_still_reject_escape_and_reparse(self):
        for relative in ("../outside", self.base / "outside"):
            with self.assertRaises(RoadError):
                self.app.store.path(relative)
        with patch.object(Path, "is_symlink", return_value=True):
            with self.assertRaises(RoadError):
                self.app.store.path("sessions")

    def test_revision_file_link_is_rejected(self):
        s = self.start()
        original = Path.is_symlink
        with patch.object(Path, "is_symlink", lambda p: True if p.name == "000001.json" else original(p)):
            with self.assertRaises(RoadError):
                self.app.store.read(s["id"])

    def test_verified_msix_alias_preserves_logical_view(self):
        if os.name != "nt":
            self.skipTest("Windows MSIX mapping")
        local = self.base / "Local"
        root = local / "RoadMaintenanceExpert/key"
        root.mkdir(parents=True)
        logical = root / "sessions"
        logical.mkdir()
        mapped = local / "Packages/TestFamily/LocalCache/Local/RoadMaintenanceExpert/key/sessions"
        mapped.mkdir(parents=True)
        original = Path.resolve
        def resolve(p, *args, **kwargs):
            return mapped if p == logical else original(p, *args, **kwargs)
        with patch.dict(os.environ, {"LOCALAPPDATA": str(local)}), patch.object(Path, "resolve", resolve):
            with patch.object(Path, "samefile", return_value=True):
                self.assertEqual(local_store_path(root, "sessions"), logical)
            # Same shape is insufficient without matching filesystem identity.
            with patch.object(Path, "samefile", return_value=False):
                with self.assertRaises(RoadError):
                    local_store_path(root, "sessions")

    def test_arbitrary_resolved_directory_is_rejected(self):
        logical = self.app.store.root / "sessions"
        outside = self.base / "unrelated"
        outside.mkdir()
        original = Path.resolve
        with patch.object(Path, "resolve", lambda p, *a, **kw: outside if p == logical else original(p, *a, **kw)):
            with self.assertRaises(RoadError):
                self.app.store.path("sessions")
