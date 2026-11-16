from pathlib import Path
from PIL import Image


def test_desktop_icon_contains_256px_resource():
    icon = Path(__file__).resolve().parents[1] / "desktop-app" / "assets" / "messenger.ico"
    image = Image.open(icon)
    sizes = image.info.get("sizes", set())
    assert (256, 256) in sizes
    assert len(sizes) >= 6
