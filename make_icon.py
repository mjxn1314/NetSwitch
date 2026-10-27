# -*- coding: utf-8 -*-
"""
生成 NetSwitch 工具图标：
- 圆角方形 + 深蓝→蓝→青 渐变底
- 白色「切换」双向箭头（在 16px 下依然清晰）
产出：
- NetSwitch.ico        多尺寸（256/128/64/48/32/16）
- icon_256.png         界面横幅 / 标题栏使用的高清 PNG
"""
import os
from PIL import Image, ImageDraw

S = 1024
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# 配色（与界面横幅一致）
C0 = (0x1e, 0x3a, 0x8a)   # 深蓝
C1 = (0x25, 0x63, 0xeb)   # 主蓝
C2 = (0x06, 0xb6, 0x6d if False else 0xb6, 0xd4)  # 青
C2 = (0x06, 0xb6, 0xd4)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def make_gradient(size):
    """对角线渐变：左上深蓝 → 中部主蓝 → 右下青。"""
    img = Image.new("RGB", (size, size))
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            if t < 0.55:
                k = t / 0.55
                c = lerp(C0, C1, k)
            else:
                k = (t - 0.55) / 0.45
                c = lerp(C1, C2, k)
            px[x, y] = c
    return img


def rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def draw_swap(size):
    """白色双向切换箭头，返回 RGBA 图层。"""
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    white = (255, 255, 255, 255)
    sc = size / 1024.0

    def P(v):
        return v * sc

    w = P(78)  # 笔画粗细
    # 上箭头（指向左）：箭杆 + 三角箭头
    d.line([(P(498), P(372)), (P(668), P(372))], fill=white,
           width=int(w), joint="curve")
    d.polygon([(P(366), P(372)), (P(478), P(282)), (P(478), P(462))],
              fill=white)
    # 下箭头（指向右）
    d.line([(P(356), P(652)), (P(526), P(652))], fill=white,
           width=int(w), joint="curve")
    d.polygon([(P(658), P(652)), (P(546), P(562)), (P(546), P(742))],
              fill=white)
    # 圆形端点（让箭杆末端圆润）
    r = w / 2
    d.ellipse([P(668) - r, P(372) - r, P(668) + r, P(372) + r], fill=white)
    d.ellipse([P(356) - r, P(652) - r, P(356) + r, P(652) + r], fill=white)
    return layer


def main():
    base = make_gradient(S).convert("RGBA")
    glyph = draw_swap(S)
    base = Image.alpha_composite(base, glyph)

    # 圆角裁剪
    radius = int(S * 0.225)
    mask = rounded_mask(S, radius)
    base.putalpha(mask)

    # 高清 PNG
    png_path = os.path.join(OUT_DIR, "icon_256.png")
    base.resize((256, 256), Image.LANCZOS).save(png_path)

    # 多尺寸 ICO
    ico_sizes = [256, 128, 64, 48, 32, 16]
    imgs = [base.resize((s, s), Image.LANCZOS) for s in ico_sizes]
    ico_path = os.path.join(OUT_DIR, "NetSwitch.ico")
    imgs[0].save(ico_path, sizes=[(s, s) for s in ico_sizes],
                 append_images=imgs[1:])
    print("saved:", png_path, ico_path)


if __name__ == "__main__":
    main()
