"""No network or automatic dependency installation in the Word export path."""
import json
import subprocess
import uuid
import hashlib
from zipfile import ZipFile, BadZipFile
from xml.etree import ElementTree
from pathlib import Path

from .storage import RoadError


def runtime_path(config):
    default = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"
    runtime = Path(config.get("document_python", default))
    if not runtime.is_absolute() or not runtime.is_file():
        raise RoadError("Word 导出需要本机文档运行环境，请配置 document_python；不会自动安装或联网")
    return runtime


def export_word(payload, destination, config):
    runtime = runtime_path(config)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name("." + uuid.uuid4().hex + ".docx")
    try:
        result = subprocess.run([str(runtime), "-X", "utf8", str(Path(__file__).with_name("word_document.py")), str(temporary)],
                                input=json.dumps(payload, ensure_ascii=False), capture_output=True,
                                encoding="utf-8", timeout=90, shell=False)
        if result.returncode or not temporary.is_file():
            raise RoadError("Word 文件生成失败，未交付不完整文件：" + result.stderr[-1500:])
        try:
            with ZipFile(temporary) as archive:
                media = {hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()
                         if name.startswith("word/media/")}
                expected = {image.get("sha256") or hashlib.sha256(Path(image["path"]).read_bytes()).hexdigest()
                            for image in payload.get("images", [])}
                if media != expected:
                    raise RoadError("Word嵌入图片与本次要求的照片不对应，未交付文件")
                document = ElementTree.fromstring(archive.read("word/document.xml"))
                document_text = "".join(node.text or "" for node in document.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"))
                if any(image["caption"] not in document_text for image in payload.get("images", [])):
                    raise RoadError("Word照片说明缺失或不对应，未交付文件")
        except (BadZipFile, KeyError, ElementTree.ParseError) as exc:
            raise RoadError("Word文件结构不完整，未交付文件") from exc
        temporary.replace(destination)
    except subprocess.TimeoutExpired as exc:
        raise RoadError("Word 文件生成超时，未交付不完整文件") from exc
    finally:
        if temporary.exists():
            temporary.unlink()
