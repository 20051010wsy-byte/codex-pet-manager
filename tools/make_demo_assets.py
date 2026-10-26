import json
import math
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw


ROWS = [6, 8, 8, 4, 5, 8, 6, 6, 6]
CELL_WIDTH = 192
CELL_HEIGHT = 208


def draw_demo(cell: Image.Image, row: int, frame: int, color):
    draw = ImageDraw.Draw(cell)
    bob = round(4 * math.sin((frame + 1) / 6 * math.tau))
    cx, cy = 96, 114 + bob
    shade = tuple(max(0, value - 20) for value in color)
    draw.ellipse((40, 180, 152, 198), fill=(29, 48, 58, 35))
    draw.rounded_rectangle(
        (40, cy - 52, 152, cy + 54),
        radius=42,
        fill=(*color, 255),
        outline=(*shade, 255),
        width=5,
    )
    draw.ellipse((50, cy - 76, 92, cy - 28), fill=(*color, 255), outline=(*shade, 255), width=5)
    draw.ellipse((100, cy - 76, 142, cy - 28), fill=(*color, 255), outline=(*shade, 255), width=5)
    eye_shift = max(-2, min(2, row - 2))
    draw.ellipse((66 + eye_shift, cy - 14, 82 + eye_shift, cy + 2), fill=(19, 34, 42, 255))
    draw.ellipse((110 + eye_shift, cy - 14, 126 + eye_shift, cy + 2), fill=(19, 34, 42, 255))
    draw.ellipse((71 + eye_shift, cy - 9, 76 + eye_shift, cy - 4), fill=(255, 255, 255, 255))
    draw.ellipse((115 + eye_shift, cy - 9, 120 + eye_shift, cy - 4), fill=(255, 255, 255, 255))
    draw.arc((78, cy + 8, 114, cy + 34), 12, 168, fill=(19, 34, 42, 255), width=4)
    draw.rounded_rectangle((53, cy + 42, 86, cy + 64), radius=9, fill=(*shade, 255))
    draw.rounded_rectangle((106, cy + 42, 139, cy + 64), radius=9, fill=(*shade, 255))
    if row in (1, 2):
        swing = 10 if frame % 2 else -10
        draw.rounded_rectangle((34, cy + 5 + swing, 58, cy + 58 + swing), radius=10, fill=(*shade, 255))
        draw.rounded_rectangle((134, cy + 5 - swing, 158, cy + 58 - swing), radius=10, fill=(*shade, 255))
    if row == 3:
        draw.ellipse((142, cy - 72, 174, cy - 36), fill=(*color, 255), outline=(*shade, 255), width=4)
    if row == 4:
        draw.ellipse((48, cy + 70, 62, cy + 84), fill=(244, 190, 90, 255))
        draw.ellipse((130, cy + 70, 144, cy + 84), fill=(244, 190, 90, 255))
    if row == 5:
        draw.arc((78, cy + 18, 114, cy + 44), 190, 350, fill=(19, 34, 42, 255), width=4)
    if row == 6:
        draw.ellipse((84, cy - 30, 108, cy - 6), fill=(255, 255, 255, 170))
    if row in (7, 8):
        draw.rounded_rectangle((70, cy + 50, 122, cy + 72), radius=8, fill=(19, 34, 42, 220))
        draw.rectangle((76, cy + 56, 116, cy + 66), fill=(151, 231, 223, 255))


def make_sheet(path: Path, color):
    atlas = Image.new("RGBA", (CELL_WIDTH * 8, CELL_HEIGHT * len(ROWS)), (0, 0, 0, 0))
    for row, count in enumerate(ROWS):
        for frame in range(count):
            cell = Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (0, 0, 0, 0))
            draw_demo(cell, row, frame, color)
            atlas.alpha_composite(cell, (frame * CELL_WIDTH, row * CELL_HEIGHT))
    path.parent.mkdir(parents=True, exist_ok=True)
    atlas.save(path, "WEBP", lossless=True, quality=100, method=6)


def add_pet(root: Path, pet_id: str, name: str, color):
    sheet = "spritesheet.webp"
    metadata = {
        "id": pet_id,
        "displayName": name,
        "description": "用于界面截图的可复现演示人物，不对应任何商业角色。",
        "spriteVersionNumber": 1,
        "spritesheetPath": sheet,
    }
    for kind, metadata_name in (("pets", "pet.json"), ("avatars", "avatar.json")):
        folder = root / kind / pet_id
        folder.mkdir(parents=True, exist_ok=True)
        make_sheet(folder / sheet, color)
        (folder / metadata_name).write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def build(root: Path) -> None:
    if root.exists():
        shutil.rmtree(root)
    for pet_id, display_name, color in (
        ("demo-mint", "示例小青龙", (65, 170, 158)),
        ("demo-gold", "示例小金龙", (215, 157, 67)),
        ("demo-coral", "示例小珊瑚", (204, 104, 105)),
    ):
        add_pet(root, pet_id, display_name, color)
    disabled = root / "pet-manager" / "disabled" / "demo-coral"
    for kind in ("pets", "avatars"):
        source = root / kind / "demo-coral"
        if source.exists():
            (disabled / kind).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(disabled / kind))


if __name__ == "__main__":
    build(Path(tempfile.gettempdir()) / "CodexPetManagerScreenshot" / ".codex")
