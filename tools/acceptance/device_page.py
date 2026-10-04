"""Three-button host page. Rendering and physical transport are separate modules."""
from pathlib import Path

HERE = Path(__file__).resolve().parent


def page_html():
    html = (HERE / "device_page.html").read_text()
    for marker, name in (("DEVICE_STYLE", "device_page.css"),
                         ("DEVICE_RENDERER", "device_renderer.js"),
                         ("DEVICE_INPUT", "device_input.js")):
        html = html.replace("/* " + marker + " */", (HERE / name).read_text())
    return html


HTML = page_html()
