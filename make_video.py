"""인스타그램 릴스용 '이번 주 접수 시작' 영상 생성 (1080x1920, 30fps, 약 30초)

사용법:  python3 make_video.py [기준일 YYYY-MM-DD] [--region 서울|경기|경상]   (기본: 오늘, KST / 지역 없으면 전국 '이번 주 접수 시작')
결과:    video/reel_YYYYMMDD.mp4, video/caption_YYYYMMDD.txt
필요:    ffmpeg, Pillow, 한글 글꼴(Noto Sans CJK KR)
"""
import json, os, random, re, subprocess, sys, shutil
from datetime import datetime, date, timedelta
from PIL import Image, ImageDraw, ImageFont, ImageOps
from collect_myhome import DATA, HERE, KST

W, H, FPS = 1080, 1920, 30
SITE = "dia1117sq.github.io/korea-lease-notice"
OUT = os.path.join(HERE, "video")
TMP = os.path.join(OUT, "_tmp")

# 사이트와 같은 색
BG, SURF, INK, MUTED, LINE = (245, 246, 244), (255, 255, 255), (27, 35, 33), (95, 107, 103), (225, 229, 226)
ACCENT, ACCENT_SOFT, BLUE, BLUE_SOFT, URGENT = (31, 107, 92), (227, 240, 236), (36, 89, 168), (230, 238, 250), (194, 54, 43)

FONT_DIRS = ["/usr/share/fonts/opentype/noto", "/usr/share/fonts/noto-cjk", "/System/Library/Fonts"]


def font(weight, size):
    names = {"black": "NotoSansCJK-Black.ttc", "bold": "NotoSansCJK-Bold.ttc",
             "medium": "NotoSansCJK-Medium.ttc", "regular": "NotoSansCJK-Regular.ttc"}
    fallback = {"black": ["black", "bold"], "bold": ["bold", "black"],
                "medium": ["medium", "regular", "bold"], "regular": ["regular", "medium", "bold"]}[weight]
    for w in fallback:                               # 없는 굵기는 가까운 굵기로 대신
        for d in FONT_DIRS:
            p = os.path.join(d, names[w])
            if os.path.exists(p):
                return ImageFont.truetype(p, size, index=1)   # index 1 = KR
    raise SystemExit("한글 글꼴(Noto Sans CJK)을 찾을 수 없습니다: sudo apt-get install fonts-noto-cjk fonts-noto-cjk-extra")


SHORT = {"서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "광주광역시": "광주",
         "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종", "경기도": "경기", "강원특별자치도": "강원",
         "충청북도": "충북", "충청남도": "충남", "전북특별자치도": "전북", "전라남도": "전남",
         "전남광주통합특별시": "전남·광주", "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주"}
WD = "월화수목금토일"


def md(s):
    d = s if isinstance(s, date) else date.fromisoformat(s)
    return f"{d.month}.{d.day}({WD[d.weekday()]})"


def man(v):
    v = int(v or 0)
    if v >= 100_000_000:
        e, m = divmod(v, 100_000_000)
        return f"{e}억" + (f" {round(m / 10000):,}만" if m >= 10000 else "") + "원"
    if v >= 100_000:
        return f"{round(v / 10000):,}만원"
    return f"{v / 10000:.1f}만원".replace(".0만", "만")


def clean_title(t):
    t = re.sub(r"\[[^\]]*\]", "", t)
    t = re.sub(r"\(\s*['‘’]?\d{2,4}[.\s]\d{1,2}[.\s]?\d{0,2}\.?\s*\)", "", t)
    t = re.sub(r",\s*", ", ", t)
    t = re.sub(r"\s+", " ", t).strip(" -_")
    return t


def is_public(n):
    t = n.get("유형") or ""
    if "민영" in t or "임의공급" in t or "잔여세대" in t or "오피스텔" in t:
        return False
    org = n.get("공급기관") or ""
    return org in ("LH", "SH") or "공사" in org or any(k in t for k in ("국민", "공공", "임대", "행복", "영구", "수요자맞춤", "희망하우징"))


def pick(items, start, end, k=10):
    """이번 주 접수 시작 공공주택을 공급 규모순으로 k개. 1차로 시·도가 겹치지 않게 고르고, 모자라면 규모순으로 채움."""
    c = [n for n in items if n["접수상태"] in ("접수예정", "접수중") and n["접수시작"] and start <= n["접수시작"] <= end and is_public(n)]
    c.sort(key=lambda n: -(n["총공급호수"] or 0))
    out, seen = [], set()
    for n in c:
        if n["시도"] not in seen:
            out.append(n); seen.add(n["시도"])
        if len(out) == k: break
    for n in c:
        if len(out) == k: break
        if n not in out: out.append(n)
    out.sort(key=lambda n: -(n["총공급호수"] or 0))   # 순위 = 공급 규모
    return out


REGIONS = {   # 요일별 지역 영상: 키 → (시·도 목록, 화면 표시 이름, 파일 이름용)
    "서울": (["서울특별시"], "서울", "seoul"),
    "경기": (["경기도"], "경기", "gyeonggi"),
    "경상": (["경상북도", "경상남도", "부산광역시", "대구광역시", "울산광역시"], "경상권", "gyeongsang"),
}


def region_live(items, sidos, today):
    """지역의 지금 신청 가능한(접수중·접수예정, 마감 전) 공고"""
    t = today.isoformat()
    return [n for n in items if n["시도"] in sidos and n["접수상태"] in ("접수중", "접수예정")
            and (not n["접수마감"] or n["접수마감"] >= t)]


def pick_region(live, k=10):
    """공공주택을 공급 규모순으로 먼저, 모자라면 민간 분양 등으로 채움"""
    pub = sorted([n for n in live if is_public(n)], key=lambda n: -(n["총공급호수"] or 0))
    etc = sorted([n for n in live if not is_public(n)], key=lambda n: -(n["총공급호수"] or 0))
    return (pub + etc)[:k]


def rent_text(n):
    dep = [d.get("임대보증금") for d in n.get("단지", []) if d.get("임대보증금")]
    mon = [d.get("월임대료") for d in n.get("단지", []) if d.get("월임대료")]
    if not dep and not mon:
        return None
    s = []
    if dep: s.append(f"보증금 {man(min(dep))}" + ("~" if len(set(dep)) > 1 else ""))
    if mon: s.append(f"월 {man(min(mon))}" + ("~" if len(set(mon)) > 1 else ""))
    return " · ".join(s)


# ---------- 그리기 도구 ----------
def wrap(draw, text, f, maxw, max_lines):
    words, lines, cur = text.split(" "), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=f) <= maxw:
            cur = t; continue
        if cur: lines.append(cur)
        cur = w
        while draw.textlength(cur, font=f) > maxw:       # 띄어쓰기 없는 긴 단어는 글자 단위로
            i = len(cur)
            while draw.textlength(cur[:i], font=f) > maxw: i -= 1
            lines.append(cur[:i]); cur = cur[i:]
    if cur: lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while draw.textlength(lines[-1] + "…", font=f) > maxw: lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines


def layer(w, h):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def text_layer(lines, f, color, gap=1.25):
    asc, desc = f.getmetrics(); lh = int((asc + desc) * gap)
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    wmax = max(int(tmp.textlength(l, font=f)) for l in lines) + 4
    im, d = layer(wmax, lh * len(lines))
    for i, l in enumerate(lines):
        d.text((0, i * lh), l, font=f, fill=color)
    return im


def pill_layer(text, f, fg, bg, padx=28, pady=14, r=16):
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    tw = int(tmp.textlength(text, font=f)); asc, desc = f.getmetrics()
    im, d = layer(tw + padx * 2, asc + desc + pady * 2)
    d.rounded_rectangle([0, 0, im.width - 1, im.height - 1], r, fill=bg)
    d.text((padx, pady), text, font=f, fill=fg)
    return im


def ease(x):
    x = max(0.0, min(1.0, x)); return 1 - (1 - x) ** 3


BG_DIR = os.path.join(HERE, "assets", "bg")


def load_backgrounds():
    if not os.path.isdir(BG_DIR):
        return []
    fs = sorted(f for f in os.listdir(BG_DIR) if f.lower().endswith((".jpg", ".jpeg", ".png")))
    out = []
    for f in fs:
        im = Image.open(os.path.join(BG_DIR, f)).convert("RGB")
        r = max(W / im.width, H / im.height)            # 화면을 꽉 채우도록 자르기
        im = im.resize((round(im.width * r), round(im.height * r)), Image.LANCZOS)
        x, y = (im.width - W) // 2, (im.height - H) // 2
        out.append(im.crop((x, y, x + W, y + H)))
    return out


def tint_layer(kind):
    """사진 위 덧씌우기. 'dark' = 위아래 어두운 그라데이션(공고 카드), 'brand' = 반투명 초록."""
    im = Image.new("RGBA", (W, H))
    px = ImageDraw.Draw(im)
    for y in range(0, H, 4):
        t = y / H
        if kind == "dark":
            a = 0.62 - 0.22 * min(1, t / 0.45) + (0.3 * max(0, (t - 0.55) / 0.45))
            px.rectangle([0, y, W, y + 4], fill=(12, 20, 18, int(255 * a)))
        else:
            a = 0.70 + 0.12 * t
            px.rectangle([0, y, W, y + 4], fill=ACCENT + (int(255 * a),))
    return im


class Scene:
    """배경 + (레이어, x, y, 등장시각) 목록. 레이어는 0.45초 동안 아래에서 떠오르며 나타남."""
    def __init__(self, dur, bg, photo=None, tint=None):
        self.dur, self.bg, self.items, self.dynamic = dur, Image.new("RGBA", (W, H), bg + (255,)), [], []
        self.photo, self.tint = photo, (tint_layer(tint) if photo is not None and tint else None)
        if photo is not None:
            self.dynamic.append(lambda f, t: None)   # 매 프레임 다시 그림(배경이 움직이므로)
        self.label = None

    def base(self, t):
        if self.photo is None:
            return self.bg.copy()
        z = 1.0 + 0.07 * (t / self.dur)                  # 천천히 확대 (켄 번스)
        cw, ch = W / z, H / z
        x0, y0 = (W - cw) / 2, (H - ch) * 0.4
        f = self.photo.resize((W, H), Image.BILINEAR, box=(x0, y0, x0 + cw, y0 + ch)).convert("RGBA")
        if self.tint is not None:
            f.alpha_composite(self.tint)
        return f

    def add(self, im, x, y, at=0.0, rise=36):
        self.items.append((im, x, y, at, rise)); return im

    def frame(self, t):
        f = self.base(t)
        for im, x, y, at, rise in self.items:
            p = ease((t - at) / 0.45)
            if p <= 0: continue
            if p < 1:
                a = im.copy(); a.putalpha(a.getchannel("A").point(lambda v: int(v * p)))
                f.alpha_composite(a, (int(x), int(y + rise * (1 - p))))
            else:
                f.alpha_composite(im, (int(x), int(y)))
        for fn in self.dynamic:
            fn(f, t)
        if self.photo is not None:
            f.alpha_composite(EXAMPLE_LABEL, (W - M - EXAMPLE_LABEL.width, 196))
        return f.convert("RGB")

    def settled(self):
        return max([at + 0.45 for _, _, _, at, _ in self.items] + [0]) if not self.dynamic else self.dur

    def render(self, path):
        tmp = path[:-4] + ".part.mp4"
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
               "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
               "-pix_fmt", "yuv420p", "-r", str(FPS), tmp]
        pr = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        n, still, cut = round(self.dur * FPS), None, self.settled()
        for i in range(n):
            t = i / FPS
            if t >= cut + 1 / FPS:
                still = still or self.frame(t).tobytes()
                pr.stdin.write(still)
            else:
                pr.stdin.write(self.frame(t).tobytes())
        pr.stdin.close()
        if pr.wait() != 0:
            raise SystemExit(f"ffmpeg 실패: {path}")
        os.replace(tmp, path)


# ---------- 장면 ----------
EXAMPLE_LABEL = None


def make_label():
    global EXAMPLE_LABEL
    EXAMPLE_LABEL = pill_layer("이미지는 예시입니다", font("medium", 28), (255, 255, 255, 230), (0, 0, 0, 110), padx=16, pady=8, r=10)

M = 90   # 좌우 여백 (인스타그램 UI를 피해 위 240px, 아래 380px 안쪽에 내용 배치)


def scene_hook(start, end, total, picks, photo=None, part=1, parts=2, lo=1, hi=5, lines=None, date_text=None):
    s = Scene(3.5, ACCENT, photo, "brand")
    y = 300
    row, d = layer(W - 2 * M, 80)
    p1 = pill_layer(f"PART {part}/{parts} · {lo}~{hi}위", font("black", 42), (255, 255, 255), (12, 20, 18, 150))
    p2 = pill_layer(date_text or f"{md(start)} ~ {md(end)}", font("bold", 42), ACCENT, (255, 255, 255, 235))
    row.alpha_composite(p1, (0, 0)); row.alpha_composite(p2, (p1.width + 16, 0))
    s.add(row, M, y, 0.0)
    y += p1.height + 50
    tl = s.add(text_layer(lines or ["이번 주", "접수 시작하는", "공공주택"], font("black", 120), (255, 255, 255), 1.18), M, y, 0.15)
    y += tl.height + 10
    num_f, unit_f = font("black", 240), font("black", 100)
    ny = y

    def counter(f, t):   # 숫자 카운트업
        p = ease((t - 0.55) / 0.9)
        if p <= 0: return
        d = ImageDraw.Draw(f)
        val = f"{round(total * p)}"
        d.text((M - 8, ny), val, font=num_f, fill=(255, 255, 255))
        x = M + d.textlength(val, font=num_f) + 16
        d.text((x, ny + 150), "건", font=unit_f, fill=(255, 255, 255))
    s.dynamic.append(counter)
    s.add(text_layer([f"공급 규모 {lo}~{hi}위를 소개해요"], font("bold", 52), (255, 255, 255)), M, ny + 330, 1.2)
    other = f"6~10위는 다음 영상에서 이어져요 ▶" if part == 1 else "◀ 1~5위는 이전 영상에서 확인하세요"
    if parts > 1:
        s.add(text_layer([other.replace("▶", "→").replace("◀", "←")], font("medium", 44), (210, 232, 225)), M, ny + 410, 1.4)
    return s


def scene_card(i, n, today, photo=None, total=5):
    s = Scene(4.5, BG, photo, "dark")
    on_photo = photo is not None
    title_col = (255, 255, 255) if on_photo else INK
    sub_col = (215, 225, 221) if on_photo else MUTED
    track = (255, 255, 255, 90) if on_photo else LINE
    is_rent = n["구분"] == "임대"
    col, soft = (ACCENT, ACCENT_SOFT) if is_rent else (BLUE, BLUE_SOFT)
    # 진행 표시
    prog, d = layer(W - 2 * M, 60)
    d.text((0, 0), f"{i:02d}", font=font("black", 44), fill=(255, 255, 255) if on_photo else col)
    d.text((62, 6), f"/ {total:02d}위", font=font("medium", 36), fill=sub_col)
    bar = (255, 255, 255) if on_photo else col
    seg = (W - 2 * M - 230) / total
    for k in range(total):
        x0 = 230 + k * seg
        d.rounded_rectangle([x0, 24, x0 + seg - 10, 32], 4, fill=bar if k < i else track)
    s.add(prog, M, 280, 0.0, rise=0)
    # 구분 칩 + D-day
    typ = (n.get("유형") or "").replace("APT 국민", "공공분양(국민주택)").replace("APT", "아파트").strip()
    chip = pill_layer(f"{n['구분']} · {typ}", font("bold", 42), col, soft)
    s.add(chip, M, 400, 0.05)
    dd = (date.fromisoformat(n["접수시작"]) - today).days if n.get("접수시작") else -1
    if dd > 1: badge = f"접수 D-{dd}"
    elif dd == 1: badge = "내일 접수 시작"
    elif dd == 0: badge = "오늘 접수 시작"
    else:   # 이미 접수 중: 마감까지 남은 날
        left = (date.fromisoformat(n["접수마감"]) - today).days if n.get("접수마감") else None
        badge = "접수중" if left is None or left > 60 else ("오늘 마감" if left == 0 else f"마감 D-{left}")
    s.add(pill_layer(badge, font("bold", 42), (255, 255, 255), URGENT), M + chip.width + 18, 400, 0.05)
    # 지역 + 공고명
    region = SHORT.get(n["시도"], n["시도"])
    if n.get("시군구") and len(n.get("단지", [])) <= 1: region += " " + n["시군구"]
    s.add(text_layer([region], font("bold", 54), sub_col), M, 535, 0.12)
    tmpd = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    tf = font("black", 84)
    lines = wrap(tmpd, clean_title(n["공고명"]), tf, W - 2 * M, 3)
    title = s.add(text_layer(lines, tf, title_col, 1.22), M, 620, 0.18)
    # 정보 카드
    rows = []
    if n.get("총공급호수"): rows.append(("공급", f"{int(n['총공급호수']):,}호"))
    far = n["접수마감"] and n["접수마감"] > (today + timedelta(days=60)).isoformat()
    if n.get("접수시작"):
        rows.append(("접수", md(n["접수시작"]) + ("부터" if far else f" ~ {md(n['접수마감'])}" if n["접수마감"] and n["접수마감"] != n["접수시작"] else "")))
    else:
        rows.append(("접수", f"~ {md(n['접수마감'])}" if n.get("접수마감") else "모집중 · 공고문 확인"))
    if is_rent:
        dep = [d.get("임대보증금") for d in n.get("단지", []) if d.get("임대보증금")]
        mon = [d.get("월임대료") for d in n.get("단지", []) if d.get("월임대료")]
        if dep: rows.append(("보증금", man(min(dep)) + ("부터" if len(set(dep)) > 1 else "")))
        if mon: rows.append(("월 임대료", man(min(mon)) + ("부터" if len(set(mon)) > 1 else "")))
    ann = n.get("당첨발표")
    if ann and n.get("접수시작") and n["접수시작"] <= ann <= (date.fromisoformat(n["접수시작"]) + timedelta(days=120)).isoformat():
        rows.append(("당첨 발표", md(ann)))
    if n.get("공급기관"): rows.append(("공급기관", n["공급기관"][:20]))
    rows = rows[:5]
    lab, val = font("medium", 40), font("bold", 50)
    rh = 118
    card, d = layer(W - 2 * M, 44 + rh * len(rows))
    d.rounded_rectangle([0, 0, card.width - 1, card.height - 1], 28, fill=SURF, outline=LINE, width=2)
    for k, (a, b) in enumerate(rows):
        y = 22 + k * rh
        if k: d.line([40, y, card.width - 40, y], fill=LINE, width=2)
        d.text((44, y + 34), a, font=lab, fill=MUTED)
        vv = b
        while d.textlength(vv, font=val) > card.width - 290 and len(vv) > 4: vv = vv[:-2] + "…"
        d.text((250, y + 28), vv, font=val, fill=INK)
    top = 620 + title.height + 50
    s.add(card, M, top, 0.3)
    if top + card.height + 44 < 1450:   # 인스타그램 하단 캡션 영역(약 1500px 아래)과 겹치지 않을 때만
        s.add(text_layer(["자격·조건은 사이트에서 확인하세요"], font("medium", 40), sub_col), M, top + card.height + 44, 0.5)
    return s


def scene_cta(more, photo=None, part=1, parts=1, more_text=None):
    s = Scene(4.0, ACCENT, photo, "brand")
    y = 300
    if parts > 1:
        box2, d2 = layer(W - 2 * M, 150)
        d2.rounded_rectangle([0, 0, box2.width - 1, box2.height - 1], 26, fill=(12, 20, 18, 150), outline=(255, 255, 255, 120), width=2)
        if part == 1:
            d2.text((40, 26), "PART 2 · 6~10위", font=font("bold", 38), fill=(210, 232, 225))
            d2.text((40, 76), "다음 영상에서 이어져요  →", font=font("black", 50), fill=(255, 255, 255))
        else:
            d2.text((40, 26), "PART 1 · 1~5위", font=font("bold", 38), fill=(210, 232, 225))
            d2.text((40, 76), "←  이전 영상도 확인하세요", font=font("black", 50), fill=(255, 255, 255))
        s.add(box2, M, y, 0.0)
        y += box2.height + 60
    if more > 0:
        a = s.add(text_layer([(more_text or "이번 주 공고 {n}건 더 있어요").format(n=more)], font("bold", 52), (210, 232, 225)), M, y, 0.1)
        y += a.height + 24
    b = s.add(text_layer(["전국 공공임대·분양", "모집공고 한눈에"], font("black", 96), (255, 255, 255), 1.2), M, y, 0.18)
    y += b.height + 24
    c = s.add(text_layer(["매일 아침 자동 업데이트 · 마감 임박순"], font("medium", 46), (210, 232, 225)), M, y, 0.25)
    y += c.height + 70
    box, d = layer(W - 2 * M, 250)
    d.rounded_rectangle([0, 0, box.width - 1, box.height - 1], 30, fill=(255, 255, 255))
    d.text((48, 42), "프로필 링크에서 바로 보기", font=font("black", 62), fill=ACCENT)
    uf = 44
    while ImageDraw.Draw(box).textlength(SITE, font=font("bold", uf)) > box.width - 96: uf -= 2
    d.text((48, 156), SITE, font=font("bold", uf), fill=MUTED)
    s.add(box, M, y, 0.4)
    y += box.height + 44
    if y < 1440:
        s.add(text_layer(["저장해두고 신청 일정 놓치지 마세요"], font("medium", 44), (255, 255, 255)), M, y, 0.6)
    return s


def caption(picks, start, end, total, part=1, parts=1, offset=0, head_text=None, tags=""):
    lo, hi = offset + 1, offset + len(picks)
    head = (head_text or "📢 이번 주({s}~{e}) 접수 시작하는 공공주택 {t}건 — 공급 규모 {lo}~{hi}위").format(
        s=md(start), e=md(end), t=total, lo=lo, hi=hi)
    if parts > 1: head = f"[PART {part}/{parts}] " + head
    L = [head, ""]
    for k, n in enumerate(picks, lo):
        ln = f"{k}. [{SHORT.get(n['시도'], n['시도'])}] {clean_title(n['공고명'])}"
        ln += f" — {n['총공급호수']:,}호" if n.get("총공급호수") else ""
        L.append(ln)
        if not n.get("접수시작"):
            L.append("   모집중 (일정은 공고문 확인)"); continue
        far = n["접수마감"] and n["접수마감"] > (date.fromisoformat(n["접수시작"]) + timedelta(days=60)).isoformat()
        L.append(f"   접수 {md(n['접수시작'])}" + ("부터 (선착순)" if far else f" ~ {md(n['접수마감'])}" if n["접수마감"] and n["접수마감"] != n["접수시작"] else ""))
    if parts > 1:
        L += ["", "👉 6~10위는 PART 2 영상에서 이어집니다" if part == 1 else "👈 1~5위는 PART 1 영상에서 확인하세요"]
    L += ["", "전체 공고와 자격 조건은 프로필 링크에서 확인하세요 👉 " + SITE, "",
          "※ 공공데이터(마이홈·LH·청약홈)와 서울주거포털(SH) 기준이며, 신청 전 공고문 원문을 꼭 확인하세요.", "",
          ((tags + " ") if tags else "") + "#공공임대 #국민임대 #행복주택 #공공분양 #청약 #LH청약 #임대주택 #청약정보 #내집마련 #주거복지"]
    return "\n".join(L)


def main():
    dates = [a for a in sys.argv[1:] if re.match(r"\d{4}-\d{2}-\d{2}$", a)]
    today = date.fromisoformat(dates[0]) if dates else datetime.now(KST).date()
    region = sys.argv[sys.argv.index("--region") + 1] if "--region" in sys.argv else None
    start, end = today, today + timedelta(days=6)   # 월요일 게시 기준: 월~일
    items = json.load(open(os.path.join(DATA, "merged.json"), encoding="utf-8"))["items"]
    if region:
        sidos, label, slug = REGIONS[region]
        week = region_live(items, sidos, today)      # 지역에서 지금 신청 가능한 전체 공고
        picks = pick_region(week)
        texts = dict(lines=["지금 신청 가능한", f"{label}", "모집공고"], date_text=f"{md(today)} 기준",
                     more_text=f"{label} 공고 {{n}}건 더 있어요",
                     head_text=f"📢 {label} 지금 신청 가능한 공공임대·분양 {{t}}건 — 공급 규모 {{lo}}~{{hi}}위 ({md(today)} 기준)",
                     tags=f"#{label}임대 #{label}청약 #{label}공공임대")
    else:
        slug = ""
        week = [n for n in items if n["접수상태"] in ("접수예정", "접수중") and n["접수시작"] and start.isoformat() <= n["접수시작"] <= end.isoformat() and is_public(n)]
        picks = pick(items, start.isoformat(), end.isoformat(), k=10)
        texts = {}
    if len(picks) < 3:
        raise SystemExit(f"소개할 공고가 부족합니다 ({len(picks)}건)")
    groups = [picks[:5], picks[5:10]] if len(picks) >= 8 else [picks[:5]]   # 6~10위가 3건 미만이면 한 편만
    parts, total = len(groups), len(picks)
    make_label()
    bgs = load_backgrounds()
    # 날짜로 섞어서 매주 다른 조합, 두 편이 서로 겹치지 않게. 절반은 좌우 반전.
    rng = random.Random(today.toordinal())
    order = list(range(len(bgs))); rng.shuffle(order)
    flips = [rng.random() < 0.5 for _ in range(32)]
    def bg(k):
        if not bgs: return None
        im = bgs[order[k % len(bgs)]]
        return ImageOps.mirror(im) if flips[k % 32] else im
    tag = today.strftime("%Y%m%d")
    for pi, grp in enumerate(groups):
        part, off = pi + 1, pi * 5
        lo, hi = off + 1, off + len(grp)
        os.makedirs(TMP, exist_ok=True)
        b0 = pi * (len(grp) + 2)
        scenes = [scene_hook(start, end, len(week), grp, bg(b0), part, parts, lo, hi,
                             texts.get("lines"), texts.get("date_text"))] + \
                 [scene_card(off + i, n, today, bg(b0 + i), total) for i, n in enumerate(grp, 1)] + \
                 [scene_cta(max(0, len(week) - total), bg(b0 + len(grp) + 1), part, parts, texts.get("more_text"))]
        files = []
        for k, sc in enumerate(scenes):
            p = os.path.join(TMP, f"s{k:02d}.mp4"); sc.render(p); files.append(p)
        lst = os.path.join(TMP, "list.txt")
        open(lst, "w").write("".join(f"file '{f}'\n" for f in files))
        suffix = (f"_{slug}" if slug else "") + (f"_{part}" if parts > 1 else "")
        out = os.path.join(OUT, f"reel_{tag}{suffix}.mp4"); prt = out[:-4] + ".part.mp4"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
                        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-c:v", "copy", "-c:a", "aac",
                        "-shortest", "-movflags", "+faststart", prt], check=True)
        os.replace(prt, out)
        open(os.path.join(OUT, f"caption_{tag}{suffix}.txt"), "w", encoding="utf-8").write(
            caption(grp, start, end, len(week), part, parts, off, texts.get("head_text"), texts.get("tags", "")))
        shutil.rmtree(TMP, ignore_errors=True)
        print("완성:", out)


if __name__ == "__main__":
    main()
