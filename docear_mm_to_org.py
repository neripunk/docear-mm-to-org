#!/usr/bin/env python3
"""Convert a Freeplane/Docear .mm map to an Org-mode file.

The conversion keeps the root node as the Org file title, then renders each
subsequent branch as nested org headings. Selected node metadata is preserved:
- node LINK values are rewritten from project://... to pdf://~/...
- if a node has a pdf_annotation with page="N", the pdf link is rewritten as
  pdf://...::N to match org-pdftools style
- node attribute NAME="key" is emitted as an Org citation like [cite:key]
- these values are placed as body text under the heading rather than attached to
  the heading text itself
"""

from __future__ import annotations

import argparse
import html
import os
from pathlib import Path, PurePosixPath
import xml.etree.ElementTree as ET


def clean_text(value: str | None) -> str:
    if value is None:
        return ""
    text = html.unescape(value)
    text = text.replace("\r", " ")
    text = text.replace("\n", " ")
    return " ".join(text.split())


def extract_node_text(node: ET.Element) -> str:
    text = node.get("TEXT")
    if text:
        return clean_text(text)

    for child in node:
        if child.tag == "richcontent":
            text = " ".join(child.itertext())
            cleaned = clean_text(text)
            if cleaned:
                return cleaned

    return "Untitled"


def extract_attrs(node: ET.Element) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for child in node:
        if child.tag == "attribute":
            name = child.get("NAME")
            value = child.get("VALUE")
            if name and value is not None:
                attrs[name] = value
    return attrs


def pdf_page_from_node(node: ET.Element) -> str | None:
    for child in node:
        if child.tag == "pdf_annotation":
            page = child.get("page")
            if page is not None and page.strip():
                return page.strip()
    return None


def project_relative_parts(raw_link: str) -> list[str]:
    """Extract the relative path carried by a project:// URI.

    Example:
      project://16AA.../../../../articulos/pedagogy/Foo.pdf
      -> ["articulos", "pedagogy", "Foo.pdf"]
    """
    rest = raw_link[len("project://") :]
    if not rest:
        return []

    # drop the UUID/id segment if present
    if "/" in rest:
        _, _, remainder = rest.partition("/")
    else:
        remainder = ""

    parts = []
    for piece in (remainder or "").split("/"):
        if not piece or piece == ".":
            continue
        if piece == "..":
            # We intentionally drop leading relative navigation because the
            # goal is to convert to a stable document path relative to the(pdf)
            # root, not to preserve filesystem traversal in the output.
            continue
        parts.append(piece)

    return parts


def convert_project_link(raw_link: str | None, project_root: str | None = None, pdf_root: str = "~/") -> str | None:
    """Convert project://... URIs into a portable pdf:// URI.

    The function resolves the project link to a filesystem path when a project
    root is given, then emits a relative path under the configured Org PDF root.
    """
    if not raw_link:
        return None

    if raw_link.startswith("project://"):
        rel_parts = project_relative_parts(raw_link)
        if not rel_parts:
            return None

        rel_path = PurePosixPath(*rel_parts)
        if project_root:
            # Optional validation: resolve the actual file path for debugging or
            # downstream consumers while still exporting a portable relative path.
            _ = (Path(project_root) / Path(*rel_path.parts)).resolve()

        # Build a portable pdf:// link relative to the configured pdf root.
        pdf_root = pdf_root.strip() or "~/"
        uri_base = ""
        if pdf_root.startswith("~/"):
            uri_base = "pdf://" + pdf_root.rstrip("/")
        elif pdf_root.startswith("~"):
            uri_base = "pdf://~" + pdf_root[1:].rstrip("/")
        elif pdf_root.startswith("/"):
            uri_base = "pdf://" + pdf_root.rstrip("/")
        else:
            uri_base = "pdf://~/" + pdf_root.strip("/")

        rel_text = rel_path.as_posix().lstrip("/")
        return f"{uri_base}/{rel_text}"

    if raw_link.startswith("pdf://"):
        return raw_link

    # Non-project links are kept as-is.
    return raw_link


def format_pdf_link(node: ET.Element, project_root: str | None = None, pdf_root: str = "~/") -> str | None:
    raw_link = node.get("LINK")
    link = convert_project_link(raw_link, project_root=project_root, pdf_root=pdf_root)
    if not link:
        return None

    page = pdf_page_from_node(node)
    if page is not None:
        return f"[[{link}::{page}]]"
    return f"[[{link}]]"


def format_citation(node: ET.Element) -> str:
    attrs = extract_attrs(node)
    key = attrs.get("key")
    if not key:
        key = node.get("KEY")
    if not key:
        return ""
    return f"[cite:{key}]"


def format_org_heading(node: ET.Element, depth: int) -> str:
    title = extract_node_text(node)
    return f"{'*' * depth} {title}".strip()


def format_body_lines(node: ET.Element, project_root: str | None = None, pdf_root: str = "~/") -> list[str]:
    lines: list[str] = []
    pdf_link = format_pdf_link(node, project_root=project_root, pdf_root=pdf_root)
    if pdf_link:
        lines.append(f"  {pdf_link}")

    cite = format_citation(node)
    if cite:
        lines.append(f"  {cite}")

    return lines


def walk_nodes(node: ET.Element, depth: int = 1, project_root: str | None = None, pdf_root: str = "~/") -> list[str]:
    lines: list[str] = []
    lines.append(format_org_heading(node, depth))
    lines.extend(format_body_lines(node, project_root=project_root, pdf_root=pdf_root))
    for child in node:
        if child.tag == "node":
            lines.extend(walk_nodes(child, depth + 1, project_root=project_root, pdf_root=pdf_root))
    return lines


def parse_map(mm_path: Path, project_root: str | None = None, pdf_root: str = "~/") -> tuple[str, list[str]]:
    tree = ET.parse(mm_path)
    root = tree.getroot()

    root_node = None
    for child in root:
        if child.tag == "node":
            root_node = child
            break

    if root_node is None:
        raise ValueError(f"No root node found in {mm_path}")

    title = extract_node_text(root_node)
    children = []
    for child in root_node:
        if child.tag == "node":
            children.extend(walk_nodes(child, depth=1, project_root=project_root, pdf_root=pdf_root))

    return title, children


def convert_file(input_path: Path, output_path: Path | None = None, project_root: str | None = None, pdf_root: str = "~/") -> Path:
    title, lines = parse_map(input_path, project_root=project_root, pdf_root=pdf_root)

    org_lines = [f"#+TITLE: {title}"]
    org_lines.extend(lines)
    out = output_path or input_path.with_suffix(".org")
    out.write_text("\n".join(org_lines) + "\n", encoding="utf-8")
    return out


def _default_project_root() -> str | None:
    return os.environ.get("DOCEAR_PROJECT_ROOT") or None


def _default_pdf_root() -> str:
    return os.environ.get("ORG_PDF_ROOT") or "~/"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert a Docear/Freeplane .mm file to an Org-mode file."
    )
    parser.add_argument("input", type=Path, help="Path to the Docear/Freeplane .mm file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Path for the output .org file (defaults to the input stem with .org)",
    )
    parser.add_argument(
        "--project-root",
        type=str,
        default=_default_project_root(),
        help="Base directory used to interpret project:// links. Optional but useful for portability.",
    )
    parser.add_argument(
        "--pdf-root",
        type=str,
        default=_default_pdf_root(),
        help="Org PDF base root used in output links, e.g. ~/ or ~/pdfs.",
    )
    args = parser.parse_args()

    output = convert_file(args.input, args.output, project_root=args.project_root, pdf_root=args.pdf_root)
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
