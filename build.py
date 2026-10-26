"""產生圖示並用 PyInstaller 把 tomato.pyw 編成單一 exe（輸出到 tomato_timer\\dist）。"""
import os
import subprocess
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ICO = os.path.join(HERE, "tomato.ico")


def make_icon():
    s = 512
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((48, 92, 464, 484), fill="#E5533D")
    d.ellipse((120, 150, 200, 210), fill=(255, 255, 255, 110))
    d.polygon([(256, 120), (190, 60), (230, 104), (256, 40), (282, 104), (322, 60)], fill="#4CAF50")
    d.polygon([(150, 118), (256, 150), (362, 118), (310, 170), (256, 160), (202, 170)], fill="#4CAF50")
    for x in (190, 322):
        d.ellipse((x - 16, 290, x + 16, 330), fill="#4A2A24")
        d.ellipse((x - 40 if x < 256 else x + 4, 336, x + 36 if x < 256 else x + 40, 376),
                  fill="#F48B7B")
    d.arc((216, 310, 296, 390), 20, 160, fill="#4A2A24", width=10)
    im.save(ICO, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])


if __name__ == "__main__":
    make_icon()
    subprocess.check_call([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--noconsole",
        "--name", "小番茄", "--icon", ICO,
        "--distpath", os.path.join(HERE, "dist"),
        "--workpath", os.path.join(HERE, "build"),
        "--specpath", os.path.join(HERE, "build"),
        os.path.join(HERE, "tomato.pyw"),
    ])
