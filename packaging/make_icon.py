"""生成程序图标：
- packaging/output/app.ico（exe、安装包、开始菜单用）
- ui/img/tray.png（托盘用）
- android/app/src/main/res/mipmap-xxxhdpi/ic_launcher_fg.png（手机桌面图标的前景，见 android/…/mipmap-anydpi-v26/ic_launcher.xml）

原图：assets/icon-source.png（用户提供的手绘角色图，1254×1254；2026-11-22 换成比剪刀手的那张）。
大尺寸用「头和肩膀」，小尺寸（≤64）只裁脸，不然 16 像素时糊成一团。都放进圆形里，四周透明。
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "assets" / "icon-source.png"
ANDROID_FG = ROOT / "android" / "app" / "src" / "main" / "res" / "mipmap-xxxhdpi" / "ic_launcher_fg.png"

# 不同尺寸用不同的裁剪框（原图坐标）
HEAD = (120, 10, 1130, 1020)
CROPS = {
    256: HEAD, 128: HEAD,
    64: (300, 240, 900, 840), 48: (340, 290, 860, 810),
    32: (365, 320, 835, 790), 24: (378, 335, 822, 780), 16: (390, 350, 810, 770),
}


def badge(src: Image.Image, size: int) -> Image.Image:
    crop = src.crop(CROPS[size]).resize((size, size), Image.LANCZOS)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    out.paste(crop, (0, 0), mask.resize((size, size), Image.LANCZOS))
    return out


def android_foreground(src: Image.Image) -> Image.Image:
    """安卓自适应图标的前景：108dp（xxxhdpi 下 432 像素），系统只露出中间约 72dp，四周会被裁成圆或圆角方。
    所以把「头和肩膀」放在中间 304 像素里（比 72dp 稍大一点，让脸占满），底色白色在 ic_launcher.xml 里。"""
    size, inner = 432, 304
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    face = src.crop(HEAD).resize((inner, inner), Image.LANCZOS)
    out.paste(face, ((size - inner) // 2, (size - inner) // 2))
    return out


def main(out_ico: Path) -> None:
    src = Image.open(SRC).convert("RGB")
    out_ico.parent.mkdir(parents=True, exist_ok=True)
    images = {s: badge(src, s) for s in CROPS}
    # ICO 里每个尺寸放各自裁好的那张（Pillow 的 append_images 按尺寸匹配）
    images[256].save(out_ico, format="ICO", sizes=[(s, s) for s in sorted(CROPS)],
                     append_images=[images[s] for s in sorted(CROPS) if s != 256])
    tray = ROOT / "ui" / "img" / "tray.png"
    tray.parent.mkdir(parents=True, exist_ok=True)
    images[64].save(tray)
    ANDROID_FG.parent.mkdir(parents=True, exist_ok=True)
    android_foreground(src).save(ANDROID_FG)
    print("icon ->", out_ico, "| tray ->", tray, "| android ->", ANDROID_FG)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "packaging" / "output" / "app.ico")
