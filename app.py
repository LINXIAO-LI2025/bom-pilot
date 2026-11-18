"""Gradio entry point for local usage and ModelScope."""
import os
from pathlib import Path
import sys

import gradio as gr

# ModelScope installs third-party dependencies before copying this source tree.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from bom_pilot.ui import CSS, build_app

demo = build_app()

if __name__ == "__main__":
    demo.launch(
        server_name=os.environ.get("GRADIO_SERVER_NAME", "0.0.0.0"),
        server_port=int(os.environ.get("GRADIO_SERVER_PORT", "7860")),
        max_file_size="8mb",
        css=CSS,
        theme=gr.themes.Soft(primary_hue="teal", neutral_hue="slate", font=["system-ui", "sans-serif"]),
        footer_links=[],
        share=False,
    )
