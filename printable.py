#!/usr/bin/env python3
"""
printable - build a real A4 PDF from stdin or a file.

Purpose: any fleet device (hetzner / desk / netcup) can produce a printable
A4 PDF and scp it to macbook's ~/PrintQueue/inbox/ for the local watcher to
print. The watcher does NOT convert or transform; it passes the PDF through.
The sender is responsible for the layout.

Use cases:
- Build the JP Future Authoring mini program on hetzner, scp to macbook.
- Render a JSON report from the finances app, scp to macbook.
- Drop a README, table, or Markdown file as A4 for handwriting notes.

Input formats (auto-detected):
- .md / .markdown  -> Markdown renderer (headings, lists, code, bold/italic,
                     links, tables, blockquotes)
- .json            -> pretty-printed with monospace
- .txt / anything  -> monospace preformatted
- A pre-built .pdf -> passed through unchanged (cp $src $dst)

Output: A real PDF, page size A4 (595 x 842 pt = 210 x 297 mm).
Margins: 18mm. Font: Helvetica 10pt body / Courier 9pt for code/preformatted.

Requirements: reportlab (apt: python3-reportlab on Debian/Ubuntu,
pip: reportlab on macOS). Stdlib-only for everything else.

Usage:
    printable < input.txt > out.pdf
    printable input.txt > out.pdf
    printable --title "My Doc" input.md > out.pdf
    cat input.json | printable --format json --title "Report" > out.pdf

Page breaking is handled by ReportLab's platypus; long content paginates
automatically. For Markdown, an 8cm right margin leaves room for handwritten
notes beside the printed text.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shutil
import sys
from pathlib import Path

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.lib.enums import TA_LEFT
    from reportlab.platypus import (
        SimpleDocTemplate,
        Paragraph,
        Spacer,
        Preformatted,
        PageBreak,
        Table,
        TableStyle,
        KeepTogether,
    )
    from reportlab.lib import colors
except ImportError as e:
    sys.stderr.write(
        "printable: reportlab is not installed.\n"
        "  Debian/Ubuntu: sudo apt install -y python3-reportlab\n"
        "  macOS:         python3 -m pip install --user reportlab\n"
        f"  ({e})\n"
    )
    sys.exit(2)


A4_W, A4_H = A4
MARGIN = 18 * mm
RIGHT_GUTTER = 8 * cm if False else 0  # leave 0mm extra; the 18mm margin is enough


# ---------- helpers ----------

def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=20, leading=24, spaceAfter=8 * mm, alignment=TA_LEFT,
        ),
        "h1": ParagraphStyle(
            "h1", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=14, leading=18, spaceBefore=6 * mm, spaceAfter=2 * mm,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=12, leading=15, spaceBefore=4 * mm, spaceAfter=2 * mm,
        ),
        "h3": ParagraphStyle(
            "h3", parent=base["Heading3"], fontName="Helvetica-Bold",
            fontSize=11, leading=14, spaceBefore=3 * mm, spaceAfter=1 * mm,
        ),
        "body": ParagraphStyle(
            "body", parent=base["BodyText"], fontName="Helvetica",
            fontSize=10, leading=13, spaceAfter=2 * mm, alignment=TA_LEFT,
        ),
        "code": ParagraphStyle(
            "code", parent=base["Code"], fontName="Courier",
            fontSize=8.5, leading=10.5, leftIndent=4 * mm, rightIndent=4 * mm,
            spaceBefore=1 * mm, spaceAfter=2 * mm,
            backColor=colors.HexColor("#f4f4f4"),
            borderPadding=4, borderColor=colors.HexColor("#cccccc"),
            borderWidth=0.5,
        ),
        "pre": ParagraphStyle(
            "pre", parent=base["Code"], fontName="Courier",
            fontSize=9, leading=11, spaceAfter=2 * mm,
        ),
        "quote": ParagraphStyle(
            "quote", parent=base["BodyText"], fontName="Helvetica-Oblique",
            fontSize=10, leading=13, leftIndent=8 * mm, rightIndent=4 * mm,
            textColor=colors.HexColor("#444444"), spaceAfter=2 * mm,
        ),
        "list": ParagraphStyle(
            "list", parent=base["BodyText"], fontName="Helvetica",
            fontSize=10, leading=13, leftIndent=6 * mm,
            bulletIndent=2 * mm, spaceAfter=1 * mm,
        ),
    }


def _esc(s: str) -> str:
    """Escape text for ReportLab Paragraph XML-ish input."""
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
    )


# ---------- Markdown ----------

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_MD_HR = re.compile(r"^[-*_]{3,}\s*$")
_MD_FENCE = re.compile(r"^```(\w*)\s*$")
_MD_OL = re.compile(r"^(\s*)(\d+)\.\s+(.*)$")
_MD_UL = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_MD_TABLE_SEP = re.compile(r"^[-:|\s]+$")


def _md_inline(s: str) -> str:
    """Apply inline Markdown emphasis to a string. Order matters: code first."""
    # inline code (protect from further processing)
    placeholders = []
    def _stash(m):
        placeholders.append(m.group(1))
        return f"\x00CODE{len(placeholders) - 1}\x00"
    s = re.sub(r"`([^`]+)`", _stash, s)

    # bold + italic (handle ***, **, *)
    s = re.sub(r"\*\*\*([^*]+)\*\*\*", r"<b><i>\1</i></b>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![*])\*([^*\n]+)\*(?![*])", r"<i>\1</i>", s)

    # links [text](url) -> text
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)

    # restore code
    def _unstash(m):
        idx = int(m.group(1))
        return _esc(placeholders[idx])
    s = re.sub(r"\x00CODE(\d+)\x00", _unstash, s)

    return _esc(s)


def render_markdown(text: str, styles: dict) -> list:
    """Convert a Markdown string to a ReportLab flowable list.

    Supports: headings, paragraphs, ordered/unordered lists, fenced code blocks,
    blockquotes (lines starting with >), horizontal rules (---), simple tables
    (pipe-syntax with header + separator row). Anything else falls back to a
    paragraph.
    """
    lines = text.splitlines()
    out: list = []
    i = 0
    n = len(lines)

    def flush_para(buf: list) -> None:
        if not buf:
            return
        joined = " ".join(buf).strip()
        if joined:
            out.append(Paragraph(_md_inline(joined), styles["body"]))

    para_buf: list = []
    list_buf: list = []  # list of (kind, depth, text)

    def flush_list():
        nonlocal list_buf
        if not list_buf:
            return
        for kind, depth, text in list_buf:
            style = ParagraphStyle(
                "lvl", parent=styles["list"],
                leftIndent=(6 + depth * 6) * mm, bulletIndent=(2 + depth * 6) * mm,
            )
            bullet = f"{depth * '    '}{'•' if kind == 'ul' else ''}"
            # reportlab <bullet> tag inside Paragraph
            content = f'<bullet>{bullet}</bullet>{_md_inline(text)}'
            out.append(Paragraph(content, style))
        list_buf = []

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # fenced code block
        m = _MD_FENCE.match(stripped)
        if m:
            flush_para(para_buf); para_buf = []
            flush_list()
            code_lines = []
            i += 1
            while i < n and not _MD_FENCE.match(lines[i].strip()):
                code_lines.append(lines[i])
                i += 1
            if i < n:
                i += 1  # skip closing fence
            code_text = "\n".join(code_lines)
            if code_text.strip():
                out.append(Preformatted(code_text, styles["code"]))
            continue

        # heading
        m = _MD_HEADING.match(stripped)
        if m:
            flush_para(para_buf); para_buf = []
            flush_list()
            level = len(m.group(1))
            text = m.group(2).strip()
            out.append(Paragraph(_md_inline(text), styles[f"h{min(level, 3)}"]))
            i += 1
            continue

        # horizontal rule
        if _MD_HR.match(stripped):
            flush_para(para_buf); para_buf = []
            flush_list()
            out.append(Spacer(1, 4 * mm))
            out.append(Paragraph(
                "<font color='#888888'>" + ("-" * 60) + "</font>",
                styles["body"],
            ))
            out.append(Spacer(1, 4 * mm))
            i += 1
            continue

        # blockquote
        if stripped.startswith(">"):
            flush_para(para_buf); para_buf = []
            flush_list()
            quote_lines = []
            while i < n and lines[i].lstrip().startswith(">"):
                quote_lines.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            out.append(Paragraph(_md_inline(" ".join(quote_lines)), styles["quote"]))
            continue

        # ordered list
        m = _MD_OL.match(line)
        if m:
            flush_para(para_buf); para_buf = []
            depth = len(m.group(1)) // 2
            list_buf.append(("ol", depth, m.group(3)))
            i += 1
            continue

        # unordered list
        m = _MD_UL.match(line)
        if m:
            flush_para(para_buf); para_buf = []
            depth = len(m.group(1)) // 2
            list_buf.append(("ul", depth, m.group(2)))
            i += 1
            continue

        # blank line: paragraph/list break
        if not stripped:
            flush_para(para_buf); para_buf = []
            flush_list()
            i += 1
            continue

        # pipe table: a row of pipes, followed by separator, followed by data
        if "|" in stripped and i + 1 < n and _MD_TABLE_SEP.match(lines[i + 1].strip()):
            flush_para(para_buf); para_buf = []
            flush_list()
            def split_row(s: str) -> list:
                s = s.strip()
                if s.startswith("|"):
                    s = s[1:]
                if s.endswith("|"):
                    s = s[:-1]
                return [_md_inline(c.strip()) for c in s.split("|")]
            header = split_row(line)
            i += 2  # skip header + separator
            rows = [header]
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(split_row(lines[i]))
                i += 1
            tbl = Table(rows, hAlign="LEFT")
            tbl.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eeeeee")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#888888")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]))
            out.append(tbl)
            out.append(Spacer(1, 2 * mm))
            continue

        # plain paragraph content
        flush_list()
        para_buf.append(stripped)
        i += 1

    flush_para(para_buf)
    flush_list()
    return out


# ---------- plain text / JSON ----------

def render_text(text: str, styles: dict) -> list:
    """Render plain text as a single monospace preformatted block."""
    return [Preformatted(text, styles["pre"])]


def render_json(text: str, styles: dict) -> list:
    """Pretty-print JSON then render as monospace."""
    try:
        obj = json.loads(text)
        pretty = json.dumps(obj, indent=2, ensure_ascii=False)
    except json.JSONDecodeError:
        pretty = text
    return [Preformatted(pretty, styles["pre"])]


# ---------- main ----------

def _detect_format(src_path: str | None, explicit: str | None) -> str:
    if explicit and explicit != "auto":
        return explicit
    if src_path:
        ext = Path(src_path).suffix.lower()
        if ext in (".md", ".markdown"):
            return "md"
        if ext == ".json":
            return "json"
        if ext == ".pdf":
            return "pdf"
        mime, _ = mimetypes.guess_type(src_path)
        if mime:
            if mime.startswith("text/markdown"):
                return "md"
            if mime.startswith("application/json"):
                return "json"
            if mime == "application/pdf":
                return "pdf"
    return "txt"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Build a printable A4 PDF from stdin or a file.",
    )
    ap.add_argument("input", nargs="?", help="Input file (default: stdin)")
    ap.add_argument("--title", default="", help="Optional document title")
    ap.add_argument(
        "--format", default="auto",
        choices=["auto", "md", "markdown", "txt", "json", "pdf"],
        help="Input format (default: auto-detect from extension)",
    )
    ap.add_argument(
        "--output", "-o", default="-",
        help="Output PDF path (default: stdout, but you almost always want a file)",
    )
    args = ap.parse_args()

    fmt = _detect_format(args.input, args.format)

    # Pass-through for already-PDF input
    if fmt == "pdf":
        if not args.input:
            sys.stderr.write("printable: --format pdf requires an input file path\n")
            return 2
        with open(args.input, "rb") as f:
            data = f.read()
        if not data.startswith(b"%PDF"):
            sys.stderr.write(f"printable: {args.input} is not a valid PDF (no %PDF header)\n")
            return 2
        if args.output == "-":
            sys.stdout.buffer.write(data)
        else:
            Path(args.output).write_bytes(data)
        return 0

    # Read text input
    if args.input:
        text = Path(args.input).read_text(encoding="utf-8", errors="replace")
    else:
        text = sys.stdin.read()

    styles = _styles()

    # Decide renderer
    if fmt in ("md", "markdown"):
        body = render_markdown(text, styles)
    elif fmt == "json":
        body = render_json(text, styles)
    else:
        body = render_text(text, styles)

    # Optionally prepend a title
    if args.title:
        body = [Paragraph(_esc(args.title), styles["title"])] + body

    # Build the PDF
    out_path = args.output if args.output != "-" else None
    buf_path = None
    if out_path is None:
        # Write to a temp file so SimpleDocTemplate has a filename
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            buf_path = tmp.name
        out_path = buf_path

    doc = SimpleDocTemplate(
        out_path,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=args.title or "printable",
        author="printable.py",
    )
    doc.build(body)

    # If we wrote to a tempfile, copy to stdout
    if buf_path is not None:
        with open(buf_path, "rb") as f:
            sys.stdout.buffer.write(f.read())
        os.unlink(buf_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
