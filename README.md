# Bug Resolver

Extract bug photos and their descriptions from a Word (`.docx`) bug report and
output JSON pairing each photo's local path with its description.

The document is assumed to list each bug as an **image followed by its
description text**. Images and the text after them are paired in reading order.

## Setup

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

## UI (Streamlit)

Prefer a point-and-click flow:

```bash
streamlit run app.py
```

Upload the `.docx`, set the output folder + optional project path, click
**Extract bugs**, then preview each bug's photo and description and download
`bugs.json` / the Claude prompt.

## CLI

```bash
python bug_resolver.py <input.docx> [--out <output_dir>] [--project <repo_path>] [--prompt]
```

- `<input.docx>` — path to the Word bug report.
- `--out` — output directory (default: `./output`).
- `--project` — optional path to the codebase the bugs live in; written to each
  bug's `project_path` so the tool fixing them knows where to look.
- `--prompt` — also print a Claude-ready brief and write `claude_prompt.txt`.

Produces:

- `<out>/images/bug_1.png`, `bug_2.jpg`, … — extracted photos.
- `<out>/bugs.json` — array of bug records (fields below).
- `<out>/claude_prompt.txt` — only with `--prompt`.

### Example output (`bugs.json`)

```json
[
  {
    "id": 1,
    "photo_path": "images/bug_1.png",
    "photo_abs_path": "C:\\...\\output\\images\\bug_1.png",
    "description": "Login button overlaps footer on mobile.",
    "project_path": "C:/leadforge"
  }
]
```

- `photo_path` — relative to the output dir (portable).
- `photo_abs_path` — absolute path, so Claude can open the image from any directory.
- `project_path` — the repo to fix (empty unless `--project` is passed).

## Handing off to Claude

Run with `--project` and `--prompt`, then give Claude the printed brief (or just
point it at `output/bugs.json`). Claude opens each photo, reads the description,
and fixes the bug in the named project.
