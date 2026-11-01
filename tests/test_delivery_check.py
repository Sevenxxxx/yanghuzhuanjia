"""Checks are deterministic findings, never a certificate of engineering correctness."""
import copy
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from test_workflow import Isolated
import test_photo_word_comparison as photo_helpers
from roadexpert.storage import RoadError
from roadexpert.word_export import export_word


class DeliveryCheckTests(Isolated):
    add_photo = photo_helpers.PhotoWordComparisonTests.add_photo
    observe = photo_helpers.PhotoWordComparisonTests.observe
    comparison = photo_helpers.PhotoWordComparisonTests.comparison
    answer_with_delivery = photo_helpers.PhotoWordComparisonTests.answer_with_delivery

    def prepared(self, **changes):
        s = self.start(**changes)
        self.request(s, "answer", answer=self.answer_with_delivery())
        return self.app.store.read(s["id"])

    def codes(self, result, field="errors"):
        return {item["code"] for item in result[field]}

    def test_check_is_read_only_and_does_not_claim_semantic_approval(self):
        s = self.prepared()
        check = self.request(s, "delivery-check")
        self.assertTrue(check["exportable"])
        self.assertTrue(check["manual_checks"])
        self.assertIn("manual_review_required", check["status"])
        self.assertEqual(self.app.store.read(s["id"]), s)
        self.assertFalse(self.app.store.path("exports").exists())

    def test_empty_and_stale_opinions_block_current_export_but_allow_labeled_history(self):
        s = self.start()
        self.assertIn("no_opinion", self.codes(self.request(s, "delivery-check")))
        with self.assertRaises(RoadError):
            self.request(s, "export", user_requested=True)
        self.request(s, "answer", answer=self.answer_data())
        s = self.app.store.read(s["id"])
        s = self.request(s, "turn", text="合成新增信息")["session"]
        self.assertIn("stale_opinion", self.codes(self.request(s, "delivery-check")))
        with self.assertRaises(RoadError):
            self.request(s, "export", user_requested=True)
        result = self.request(s, "export", user_requested=True, history_only=True)
        self.assertEqual(result["status"], "historical_export_not_for_delivery")
        self.assertIn("不作为当前意见交付", Path(result["markdown"]).read_text(encoding="utf-8"))
        for values in ({"format": "docx"}, {"kind": "field_advice"}):
            with self.assertRaises(RoadError):
                self.request(s, "export", user_requested=True, history_only=True, **values)

    def test_export_rechecks_and_can_bind_exact_scope_and_content(self):
        s = self.prepared()
        check = self.request(s, "delivery-check", kind="field_advice")
        result = self.request(s, "export", user_requested=True, kind="field_advice", expected_check_sha256=check["content_sha256"])
        self.assertEqual(result["delivery_check"], check)
        with self.assertRaises(RoadError):
            self.request(s, "export", user_requested=True, kind="department_reply", expected_check_sha256=check["content_sha256"])
        self.request(s, "question-ask", fields=["traffic"])
        with self.assertRaises(RoadError):
            self.request(s, "export", user_requested=True, kind="field_advice", expected_check_sha256=check["content_sha256"])
        s = self.app.store.read(s["id"])
        s = self.request(s, "turn", text="合成补充信息")["session"]
        self.request(s, "answer", answer=self.answer_with_delivery())
        with self.assertRaises(RoadError):
            self.request(s, "export", user_requested=True, kind="field_advice", expected_check_sha256=check["content_sha256"])

    def test_changed_norm_source_is_blocked_without_overwriting_prior_file(self):
        s = self.start()
        s, receipt = self.attach_read(s)
        review = self.app.dispatch(self.review_request(s, receipt))["review"]
        s = self.app.store.read(s["id"])
        answer = self.answer_data()
        answer["claims"] = [{"text": "合成规范依据", "review_ids": [review["id"]]}]
        self.request(s, "answer", answer=answer)
        result = self.request(s, "export", user_requested=True)
        path = Path(result["markdown"]); before = path.read_bytes()
        Path(receipt["payload"]["source_path"]).write_bytes(b"synthetic changed source")
        self.assertIn("invalid_norm_source", self.codes(self.request(s, "delivery-check")))
        with self.assertRaises(RoadError):
            self.request(s, "export", user_requested=True)
        self.assertEqual(path.read_bytes(), before)

    def test_missing_or_unviewed_photos_and_photo_context(self):
        s, photo, _ = self.add_photo(self.start())
        self.request(s, "answer", answer=self.answer_data())
        s = self.app.store.read(s["id"])
        check = self.request(s, "delivery-check", format="docx", include_photos=True)
        self.assertIn("photo_not_viewed", self.codes(check, "warnings"))
        self.assertTrue(check["exportable"])
        self.app.store.path(photo["relative_path"]).write_bytes(b"changed")
        self.assertIn("photo_changed", self.codes(self.request(s, "delivery-check")))
        with self.assertRaises(RoadError):
            self.request(s, "export", format="docx", include_photos=True, user_requested=True)

    def test_requested_photos_must_exist(self):
        s = self.prepared()
        check = self.request(s, "delivery-check", format="docx", include_photos=True)
        self.assertIn("no_photos", self.codes(check))
        with self.assertRaises(RoadError):
            self.request(s, "export", format="docx", include_photos=True, user_requested=True)

    def test_numbers_and_clauses_missing_sources_have_exact_locations(self):
        s = self.start()
        answer = self.answer_data()
        answer["summary"] = "合成描述：裂缝宽度5mm，参考JTG 5110—2023第3.1.2条，适用性待核。"
        self.request(s, "answer", answer=answer)
        result = self.request(s, "delivery-check")
        self.assertTrue(result["exportable"])
        self.assertTrue({"quantity_source_unmatched", "standard_source_unmatched", "clause_source_unmatched"} <= self.codes(result, "warnings"))
        self.assertTrue(all(item["location"] == "answer.summary" for item in result["warnings"]))
        self.assertIn("5mm", [item.get("excerpt") for item in result["warnings"]])
        exported = self.request(s, "export", user_requested=True)
        self.assertEqual(exported["delivery_check"]["warnings"], result["warnings"])

    def test_grounded_numeric_text_is_only_a_match_not_an_approval(self):
        s = self.start(text="合成记录裂缝宽度5mm", facts=[{"field": "dimensions", "value": "裂缝宽度5mm"}])
        answer = self.answer_data(); answer["summary"] = "裂缝宽度5mm为用户陈述，现场情况待核。"
        self.request(s, "answer", answer=answer)
        check = self.request(s, "delivery-check")
        self.assertNotIn("quantity_source_unmatched", self.codes(check, "warnings"))
        self.assertTrue(check["manual_checks"])

    def test_only_selected_delivery_text_is_scanned(self):
        s = self.start(); answer = self.answer_with_delivery()
        answer["deliverables"]["department_reply"]["conditional_conclusion"] = ["合成未核实值厚度10cm"]
        self.request(s, "answer", answer=answer)
        self.assertNotIn("quantity_source_unmatched", self.codes(self.request(s, "delivery-check", kind="field_advice"), "warnings"))
        check = self.request(s, "delivery-check", kind="department_reply")
        self.assertIn("quantity_source_unmatched", self.codes(check, "warnings"))
        self.assertTrue(any("department_reply" in item["location"] for item in check["warnings"]))

    def test_named_selection_conflicts_are_flagged_but_negations_are_not(self):
        s = self.start(); answer = self.answer_with_delivery()
        answer["summary"] = "建议采用调查方向甲。"
        self.request(s, "answer", answer=answer)
        self.assertIn("comparison_selection_conflict", self.codes(self.request(s, "delivery-check"), "warnings"))
        s = self.app.store.read(s["id"])
        answer["summary"] = "目前不能建议采用调查方向甲。"
        self.request(s, "answer", answer=answer)
        self.assertNotIn("comparison_selection_conflict", self.codes(self.request(s, "delivery-check"), "warnings"))

    def test_restricted_check_does_not_return_text(self):
        s = self.prepared()
        self.request(s, "permission", action="revoke", basis="合成撤销")
        with self.assertRaises(RoadError):
            self.request(s, "delivery-check")
        result = self.request(s, "export", user_requested=True)
        self.assertNotIn("warnings", result["delivery_check"])

    def test_unknown_fact_cannot_ground_a_comparison_after_correction(self):
        s = self.prepared()
        answer = copy.deepcopy(s["answers"][-1])
        answer["comparison"]["alternatives"][0]["evidence_fact_ids"] = ["invented"]
        s["answers"][-1] = answer
        s = self.app.store.write(s, s["revision"])
        self.assertIn("invalid_structure", self.codes(self.request(s, "delivery-check")))

    def test_word_mismatched_media_or_caption_never_publish_file(self):
        destination = self.base / "export.docx"
        for extra_image in (True, False):
            images = [] if extra_image else [{"path": "unused", "sha256": hashlib.sha256(b"expected").hexdigest(), "caption": "missing caption"}]
            def fake_builder(args, **kwargs):
                with ZipFile(args[-1], "w") as archive:
                    archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>')
                    if extra_image:
                        archive.writestr("word/media/image.png", b"unrequested")
                    else:
                        archive.writestr("word/media/image.png", b"expected")
                return SimpleNamespace(returncode=0, stderr="")
            with patch("roadexpert.word_export.subprocess.run", side_effect=fake_builder):
                with self.assertRaises(RoadError):
                    export_word({"report": "synthetic", "images": images}, destination, self.app.config)
            self.assertFalse(destination.exists())
            self.assertEqual(list(self.base.glob(".*.docx")), [])
