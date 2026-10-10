from pathlib import Path

import AppKit as AK
from Foundation import NSMakeRect

root = Path(__file__).resolve().parent.parent
destination = root / "build/Typeflo.iconset"
destination.mkdir(parents=True, exist_ok=True)
AK.NSApplication.sharedApplication()


def draw(size, path):
    image = AK.NSImage.alloc().initWithSize_((size, size))
    image.lockFocus()
    scale = size / 1024
    AK.NSColor.colorWithCalibratedRed_green_blue_alpha_(.90, .92, .86, 1).setFill()
    AK.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(20 * scale, 20 * scale, 984 * scale, 984 * scale), 218 * scale, 218 * scale).fill()
    AK.NSColor.colorWithCalibratedRed_green_blue_alpha_(.23, .29, .20, 1).setFill()
    for x, height in ((262, 172), (400, 390), (538, 554), (676, 280)):
        AK.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(x * scale, (1024 - height) / 2 * scale, 86 * scale, height * scale), 43 * scale, 43 * scale).fill()
    image.unlockFocus()
    representation = AK.NSBitmapImageRep.imageRepWithData_(image.TIFFRepresentation())
    representation.representationUsingType_properties_(AK.NSBitmapImageFileTypePNG, {}).writeToFile_atomically_(str(path), True)


for size in (16, 32, 128, 256, 512):
    draw(size, destination / f"icon_{size}x{size}.png")
    draw(size * 2, destination / f"icon_{size}x{size}@2x.png")
