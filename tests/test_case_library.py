"""Candidate case library: import, list, background search, rejection and citation gate."""
import hashlib
import json

from test_workflow import Isolated
from roadexpert.storage import RoadError


class CaseLibraryTests(Isolated):
    def case(self, **changes):
        case = {
            "case_id": "CASE-TEST-0001",
            "event_id": "EVENT-TEST-0001",
            "domain": "pavement",
            "title": "隔离合成候选案例：沉陷与排水",
            "digest": "隔离摘要：沉陷与排水线索",
            "tags": ["沉陷", "排水"],
            "source": {
                "type": "public_report",
                "url": "https://example.invalid/isolated-case",
                "publisher": "隔离测试",
                "published_at": "2026-01-01",
                "collected_at": "2026-11-05",
                "rights": "public_deidentified",
                "external_model_allowed": True,
            },
            "security_level": "public_deidentified",
            "source_grade": "S3",
            "cause_status": "reported_context_not_independently_verified",
            "treatment_status": "implemented_reported",
            "follow_up_status": "not_reported",
            "reviews": [],
            "allowed_claims": [],
        }
        case.update(changes)
        return case

    def import_case(self, **changes):
        return self.app.dispatch({"op": "case-import", "case": self.case(**changes)})

    def add_source(self, pages):
        folder = self.project / "data/cases/sources/CASE-TEST-0001"
        folder.mkdir(parents=True)
        pdf = folder / "source.pdf"
        pdf.write_bytes(b"%PDF-isolated-test")
        text = "\n\n".join(f"===== 第 {item['page']} 页 =====\n{item['text']}" for item in pages)
        (folder / "source.txt").write_bytes(text.encode("utf-8"))
        (folder / "pages.json").write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
        meta = {
            "case_id": "CASE-TEST-0001", "title": "隔离全文", "access_level": "full_text",
            "file": "source.pdf", "text_file": "source.txt", "pages": len(pages), "chars": len(text),
            "sha256_pdf": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            "sha256_text": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "rights_note": "仅隔离测试，不提交",
        }
        (folder / "source.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    def test_full_text_source_can_be_meta_read_and_searched(self):
        self.import_case()
        self.add_source([
            {"page": 1, "text": "沉陷段位于路肩，钻孔揭示土洞。"},
            {"page": 2, "text": "采用袖阀管注浆，监测沉降稳定。"},
        ])
        meta = self.app.dispatch({"op": "case-source", "case_id": "CASE-TEST-0001"})
        self.assertTrue(meta["available"])
        self.assertEqual(meta["pages"], 2)
        page = self.app.dispatch({"op": "case-source-read", "case_id": "CASE-TEST-0001", "page": 2})
        self.assertIn("袖阀管", page["text"])
        hits = self.app.dispatch({"op": "case-source-search", "case_id": "CASE-TEST-0001", "query": "土洞"})
        self.assertEqual(hits["hits"][0]["page"], 1)
        listing = self.app.dispatch({"op": "case-list"})
        self.assertTrue(listing["cases"][0]["source"]["available"])

    def test_missing_full_text_is_reported_not_invented(self):
        self.import_case()
        meta = self.app.dispatch({"op": "case-source", "case_id": "CASE-TEST-0001"})
        self.assertFalse(meta["available"])
        self.assertEqual(meta["access_level"], "abstract_only")
        with self.assertRaises(RoadError):
            self.app.dispatch({"op": "case-source-read", "case_id": "CASE-TEST-0001", "page": 1})
        with self.assertRaises(RoadError):
            self.app.dispatch({"op": "case-source-search", "case_id": "CASE-TEST-0001", "query": "沉陷"})

    def test_source_page_query_and_hash_are_checked(self):
        self.import_case()
        self.add_source([{"page": 1, "text": "沉陷段位于路肩。"}])
        for page in (0, 2):
            with self.assertRaises(RoadError):
                self.app.dispatch({"op": "case-source-read", "case_id": "CASE-TEST-0001", "page": page})
        with self.assertRaises(RoadError):
            self.app.dispatch({"op": "case-source-search", "case_id": "CASE-TEST-0001", "query": ""})
        text = self.project / "data/cases/sources/CASE-TEST-0001/source.txt"
        text.write_text("changed", encoding="utf-8")
        with self.assertRaises(RoadError):
            self.app.dispatch({"op": "case-source", "case_id": "CASE-TEST-0001"})

    def test_candidate_is_listed_and_searchable_but_not_verified(self):
        self.assertEqual(self.import_case()["status"], "pending_review")
        listing = self.app.dispatch({"op": "case-list"})
        self.assertEqual(listing["counts"]["incoming"], 1)
        self.assertEqual(listing["cases"][0]["area"], "incoming")
        self.assertEqual(listing["cases"][0]["status"], "pending_review")
        self.assertEqual(listing["cases"][0]["digest"], "隔离摘要：沉陷与排水线索")
        shown = self.app.dispatch({"op": "case-show", "case_id": "CASE-TEST-0001"})
        self.assertEqual(shown["area"], "incoming")
        self.assertEqual(shown["case"]["case_id"], "CASE-TEST-0001")
        verified = self.app.dispatch({"op": "case-search", "domain": "pavement", "tags": ["沉陷"]})["receipt"]["payload"]
        self.assertEqual(verified["status"], "no_qualified_cases")
        candidate = self.app.dispatch({"op": "case-search", "domain": "pavement",
                                       "tags": ["沉陷"], "scope": "candidate"})["receipt"]["payload"]
        self.assertEqual(candidate["status"], "candidate_matches")
        self.assertEqual(candidate["matches"][0]["evidence_status"], "unverified_candidate")
        self.assertIn("候选案例未经人工审核", candidate["notice"])

    def test_exact_tag_match_ranks_before_alias(self):
        self.import_case(case_id="CASE-TEST-EXACT", event_id="EVENT-TEST-EXACT", tags=["沉陷"])
        self.import_case(case_id="CASE-TEST-ALIAS", event_id="EVENT-TEST-ALIAS", tags=["塌陷"])
        result = self.app.dispatch({"op": "case-search", "domain": "pavement",
                                    "tags": ["沉陷"], "scope": "candidate"})["receipt"]["payload"]
        self.assertEqual([m["case_id"] for m in result["matches"]],
                         ["CASE-TEST-EXACT", "CASE-TEST-ALIAS"])

    def test_candidate_cannot_be_used_in_answer(self):
        self.import_case()
        session = self.start()
        found = self.request(session, "case-search", domain="pavement", tags=["沉陷"], scope="candidate")
        session = self.app.store.read(session["id"])
        answer = self.answer_data()
        answer["case_refs"] = [{
            "query_receipt_id": found["receipt"]["id"], "case_id": "CASE-TEST-0001",
            "similarities": "同为沉陷", "differences": "条件不同", "borrow_scope": "仅借鉴调查顺序",
        }]
        with self.assertRaises(RoadError):
            self.request(session, "answer", answer=answer)

    def test_reject_removes_candidate_and_keeps_reason(self):
        self.import_case()
        result = self.app.dispatch({"op": "case-reject", "case_id": "CASE-TEST-0001",
                                    "reason": "隔离测试拒绝"})
        self.assertEqual(result["status"], "rejected")
        rejected = self.app.dispatch({"op": "case-list", "area": "rejected"})
        self.assertEqual(rejected["counts"]["rejected"], 1)
        self.assertEqual(rejected["cases"][0]["status"], "rejected")
        incoming = self.app.dispatch({"op": "case-list", "area": "incoming"})
        self.assertEqual(incoming["counts"]["incoming"], 0)
        candidate = self.app.dispatch({"op": "case-search", "domain": "pavement",
                                       "tags": ["沉陷"], "scope": "candidate"})["receipt"]["payload"]
        self.assertEqual(candidate["status"], "no_qualified_cases")

    def test_invalid_scope_area_and_rejection_reason_are_rejected(self):
        self.import_case()
        with self.assertRaises(RoadError):
            self.app.dispatch({"op": "case-search", "domain": "pavement", "tags": ["沉陷"], "scope": "unknown"})
        with self.assertRaises(RoadError):
            self.app.dispatch({"op": "case-list", "area": "elsewhere"})
        with self.assertRaises(RoadError):
            self.app.dispatch({"op": "case-show", "case_id": "CASE-NOT-FOUND"})
        with self.assertRaises(RoadError):
            self.app.dispatch({"op": "case-reject", "case_id": "CASE-TEST-0001", "reason": ""})
