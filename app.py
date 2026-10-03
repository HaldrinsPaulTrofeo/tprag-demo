"""Hugging Face Space entry point for the T-PRAG public demo.

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
