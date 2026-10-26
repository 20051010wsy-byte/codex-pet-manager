from pathlib import Path

from PIL import Image, ImageDraw


def make_icon(output_dir: Path) -> None:
    size = 1024
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (56, 56, 968, 968),
        radius=220,
        fill=(19, 124, 139, 255),
    )
    draw.ellipse(
        (252, 466, 772, 834),
        fill=(247, 250, 247, 255),
    )
    for left, top, right, bottom in (
        (252, 278, 410, 494),
        (376, 218, 548, 474),
        (552, 220, 714, 474),
        (674, 300, 816, 510),
    ):
        draw.ellipse(
            (left, top, right, bottom),
            fill=(247, 250, 247, 255),
        )
    draw.ellipse((396, 552, 452, 610), fill=(19, 124, 139, 255))
    draw.ellipse((572, 552, 628, 610), fill=(19, 124, 139, 255))
    draw.arc(
        (460, 590, 564, 692),
        start=20,
        end=160,
        fill=(19, 124, 139, 255),
        width=28,
    )
    draw.ellipse((776, 160, 902, 286), fill=(244, 190, 90, 255))
    draw.ellipse((802, 186, 876, 260), fill=(255, 247, 230, 255))
    output_dir.mkdir(parents=True, exist_ok=True)
    image.resize((256, 256), Image.Resampling.LANCZOS).save(output_dir / "app.png")
    image.resize((256, 256), Image.Resampling.LANCZOS).save(
        output_dir / "app.ico",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


if __name__ == "__main__":
    make_icon(Path(__file__).resolve().parents[1] / "assets")
