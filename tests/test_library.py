"""Local source library: PDF ingestion, page read/search/render and integrity checks."""
from pathlib import Path

import fitz

from test_workflow import Isolated
from roadexpert.storage import RoadError


class LibraryTests(Isolated):
    def make_pdf(self, texts):
        path = self.base / "library-source.pdf"
        document = fitz.open()
        for text in texts:
            page = document.new_page()
            page.insert_text((72, 72), text)
        document.save(path)
        document.close()
        return path

    def add(self, path=None, **changes):
        path = path or self.make_pdf(["subgrade settlement and drainage", "grouting monitoring"])
        request = {
            "op": "library-add", "path": str(path), "type": "paper",
            "title": "Isolated library source", "authors": "test", "year": "2026",
            "publisher": "isolated", "domain": ["pavement"], "topics": ["沉陷"],
            "language": "en", "rights_basis": "隔离测试资料，仅本地", "library_id": "LIB-TEST-0001",
        }
        request.update(changes)
        return self.app.dispatch(request)

    def test_add_list_source_read_search_and_render(self):
        added = self.add()
        self.assertEqual(added["status"], "added")
        listing = self.app.dispatch({"op": "library-list"})
        self.assertEqual(listing["counts"]["paper"], 1)
        source = self.app.dispatch({"op": "library-source", "library_id": "LIB-TEST-0001"})
        self.assertEqual(source["pages"], 2)
        page = self.app.dispatch({"op": "library-read", "library_id": "LIB-TEST-0001", "page": 1})
        self.assertIn("settlement", page["text"])
        self.assertEqual(page["printed_page"], 1)
        hits = self.app.dispatch({"op": "library-search", "query": "grouting"})
        self.assertEqual(hits["status"], "matched")
        self.assertEqual(hits["hits"][0]["page"], 2)
        rendered = self.app.dispatch({"op": "library-render", "library_id": "LIB-TEST-0001", "page": 1})
        self.assertTrue(Path(rendered["path"]).is_file())
        self.assertEqual(self.app.dispatch({"op": "library-toc", "library_id": "LIB-TEST-0001"})["toc"], [])

    def test_invalid_add_type_path_duplicate_and_basis_are_rejected(self):
        with self.assertRaises(RoadError):
            self.add(rights_basis="")
        with self.assertRaises(RoadError):
            self.add(type="video")
        with self.assertRaises(RoadError):
            self.add(path=self.base / "missing.pdf")
        self.add()
        with self.assertRaises(RoadError):
            self.add()

    def test_page_bounds_missing_source_and_search_filters(self):
        self.add()
        with self.assertRaises(RoadError):
            self.app.dispatch({"op": "library-read", "library_id": "LIB-TEST-0001", "page": 3})
        with self.assertRaises(RoadError):
            self.app.dispatch({"op": "library-source", "library_id": "LIB-MISSING"})
        self.assertEqual(self.app.dispatch({"op": "library-search", "query": "not-present"})["status"], "no_match")
        self.assertEqual(self.app.dispatch({"op": "library-search", "query": "grouting", "type": "textbook"})["hits"], [])

    def test_changed_text_or_pdf_is_detected(self):
        self.add()
        folder = self.project / "data/library/LIB-TEST-0001"
        (folder / "source.txt").write_bytes(b"changed")
        with self.assertRaises(RoadError):
            self.app.dispatch({"op": "library-read", "library_id": "LIB-TEST-0001", "page": 1})
        with self.assertRaises(RoadError):
            self.app.dispatch({"op": "library-render", "library_id": "LIB-TEST-0001", "page": 1})

    def test_rebuild_recovers_index(self):
        self.add()
        (self.project / "data/library/index.json").write_text('{"schema_version":1,"sources":[]}',
                                                             encoding="utf-8")
        result = self.app.dispatch({"op": "library-rebuild"})
        self.assertEqual(result["count"], 1)
        self.assertEqual(self.app.dispatch({"op": "library-list"})["counts"]["paper"], 1)
