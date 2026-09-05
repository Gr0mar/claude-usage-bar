"""Renders the app icon: the gauge mark on a graphite squircle.

    .venv/bin/python scripts/make-icon.py [out.icns]

Writes an .iconset at every size macOS asks for and runs iconutil over it. The result
is committed, so installing does not depend on rendering it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from AppKit import (  # noqa: E402
    NSApplication,
    NSBezierPath,
    NSBitmapImageFileTypePNG,
    NSBitmapImageRep,
    NSColor,
    NSGradient,
    NSGraphicsContext,
    NSShadow,
)
from Foundation import NSMakePoint, NSMakeRect, NSMakeSize  # noqa: E402

from quotabar.ui.mark import draw_mark  # noqa: E402

#: Apple's icon grid leaves the artwork inset from the canvas edge.
INSET_RATIO = 0.086
CORNER_RATIO = 0.225
#: The spark's diameter, as a fraction of the artwork square.
SPARK_RATIO = 0.66

#: A graphite tile, so the amber gauge reads as an instrument rather than a brand.
TOP = (0x3A / 255.0, 0x3D / 255.0, 0x44 / 255.0)
BOTTOM = (0x24 / 255.0, 0x26 / 255.0, 0x2B / 255.0)
MARK = (0xF2 / 255.0, 0x9A / 255.0, 0x4B / 255.0)

#: (iconset filename, pixel size)
ICONSET = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]


def render(size: int) -> bytes:
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, size, size, 8, 4, True, False, "NSCalibratedRGBColorSpace", 0, 0
    )
    context = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(context)

    inset = size * INSET_RATIO
    artwork = NSMakeRect(inset, inset, size - 2 * inset, size - 2 * inset)
    radius = artwork.size.width * CORNER_RATIO
    squircle = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(artwork, radius, radius)

    # A drop shadow the way macOS icons carry one; it also separates the tile from a
    # light Finder background.
    shadow = NSShadow.alloc().init()
    shadow.setShadowOffset_(NSMakeSize(0, -size * 0.012))
    shadow.setShadowBlurRadius_(size * 0.03)
    shadow.setShadowColor_(NSColor.colorWithCalibratedWhite_alpha_(0.0, 0.28))
    shadow.set()

    NSGradient.alloc().initWithStartingColor_endingColor_(
        NSColor.colorWithSRGBRed_green_blue_alpha_(*TOP, 1.0),
        NSColor.colorWithSRGBRed_green_blue_alpha_(*BOTTOM, 1.0),
    ).drawInBezierPath_angle_(squircle, -90.0)

    NSShadow.alloc().init().set()
    centre = size / 2.0
    draw_mark(centre, centre, artwork.size.width * SPARK_RATIO / 2.0,
              NSColor.colorWithSRGBRed_green_blue_alpha_(*MARK, 1.0))

    NSGraphicsContext.restoreGraphicsState()
    return rep.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})


def main() -> None:
    output = sys.argv[1] if len(sys.argv) > 1 else "docs/AppIcon.icns"
    NSApplication.sharedApplication()

    workdir = tempfile.mkdtemp(prefix="usage-bar-icon-")
    iconset = os.path.join(workdir, "AppIcon.iconset")
    os.makedirs(iconset)
    try:
        for name, size in ICONSET:
            render(size).writeToFile_atomically_(os.path.join(iconset, name), True)
        subprocess.run(
            ["/usr/bin/iconutil", "-c", "icns", iconset, "-o", output], check=True
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    print("wrote {} ({} bytes)".format(output, os.path.getsize(output)))


if __name__ == "__main__":
    main()
