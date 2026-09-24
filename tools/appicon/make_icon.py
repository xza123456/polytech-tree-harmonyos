#!/usr/bin/env python3
"""人类科技树 · 应用图标

太空视角的地球：深空黑底 + 星点/星云，蓝色地球带大气辉光，主光来自左上。
纯 PIL 实现（本机无 numpy），球面逐像素着色后 1.25x 超采样降采样。
产物：
  icon_foreground.png  前景：地球 + 大气辉光（透明底）
  icon_background.png  背景：深空渐变 + 星云 + 星点
  icon_full.png        合成图（兼容用单张图标）
"""
import math
import random

from PIL import Image, ImageDraw, ImageFilter

S = 1280                    # 内部渲染尺寸
OUT = 1024                  # 输出尺寸
CX = CY = S / 2.0
R = 440.0                   # 地球半径
GLOW = 1.20                 # 大气辉光外沿 = R * GLOW
random.seed(20260924)

# ───── 小工具 ─────
def smoothstep(a, b, x):
    t = (x - a) / (b - a)
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return t * t * (3.0 - 2.0 * t)


def unit(v):
    l = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / l, v[1] / l, v[2] / l)


def rand_dir():
    while True:
        v = (random.uniform(-1, 1), random.uniform(-1, 1), random.uniform(-1, 1))
        d = v[0] * v[0] + v[1] * v[1] + v[2] * v[2]
        if 0.06 < d <= 1.0:
            return unit(v)


def _hash3(i, j, k):
    n = (i * 374761393 + j * 668265263 + k * 1274126177) & 0x7FFFFFFF
    n = (n ^ (n >> 13)) * 1274126177 & 0x7FFFFFFF
    n = n ^ (n >> 16)
    return (n & 0xFFFF) / 65535.0


def vnoise3(x, y, z):
    """3D 值噪声：格点哈希 + 三线性插值，用来把球冠切成自然的海岸线。"""
    ix, iy, iz = math.floor(x), math.floor(y), math.floor(z)
    fx, fy, fz = x - ix, y - iy, z - iz
    ix, iy, iz = int(ix), int(iy), int(iz)
    ux = fx * fx * (3.0 - 2.0 * fx)
    uy = fy * fy * (3.0 - 2.0 * fy)
    uz = fz * fz * (3.0 - 2.0 * fz)

    def h(di, dj, dk):
        return _hash3(ix + di, iy + dj, iz + dk)

    c00 = h(0, 0, 0) + (h(1, 0, 0) - h(0, 0, 0)) * ux
    c10 = h(0, 1, 0) + (h(1, 1, 0) - h(0, 1, 0)) * ux
    c01 = h(0, 0, 1) + (h(1, 0, 1) - h(0, 0, 1)) * ux
    c11 = h(0, 1, 1) + (h(1, 1, 1) - h(0, 1, 1)) * ux
    c0 = c00 + (c10 - c00) * uy
    c1 = c01 + (c11 - c01) * uy
    return c0 + (c1 - c0) * uz


def fbm3(x, y, z, octaves=3):
    total = 0.0
    amp = 0.5
    freq = 1.0
    for _ in range(octaves):
        total += amp * vnoise3(x * freq, y * freq, z * freq)
        amp *= 0.5
        freq *= 2.0
    return total


# ───── 地貌：球面上的球冠叠加成高度场 ─────
LAND = []
for _ in range(4):                                     # 大陆核心：半径收小，海陆比才接近地球
    LAND.append((rand_dir(), math.cos(random.uniform(0.30, 0.56)), random.uniform(0.95, 1.30)))
for _ in range(14):                                    # 半岛 / 岛链 / 碎边
    LAND.append((rand_dir(), math.cos(random.uniform(0.09, 0.20)), random.uniform(0.40, 0.82)))

CLOUD = []
for _ in range(22):                                    # 碎云，避免糊成大块白斑
    CLOUD.append((rand_dir(), math.cos(random.uniform(0.10, 0.30)), random.uniform(0.55, 1.0)))

# 光照：来自左上偏前（z 分量给足，球体正面才不至于大片压黑）
L = unit((-0.52, -0.56, 0.65))
HV = unit((L[0], L[1], L[2] + 1.0))                    # 半程向量（视线沿 +z）

SEA_DEEP = (4, 18, 48)
SEA_MID = (11, 48, 98)
SEA_SHALLOW = (20, 66, 114)
LAND_LOW = (28, 64, 38)
LAND_MID = (48, 82, 44)
LAND_HIGH = (78, 92, 54)
ICE_COL = (226, 236, 248)
CLOUD_COL = (236, 243, 255)
GLOW_COL = (96, 166, 255)
LAND_SEA = 0.84                                        # 高度场判陆阈值


def shade_sphere():
    """渲染地球 + 大气辉光，返回 RGBA 图层。"""
    img = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    pad = 3
    x0 = max(0, int(CX - R * GLOW) - pad)
    x1 = min(S, int(CX + R * GLOW) + pad)
    y0 = max(0, int(CY - R * GLOW) - pad)
    y1 = min(S, int(CY + R * GLOW) + pad)

    rows = []
    glow_sq = GLOW * GLOW
    for y in range(y0, y1):
        fy = (y + 0.5 - CY) / R
        row = []
        for x in range(x0, x1):
            fx = (x + 0.5 - CX) / R
            d2 = fx * fx + fy * fy
            if d2 > glow_sq:
                row.append((0, 0, 0, 0))
                continue

            if d2 <= 1.0:
                # ── 球面着色 ──
                nz = math.sqrt(1.0 - d2)
                nx, ny = fx, fy

                # 高度场
                h = 0.0
                for (bx, by, bz), c0, w in LAND:
                    c = nx * bx + ny * by + nz * bz
                    if c > c0:
                        h += w * smoothstep(c0, 1.0, c)
                h_base = h
                # 高频噪声只用来切海岸线，不参与基色，否则陆地内部会被切成同心环
                if 0.42 < h < 1.20:
                    h += (fbm3(nx * 14.0 + 9.1, ny * 14.0 + 3.3, nz * 14.0 + 7.7) - 0.47) * 0.85
                is_land = h > LAND_SEA

                if is_land:
                    t = min(1.0, (h_base - LAND_SEA) / 1.70)
                    if t < 0.5:
                        k = t / 0.5
                        base = tuple(LAND_LOW[i] + (LAND_MID[i] - LAND_LOW[i]) * k for i in range(3))
                    else:
                        k = (t - 0.5) / 0.5
                        base = tuple(LAND_MID[i] + (LAND_HIGH[i] - LAND_MID[i]) * k for i in range(3))
                else:
                    t = smoothstep(0.66, LAND_SEA, h)
                    if t < 0.5:
                        k = t / 0.5
                        base = tuple(SEA_DEEP[i] + (SEA_MID[i] - SEA_DEEP[i]) * k for i in range(3))
                    else:
                        k = (t - 0.5) / 0.5
                        base = tuple(SEA_MID[i] + (SEA_SHALLOW[i] - SEA_MID[i]) * k for i in range(3))

                # 光照
                diff = nx * L[0] + ny * L[1] + nz * L[2]
                if diff < 0.0:
                    diff = 0.0
                lit = 0.075 + 1.02 * diff
                col = [base[i] * lit for i in range(3)]

                # 大气散射：边缘偏蓝，只出现在受光侧
                rim = (1.0 - nz) ** 3
                rr = rim * diff * 130.0
                col[0] += rr * 0.34
                col[1] += rr * 0.60
                col[2] += rr

                # 海洋镜面高光
                if not is_land:
                    nh = nx * HV[0] + ny * HV[1] + nz * HV[2]
                    if nh > 0.0:
                        spec = nh ** 90 * 0.55
                        col[0] += spec * 255
                        col[1] += spec * 250
                        col[2] += spec * 235

                # 极地冰盖：纬度越高越白，侧面（nz 小）压暗，暗面也保留一点反射光
                ice = smoothstep(0.80, 0.975, abs(ny)) * (0.22 + 0.78 * nz) * (0.42 + 0.58 * diff)
                if ice > 0.0:
                    col[0] += (ICE_COL[0] - col[0]) * ice
                    col[1] += (ICE_COL[1] - col[1]) * ice
                    col[2] += (ICE_COL[2] - col[2]) * ice

                # 云
                ch = 0.0
                for (bx, by, bz), c0, w in CLOUD:
                    c = nx * bx + ny * by + nz * bz
                    if c > c0:
                        ch += w * smoothstep(c0, 1.0, c)
                cl = smoothstep(0.74, 1.06, ch) * 0.70 * (0.06 + 0.94 * diff)
                if cl > 0.0:
                    col[0] += (CLOUD_COL[0] - col[0]) * cl
                    col[1] += (CLOUD_COL[1] - col[1]) * cl
                    col[2] += (CLOUD_COL[2] - col[2]) * cl

                row.append((
                    min(255, int(col[0])),
                    min(255, int(col[1])),
                    min(255, int(col[2])),
                    255,
                ))
            else:
                # ── 球外大气辉光 ──
                d = math.sqrt(d2)
                t = (d - 1.0) / (GLOW - 1.0)
                a = (1.0 - t) ** 2.4
                ux, uy = fx / d, fy / d
                d2f = ux * L[0] + uy * L[1]
                w = 0.28 + 0.72 * (d2f if d2f > 0.0 else 0.0)
                row.append((
                    GLOW_COL[0],
                    GLOW_COL[1],
                    GLOW_COL[2],
                    min(255, int(a * 255 * 0.92 * w)),
                ))
        rows.append(row)

    px = img.load()
    for j, row in enumerate(rows):
        y = y0 + j
        for i, c in enumerate(row):
            if c[3]:
                px[x0 + i, y] = c
    return img


# ───── 星空背景 ─────
def make_starfield():
    grad = Image.radial_gradient('L').resize((S, S), Image.BILINEAR)
    inv = Image.eval(grad, lambda v: 255 - v)
    bright = Image.new('RGB', (S, S), (14, 22, 46))
    dark = Image.new('RGB', (S, S), (2, 4, 10))
    bg = Image.composite(bright, dark, inv).convert('RGBA')

    # 星云
    neb = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    nd = ImageDraw.Draw(neb)
    for _ in range(4):
        nx0 = random.uniform(0, S)
        ny0 = random.uniform(0, S)
        nr = random.uniform(S * 0.20, S * 0.44)
        col = random.choice([(44, 76, 158, 36), (74, 52, 146, 30), (32, 92, 146, 28)])
        nd.ellipse([nx0 - nr, ny0 - nr, nx0 + nr, ny0 + nr], fill=col)
    neb = neb.filter(ImageFilter.GaussianBlur(S * 0.10))
    bg = Image.alpha_composite(bg, neb)

    # 星点
    sd = ImageDraw.Draw(bg)
    for _ in range(640):
        x = random.uniform(0, S)
        y = random.uniform(0, S)
        r = random.choice([0.6, 0.8, 0.9, 1.1, 1.3, 1.6, 2.0, 2.6])
        v = random.randint(120, 255)
        tint = random.choice([(v, v, v), (v, v, 255), (198, 218, 255), (255, 244, 224)])
        sd.ellipse([x - r, y - r, x + r, y + r], fill=(tint[0], tint[1], tint[2], random.randint(130, 255)))

    # 亮星柔光（一次性画完再统一模糊）
    halo = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    spots = []
    for _ in range(15):
        x = random.uniform(0, S)
        y = random.uniform(0, S)
        r = random.uniform(3.0, 6.0)
        spots.append((x, y, r))
        hd.ellipse([x - r * 4.5, y - r * 4.5, x + r * 4.5, y + r * 4.5], fill=(152, 194, 255, 44))
    halo = halo.filter(ImageFilter.GaussianBlur(9))
    bg = Image.alpha_composite(bg, halo)
    head = ImageDraw.Draw(bg)
    for (x, y, r) in spots:
        head.ellipse([x - r * 0.55, y - r * 0.55, x + r * 0.55, y + r * 0.55], fill=(255, 255, 255, 255))
    return bg


print('渲染地球…')
earth = shade_sphere()
print('渲染星空…')
stars = make_starfield()

earth.resize((OUT, OUT), Image.LANCZOS).save('icon_earth.png')
stars.resize((OUT, OUT), Image.LANCZOS).save('icon_background.png')
Image.alpha_composite(stars, earth).resize((OUT, OUT), Image.LANCZOS).convert('RGB').save('icon_full.png')

# 前景：系统会把 foreground 整体缩放后叠加，先放大 1.13 倍，地球才不会被留白压小。
# 放大后辉光外沿仍在画布内，不会被裁。
ZOOM = 1.131
big = earth.resize((int(OUT * ZOOM), int(OUT * ZOOM)), Image.LANCZOS)
off = (big.width - OUT) // 2
fg = big.crop((off, off, off + OUT, off + OUT))
fg.save('icon_foreground.png')
fg.resize((144, 144), Image.LANCZOS).save('icon_start.png')
print('完成：icon_foreground.png / icon_background.png / icon_full.png / icon_start.png')
