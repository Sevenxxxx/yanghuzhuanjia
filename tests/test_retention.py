"""Retention tests use only isolated synthetic records."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from test_workflow import Isolated
from roadexpert.service import App
from roadexpert.storage import RoadError, atomic_json, canonical, digest


class RetentionTests(Isolated):
    def save(self, s):
        self.request(s, "save", user_requested=True, basis="合成用户明确要求保存")
        return self.app.store.read(s["id"])

    def age(self, s):
        # Modify an isolated fixture with a valid envelope, never production data.
        s["expires_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        atomic_json(self.app.store.path(f"sessions/{s['id']}/{s['revision']:06}.json"),
                    {"data": s, "sha256": digest(canonical(s))})

    def test_default_is_temporary_and_hidden_but_multiturn_works(self):
        s = self.start()
        self.assertEqual(s["retention"], "temporary")
        self.assertIn("expires_at", s)
        self.assertEqual(self.app.dispatch({"op": "sessions"}), [])
        s = self.request(s, "turn", text="这是后续合成补充")["session"]
        self.assertEqual(len(self.app.dispatch({"op": "resume", "session_id": s["id"]})["session"]["turns"]), 2)
        with self.assertRaises(RoadError):
            self.start(retention="saved")

    def test_save_requires_explicit_request_and_survives_expiry(self):
        s = self.start()
        with self.assertRaises(RoadError):
            self.request(s, "save", basis="模型自行决定")
        saved = self.save(s)
        self.assertNotIn("expires_at", saved)
        self.assertEqual(self.app.dispatch({"op": "sessions"})[0]["id"], s["id"])
        result = self.request(saved, "finish")
        self.assertEqual(result["status"], "saved_consultation_retained")
        self.assertEqual(self.app.store.read(saved["id"])["retention"], "saved")

    def test_expiry_removes_state_receipt_and_image_but_not_other_session(self):
        s = self.start()
        image = self.app.store.path("images/temporary.png")
        image.parent.mkdir()
        image.write_bytes(b"synthetic image")
        rec = self.app.store.receipt("spec-render", {"relative_path": "images/temporary.png", "path": str(image)})
        s["evidence_ids"].append(rec["id"])
        s = self.app.store.write(s, s["revision"])
        saved = self.save(self.start())
        self.age(s)
        result = self.app.dispatch({"op": "cleanup"})
        self.assertEqual(result["removed_sessions"], 1)
        self.assertFalse(image.exists())
        self.assertFalse(self.app.store.path(f"receipts/{rec['id']}.json").exists())
        with self.assertRaises(RoadError):
            self.app.store.read(s["id"])
        self.assertEqual(self.app.store.read(saved["id"]), saved)

    def test_finish_preserves_shared_receipt_and_explicit_export(self):
        s = self.start()
        rec = self.app.store.receipt("spec-read", {"status": "synthetic"})
        s["evidence_ids"].append(rec["id"])
        s = self.app.store.write(s, s["revision"])
        other = self.start()
        other["evidence_ids"].append(rec["id"])
        other = self.app.store.write(other, other["revision"])
        exported = self.request(s, "export", user_requested=True, history_only=True)
        self.request(s, "finish")
        self.assertTrue(Path(exported["markdown"]).exists())
        self.assertTrue(self.app.store.path(f"receipts/{rec['id']}.json").exists())
        self.request(other, "finish")
        self.assertFalse(self.app.store.path(f"receipts/{rec['id']}.json").exists())

    def test_backup_contains_only_saved_session_and_its_evidence(self):
        saved = self.save(self.start())
        temp = self.start()
        rec = self.app.store.receipt("spec-read", {"private_temp": "synthetic only"})
        temp["evidence_ids"].append(rec["id"])
        self.app.store.write(temp, temp["revision"])
        dest = self.base / "selected-backup"
        self.app.dispatch({"op": "backup", "destination": str(dest)})
        restored = App(self.project, dest, self.config)
        self.assertEqual([x["id"] for x in restored.store.list_sessions()], [saved["id"]])
        self.assertFalse(restored.store.path(f"receipts/{rec['id']}.json").exists())
        self.assertEqual(restored.dispatch({"op": "backup-verify"})["status"], "backup_verified")

    def test_no_automatic_export_or_backup_of_temporary_data(self):
        s = self.start()
        with self.assertRaises(RoadError):
            self.request(s, "export")
        with self.assertRaises(RoadError):
            self.app.dispatch({"op": "backup", "destination": str(self.base / "backup")})
        self.assertFalse(self.app.store.path(f"exports/{s['id']}").exists())

    def test_locked_and_saved_legacy_records_are_not_expired(self):
        s = self.start()
        self.age(s)
        with self.app.store.lock(s["id"]):
            self.assertTrue(self.app.dispatch({"op": "cleanup"})["skipped_locked"])
            self.assertEqual(self.app.store.read(s["id"])["id"], s["id"])
        self.app.dispatch({"op": "cleanup"})
        legacy = self.start()
        legacy.pop("retention")
        legacy = self.app.store.write(legacy, legacy["revision"])
        self.app.dispatch({"op": "cleanup"})
        self.assertEqual(self.app.dispatch({"op": "sessions"})[0]["id"], legacy["id"])

    def test_finish_requires_current_revision_and_never_deletes_source_path(self):
        s = self.start()
        with self.assertRaises(RoadError):
            self.app.dispatch({"op": "finish", "session_id": s["id"]})
        source = self.base / "original.pdf"
        source.write_bytes(b"original source fixture")
        rec = self.app.store.receipt("spec-read", {"source_path": str(source)})
        s["evidence_ids"].append(rec["id"])
        s = self.app.store.write(s, s["revision"])
        self.request(s, "finish")
        self.assertEqual(source.read_bytes(), b"original source fixture")
