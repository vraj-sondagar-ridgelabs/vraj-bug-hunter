#!/usr/bin/env python3
"""Bug Resolver — Streamlit UI.

Upload a Word (.docx) bug report, choose where to save, run the extractor, then
preview each bug's photo + description and download bugs.json / the Claude prompt.

Run:
    streamlit run app.py
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import streamlit as st

from bug_resolver import build_claude_prompt, extract_bugs

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
      /* Danger emphasis for the delete button (keyed st.button) */
      .st-key-delete_output button:not(:disabled) {
        border-color: #d64545;
        color: #d64545;
      }
      .st-key-delete_output button:not(:disabled):hover {
        background: #d64545;
        border-color: #d64545;
        color: #ffffff;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Bug Resolver")
st.caption(
    "Upload a Word bug report → extract each bug's photo + description → "
    "get structured JSON ready to hand to Claude."
)

# --- Inputs ------------------------------------------------------------------
with st.container(border=True):
    uploaded = st.file_uploader(
        "Bug report (.docx)",
        type=["docx"],
        help="Each bug should be a photo followed by its description text.",
    )

    col1, col2 = st.columns(2)
    with col1:
        out_dir_str = st.text_input(
            "Output folder",
            value="output",
            help="Where images/ and bugs.json are written.",
        )
    with col2:
        project_path = st.text_input(
            "Project path (optional)",
            value="",
            placeholder="C:/leadforge",
            help="The codebase the bugs live in. Stored in each bug's project_path.",
        )

    make_prompt = st.checkbox(
        "Also generate a Claude-ready prompt", value=True
    )

    run = st.button(
        "Extract bugs",
        type="primary",
        width="stretch",
        disabled=uploaded is None,
    )

# --- Run extraction ----------------------------------------------------------
if run and uploaded is not None:
    out_dir = Path(out_dir_str.strip() or "output")
    try:
        # python-docx needs a real path; write the upload to a temp .docx.
        with tempfile.NamedTemporaryFile(
            suffix=".docx", delete=False
        ) as tmp:
            tmp.write(uploaded.getvalue())
            tmp_path = Path(tmp.name)

        with st.spinner("Extracting photos and descriptions…"):
            bugs = extract_bugs(tmp_path, out_dir, project_path=project_path.strip())
            json_path = out_dir / "bugs.json"
            json_path.write_text(
                json.dumps(bugs, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            prompt_text = (
                build_claude_prompt(bugs, json_path.resolve())
                if make_prompt
                else None
            )
            if prompt_text is not None:
                (out_dir / "claude_prompt.txt").write_text(
                    prompt_text, encoding="utf-8"
                )

        tmp_path.unlink(missing_ok=True)

        st.session_state["bugs"] = bugs
        st.session_state["json_path"] = str(json_path.resolve())
        st.session_state["out_dir"] = str(out_dir.resolve())
        st.session_state["prompt_text"] = prompt_text
        st.session_state["source_name"] = uploaded.name
    except Exception as exc:  # noqa: BLE001 - surface a clean message to the user
        st.error(f"Failed to process the document: {exc}")

# --- Results -----------------------------------------------------------------
bugs = st.session_state.get("bugs")
if bugs is not None:
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
        # --- Downloads (primary actions, kept above the long bug list) -------
        st.subheader("Output")
        st.markdown(
            f'<p class="muted">Saved to <code>{st.session_state["json_path"]}</code></p>',
            unsafe_allow_html=True,
        )

        json_bytes = json.dumps(bugs, indent=2, ensure_ascii=False).encode("utf-8")
        d1, d2 = st.columns(2)
        with d1:
            st.download_button(
                "Download bugs.json",
                data=json_bytes,
                file_name="bugs.json",
                mime="application/json",
                width="stretch",
            )
        with d2:
            prompt_text = st.session_state.get("prompt_text")
            st.download_button(
                "Download Claude prompt",
                data=(prompt_text or "").encode("utf-8"),
                file_name="claude_prompt.txt",
                mime="text/plain",
                width="stretch",
                disabled=not prompt_text,
            )

        with st.expander("Preview bugs.json"):
            st.json(bugs)

        if st.session_state.get("prompt_text"):
            with st.expander("Preview Claude prompt"):
                st.code(st.session_state["prompt_text"], language="markdown")

        # --- Extracted bug cards (below, since this is the scrollable part) --
        st.divider()
        st.subheader("Extracted bugs")
        for bug in bugs:
            with st.container(border=True):
                img_col, txt_col = st.columns([1, 2])
                with img_col:
                    photo = Path(bug["photo_abs_path"])
                    if photo.is_file():
                        st.image(str(photo), width="stretch")
                    else:
                        st.warning("Image file missing")
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

    # --- Danger zone: clean up the output folder once done -------------------
    out_dir = st.session_state.get("out_dir")
    if out_dir:
        st.divider()
        with st.container(border=True):
            st.markdown("**Clean up**")
            st.markdown(
                f'<p class="muted">Done with these results? Delete the output '
                f"folder (images + bugs.json + prompt) at "
                f"<code>{out_dir}</code>. Download anything you need first — "
                f"this cannot be undone.</p>",
                unsafe_allow_html=True,
            )
            confirm = st.checkbox(
                "Yes, I've saved what I need — permanently delete this folder.",
                key="confirm_delete",
            )
            if st.button(
                "Delete output folder",
                type="secondary",
                disabled=not confirm,
                key="delete_output",
            ):
                try:
                    target = Path(out_dir)
                    if target.is_dir():
                        shutil.rmtree(target)
                        # Clear results so the page resets to the upload state.
                        for k in (
                            "bugs",
                            "json_path",
                            "out_dir",
                            "prompt_text",
                            "source_name",
                            "confirm_delete",
                        ):
                            st.session_state.pop(k, None)
                        st.success(f"Deleted {out_dir}")
                        st.rerun()
                    else:
                        st.info("Folder no longer exists — nothing to delete.")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Could not delete the folder: {exc}")
