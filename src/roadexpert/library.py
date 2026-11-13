"""Local source library: PDFs plus page text, literal search and page rendering.

Standards stay in guifanchaxun. This library holds textbooks, papers and case
source documents in a local, gitignored folder; it is a reading aid, not an
engineering approval or a reviewed case record.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path

from .storage import RoadError, atomic_json, digest, inside, load_json, now, safe_id

TYPES = {"textbook", "paper", "case_source", "report", "other"}


def _sha256(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


class Library:
    def __init__(self, root, store):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.store = store
        if not self._index_path().is_file():
            atomic_json(self._index_path(), {"schema_version": 1, "sources": []})

    def _index_path(self):
        return self.root / "index.json"

    def _index(self):
        data = load_json(self._index_path())
        if data.get("schema_version") != 1 or not isinstance(data.get("sources"), list):
            raise RoadError("资料库索引损坏")
        return data

    def _save(self, data):
        atomic_json(self._index_path(), data)

    def _folder(self, library_id):
        return inside(self.root, safe_id(library_id))

    def _text(self, value, name, maximum):
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise RoadError(f"{name} 须为非空文本且不超过 {maximum} 字符")
        return value.strip()

    def _strings(self, value, name):
        if value is None:
            return []
        if not isinstance(value, list) or not all(isinstance(x, str) and x.strip() for x in value):
            raise RoadError(f"{name} 须为字符串数组")
        return [x.strip() for x in value]

    def _row(self, library_id):
        safe_id(library_id)
        rows = [row for row in self._index()["sources"] if row.get("library_id") == library_id]
        if len(rows) != 1:
            raise RoadError("未找到资料")
        return rows[0]

    def add(self, req):
        if not isinstance(req, dict):
            raise RoadError("library-add 须为对象")
        source_path = Path(self._text(req.get("path"), "path", 2000))
        if (not source_path.is_absolute() or str(source_path).startswith("\\\\")
                or not source_path.is_file()):
            raise RoadError("资料须为已获准的本机绝对路径文件")
        if source_path.suffix.lower() != ".pdf":
            raise RoadError("当前资料库只接收 PDF；其他格式先人工处理")
        if source_path.stat().st_size > 100 * 1024 * 1024:
            raise RoadError("单个资料不得超过 100MB")
        kind = req.get("type")
        if kind not in TYPES:
            raise RoadError("资料 type 只允许 textbook、paper、case_source、report、other")
        title = self._text(req.get("title"), "title", 300)
        library_id = req.get("library_id") or f"{kind}-{uuid.uuid4().hex[:10]}"
        safe_id(library_id)
        index = self._index()
        if self._folder(library_id).exists() or any(row.get("library_id") == library_id for row in index["sources"]):
            raise RoadError("资料编号已存在，不能覆盖")
        offset = req.get("printed_page_offset", 0)
        if type(offset) is not int or not -1000 <= offset <= 1000:
            raise RoadError("printed_page_offset 须为 -1000～1000 的整数")
        try:
            import fitz
        except ImportError as exc:
            raise RoadError("资料解析需要本机 PyMuPDF；不会自动安装") from exc
        try:
            with fitz.open(source_path) as document:
                pages = [{"page": number + 1, "text": page.get_text()}
                         for number, page in enumerate(document)]
        except Exception as exc:  # noqa: BLE001 - upstream parser failure
            raise RoadError("PDF 无法解析或已加密") from exc
        if not pages:
            raise RoadError("PDF 没有可读取页面")
        folder = self._folder(library_id)
        folder.mkdir(parents=True)
        try:
            pdf = folder / "source.pdf"
            shutil.copy2(source_path, pdf)
            text = "\n\n".join(f"===== 第 {item['page']} 页 =====\n{item['text']}" for item in pages)
            (folder / "source.txt").write_bytes(text.encode("utf-8"))
            (folder / "pages.json").write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
            needs_visual = [item["page"] for item in pages if len(item["text"].strip()) < 20]
            manifest = {
                "schema_version": 1,
                "library_id": library_id,
                "type": kind,
                "title": title,
                "authors": self._text(req.get("authors", "未注明"), "authors", 500),
                "year": self._text(req.get("year", "未注明"), "year", 20),
                "publisher": self._text(req.get("publisher", "未注明"), "publisher", 300),
                "source_url": req.get("source_url", ""),
                "doi": req.get("doi", ""),
                "domain": self._strings(req.get("domain"), "domain"),
                "topics": self._strings(req.get("topics"), "topics"),
                "language": self._text(req.get("language", "zh"), "language", 20),
                "access_level": "full_text",
                "pages": len(pages),
                "printed_page_offset": offset,
                "chars": len(text),
                "text_chars": sum(len(item["text"].strip()) for item in pages),
                "needs_visual_pages": needs_visual,
                "sha256_pdf": _sha256(pdf),
                "sha256_text": digest(text.encode("utf-8")),
                "added_at": now(),
                "rights_basis": self._text(req.get("rights_basis"), "rights_basis", 1000),
                "rights_note": self._text(req.get("rights_note", "仅本地研究与核对；不提交或再分发"),
                                          "rights_note", 1000),
                "original_filename": source_path.name,
            }
            (folder / "source.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                                                encoding="utf-8")
            index["sources"].append({key: manifest[key] for key in (
                "library_id", "type", "title", "authors", "year", "publisher", "domain", "topics",
                "language", "access_level", "pages", "printed_page_offset", "needs_visual_pages",
                "sha256_pdf", "sha256_text", "added_at", "source_url", "doi")})
            self._save(index)
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        return {"status": "added", "source": self.source(library_id),
                "notice": "资料已复制到本地库；原文不等于已审核结论，也不替代规范回源"}

    def list(self, kind=None, topic=None, domain=None):
        if kind is not None and kind not in TYPES:
            raise RoadError("资料 type 无效")
        rows = []
        for row in self._index()["sources"]:
            if kind is not None and row.get("type") != kind:
                continue
            if topic is not None and topic not in row.get("topics", []):
                continue
            if domain is not None and domain not in row.get("domain", []):
                continue
            rows.append(row)
        rows.sort(key=lambda item: (item.get("type", ""), item.get("library_id", "")))
        return {"status": "listed", "counts": {name: sum(1 for row in rows if row["type"] == name)
                                              for name in sorted(TYPES)},
                "sources": rows}

    def source(self, library_id):
        row = self._row(library_id)
        folder = self._folder(library_id)
        manifest = load_json(folder / "source.json")
        if manifest.get("library_id") != library_id:
            raise RoadError("资料元数据与编号不一致")
        return {**manifest, "relative_folder": folder.relative_to(self.root).as_posix(),
                "notice": "原文仅供本地检索和核对；引用须标来源、页码和适用性"}

    def _pages(self, library_id):
        folder = self._folder(library_id)
        manifest = load_json(folder / "source.json")
        pages = load_json(folder / "pages.json")
        if not isinstance(pages, list) or not pages:
            raise RoadError("资料分页文本缺失")
        text_path = folder / "source.txt"
        if not text_path.is_file() or digest(text_path.read_bytes()) != manifest.get("sha256_text"):
            raise RoadError("资料文本已变化或缺失")
        return folder, manifest, pages

    def toc(self, library_id):
        folder, manifest, _ = self._pages(library_id)
        pdf = folder / "source.pdf"
        if not pdf.is_file() or _sha256(pdf) != manifest.get("sha256_pdf"):
            raise RoadError("资料 PDF 已变化或缺失")
        try:
            import fitz
        except ImportError as exc:
            raise RoadError("读取目录需要本机 PyMuPDF") from exc
        with fitz.open(pdf) as document:
            rows = [{"level": level, "title": title, "page": page}
                    for level, title, page in document.get_toc(simple=True)]
        return {"library_id": library_id, "toc": rows,
                "notice": "目录页码为 PDF 页；没有书签时请按页读取或使用主题检索"}

    def read(self, library_id, page):
        _, manifest, pages = self._pages(library_id)
        if type(page) is not int or not 1 <= page <= len(pages):
            raise RoadError("页码超界")
        content = pages[page - 1].get("text", "")
        return {"library_id": library_id, "page": page, "pages": len(pages),
                "printed_page": page + int(manifest.get("printed_page_offset", 0)),
                "text": content[:16000], "truncated": len(content) > 16000,
                "needs_visual": page in manifest.get("needs_visual_pages", []),
                "notice": "本页文本供定位；表格、公式和扫描页仍须实际查看"}

    def search(self, query, kind=None, topic=None, limit=5):
        if not isinstance(query, str) or not 1 <= len(query) <= 100:
            raise RoadError("检索词长度须为 1～100")
        if type(limit) is not int or not 1 <= limit <= 20:
            raise RoadError("检索 limit 须为 1～20")
        if kind is not None and kind not in TYPES:
            raise RoadError("资料 type 无效")
        groups = []
        scanned = 0
        needle = query.casefold()
        for row in self._index()["sources"]:
            if kind is not None and row.get("type") != kind:
                continue
            if topic is not None and topic not in row.get("topics", []):
                continue
            scanned += 1
            try:
                _, manifest, pages = self._pages(row["library_id"])
            except RoadError:
                continue
            source_hits, count = [], 0
            for item in pages:
                text = item.get("text", "")
                position = text.casefold().find(needle)
                while position != -1:
                    count += 1
                    if len(source_hits) < 2:
                        start = max(0, position - 100)
                        end = min(len(text), position + len(query) + 100)
                        source_hits.append({"library_id": row["library_id"], "title": manifest.get("title"),
                                            "type": manifest.get("type"), "page": item.get("page"),
                                            "printed_page": item.get("page", 0) +
                                            int(manifest.get("printed_page_offset", 0)),
                                            "excerpt": text[start:end]})
                    position = text.casefold().find(needle, position + len(query))
            if source_hits:
                title_match = 1 if needle in str(row.get("title", "")).casefold() else 0
                groups.append((title_match, count, row.get("library_id", ""), source_hits))
        groups.sort(key=lambda item: (-item[0], -item[1], item[2]))
        hits = []
        for _, _, _, source_hits in groups:
            hits.extend(source_hits)
            if len(hits) >= limit:
                break
        hits = hits[:limit]
        total = sum(item[1] for item in groups)
        return {"status": "matched" if hits else "no_match", "query": query, "hits": hits,
                "truncated": total > len(hits), "scanned_sources": scanned,
                "notice": "命中仅表示字面出现；须读原文、核对页码和适用性"}

    def render(self, library_id, page):
        folder, manifest, pages = self._pages(library_id)
        if type(page) is not int or not 1 <= page <= len(pages):
            raise RoadError("页码超界")
        pdf = folder / "source.pdf"
        if not pdf.is_file() or _sha256(pdf) != manifest.get("sha256_pdf"):
            raise RoadError("资料 PDF 已变化或缺失")
        try:
            import fitz
        except ImportError as exc:
            raise RoadError("渲染需要本机 PyMuPDF") from exc
        target = self.store.path(f"images/library-{safe_id(library_id)}-p{page}.png")
        target.parent.mkdir(parents=True, exist_ok=True)
        with fitz.open(pdf) as document:
            document[page - 1].get_pixmap(dpi=160).save(str(target))
        return {"library_id": library_id, "page": page, "path": str(target),
                "sha256": _sha256(target),
                "notice": "渲染不等于已看图；表格、公式和扫描页须记录实际查看者和范围"}

    def rebuild(self):
        rows, excluded = [], []
        for folder in sorted(self.root.glob("*/source.json")):
            try:
                manifest = load_json(folder)
                library_id = manifest.get("library_id")
                safe_id(library_id)
                if folder.parent.name != library_id:
                    raise RoadError("目录与资料编号不一致")
                _, verified, _ = self._pages(library_id)
                pdf = folder.parent / "source.pdf"
                if not pdf.is_file() or _sha256(pdf) != verified.get("sha256_pdf"):
                    raise RoadError("资料 PDF 已变化或缺失")
                rows.append({key: verified[key] for key in (
                    "library_id", "type", "title", "authors", "year", "publisher", "domain", "topics",
                    "language", "access_level", "pages", "printed_page_offset", "needs_visual_pages",
                    "sha256_pdf", "sha256_text", "added_at", "source_url", "doi")})
            except (RoadError, KeyError, TypeError) as exc:
                excluded.append({"folder": folder.parent.name, "reason": str(exc)})
        self._save({"schema_version": 1, "sources": rows})
        return {"status": "rebuilt", "count": len(rows), "excluded": excluded}
