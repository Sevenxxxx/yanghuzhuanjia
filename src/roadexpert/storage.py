"""Versioned local records outside the repository, with integrity and write locks."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path


class RoadError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


TEMPORARY_HOURS = 24


def is_saved(data):
    # Pre-0.1.2 records were permanent. Never expire legacy archives implicitly.
    return data.get("retention", "saved") == "saved"


def digest(data: bytes):
    return hashlib.sha256(data).hexdigest()


def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise RoadError(f"无法读取 JSON {path}: {exc}") from exc


def atomic_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(canonical(obj) + b"\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value):
        raise RoadError("标识只能含字母、数字、下划线或短横线，最长 80 字符")
    return value


def inside(root, relative):
    root = Path(root).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise RoadError("路径超出允许目录")
    return target


def local_store_path(root, relative):
    """Keep the Windows merged view; permit only its verified LocalCache alias.

    Do not use this for the standards library. Resolving a merged directory to
    its package cache hides records that exist only in the ordinary directory.
    """
    root = Path(root)
    relative = Path(relative)
    if relative.is_absolute() or relative.drive or ".." in relative.parts:
        raise RoadError("路径超出允许目录")
    logical = root / relative
    cursor = root
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink() or (hasattr(cursor, "is_junction") and cursor.is_junction()):
            raise RoadError("存储子路径不能通过符号链接或目录联接跳转")
    resolved = logical.resolve()
    if resolved.is_relative_to(root):
        return logical
    # MSIX can redirect individual children without redirecting the root.
    # Require the exact Local -> Packages/<family>/LocalCache/Local mapping,
    # matching file identity, and no reparse points in the mapped path.
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    if os.name == "nt" and local.is_absolute() and root.is_relative_to(local / "RoadMaintenanceExpert"):
        suffix = logical.relative_to(local)
        try:
            mapped = resolved.relative_to(local / "Packages")
        except ValueError:
            mapped = Path()
        parts = mapped.parts
        if (len(parts) >= 4 and parts[1:3] == ("LocalCache", "Local")
                and Path(*parts[3:]) == suffix):
            cursor = local / "Packages"
            for part in parts:
                cursor /= part
                if cursor.is_symlink() or cursor.is_junction():
                    raise RoadError("应用缓存映射含路径跳转")
            # For a not-yet-created leaf compare its closest existing ancestor.
            left, right = logical, resolved
            while not left.exists() and left != root:
                left, right = left.parent, right.parent
            if left.exists() and right.exists() and left.samefile(right):
                return logical
    raise RoadError("路径超出允许目录")


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        if str(self.root).startswith("\\\\"):
            raise RoadError("此个人版仅使用本地存储，不自动连接网络共享")
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, relative):
        return local_store_path(self.root, relative)

    @contextmanager
    def lock(self, name):
        path = self.path(f"locks/{safe_id(name)}.lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise RoadError(f"记录正被写入或有未处理锁：{path}；先确认无活跃进程，不自动夺锁") from exc
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                out.write(json.dumps({"pid": os.getpid(), "time": now()}))
            yield
        finally:
            path.unlink(missing_ok=True)

    def _folder(self, session_id):
        return self.path(f"sessions/{safe_id(session_id)}")

    def read(self, session_id, revision=None):
        folder = self._folder(session_id)
        files = sorted(folder.glob("[0-9]" * 6 + ".json"))
        if not files:
            raise RoadError("未找到咨询记录")
        filename = files[-1].name if revision is None else f"{int(revision):06}.json"
        path = self.path(f"sessions/{safe_id(session_id)}/{filename}")
        envelope = load_json(path)
        data = envelope.get("data")
        if not isinstance(data, dict) or digest(canonical(data)) != envelope.get("sha256"):
            raise RoadError("咨询记录完整性检查失败，保留原件并从已验证备份恢复")
        if data.get("id") != session_id or data.get("revision") != int(path.stem):
            raise RoadError("咨询标识或修订号不匹配")
        return data

    def create(self, data):
        session_id = uuid.uuid4().hex
        data = copy.deepcopy(data)
        data.update(id=session_id, revision=0, created_at=now())
        return self.write(data, expected=0)

    def write(self, data, expected):
        data = copy.deepcopy(data)
        folder = self._folder(data["id"])
        with self.lock(data["id"]):
            files = sorted(folder.glob("[0-9]" * 6 + ".json"))
            actual = self.read(data["id"])["revision"] if files else 0
            if actual != expected:
                raise RoadError(f"咨询已变化：当前 {actual}，请求基于 {expected}；请恢复最新版本")
            if actual >= 999999:
                raise RoadError("修订数超过本版本上限")
            data.update(revision=actual + 1, updated_at=now())
            if not is_saved(data):
                data["expires_at"] = (datetime.fromisoformat(data["updated_at"]) + timedelta(hours=TEMPORARY_HOURS)).isoformat()
            else:
                data.pop("expires_at", None)
            atomic_json(folder / f"{actual + 1:06}.json", {
                "data": data, "sha256": digest(canonical(data))
            })
        return data

    def receipt(self, kind, payload):
        item = {"id": uuid.uuid4().hex, "kind": kind, "created_at": now(), "payload": payload}
        item["sha256"] = digest(canonical(payload))
        atomic_json(self.path(f"receipts/{item['id']}.json"), item)
        return item

    def get_receipt(self, receipt_id):
        item = load_json(self.path(f"receipts/{safe_id(receipt_id)}.json"))
        if item.get("id") != receipt_id or item.get("sha256") != digest(canonical(item.get("payload"))):
            raise RoadError("工具证据记录损坏")
        return item

    def list_sessions(self):
        out = []
        for folder in sorted(self.path("sessions").glob("*")):
            if folder.is_dir():
                data = self.read(folder.name)
                out.append({**{k: data.get(k) for k in ("id", "title", "revision", "updated_at", "privacy")},
                            "retention": data.get("retention", "saved")})
        return out

    def remove_local(self, relative):
        """Delete only a validated child of this store; no links or source paths."""
        relative = Path(relative)
        if not relative.parts or relative == Path("."):
            raise RoadError("不能删除存储根目录")
        target = self.path(relative)
        # Validate every resolved descendant before a recursive removal. path()
        # permits only this root or its verified Windows package-cache mapping.
        if target.is_dir():
            for child in target.rglob("*"):
                self.path(child.relative_to(self.root))
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        if target.exists():
            raise RoadError("清理未完成，仍有残留路径")

    def discard_temporary(self, session_id, expected=None, expired_only=False):
        with self.lock(session_id):
            data = self.read(session_id)
            if is_saved(data):
                if expired_only:
                    return False
                raise RoadError("已保存咨询不能用临时清理删除")
            if expected is not None and data["revision"] != expected:
                raise RoadError("咨询已更新，请读取最新状态后结束")
            if expired_only and datetime.fromisoformat(data["expires_at"]) > datetime.now(timezone.utc):
                return False
            # Evidence may be shared. Remove only receipts no other session uses.
            used = set()
            for row in self.list_sessions():
                if row["id"] != session_id:
                    used.update(self.read(row["id"])["evidence_ids"])
            disposable = set(data["evidence_ids"]) - used
            protected_images = self.receipt_images(used)
            images = []
            for rid in disposable:
                item = self.get_receipt(rid)
                if item["kind"] == "spec-render":
                    rel = item["payload"].get("relative_path")
                    if rel:
                        rel = Path(rel)
                        if not rel.parts or rel.parts[0] != "images":
                            raise RoadError("渲染图片清理路径无效")
                        self.path(rel)
                        if rel.as_posix() not in protected_images:
                            images.append(rel)
            self.remove_local(f"sessions/{safe_id(session_id)}")
            for rel in images:
                self.remove_local(rel)
            for rid in disposable:
                self.remove_local(f"receipts/{safe_id(rid)}.json")
            # Explicitly requested exports are deliberate files, not temp state.
            return True

    def receipt_images(self, ids):
        paths = set()
        for rid in ids:
            item = self.get_receipt(rid)
            if item["kind"] == "spec-render" and item["payload"].get("relative_path"):
                paths.add(Path(item["payload"]["relative_path"]).as_posix())
        return paths

    def purge_expired(self):
        if list(self.path("locks").glob("*.lock")):
            return {"removed_sessions": 0, "skipped_locked": True}
        removed = 0
        for row in self.list_sessions():
            if row["retention"] == "temporary":
                data = self.read(row["id"])
                if datetime.fromisoformat(data["expires_at"]) <= datetime.now(timezone.utc):
                    removed += int(self.discard_temporary(row["id"], expired_only=True))
        # Unattached/failed-query receipts also have a finite lifetime.
        referenced = set()
        for row in self.list_sessions():
            referenced.update(self.read(row["id"])["evidence_ids"])
        protected_images = self.receipt_images(referenced)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=TEMPORARY_HOURS)).timestamp()
        orphaned = 0
        for path in self.path("receipts").glob("*.json"):
            if path.stem not in referenced and path.stat().st_mtime < cutoff:
                item = self.get_receipt(path.stem)
                rel = item["payload"].get("relative_path") if item["kind"] == "spec-render" else None
                if rel and Path(rel).parts[0] == "images" and Path(rel).as_posix() not in protected_images:
                    self.remove_local(rel)
                self.remove_local(path.relative_to(self.root))
                orphaned += 1
        return {"removed_sessions": removed, "removed_orphan_receipts": orphaned, "skipped_locked": False}
