"""Read-only checks for project Markdown links, anchors and version references.

Checks root Markdown, docs/ and the project skill; excludes attachments and
consultation storage. Does not call the consultation CLI or access the network.
"""
import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
PRODUCT = ROOT / "docs/道路养护 AI 技术专家——项目总体方案与 Codex 开发交接文档.md"
HANDOFF = ROOT / "docs/交接.md"
LINK = re.compile(r"\[[^\]\n]+\]\(\s*(<[^>\n]+>|[^)\n]+)\s*\)")


def markdown(path, errors):
    """Return text outside fenced code and GitHub-style heading anchors."""
    lines, anchors, counts = [], set(), {}
    fence = None
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        marker = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
                fence = None
            continue
        if marker:
            fence = marker[1]
            continue
        lines.append((number, line))
        heading = re.match(r"^#{1,6}\s+(.+?)(?:\s+#+)?\s*$", line)
        if heading:
            label = re.sub(r"<[^>]+>", "", heading[1]).lower()
            slug = "".join(c for c in label if c in "_-" or unicodedata.category(c)[0] not in "PS")
            slug = slug.replace(" ", "-")
            count = counts.get(slug, 0)
            counts[slug] = count + 1
            anchors.add(slug + (f"-{count}" if count else ""))
    if fence:
        errors.append(f"{path.relative_to(ROOT)}: 代码围栏未闭合")
    return lines, anchors


def main():
    errors = []
    files = sorted(set(ROOT.glob("*.md")) | set((ROOT / "docs").rglob("*.md"))
                   | set((ROOT / ".agents/skills/road-diagnosis").rglob("*.md")))
    parsed = {p.resolve(): markdown(p, errors) for p in files}
    checked = 0
    for path in files:
        for number, line in parsed[path.resolve()][0]:
            for match in LINK.finditer(line):
                raw = match[1].strip()
                raw = raw[1:-1] if raw.startswith("<") and raw.endswith(">") else raw
                if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", raw) or raw.startswith("//"):
                    continue
                checked += 1
                destination, _, fragment = raw.partition("#")
                target = (path.parent / unquote(destination)).resolve() if destination else path.resolve()
                location = f"{path.relative_to(ROOT)}:{number}"
                if not target.is_relative_to(ROOT):
                    errors.append(f"{location}: 本地链接超出项目范围：{raw}")
                elif not target.exists():
                    errors.append(f"{location}: 本地链接不存在：{raw}")
                elif fragment and target.suffix.lower() == ".md":
                    if target not in parsed:
                        errors.append(f"{location}: 锚点目标不在文档检查范围：{raw}")
                    elif unquote(fragment) not in parsed[target][1]:
                        errors.append(f"{location}: 锚点不存在：{raw}")
    version = baseline = None
    if not HANDOFF.is_file() or not PRODUCT.is_file():
        errors.append("缺少当前交接或产品总方案")
    else:
        handoff = HANDOFF.read_text(encoding="utf-8-sig")
        product = PRODUCT.read_text(encoding="utf-8-sig")
        source = (ROOT / "src/roadexpert/__init__.py").read_text(encoding="utf-8-sig")
        patterns = [("实现版本", r"实现版本：([\d.]+)", handoff,
                     r'__version__\s*=\s*[\"\x27]([^\"\x27]+)', source),
                    ("产品基线", r"产品基线：(v[\d.]+)", handoff,
                     r"\*\*文档版本\*\*：(v[\d.]+)", product)]
        for label, left_pattern, left, right_pattern, right in patterns:
            a, b = re.search(left_pattern, left), re.search(right_pattern, right)
            if not a or not b or a[1] != b[1]:
                errors.append(f"{label}缺失或与维护来源不一致")
            elif label == "实现版本":
                version = a[1]
            else:
                baseline = a[1]
    print(json.dumps({"status": "failed" if errors else "docs_checks_passed",
                      "documents": len(files), "local_links": checked,
                      "implementation_version": version, "product_baseline": baseline,
                      "errors": errors}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
