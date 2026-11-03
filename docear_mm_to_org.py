#!/usr/bin/env python3
"""Convert a Freeplane/Docear .mm map to an Org-mode file.

The conversion keeps the root node as the Org file title, then renders each
subsequent branch as nested org headings. Selected node metadata is preserved:
- node LINK values are rewritten from project://... to pdf://~/...
- if a node has a pdf_annotation with page="N", the pdf link is rewritten as
  pdf://...::N to match org-pdftools style
- node attribute NAME="key" is emitted before node text as [cite:@key]
- a node's PDF link is emitted after its text on the same heading
- node IDs and arrowlink destinations are converted to Org ID links
"""

from __future__ import annotations

import argparse
import html
import os
import re
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


def org_id_from_node_id(node_id: str) -> str:
    """Make a readable Org ID from a source node ID."""
    safe_id = re.sub(r"[^A-Za-z0-9_-]+", "-", node_id.strip()).strip("-")
    return f"docear-{safe_id or 'node'}"


def build_node_id_map(root_node: ET.Element) -> dict[str, str]:
    """Map source IDs for emitted headings to unique Org IDs.

    The root node is the document title rather than an Org heading, so it is
    intentionally not included as a link target.
    """
    node_ids: dict[str, str] = {}
    used_org_ids: set[str] = set()

    def visit(node: ET.Element, is_root: bool = False) -> None:
        source_id = node.get("ID")
        if source_id and not is_root and source_id not in node_ids:
            base_id = org_id_from_node_id(source_id)
            org_id = base_id
            suffix = 2
            while org_id in used_org_ids:
                org_id = f"{base_id}-{suffix}"
                suffix += 1
            node_ids[source_id] = org_id
            used_org_ids.add(org_id)

        for child in node:
            if child.tag == "node":
                visit(child)

    visit(root_node, is_root=True)
    return node_ids


def format_internal_links(node: ET.Element, node_ids: dict[str, str]) -> str | None:
    links = []
    for child in node:
        if child.tag == "arrowlink":
            destination = child.get("DESTINATION")
            org_id = node_ids.get(destination) if destination else None
            if org_id:
                links.append(f"[[id:{org_id}]]")
    return " ".join(links) or None


def format_citation(node: ET.Element) -> str:
    attrs = extract_attrs(node)
    key = attrs.get("key")
    if not key:
        key = node.get("KEY")
    if not key:
        return ""
    cite_key = key if key.startswith("@") else f"@{key}"
    return f"[cite:{cite_key}]"


def format_org_heading(
    node: ET.Element,
    depth: int,
    project_root: str | None = None,
    pdf_root: str = "~/",
    node_ids: dict[str, str] | None = None,
) -> str:
    title = extract_node_text(node)
    parts = [part for part in (
        format_citation(node),
        title,
        format_pdf_link(node, project_root=project_root, pdf_root=pdf_root),
        format_internal_links(node, node_ids or {}),
    ) if part]
    return f"{'*' * depth} {' '.join(parts)}".strip()


def walk_nodes(
    node: ET.Element,
    depth: int = 1,
    project_root: str | None = None,
    pdf_root: str = "~/",
    node_ids: dict[str, str] | None = None,
) -> list[str]:
    lines = [format_org_heading(
        node,
        depth,
        project_root=project_root,
        pdf_root=pdf_root,
        node_ids=node_ids,
    )]
    org_id = (node_ids or {}).get(node.get("ID", ""))
    if org_id:
        lines.extend([":PROPERTIES:", f":ID: {org_id}", ":END:"])

    for child in node:
        if child.tag == "node":
            lines.extend(walk_nodes(
                child,
                depth + 1,
                project_root=project_root,
                pdf_root=pdf_root,
                node_ids=node_ids,
            ))
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
    node_ids = build_node_id_map(root_node)
    children = []
    for child in root_node:
        if child.tag == "node":
            children.extend(walk_nodes(
                child,
                depth=1,
                project_root=project_root,
                pdf_root=pdf_root,
                node_ids=node_ids,
            ))

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
        description="Convert a Docear/Freeplane .mm map to an Org-mode file."
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
