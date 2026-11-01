"""Local DOCX builder executed by the configured bundled Python runtime."""
import json
import re
import sys
from pathlib import Path

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from PIL import Image


def heading_text(value):
    return re.sub(r"[^\w\s\u3400-\u9fff]", " ", value).strip()


def font_style(style, size):
    style.font.name = "Microsoft YaHei"
    style.font.size = Pt(size)
    style.font.color.rgb = RGBColor(0, 0, 0)
    style.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
    for border in list(style.element.iter(qn("w:pBdr"))):
        border.getparent().remove(border)


def table(doc, rows):
    grid = doc.add_table(rows=0, cols=len(rows[0]))
    grid.autofit = False
    widths = [1.05, 0.9, 2.25, 2.3] if len(rows[0]) == 4 else [6.5 / len(rows[0])] * len(rows[0])
    for col, width in zip(grid.columns, widths):
        col.width = Inches(width)
    for index, values in enumerate(rows):
        row = grid.add_row()
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
        if index == 0:
            repeat = OxmlElement("w:tblHeader")
            row._tr.get_or_add_trPr().append(repeat)
        for cell, value, width in zip(row.cells, values, widths):
            cell.width = Inches(width)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            props = cell._tc.get_or_add_tcPr()
            borders = OxmlElement("w:tcBorders")
            for edge in ("top", "left", "bottom", "right"):
                rule = OxmlElement("w:" + edge)
                for key, setting in (("val", "single"), ("sz", "4"), ("color", "D9D9D9")):
                    rule.set(qn("w:" + key), setting)
                borders.append(rule)
            props.append(borders)
            margins = OxmlElement("w:tcMar")
            for side in ("top", "left", "bottom", "right"):
                margin = OxmlElement("w:" + side)
                margin.set(qn("w:w"), "100")
                margin.set(qn("w:type"), "dxa")
                margins.append(margin)
            props.append(margins)
            shade = OxmlElement("w:shd")
            shade.set(qn("w:fill"), "E8EEF5" if index == 0 else ("F5F7FA" if index % 2 == 0 else "FFFFFF"))
            props.append(shade)
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(4)
            paragraph.paragraph_format.keep_with_next = index == 0
            run = paragraph.add_run(value.strip())
            run.font.size = Pt(10.5)
            run.bold = index == 0
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def build(payload, destination):
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = section.bottom_margin = Inches(0.8)
    section.left_margin = section.right_margin = Inches(1)
    for name, size in (("Normal", 11), ("Title", 20), ("Heading 1", 15), ("Heading 2", 12), ("Heading 3", 11)):
        style = doc.styles[name]
        font_style(style, size)
        style.paragraph_format.space_after = Pt(7)
        style.paragraph_format.line_spacing = 1.25
        if name != "Normal":
            style.paragraph_format.keep_with_next = True
            style.paragraph_format.space_before = Pt(12 if name != "Title" else 0)
    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run("AI 辅助咨询草稿  第 ").font.size = Pt(9)
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    footer.add_run(" 页").font.size = Pt(9)
    lines = payload["report"].splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if line.startswith("|"):
            rows = []
            while index < len(lines) and lines[index].strip().startswith("|"):
                values = lines[index].strip().strip("|").split("|")
                if not all(re.fullmatch(r"\s*:?-+:?\s*", x) for x in values):
                    rows.append(values)
                index += 1
            if rows and all(len(row) == len(rows[0]) for row in rows):
                if doc.paragraphs:
                    doc.paragraphs[-1].paragraph_format.keep_with_next = True
                table(doc, rows)
            else:
                for row in rows:
                    doc.add_paragraph("；".join(row))
            continue
        if line:
            match = re.match(r"^(#{1,4})\s+(.*)", line)
            if match:
                level = len(match[1])
                doc.add_paragraph(heading_text(match[2]), "Title" if level == 1 else "Heading " + str(min(level - 1, 3)))
            else:
                paragraph = doc.add_paragraph(line[2:] if line.startswith("- ") else line)
                if line.startswith("- "):
                    paragraph.paragraph_format.left_indent = Inches(0.15)
                paragraph.paragraph_format.widow_control = True
        index += 1
    if payload.get("images"):
        doc.add_heading("照片附件", level=1)
    for photo in payload.get("images", []):
        doc.add_heading(heading_text(photo["label"]), level=2)
        with Image.open(photo["path"]) as image:
            width = min(6.5, 3.0 * image.width / image.height)
        paragraph = doc.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.keep_with_next = True
        paragraph.add_run().add_picture(photo["path"], width=Inches(width))
        caption = doc.add_paragraph(photo["caption"])
        caption.paragraph_format.space_after = Pt(10)
        caption.paragraph_format.keep_with_next = False
    doc.core_properties.title = heading_text(payload.get("title", "道路养护咨询意见"))
    doc.core_properties.author = ""
    doc.save(destination)


if __name__ == "__main__":
    build(json.load(sys.stdin), Path(sys.argv[1]))
