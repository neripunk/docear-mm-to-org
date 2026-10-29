# docear-mm-to-org

Script to convert [Docear](https://www.docear.org) mindmap files to org-mode. Created with GitHub copilot. It should work with [Freeplane](https://docs.freeplane.org/) files too. Created almost exclusively with GitHub copilot.

The conversion keeps the root node as the Org file title, then renders each
subsequent branch as nested org headings. Selected node metadata is preserved:
- node `LINK` values are rewritten to a `pdf:// link`. The location of the mindmap root and the pdf files can be specified on the command line.
- if a node has a `pdf_annotation` with `page="N"`, the pdf link is rewritten as
  `pdf://...::N` to match [`org-pdftools`](https://github.com/fuxialexander/org-pdftools) conventions
- node attribute `NAME="key"` is included as an Org citation with the format `[cite:key]`

## Usage

The converter expects a Freeplane/Docear `.mm` file and produces an Org file with the same node hierarchy.

Basic usage:
```bash
python docear_mm_to_org.py MindMap.mm
```

This writes:
```text
MindMap.org
```

The root node becomes the Org title, and each nested node becomes a heading. For nodes with a `LINK` pointing to a PDF, the exporter rewrites the link into a portable Org PDF link format.

Optional arguments:
```bash
python docear_mm_to_org.py MindMap.mm \
  --project-root /path/to/your/docear/project \
  --pdf-root ~/pdfs \
  -o output.org
```

- `--project-root`: optional base directory used to resolve `project://...` links from the Docear map
- `--pdf-root`: base root for the generated `pdf://...` links in the Org file
- `-o`: output path for the generated Org file
