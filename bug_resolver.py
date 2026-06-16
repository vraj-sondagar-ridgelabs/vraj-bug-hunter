#!/usr/bin/env python3
"""Bug Resolver.

Read a Word (.docx) bug report, extract each bug's embedded photo and the
description text that follows it, save the photos to a local folder, and write a
JSON file pairing every photo's path with its description.

Document layout assumed: each bug is an image followed by its description text
(in reading order). Images and the paragraphs after them are paired
sequentially.

Usage:
    python bug_resolver.py <input.docx> [--out <output_dir>]
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
from pathlib import Path

try:
    from docx import Document
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.oxml.ns import qn
except ImportError:
    sys.exit(
        "python-docx is not installed. Run: pip install python-docx Pillow"
    )


# Namespace-qualified tags used while walking the document body XML.
_DRAWING = qn("w:drawing")
_BLIP = qn("a:blip")
_EMBED = qn("r:embed")
_PARA = qn("w:p")
_TEXT = qn("w:t")


def _iter_block_items(document):
    """Yield ('image', rId) and ('text', str) items in true document order.

    python-docx's `document.paragraphs` reads text but the convenience API does
    not interleave inline images cleanly, so we walk the body XML directly.
    """
    body = document.element.body
    for child in body.iterchildren():
        if child.tag != _PARA:
            # Tables and other block types are skipped for this layout.
            continue

        # Within a paragraph, runs appear in order; an image may sit before,
        # between, or after text. Walk descendants to keep that order.
        for blip in child.iter(_BLIP):
            rid = blip.get(_EMBED)
            if rid:
                yield ("image", rid)

        # Collect text from w:t nodes only. Walking itertext() can revisit text
        # at multiple nesting levels and duplicate it; w:t holds the literal run
        # text exactly once.
        text = "".join(t.text or "" for t in child.iter(_TEXT)).strip()
        if text:
            yield ("text", text)


def _image_extension(image_part) -> str:
    """Best-effort file extension for an embedded image part."""
    content_type = getattr(image_part, "content_type", "") or ""
    ext = mimetypes.guess_extension(content_type)
    if ext:
        # Normalise the noisy ones.
        return {".jpe": ".jpg", ".jpeg": ".jpg"}.get(ext, ext)

    # Fall back to the part name's suffix (e.g. /word/media/image1.png).
    suffix = Path(str(getattr(image_part, "partname", ""))).suffix
    return suffix if suffix else ".png"


def extract_bugs(docx_path: Path, out_dir: Path, project_path: str = "") -> list[dict]:
    """Extract (photo, description) pairs from the docx into out_dir.

    Returns a list of dicts: {id, photo_path, photo_abs_path, description,
    project_path}. `photo_path` is relative to out_dir (portable);
    `photo_abs_path` is absolute so Claude can open it from any directory.
    `project_path` is an optional pointer to the codebase the bug lives in.
    """
    document = Document(str(docx_path))
    related = document.part.related_parts

    images_dir = out_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    items = list(_iter_block_items(document))

    bugs: list[dict] = []
    bug_no = 0

    for idx, (kind, value) in enumerate(items):
        if kind != "image":
            continue

        bug_no += 1
        image_part = related.get(value)
        if image_part is None:
            print(f"  ! Bug {bug_no}: embedded image '{value}' could not be resolved; skipping.")
            bug_no -= 1
            continue

        ext = _image_extension(image_part)
        filename = f"bug_{bug_no}{ext}"
        (images_dir / filename).write_bytes(image_part.blob)

        # Description = the text blocks that follow this image, up to the next
        # image. Accumulate so multi-paragraph descriptions are captured.
        description_parts: list[str] = []
        for next_kind, next_value in items[idx + 1:]:
            if next_kind == "image":
                break
            description_parts.append(next_value)
        description = "\n".join(description_parts).strip()

        if not description:
            print(f"  ! Bug {bug_no}: image has no following description text.")

        abs_path = (images_dir / filename).resolve()
        bugs.append(
            {
                "id": bug_no,
                "photo_path": f"images/{filename}",
                "photo_abs_path": str(abs_path),
                "description": description,
                "project_path": project_path,
            }
        )

    return bugs


def extract_bugs_in_memory(
    docx_path: Path, project_path: str = "", make_prompt: bool = True
):
    """Extract bugs without persisting to a chosen folder (cloud-safe).

    Returns ``(bugs, files)`` where:
      * ``bugs`` is the list of bug dicts, with **relative** ``photo_path`` only
        (no machine-specific absolute path — portable across local/cloud).
      * ``files`` maps relative output paths to raw bytes, ready to be zipped or
        written to a browser-picked folder:
        ``{"images/bug_1.png": b"...", "bugs.json": b"...",
           "claude_prompt.txt": b"..."}``.

    Internally it extracts to a temp dir (python-docx needs real paths), then
    reads the images back into memory and discards the temp dir.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        bugs = extract_bugs(docx_path, tmp_dir, project_path=project_path)

        files: dict[str, bytes] = {}
        for bug in bugs:
            rel = bug["photo_path"]  # e.g. "images/bug_1.png"
            files[rel] = (tmp_dir / rel).read_bytes()
            # Drop the absolute path; it would point at the (now-deleted) temp dir.
            bug.pop("photo_abs_path", None)

        files["bugs.json"] = json.dumps(
            bugs, indent=2, ensure_ascii=False
        ).encode("utf-8")

        if make_prompt:
            prompt = build_claude_prompt_relative(bugs)
            files["claude_prompt.txt"] = prompt.encode("utf-8")

    return bugs, files


# Where the user saves the output. The literal "{folder}" is a placeholder the
# folder-save component replaces with the actual folder name picked at save time.
SAVE_BASE = r"C:\Users\Offic\Downloads\{folder}"


def build_claude_prompt_relative(bugs: list[dict]) -> str:
    """Claude brief for the in-memory/cloud flow.

    Photo + JSON paths are written under ``C:\\Users\\Offic\\Downloads\\{folder}``
    where ``{folder}`` is replaced by the folder name when the user saves. This
    way the saved ``claude_prompt.txt`` points Claude at the real files on disk.
    """
    base = SAVE_BASE
    shimmed = []
    for bug in bugs:
        b = dict(bug)
        rel = bug.get("photo_path", "").replace("/", "\\")
        b["photo_abs_path"] = f"{base}\\{rel}"
        shimmed.append(b)
    return build_claude_prompt(shimmed, Path(f"{base}\\bugs.json"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract bug photos + descriptions from a .docx into JSON."
    )
    parser.add_argument("input", help="Path to the input Word (.docx) file.")
    parser.add_argument(
        "--out",
        default="output",
        help="Output directory (default: ./output). Holds images/ and bugs.json.",
    )
    parser.add_argument(
        "--project",
        default="",
        help="Optional path to the codebase the bugs live in; written to each bug's project_path.",
    )
    parser.add_argument(
        "--prompt",
        action="store_true",
        help="After extracting, also print a Claude-ready brief (and write claude_prompt.txt).",
    )
    args = parser.parse_args(argv)

    docx_path = Path(args.input)
    if not docx_path.is_file():
        print(f"Error: input file not found: {docx_path}", file=sys.stderr)
        return 1
    if docx_path.suffix.lower() != ".docx":
        print(
            f"Error: expected a .docx file, got: {docx_path.name}",
            file=sys.stderr,
        )
        return 1

    out_dir = Path(args.out)

    print(f"Reading: {docx_path}")
    try:
        bugs = extract_bugs(docx_path, out_dir, project_path=args.project)
    except Exception as exc:  # noqa: BLE001 - surface a clean message to the user
        print(f"Error: failed to process document: {exc}", file=sys.stderr)
        return 1

    json_path = out_dir / "bugs.json"
    json_path.write_text(json.dumps(bugs, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nExtracted {len(bugs)} bug(s).")
    print(f"  Images: {out_dir / 'images'}")
    print(f"  JSON:   {json_path}")

    if args.prompt:
        brief = build_claude_prompt(bugs, json_path.resolve())
        prompt_path = out_dir / "claude_prompt.txt"
        prompt_path.write_text(brief, encoding="utf-8")
        print(f"  Prompt: {prompt_path}\n")
        print(brief)

    return 0


def build_claude_prompt(bugs: list[dict], json_path: Path) -> str:
    """Build a ready-to-send brief telling Claude to view each photo and fix it."""
    lines = [
        "You are fixing bugs from a bug report. The structured data is at:",
        f"  {json_path}",
        "",
        "FIRST: create a todo list with one item per bug below, then work through "
        "them ONE BY ONE — fully fix and verify each bug before starting the next, "
        "marking each todo complete as you go. Do not batch or skip ahead.",
        "",
        "For each bug below: open the photo with the Read tool and analyze the "
        "image VERY deeply — inspect every detail (UI elements, layout, "
        "spacing, colors, text, error states, cursor, highlighted/circled areas, "
        "and anything visually off). Cross-reference what you see with the written "
        "description, then locate the root cause in the project and fix it.",
        "",
        "IMPORTANT — bug location box: each photo has a colored rectangle/square "
        "(any color) drawn on it that marks exactly WHERE the bug is. Find that "
        "box first and focus your analysis on the element(s) inside it — that is "
        "the region the report is pointing at.",
        "",
    ]
    for bug in bugs:
        lines.append(f"## Bug {bug['id']}")
        lines.append(f"- Photo: {bug['photo_abs_path']}")
        if bug.get("project_path"):
            lines.append(f"- Project: {bug['project_path']}")
        desc = bug["description"] or "(no description text in the document)"
        lines.append(f"- Description: {desc}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Final verification (required)")
    lines.append(
        "After fixing all bugs, verify EVERY bug one by one using the Playwright "
        "CLI / playwright-cli skill. For each bug: launch the app in the browser, "
        "navigate to the affected screen, reproduce the original scenario, and "
        "confirm the fix is actually implemented and the issue is gone (take a "
        "screenshot as proof). Go through the bugs sequentially (Bug 1, Bug 2, …) "
        "and report a clear PASS/FAIL for each — do not mark a bug done until "
        "Playwright confirms it visually."
    )
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
