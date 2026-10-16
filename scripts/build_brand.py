"""Rebuild original NOTTY community integration icons from simple vector geometry."""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "custom_components" / "notty" / "brand"
SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
  <rect x="8" y="8" width="240" height="240" rx="64" fill="#087f8c"/>
  <path d="M64 112V58L105 84Q128 76 151 84L192 58V112Z" fill="#ffffff"/>
  <ellipse cx="128" cy="139" rx="72" ry="65" fill="#ffffff"/>
  <path d="M90 132L106 137M150 137L166 132" fill="none" stroke="#087f8c" stroke-width="9" stroke-linecap="round"/>
  <path d="M117 153H139L128 166Z" fill="#087f8c"/>
  <path d="M128 164V178M106 176Q128 193 150 176" fill="none" stroke="#087f8c" stroke-width="6" stroke-linecap="round"/>
  <path d="M196 32L200 44L212 48L200 52L196 64L192 52L180 48L192 44Z" fill="#a5f3d2"/>
</svg>"""


def draw_icon(size: int) -> Image.Image:
    # Render at 4x, then downsample for crisp transparent PNGs.
    factor = size * 4 / 256
    canvas = Image.new("RGBA", (size * 4, size * 4))
    draw = ImageDraw.Draw(canvas)

    def box(coords):
        return tuple(round(c * factor) for c in coords)

    teal = "#087f8c"
    draw.rounded_rectangle(box((8, 8, 248, 248)), radius=round(64 * factor), fill=teal)
    draw.polygon(
        [box(p) for p in [(64, 112), (64, 58), (105, 84), (151, 84), (192, 58), (192, 112)]],
        fill="white",
    )
    draw.ellipse(box((56, 74, 200, 204)), fill="white")
    for line in [(90, 132, 106, 137), (150, 137, 166, 132)]:
        draw.line(box(line), fill=teal, width=round(9 * factor))
    draw.polygon([box(p) for p in [(117, 153), (139, 153), (128, 166)]], fill=teal)
    draw.line(box((128, 164, 128, 178)), fill=teal, width=round(6 * factor))
    draw.arc(box((102, 154, 154, 188)), 25, 155, fill=teal, width=round(6 * factor))
    draw.polygon(
        [
            box(p)
            for p in [
                (196, 32),
                (200, 44),
                (212, 48),
                (200, 52),
                (196, 64),
                (192, 52),
                (180, 48),
                (192, 44),
            ]
        ],
        fill="#a5f3d2",
    )
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def main():
    BRAND.mkdir(parents=True, exist_ok=True)
    (ROOT / "assets" / "icon.svg").write_text(SVG + "\n")
    for size, suffix in [(256, ""), (512, "@2x")]:
        draw_icon(size).save(BRAND / f"icon{suffix}.png")


if __name__ == "__main__":
    main()
