"""Allowlisted adapter. Never calls maintenance or the upstream image-writing command."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from .storage import RoadError, digest, inside, load_json


def file_hash(path):
    import hashlib
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class Specs:
    def __init__(self, skill, store, timeout=45):
        self.skill = Path(skill).resolve()
        self.store = store
        self.timeout = max(1, min(120, int(timeout)))
        cfg = load_json(self.skill / "config.json")
        self.library = Path(cfg["library_dir"]).resolve()
        self.data = Path(cfg["data_dir"]).resolve()

    def shelf(self):
        value = load_json(self.data / "bookshelf.json")
        if not isinstance(value.get("books"), list):
            raise RoadError("规范书架损坏")
        return value["books"]

    def books(self, query=""):
        query = query.casefold().replace(" ", "")
        rows = [b for b in self.shelf() if query in
                " ".join(str(b.get(k, "")) for k in ("id", "title", "std_no", "alias")).casefold().replace(" ", "")]
        return {"status": "ok", "total": len(rows),
                "books": [{k: b.get(k) for k in ("id", "title", "std_no", "version", "pages", "type", "fmt", "status", "replaced_by")}
                          for b in rows[:100]], "truncated": len(rows) > 100}

    def book(self, book_id):
        rows = [b for b in self.shelf() if b["id"] == book_id]
        if len(rows) != 1:
            raise RoadError("必须使用 spec-list 返回的准确 book_id")
        b = rows[0]
        # Mirror upstream nested index layout, but reject directory traversal/symlinks.
        directory = inside(self.data, Path(b["file"]).parent / b["id"])
        source = inside(self.library, b["file"])
        meta = load_json(directory / "meta.json")
        if meta.get("status") == "indexing" or meta.get("derivatives_dirty"):
            raise RoadError("规范正维护或派生数据失效，不能静默使用")
        recorded_source = meta.get("source_abs") or meta.get("pdf_abs")
        if recorded_source and Path(recorded_source).exists() and Path(recorded_source).resolve() != source:
            raise RoadError("元数据指向不同源文件，拒绝将另一原文与本源指纹混合")
        return b, directory, source, meta

    def _run(self, args):
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        # Pin explicitly configured upstream config; do not let ambient GFC vars reroute.
        for key in ("GFC_LIBRARY_DIR", "GFC_DATA_DIR", "GFC_TESSERACT_CMD"):
            env.pop(key, None)
        try:
            run = subprocess.run([sys.executable, "-X", "utf8", str(self.skill / "scripts/spec.py"),
                                  "--config", str(self.skill / "config.json"), *args],
                                 cwd=self.store.root, env=env, capture_output=True, encoding="utf-8",
                                 timeout=self.timeout, shell=False)
        except subprocess.TimeoutExpired:
            return {"status": "tool_timeout", "complete": False, "error": "工具超时；未自动重试"}
        except OSError as exc:
            return {"status": "tool_error", "complete": False, "error": str(exc)}
        if run.returncode:
            return {"status": "tool_error", "complete": False,
                    "error": (run.stderr or run.stdout)[-6000:], "returncode": run.returncode}
        if len(run.stdout) > 2_000_000:
            return {"status": "output_limit", "complete": False, "error": "工具输出超过上限；请缩小范围"}
        return {"status": "ok", "output": run.stdout, "complete": True}

    def search(self, query, book_id=None, limit=20):
        if not isinstance(query, str) or not 1 <= len(query) <= 300:
            raise RoadError("查询词长度须为 1～300")
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise RoadError("limit 须为 1～100")
        if book_id:
            self.book(book_id)
        # Literal terms only: no attacker-selected catastrophic regex.
        args = ["grep"] + ([book_id] if book_id else ["--all"])
        # Upstream argparse cannot intermix its optional book and pattern after "--".
        # re.escape also escapes leading "-", so the literal pattern cannot become an option.
        args += [re.escape(query), "--json", "--max", str(limit), "--ctx", "1"]
        result = self._run(args)
        if result["status"] != "ok":
            return result
        try:
            data = __import__("json").loads(result["output"])
        except ValueError:
            return {"status": "tool_error", "complete": False, "error": "规范工具未返回有效 JSON"}
        complete = data.get("complete") is True and not data.get("truncated") and not data.get("unavailable_books")
        status = "matched" if data.get("matches") else "not_found_in_scope"
        if not complete:
            status = "search_incomplete"
        return {"status": status, "complete": complete, "scope": book_id or "all-indexed-books",
                "query": query, "data": data, "evidence_status": "navigation_only"}

    def navigate(self, action, book_id, clause=None):
        self.book(book_id)
        if action not in {"toc", "clause"}:
            raise RoadError("只允许 toc 或 clause")
        args = [action, book_id]
        if action == "clause":
            if not isinstance(clause, str) or not re.fullmatch(r"[0-9A-Za-z.第条一二三四五六七八九十百零〇 -]{1,40}", clause):
                raise RoadError("条文号格式无效")
            args.append(clause)
        return self._run(args)

    def read(self, book_id, page):
        b, folder, source, meta = self.book(book_id)
        if type(page) is not int or not 1 <= page <= b["pages"]:
            raise RoadError("页码超界")
        before = file_hash(source)
        result = self._run(["read", book_id, str(page)])
        if result["status"] != "ok":
            return result
        if before != file_hash(source):
            raise RoadError("读取期间源文件变化，请重新读取")
        expected = meta.get("source_sha256") or b.get("source_sha256")
        matched = before == expected if expected else False
        raw = result["output"]
        needs_visual = ("【OCR】" in raw or "[表格页提示]" in raw or "[警告]" in raw
                        or meta.get("cache_source_verified") is False)
        return {"status": "page_read", "book_id": b["id"], "title": b["title"],
                "std_no": b.get("std_no"), "version": b.get("version"), "page": page,
                "source_path": str(source), "source_sha256": before, "index_source_matches": matched,
                "replaced_by": b.get("replaced_by"), "virtual": bool(meta.get("virtual")),
                "needs_visual": needs_visual, "raw_text": raw,
                "evidence_status": "source_read_pending_applicability",
                "notice": "原页已读取，不代表相关条文、说明、例外和适用性已全部核验"}

    def render(self, receipt_id):
        item = self.store.get_receipt(receipt_id)
        data = item["payload"]
        if item["kind"] != "spec-read" or data.get("status") != "page_read":
            raise RoadError("渲染必须引用成功回源的证据记录")
        b, _, source, _ = self.book(data["book_id"])
        if b.get("fmt", "pdf") != "pdf":
            raise RoadError("此版本仅渲染 PDF；其他格式请人工回源")
        if file_hash(source) != data["source_sha256"]:
            raise RoadError("源文件变化，旧回源记录不能用于当前渲染")
        import fitz
        target = self.store.path(f"images/{item['id']}-p{data['page']}.png")
        target.parent.mkdir(parents=True, exist_ok=True)
        with fitz.open(source) as doc:
            doc[data["page"] - 1].get_pixmap(dpi=160).save(str(target))
        return {"status": "rendered_not_reviewed", "read_receipt_id": receipt_id,
                "relative_path": target.relative_to(self.store.root).as_posix(),
                "path": str(target), "sha256": file_hash(target),
                "notice": "渲染不等于已看图；需记录实际查看者、核对内容及限制"}
