"""Assemble the public demo into a folder (and zip) ready to upload to a host.

    python demo/build_hosted_bundle.py     # -> dist/tprag-demo/ and dist/tprag-demo.zip

Target: a free Hugging Face *Gradio* Space (Docker Spaces are paid). Upload the
folder's contents; keep the README.md that Hugging Face created for the Space.

Copies only the modules and pages the demo uses. It never copies .env, the
database, uploads, signatures, credentials, evaluation data or the corpus.
"""
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist" / "tprag-demo"
MODULES = ["auth", "barangays", "requests_api", "request_allocation", "session_forecast",
           "migrate_requests", "profile_api", "signatures", "accounts_api", "barangay_portal_api",
           "provincial_letter_api", "request_letter", "citizen_api"]

REQUIREMENTS = """fastapi>=0.110
uvicorn>=0.27
pydantic>=2.6
itsdangerous>=2.1
python-multipart>=0.0.9
pillow>=10.1
python-docx>=1.1
httpx>=0.27
"""

# The demo never touches MySQL: hosted_demo.py replaces every connection with
# SQLite. This stand-in keeps imports working without shipping the real module
# (whose comments name the office's database account) or the MySQL driver.
DATABASE_STUB = '''"""Public demo build: no MySQL. hosted_demo.py supplies SQLite connections."""


def get_db_connection():
    return None
'''

# Hugging Face Gradio Spaces (free) run `python app.py` with Gradio preinstalled.
# app.py starts uvicorn itself, serving the full demo; Gradio only supplies a small
# page at /gradio so the Space is a valid Gradio app.
APP_PY = '''"""Hugging Face Space entry point for the T-PRAG public demo.

Gradio launches its own server, as Hugging Face's Gradio runtime expects. The demo
site is given to Gradio as its first route and answers every path except Gradio's
own internal ones, which Gradio needs to start up.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gradio as gr
from starlette.routing import BaseRoute, Match

from demo.hosted_demo import app as site

GRADIO_PATHS = ("/gradio_api", "/gradio", "/assets", "/svelte", "/_app", "/theme.css", "/config",
                "/file=", "/manifest.json", "/monitoring", "/favicon.ico", "/node", "/upload")


class DemoSite(BaseRoute):
    """Serve the demo for every path Gradio does not use itself."""

    def matches(self, scope):
        if scope["type"] in ("http", "websocket") and not scope["path"].startswith(GRADIO_PATHS):
            return Match.FULL, {}
        return Match.NONE, {}

    async def handle(self, scope, receive, send):
        await site(scope, receive, send)


SETTINGS = {k: v for k, v in os.environ.items()
            if k.startswith(("GRADIO", "PORT", "SYSTEM", "SPACE_HOST", "HOST"))}
print("[tprag-demo] runtime settings:", SETTINGS, flush=True)

with gr.Blocks(title="T-PRAG demo") as demo:
    gr.Markdown("# T-PRAG public demo")
    gr.Markdown("Open the [demo guide](/demo) to explore the system.")

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", ssr_mode=False, app_kwargs={"routes": [DemoSite()]})
'''


def main():
    # Empty the folder rather than delete it: it is often open in Explorer
    # during an upload, and Windows will not remove an open folder.
    OUT.mkdir(parents=True, exist_ok=True)
    for child in OUT.iterdir():
        shutil.rmtree(child) if child.is_dir() else child.unlink()
    (OUT / "demo").mkdir()
    for name in MODULES:
        shutil.copy2(ROOT / f"{name}.py", OUT / f"{name}.py")
    (OUT / "database.py").write_text(DATABASE_STUB, encoding="utf-8")
    shutil.copy2(ROOT / "demo" / "hosted_demo.py", OUT / "demo" / "hosted_demo.py")
    shutil.copytree(ROOT / "static", OUT / "static", ignore=shutil.ignore_patterns("*.bak", "*.bak*"))
    (OUT / "requirements.txt").write_text(REQUIREMENTS, encoding="utf-8")
    (OUT / "app.py").write_text(APP_PY, encoding="utf-8")

    forbidden = [p for p in OUT.rglob("*") if p.name == ".env" or p.suffix in (".sqlite", ".csv", ".sql")]
    assert not forbidden, forbidden
    leaks = [p for p in OUT.rglob("*.py") if any(k in p.read_text(encoding="utf-8")
                                                 for k in ("DB_PASSWORD", "GROQ_API_KEY", "HF_TOKEN", "haldrins"))]
    assert not leaks, leaks
    archive = OUT.parent / "tprag-demo.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(OUT.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(OUT))
    files = sum(1 for p in OUT.rglob("*") if p.is_file())
    print(f"Built {OUT} ({files} files) and {archive} ({archive.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
