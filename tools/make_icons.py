"""
生成 JustiLawAI 的应用图标。

图形是一副等臂天平：墨底 + 白线。先在 1024x1024 上画完再降采样，边缘才干净。
产物直接写进 src/JustiLawAI/Assets/：

    app.ico       给 JustiLawAI.csproj 的 <ApplicationIcon>（exe 与任务栏用它）
    app-64.png    给窗口和标题栏（ui:ImageIcon 只吃图片）

改了图形之后重跑一次即可：

    python tools/make_icons.py
"""

import os

from PIL import Image, ImageDraw

S = 1024                      # 画布边长，最后再缩到目标尺寸
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "src", "JustiLawAI", "Assets")

INK = (21, 21, 23)            # 与应用主题里的 Ink / Backdrop 同一档
PAPER = (255, 255, 255)

RADIUS = 232                  # 圆角半径
INSET = 40                    # 四周留白

# 天平各部件的位置
BEAM_Y = 300                  # 横梁
PIVOT = (512, 300)            # 支点
PAN_X = (256, 768)            # 两只秤盘的中心
RIM_Y = 566                   # 盘口
BOWL_R = 96                   # 盘半径


def bar(d, a, b, w, fill):
    """画一根带圆头的粗线（斜线也要圆头，所以不能直接用 rounded_rectangle）。"""
    d.line([a, b], fill=fill, width=int(w))
    for x, y in (a, b):
        d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=fill)


def scales(frame, bowl, tile, beam_w=30, post_w=48, rope_w=20):
    """墨底白线天平：frame 是骨架色，bowl 是秤盘色，tile 是方块底色。"""
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((INSET, INSET, S - INSET, S - INSET), radius=RADIUS, fill=tile)

    bar(d, (236, BEAM_Y), (788, BEAM_Y), beam_w, frame)          # 横梁
    r = 52                                                        # 支点圆钮
    d.ellipse((PIVOT[0] - r, PIVOT[1] - r, PIVOT[0] + r, PIVOT[1] + r), fill=frame)
    bar(d, (PIVOT[0], BEAM_Y + 10), (PIVOT[0], 748), post_w, frame)   # 立柱
    d.rounded_rectangle((300, 748, 724, 810), radius=30, fill=frame)  # 底座（上）
    d.rounded_rectangle((352, 802, 672, 858), radius=26, fill=frame)  # 底座（下）

    for cx in PAN_X:
        bar(d, (cx, BEAM_Y + 12), (cx - 92, RIM_Y - 4), rope_w, frame)   # 吊索（左）
        bar(d, (cx, BEAM_Y + 12), (cx + 92, RIM_Y - 4), rope_w, frame)   # 吊索（右）
        d.chord((cx - BOWL_R, RIM_Y - BOWL_R, cx + BOWL_R, RIM_Y + BOWL_R),
                start=0, end=180, fill=bowl)                             # 半圆浅盘
    return im


def main():
    os.makedirs(OUT, exist_ok=True)
    im = scales(PAPER, PAPER, INK)

    ico = os.path.join(OUT, "app.ico")
    png = os.path.join(OUT, "app-64.png")
    im.save(ico, format="ICO",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    im.resize((64, 64), Image.LANCZOS).save(png)
    print("wrote", ico)
    print("wrote", png)


if __name__ == "__main__":
    main()
