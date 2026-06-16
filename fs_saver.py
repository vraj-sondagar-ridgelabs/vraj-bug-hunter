"""Browser-side "save to a folder you pick" for Streamlit.

Uses the File System Access API (window.showDirectoryPicker), which runs in the
user's browser — so it works even on a deployed Streamlit Cloud app, writing
files straight into a folder the user chooses in their OS file explorer.

Supported in Chromium browsers (Chrome / Edge / Opera) over HTTPS. On
unsupported browsers (Firefox / Safari) the button explains the limitation and
the app's ZIP download should be used instead.
"""

from __future__ import annotations

import base64
import json

import streamlit.components.v1 as components


def folder_save_widget(files: dict[str, bytes], height: int = 140) -> None:
    """Render a "Pick folder & save" button that writes `files` to a chosen dir.

    `files` maps a relative path (e.g. "images/bug_1.png" or "bugs.json") to its
    raw bytes. Subfolders in the path are created inside the picked directory.
    """
    payload = [
        {"path": path, "b64": base64.b64encode(data).decode("ascii")}
        for path, data in files.items()
    ]
    files_json = json.dumps(payload)

    html = """
<div style="font-family: 'Source Sans Pro', sans-serif;">
  <button id="pick-btn" style="
      width:100%; padding:0.55rem 1rem; border-radius:8px; cursor:pointer;
      border:1px solid #2e7d32; background:#2e7d32; color:#fff;
      font-size:0.95rem; font-weight:600;">
    Pick folder &amp; save all files
  </button>
  <p id="status" style="margin:0.6rem 0 0; font-size:0.85rem; color:#9aa0a6;"></p>
</div>
<script>
const FILES = __FILES_JSON__;
const btn = document.getElementById('pick-btn');
const status = document.getElementById('status');

function b64ToBytes(b64) {
  const bin = atob(b64);
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  return arr;
}

if (!window.showDirectoryPicker) {
  btn.disabled = true;
  btn.style.opacity = 0.5;
  btn.style.cursor = 'not-allowed';
  status.textContent =
    'This browser does not support direct folder saving. ' +
    'Use Chrome or Edge, or use the Download ZIP button instead.';
}

btn.addEventListener('click', async () => {
  try {
    status.style.color = '#9aa0a6';
    status.textContent = 'Opening folder picker…';
    const dir = await window.showDirectoryPicker({ mode: 'readwrite' });

    let count = 0;
    for (const f of FILES) {
      const parts = f.path.split('/');
      let handle = dir;
      // Create nested subdirectories as needed.
      for (let i = 0; i < parts.length - 1; i++) {
        handle = await handle.getDirectoryHandle(parts[i], { create: true });
      }
      const fileHandle = await handle.getFileHandle(parts[parts.length - 1], { create: true });
      const writable = await fileHandle.createWritable();
      await writable.write(b64ToBytes(f.b64));
      await writable.close();
      count++;
    }
    status.style.color = '#2e7d32';
    status.textContent = 'Saved ' + count + ' file(s) to "' + dir.name + '".';
  } catch (err) {
    if (err && err.name === 'AbortError') {
      status.textContent = 'Cancelled — no folder selected.';
    } else {
      status.style.color = '#d64545';
      status.textContent = 'Could not save: ' + (err && err.message ? err.message : err);
    }
  }
});
</script>
"""
    html = html.replace("__FILES_JSON__", files_json)
    components.html(html, height=height)
