"""Build app icons from the Inkscape PNG export, preserving its source colours."""

import argparse
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parents[1]
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def square_png(source, size=1024):
    source = Path(source)
    if size < 256:
        raise ValueError("Use a PNG size of at least 256 pixels for the multi-size ICO.")
    if source.suffix.lower() == ".svg":
        from PyQt5 import QtCore, QtGui, QtSvg
        app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])
        renderer = QtSvg.QSvgRenderer(str(source))
        bounds = renderer.viewBoxF()
        if not renderer.isValid() or bounds.width() <= 0 or bounds.height() <= 0:
            raise ValueError("The SVG is not readable or has no valid viewBox.")
        scale = min(size / bounds.width(), size / bounds.height())
        width, height = bounds.width() * scale, bounds.height() * scale
        image = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32_Premultiplied)
        image.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(image)
        painter.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)
        try:
            renderer.render(painter, QtCore.QRectF((size-width)/2, (size-height)/2, width, height))
        finally:
            painter.end()
        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QIODevice.WriteOnly)
        if not image.save(buffer, "PNG"):
            raise ValueError("Could not render the SVG as PNG.")
        with Image.open(BytesIO(bytes(buffer.data()))) as rendered:
            return rendered.convert("RGBA")
    with Image.open(source) as image:
        fitted = image.convert("RGBA")
        if fitted.width > size or fitted.height > size:
            fitted = ImageOps.contain(fitted, (size, size), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        canvas.paste(fitted, ((size-fitted.width)//2, (size-fitted.height)//2))
        return canvas


def build_icons(source, png, ico, size=1024):
    image = square_png(source, size)
    png, ico = Path(png), Path(ico)
    if png.resolve() == Path(source).resolve() and Path(source).suffix.lower() == ".svg":
        raise ValueError("Keep the editable SVG separate from generated PNG output.")
    png.parent.mkdir(parents=True, exist_ok=True)
    ico.parent.mkdir(parents=True, exist_ok=True)
    image.save(png, format="PNG")
    image.save(ico, format="ICO", sizes=[(n, n) for n in ICO_SIZES])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "assets/SAMAnnLogo.png",
                        help="Use the Inkscape PNG export for faithful SVG colours.")
    parser.add_argument("--png", type=Path, default=ROOT / "assets/app_icon.png")
    parser.add_argument("--ico", type=Path, default=ROOT / "assets/app_icon.ico")
    parser.add_argument("--size", type=int, default=1024)
    args = parser.parse_args()
    build_icons(args.source, args.png, args.ico, args.size)
    print(f"PNG: {args.png}\nICO: {args.ico}")


if __name__ == "__main__":
    main()
