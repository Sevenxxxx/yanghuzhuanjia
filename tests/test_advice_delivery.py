"""Synthetic contract regressions, not an engineering-quality assessment."""
import copy
import json
from pathlib import Path

from test_workflow import Isolated
from roadexpert.advice import PROFILES, DELIVERIES
from roadexpert.storage import RoadError


class AdviceDeliveryTests(Isolated):
    def prepared(self, profile="pavement-distress-v1"):
        domain, fields = PROFILES[profile]
        s = self.start(domain=domain, text="全合成测试：有异常，层位、发展与通行情况不清楚。")
        a = self.answer_data()
        a.update(analysis_profile=profile, analysis_context={k: "合成：未知，待核查" for k in fields})
        a["next_checks"][0]["different_results"] = "有对应资料再核查关联，无资料保持未知。"
        a["hypotheses"] = [{"label": "合成候选，未确认", "uncertainties": ["缺少现场核查"],
            "support_fact_ids": [], "against_fact_ids": [], "reasoning": "资料不足，未能建立因果联系。",
            "discriminator": "由专业人员比对已有同位置记录。"}]
        a["deliverables"] = {kind: {key: ["合成草稿：待核查，尚未执行。"] for key in fields}
                             for kind, (_, fields) in DELIVERIES.items()}
        return s, a

    def test_all_profiles_preserve_unknowns_and_reasoning(self):
        for profile in PROFILES:
            with self.subTest(profile=profile):
                s, a = self.prepared(profile)
                self.request(s, "answer", answer=a)
                current = self.app.store.read(s["id"])
                report = self.app.render_report(current)
                self.assertIn(a["hypotheses"][0]["reasoning"], report)
                for value in a["analysis_context"].values():
                    self.assertIn(value, report)

    def test_missing_context_reasoning_and_branches_fail_without_write(self):
        for profile in list(PROFILES)[1:]:
            s, a = self.prepared(profile)
            mutations = []
            b = copy.deepcopy(a); b["analysis_context"].pop(next(iter(b["analysis_context"]))); mutations.append(b)
            b = copy.deepcopy(a); b["hypotheses"][0].pop("discriminator"); mutations.append(b)
            b = copy.deepcopy(a); b["next_checks"][0].pop("different_results"); mutations.append(b)
            for b in mutations:
                with self.assertRaises(RoadError):
                    self.request(s, "answer", answer=b)
                self.assertEqual(self.app.store.read(s["id"]), s)

    def test_cross_domain_and_malformed_profile_are_rejected(self):
        s, a = self.prepared()
        for profile in ("slope-instability-v1", "bridge-culvert-v1", "invented", []):
            a["analysis_profile"] = profile
            with self.assertRaises(RoadError):
                self.request(s, "answer", answer=a)

    def test_unknown_or_corrected_facts_cannot_support_new_profiles(self):
        s, a = self.prepared()
        s = self.request(s, "turn", text="发展不清楚", facts=[{
            "field": "progression", "value": "发展不清楚", "state": "unknown"}])["session"]
        a["hypotheses"][0]["support_fact_ids"] = [s["facts"][-1]["id"]]
        with self.assertRaises(RoadError):
            self.request(s, "answer", answer=a)

    def test_delivery_incomplete_and_wrong_types_are_rejected(self):
        s, a = self.prepared()
        invalid = [None, {"unknown": {}}, {"field_advice": {}},
                   {"field_advice": {k: "not a list" for k in DELIVERIES["field_advice"][1]}}]
        for value in invalid:
            a["deliverables"] = value
            with self.assertRaises(RoadError):
                self.request(s, "answer", answer=a)
        self.assertEqual(self.app.store.read(s["id"]), s)

    def test_three_exports_keep_sources_and_limits_without_raw_history(self):
        s, a = self.prepared()
        self.request(s, "answer", answer=a)
        s = self.app.store.read(s["id"])
        paths = set()
        for kind in DELIVERIES:
            result = self.request(s, "export", kind=kind, user_requested=True)
            paths.add(result["markdown"])
            report = Path(result["markdown"]).read_text(encoding="utf-8")
            payload = json.loads(Path(result["json"]).read_text(encoding="utf-8"))
            self.assertIn("现有信息（保留来源）", report)
            self.assertIn("规范依据与核验范围", report)
            self.assertIn("判断边界", report)
            self.assertIn("未经工程专业审阅", report)
            self.assertNotIn("turns", payload)
            self.assertNotIn(s["turns"][0]["text"], report)
            self.assertEqual(payload["report"], report)
        self.assertEqual(len(paths), 3)
        self.assertEqual(self.app.dispatch({"op": "sessions"}), [])
        self.assertEqual(self.app.store.read(s["id"])["retention"], "temporary")

    def test_stale_absent_and_invalid_delivery_do_not_create_exports(self):
        s = self.start()
        for kind in ("field_advice", "invalid", "../escape", []):
            with self.assertRaises(RoadError):
                self.request(s, "export", kind=kind, user_requested=True)
        s, a = self.prepared()
        a.pop("deliverables")
        self.request(s, "answer", answer=a)
        with self.assertRaises(RoadError):
            self.request(s, "export", kind="inspection_brief", user_requested=True)
        s, a = self.prepared()
        self.request(s, "answer", answer=a)
        s = self.app.store.read(s["id"])
        s = self.request(s, "turn", text="合成补充：位置已改变")["session"]
        with self.assertRaises(RoadError):
            self.request(s, "export", kind="department_reply", user_requested=True)
        self.assertFalse(self.app.store.path("exports").exists())

    def test_delivery_cannot_bypass_existing_claim_and_safety_checks(self):
        s, a = self.prepared()
        a["deliverables"]["department_reply"]["conditional_conclusion"] = ["保证结构安全"]
        with self.assertRaises(RoadError):
            self.request(s, "answer", answer=a)
        s, a = self.prepared()
        a["claims"] = [{"text": "合成未经核实的要求", "review_ids": []}]
        with self.assertRaises(RoadError):
            self.request(s, "answer", answer=a)

    def test_export_still_requires_explicit_request(self):
        s, a = self.prepared()
        self.request(s, "answer", answer=a)
        with self.assertRaises(RoadError):
            self.request(s, "export", kind="field_advice")
        self.assertFalse(self.app.store.path("exports").exists())

    def test_reviewed_evidence_is_included_in_each_delivery(self):
        s, a = self.prepared("bridge-culvert-v1")
        s, receipt = self.attach_read(s)
        reviewed = self.app.dispatch(self.review_request(s, receipt))
        s = self.app.store.read(s["id"])
        a["claims"] = [{"text": "合成依据：记录异常", "review_ids": [reviewed["review"]["id"]]}]
        self.request(s, "answer", answer=a)
        for kind in DELIVERIES:
            result = self.request(s, "export", kind=kind, user_requested=True)
            report = Path(result["markdown"]).read_text(encoding="utf-8")
            for expected in ("TEST-ONLY", "应记录异常。", "PDF/物理页 1", "适用性：conditional", "实际范围："):
                self.assertIn(expected, report)
