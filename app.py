#!/usr/bin/env python3
"""Bug Resolver — Streamlit UI (local + Streamlit Cloud).

Upload a Word (.docx) bug report, extract each bug's photo + description, preview
them, then either:
  * save all output straight into a folder you pick in your file explorer
    (File System Access API — works on the deployed cloud app in Chrome/Edge), or
  * download a single ZIP (works in every browser).

Extraction runs in memory, so nothing depends on a server-side disk path —
making the app portable from a local machine to Streamlit Community Cloud.

Run:
    streamlit run app.py
"""

from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

import streamlit as st

from bug_resolver import extract_bugs_in_memory
from fs_saver import folder_save_widget

st.set_page_config(
    page_title="Bug Resolver",
    page_icon=":beetle:",
    layout="centered",
)

# --- Minimal, clean utility styling -----------------------------------------
st.markdown(
    """
    <style>
      .block-container { max-width: 820px; padding-top: 2.5rem; }
      [data-testid="stMetricValue"] { font-size: 1.6rem; }
      .bug-desc {
        white-space: pre-wrap;
        background: rgba(127,127,127,0.06);
        border: 1px solid rgba(127,127,127,0.18);
        border-radius: 8px;
        padding: 0.75rem 0.9rem;
        font-size: 0.95rem;
        line-height: 1.55;
      }
      .muted { color: rgba(127,127,127,0.9); font-size: 0.85rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Bug Resolver")
st.caption(
    "Upload a Word bug report → extract each bug's photo + description → "
    "save or download structured JSON ready to hand to Claude."
)


def _make_zip(files: dict[str, bytes]) -> bytes:
    """Bundle the in-memory output files into a single ZIP."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, data in files.items():
            zf.writestr(path, data)
    buf.seek(0)
    return buf.getvalue()


# --- Inputs ------------------------------------------------------------------
with st.container(border=True):
    uploaded = st.file_uploader(
        "Bug report (.docx)",
        type=["docx"],
        help="Each bug should be a photo followed by its description text.",
    )

    project_path = st.text_input(
        "Project path (optional)",
        value="",
        placeholder="C:/leadforge",
        help="The codebase the bugs live in. Stored in each bug's project_path.",
    )

    make_prompt = st.checkbox("Also generate a Claude-ready prompt", value=True)

    run = st.button(
        "Extract bugs",
        type="primary",
        width="stretch",
        disabled=uploaded is None,
    )

# --- Run extraction (in memory — cloud-safe) ---------------------------------
if run and uploaded is not None:
    try:
        # python-docx needs a real path; write the upload to a temp .docx.
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(uploaded.getvalue())
            tmp_path = Path(tmp.name)

        with st.spinner("Extracting photos and descriptions…"):
            bugs, files = extract_bugs_in_memory(
                tmp_path,
                project_path=project_path.strip(),
                make_prompt=make_prompt,
            )

        tmp_path.unlink(missing_ok=True)

        st.session_state["bugs"] = bugs
        st.session_state["files"] = files
        st.session_state["source_name"] = uploaded.name
    except Exception as exc:  # noqa: BLE001 - surface a clean message to the user
        st.error(f"Failed to process the document: {exc}")

# --- Results -----------------------------------------------------------------
bugs = st.session_state.get("bugs")
files = st.session_state.get("files")
if bugs is not None and files is not None:
    st.divider()

    no_desc = sum(1 for b in bugs if not b["description"])
    c1, c2, c3 = st.columns(3)
    c1.metric("Bugs found", len(bugs))
    c2.metric("With description", len(bugs) - no_desc)
    c3.metric("Missing description", no_desc)

    if not bugs:
        st.warning(
            "No embedded images were found in this document. Make sure the "
            "bugs are inserted as pictures (not links) above their descriptions."
        )
    else:
        # --- Output: save to folder OR download ZIP ----------------------
        st.subheader("Output")
        src = st.session_state.get("source_name", "bug report")
        zip_name = Path(src).stem + "_bugs.zip"

        st.markdown(
            '<p class="muted">Save everything (images + bugs.json'
            + (" + claude_prompt.txt" if make_prompt else "")
            + ") to a folder you pick, or download it as a ZIP.</p>",
            unsafe_allow_html=True,
        )

        st.markdown("**Save to a folder** (Chrome / Edge)")
        folder_save_widget(files)

        has_prompt = make_prompt and "claude_prompt.txt" in files
        dl1, dl2 = st.columns(2)
        with dl1:
            st.download_button(
                "Download ZIP",
                data=_make_zip(files),
                file_name=zip_name,
                mime="application/zip",
                width="stretch",
            )
        with dl2:
            st.download_button(
                "Download Claude prompt",
                data=files.get("claude_prompt.txt", b""),
                file_name="claude_prompt.txt",
                mime="text/plain",
                width="stretch",
                disabled=not has_prompt,
                help="Saved to your picked folder too, as claude_prompt.txt"
                if has_prompt
                else "Enable 'Also generate a Claude-ready prompt' to use this.",
            )

        with st.expander("Preview bugs.json"):
            st.json(bugs)

        if has_prompt:
            with st.expander("Preview / copy Claude prompt"):
                st.markdown(
                    '<p class="muted">When saved to a folder, this is written as '
                    "<code>&lt;folder&gt;/claude_prompt.txt</code>. Use the copy "
                    "icon at the top-right of the box below.</p>",
                    unsafe_allow_html=True,
                )
                st.code(
                    files["claude_prompt.txt"].decode("utf-8"),
                    language="markdown",
                )

        # --- Extracted bug cards (the long scrollable part, kept last) ----
        st.divider()
        st.subheader("Extracted bugs")
        for bug in bugs:
            with st.container(border=True):
                img_col, txt_col = st.columns([1, 2])
                with img_col:
                    img_bytes = files.get(bug["photo_path"])
                    if img_bytes:
                        st.image(img_bytes, width="stretch")
                    else:
                        st.warning("Image missing")
                with txt_col:
                    st.markdown(f"**Bug {bug['id']}**")
                    desc = bug["description"] or "_No description text found._"
                    st.markdown(
                        f'<div class="bug-desc">{desc}</div>',
                        unsafe_allow_html=True,
                    )
                    if bug.get("project_path"):
                        st.markdown(
                            f'<p class="muted">Project: {bug["project_path"]}</p>',
                            unsafe_allow_html=True,
                        )

        # --- Clear results ------------------------------------------------
        st.divider()
        if st.button("Clear results", type="secondary"):
            for k in ("bugs", "files", "source_name"):
                st.session_state.pop(k, None)
            st.rerun()
