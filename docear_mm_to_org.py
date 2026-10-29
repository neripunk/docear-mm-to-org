#!/usr/bin/env python3
"""Convert a Freeplane/Docear .mm map to an Org-mode file.

The conversion keeps the root node as the Org file title, then renders each
subsequent branch as nested org headings. Selected node metadata is preserved:
- node LINK values are rewritten from project://... to pdf://~/...
- node attribute NAME="key" is emitted as an Org citation like [cite:key]
"""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path
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


def convert_project_link(raw_link: str | None) -> str | None:
    """Convert project://... URIs into pdf://~/... URIs.

    Example:
      project://16AA.../../../../articulos/pedagogy/Foo.pdf
      -> pdf://~/articulos/pedagogy/Foo.pdf
    """
    if not raw_link:
        return None

    if raw_link.startswith("project://"):
        rest = raw_link[len("project://") :]
        if "/" not in rest:
            return "pdf://~/"

        parts = rest.split("/")
        if len(parts) >= 2:
            tail = parts[1:]
            while tail and tail[0] in (".", ".."):
                tail.pop(0)
            if tail:
                return "pdf://~/" + "/".join(tail)
        return "pdf://~/"

    return raw_link


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
    attrs = extract_attrs(node)

    suffix = []
    link = convert_project_link(node.get("LINK"))
    if link:
        suffix.append(f"[[{link}]]")
    cite = format_citation(node)
    if cite:
        suffix.append(cite)

    if suffix:
        heading = f"{'*' * depth} {title} {' '.join(suffix)}"
    else:
        heading = f"{'*' * depth} {title}"
    return heading.strip()


def walk_nodes(node: ET.Element, depth: int = 1) -> list[str]:
    lines: list[str] = []
    lines.append(format_org_heading(node, depth))
    for child in node:
        if child.tag == "node":
            lines.extend(walk_nodes(child, depth + 1))
    return lines


def parse_map(mm_path: Path) -> tuple[str, list[str]]:
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
            children.extend(walk_nodes(child, depth=1))

    return title, children


def convert_file(input_path: Path, output_path: Path | None = None) -> Path:
    title, lines = parse_map(input_path)

    org_lines = [f"#+TITLE: {title}"]
    org_lines.extend(lines)
    out = output_path or input_path.with_suffix(".org")
    out.write_text("\n".join(org_lines) + "\n", encoding="utf-8")
    return out


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
    args = parser.parse_args()

    output = convert_file(args.input, args.output)
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
