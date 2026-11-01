"""Synthetic photo provenance, conditional comparison and DOCX regressions."""
import copy
import json
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile
from PIL import Image, PngImagePlugin

from test_workflow import Isolated
from roadexpert.storage import RoadError
from roadexpert.service import App
from roadexpert.advice import DELIVERIES
from roadexpert.specs import file_hash


class PhotoWordComparisonTests(Isolated):
    def add_photo(self, s, **changes):
        source = self.base / "synthetic.png"
        meta = PngImagePlugin.PngInfo()
        meta.add_text("private_metadata", "must not copy")
        Image.new("RGB", (300, 180), "gray").save(source, pnginfo=meta)
        values = {"path": str(source), "label": "合成照片", "user_provided": True,
                  "authorization_basis": "合成照片测试", "location": "合成位置", "direction": "不清楚"}
        values.update(changes)
        result = self.request(s, "photo-add", **values)
        return self.app.store.read(s["id"]), result["photo"], source

    def observe(self, s, photo, **changes):
        values = {"photo_id": photo["id"], "viewed": True, "viewer": "synthetic-test",
                  "observations": [{"field": "other", "state": "known", "value": "合成图中可见灰色区域",
                                    "region": "全图", "limitation": "合成图片不表示现场，无法判断隐蔽状态"}]}
        values.update(changes)
        self.request(s, "photo-observe", **values)
        return self.app.store.read(s["id"])

    def comparison(self):
        option = {"label": "调查方向甲", "purpose": "澄清异常范围", "status": "insufficient_evidence",
            "conditions": "取得相应调查资料并经专业核定", "evidence_fact_ids": [],
            "missing_evidence": ["缺少结构资料"], "advantages": "可用于研究核查顺序，尚未验证效果",
            "limitations": "不能据此直接施工", "next_step": "整理已有资料供专业核查"}
        return {"question": "合成问题：下一步研究什么方向", "decision_basis": "证据支持相应条件后再比较，未知时不确定最终方案",
                "alternatives": [option, {**copy.deepcopy(option), "label": "调查方向乙"}]}

    def answer_with_delivery(self):
        answer = self.answer_data()
        answer["comparison"] = self.comparison()
        answer["deliverables"] = {kind: {key: ["合成沟通草稿，资料待核查"] for key in fields}
                                  for kind, (_, fields) in DELIVERIES.items()}
        return answer

    def test_photo_registration_does_not_invent_observations_or_metadata(self):
        s, photo, source = self.add_photo(self.start())
        self.assertEqual(photo["status"], "registered_not_viewed")
        self.assertEqual(photo["metadata"]["capture_time"], "不清楚")
        self.assertEqual(s["facts"], [])
        path = self.app.store.path(photo["relative_path"])
        with Image.open(path) as image:
            self.assertNotIn("private_metadata", image.info)
        self.assertTrue(source.exists())
        result = self.request(s, "photo-show", photo_id=photo["id"])
        self.assertEqual(Path(result["path"]), path)

    def test_unprovided_invalid_and_stale_photos_are_rejected(self):
        s = self.start()
        for changes in ({"user_provided": False}, {"path": "relative.png"}, {"path": str(self.config)}):
            with self.assertRaises(RoadError):
                self.add_photo(s, **changes)
        current, _, _ = self.add_photo(s)
        with self.assertRaises(RoadError):
            self.add_photo(s)
        self.assertEqual(len(self.app.store.read(current["id"])["photos"]), 1)

    def test_photo_ownership_hash_and_permission_are_checked(self):
        s, photo, _ = self.add_photo(self.start())
        other = self.start()
        with self.assertRaises(RoadError):
            self.request(other, "photo-show", photo_id=photo["id"])
        self.request(s, "permission", action="revoke", basis="合成撤销许可")
        with self.assertRaises(RoadError):
            self.request(s, "photo-show", photo_id=photo["id"])
        self.app.store.path(photo["relative_path"]).write_bytes(b"changed")
        s = self.app.store.read(s["id"])
        with self.assertRaises(RoadError):
            self.request(s, "export", user_requested=True)

    def test_actual_view_is_required_and_no_user_turn_is_invented(self):
        s, photo, _ = self.add_photo(self.start())
        with self.assertRaises(RoadError):
            self.observe(s, photo, viewed=False)
        current = self.observe(s, photo)
        self.assertEqual(current["turns"], s["turns"])
        fact = current["facts"][-1]
        self.assertEqual(fact["kind"], "photo_observation")
        self.assertTrue(fact["source_ref"].startswith("photo:" + photo["id"]))
        self.assertEqual(current["photos"][0]["observations"][0]["time"], "unknown")

    def test_photo_appearance_does_not_clear_prior_risk(self):
        s, photo, _ = self.add_photo(self.start(text="道路突然塌陷，影响通行"))
        s = self.observe(s, photo, observations=[{"field": "other", "state": "known", "value": "未见异常变形",
            "region": "照片范围", "limitation": "仅外观不能排除风险", "time": "current", "time_basis": "合成模拟用户确认本次拍摄"}])
        self.assertEqual(s["risk"]["status"], "attention")

    def test_unregistered_or_unknown_photo_facts_cannot_be_promoted(self):
        s, photo, _ = self.add_photo(self.start())
        s = self.observe(s, photo, observations=[{"field": "other", "state": "unknown", "value": "看不清楚",
            "region": "全图", "limitation": "合成模糊图片"}])
        fact = s["facts"][-1]
        for ref in ("invented", fact["source_ref"]):
            with self.assertRaises(RoadError):
                self.request(s, "turn", text="合成补充", facts=[{"field": "other", "kind": "photo_observation",
                    "source_ref": ref, "value": fact["value"], "state": "known"}])

    def test_new_photo_marks_opinion_stale_and_requires_new_applicability(self):
        s = self.start()
        s, receipt = self.attach_read(s)
        review = self.app.dispatch(self.review_request(s, receipt))["review"]
        s = self.app.store.read(s["id"])
        answer = self.answer_data()
        answer["claims"] = [{"text": "合成规范依据", "review_ids": [review["id"]]}]
        self.request(s, "answer", answer=answer)
        s = self.app.store.read(s["id"])
        s, _, _ = self.add_photo(s)
        summary = self.app.resume_summary(s)
        self.assertTrue(summary["latest_opinion"]["stale"])
        self.assertEqual(len(summary["photo_updates"]), 1)
        with self.assertRaises(RoadError):
            self.request(s, "answer", answer=answer)
        with self.assertRaises(RoadError):
            self.request(s, "export", user_requested=True, format="docx")

    def test_finish_cleans_photo_copy_preserves_original(self):
        s, photo, source = self.add_photo(self.start())
        before = file_hash(source)
        path = self.app.store.path(photo["relative_path"])
        self.request(s, "finish")
        self.assertFalse(path.exists())
        self.assertEqual(file_hash(source), before)

    def test_saved_photo_backup_restore_is_independent_of_original(self):
        s, photo, source = self.add_photo(self.start())
        self.request(s, "save", user_requested=True, basis="合成保存")
        destination = self.base / "backup"
        self.app.dispatch({"op": "backup", "destination": str(destination)})
        source.unlink()  # Synthetic source owned by this test.
        restored = App(self.project, destination, self.config)
        result = restored.dispatch({"op": "photo-show", "session_id": s["id"], "photo_id": photo["id"]})
        self.assertTrue(Path(result["path"]).exists())

    def test_comparison_rejects_scores_missing_conditions_and_bad_facts(self):
        for change in ("score", "conditions", "facts", "gaps", "duplicate"):
            s = self.start()
            answer = self.answer_with_delivery()
            first = answer["comparison"]["alternatives"][0]
            if change == "score": first["score"] = 90
            if change == "conditions": first.pop("conditions")
            if change == "facts": first["evidence_fact_ids"] = ["invented"]
            if change == "gaps": first["missing_evidence"] = []
            if change == "duplicate": answer["comparison"]["alternatives"][1]["label"] = first["label"]
            with self.assertRaises(RoadError):
                self.request(s, "answer", answer=answer)
            self.assertEqual(self.app.store.read(s["id"]), s)

    def test_comparison_is_preserved_in_all_delivery_formats(self):
        s = self.start()
        self.request(s, "answer", answer=self.answer_with_delivery())
        for kind in ["consultation", *DELIVERIES]:
            result = self.request(s, "export", kind=kind, user_requested=True)
            report = Path(result["markdown"]).read_text(encoding="utf-8")
            for phrase in ("处理方向比较", "调查方向甲", "证据不足", "不是施工方案批准"):
                self.assertIn(phrase, report)

    def test_word_is_explicit_and_latest_with_no_automatic_archive(self):
        s = self.start()
        with self.assertRaises(RoadError):
            self.request(s, "export", format="docx", user_requested=True)
        self.request(s, "answer", answer=self.answer_with_delivery())
        s = self.app.store.read(s["id"])
        with self.assertRaises(RoadError):
            self.request(s, "export", format="docx")
        result = self.request(s, "export", format="docx", user_requested=True)
        with ZipFile(result["docx"]) as archive:
            body = archive.read("word/document.xml").decode()
            self.assertIn("处理方向比较", body)
            self.assertIn("w:tblHeader", body)
            self.assertIn("w:cantSplit", body)
            self.assertNotIn("工具与变更记录", body)
            from lxml import etree
            styles = etree.fromstring(archive.read("word/styles.xml"))
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            self.assertEqual(styles.xpath('//w:style[@w:styleId="Title"]//w:pBdr', namespaces=ns), [])
        self.assertEqual(self.app.dispatch({"op": "sessions"}), [])
        self.assertEqual(list(Path(result["docx"]).parent.glob("*.json")), [])
        s = self.request(s, "turn", text="合成新信息")["session"]
        with self.assertRaises(RoadError):
            self.request(s, "export", format="docx", user_requested=True)

    def test_word_photos_are_opt_in_and_survive_temporary_cleanup(self):
        s, photo, source = self.add_photo(self.start())
        s = self.observe(s, photo)
        self.request(s, "answer", answer=self.answer_with_delivery())
        s = self.app.store.read(s["id"])
        for include in (False, True):
            result = self.request(s, "export", format="docx", kind="inspection_brief", user_requested=True, include_photos=include)
            with ZipFile(result["docx"]) as archive:
                images = [n for n in archive.namelist() if n.startswith("word/media/")]
                self.assertEqual(len(images), int(include))
                self.assertIn("图片观察", archive.read("word/document.xml").decode())
        self.request(s, "finish")
        self.assertTrue(Path(result["docx"]).exists())
        self.assertTrue(source.exists())

    def test_missing_word_runtime_does_not_leave_partial_exports(self):
        s = self.start()
        self.request(s, "answer", answer=self.answer_data())
        with patch.dict(self.app.config, {"document_python": str(self.base / "missing.exe")}):
            with self.assertRaises(RoadError):
                self.request(s, "export", format="docx", user_requested=True)
        self.assertFalse(self.app.store.path("exports").exists())
