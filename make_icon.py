#!/usr/bin/env python3
"""يولّد icon.icns (شريحة بيضاء على تدرّج أزرق/بنفسجي). يعمل ضمن build_mac.sh."""
import os, shutil, subprocess
from PIL import Image, ImageDraw

S = 1024
c1, c2 = (10, 132, 255), (94, 92, 230)

grad = Image.linear_gradient("L").resize((S, S)).rotate(45, resample=Image.BICUBIC)  # قيم 0..255
base = Image.composite(Image.new("RGB", (S, S), c2), Image.new("RGB", (S, S), c1), grad)

icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle((100, 100, 924, 924), radius=185, fill=255)
icon.paste(base, (0, 0), mask)

d = ImageDraw.Draw(icon)
W = (255, 255, 255, 255)
for c in (362, 462, 562, 662):                       # أرجل الشريحة
    d.rounded_rectangle((c - 14, 250, c + 14, 774), radius=14, fill=W)
    d.rounded_rectangle((250, c - 14, 774, c + 14), radius=14, fill=W)
d.rounded_rectangle((312, 312, 712, 712), radius=64, fill=W)          # جسم الشريحة
d.rounded_rectangle((402, 402, 622, 622), radius=34, fill=(52, 112, 243, 255))  # النواة

icon.save("icon_preview.png")
if shutil.which("iconutil"):
    os.makedirs("icon.iconset", exist_ok=True)
    for sz in (16, 32, 128, 256, 512):
        icon.resize((sz, sz), Image.LANCZOS).save(f"icon.iconset/icon_{sz}x{sz}.png")
        icon.resize((sz * 2, sz * 2), Image.LANCZOS).save(f"icon.iconset/icon_{sz}x{sz}@2x.png")
    subprocess.run(["iconutil", "-c", "icns", "icon.iconset", "-o", "icon.icns"], check=True)
    shutil.rmtree("icon.iconset")
    print("icon.icns ✓")
