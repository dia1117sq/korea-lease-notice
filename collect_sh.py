"""SH(서울주택도시개발공사) 임대·분양 공고 수집 — 서울주거포털(housing.seoul.go.kr) 목록·상세 페이지

공식 API가 없어 서울시 서울주거포털의 SH 공고 목록을 읽습니다 (robots.txt 전체 허용).
사용법:  python3 collect_sh.py
결과:    data/sh_notices.json  (모집중 공고 + 마감 전 분양 공고, 상세 본문에서 신청기간·공급호수·발표일 추출)
"""
import html, json, os, re, time, urllib.request
from datetime import date, datetime, timedelta
from collect_myhome import DATA, KST

BASE = "https://housing.seoul.go.kr"
LISTS = {"임대": "/site/main/sh/publicLease/list", "분양": "/site/main/sh/publicSale/list"}
UA = {"User-Agent": "Mozilla/5.0 (compatible; korea-lease-notice/1.0; +https://dia1117sq.github.io/korea-lease-notice/)"}


def get(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            if attempt == 2: raise
            time.sleep(3)


def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def rows(page):
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = [text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        links = [html.unescape(l) for l in re.findall(r'href="([^"]+)"', tr)]
        if len(cells) >= 6:
            yield cells, links


def ymd(y, m, d):
    try: return date(int(y), int(m), int(d))
    except ValueError: return None


DATE = r"(20\d\d)\s*[.\-]\s*(\d{1,2})\s*[.\-]\s*(\d{1,2})"


def parse_detail(body, posted):
    """본문에서 신청기간 / 공급호수 / 발표일 추출 (없으면 빈 값)"""
    t = text(re.sub(r"<br\s*/?>|</p>|</li>", "\n", body))
    out = {"접수시작": "", "접수마감": "", "공급호수": 0, "당첨발표": ""}
    m = re.search(r"(신청기간|접수기간|청약기간|청약접수|인터넷\s*접수)[^0-9]{0,15}" + DATE + r"[^~]{0,25}~\s*(?:" + DATE + r"|(\d{1,2})\s*\.\s*(\d{1,2}))", t)
    if m:
        b = ymd(*m.group(2, 3, 4))
        if m.group(5):
            e = ymd(*m.group(5, 6, 7))
        else:
            e = ymd(b.year, m.group(8), m.group(9)) if b else None
        if b and e and e < b:                       # 공고문 연도 오타(예: 2026.11.30 ~ 2025.12.04) 보정
            e = ymd(b.year if (e.month, e.day) >= (b.month, b.day) else b.year + 1, e.month, e.day)
        if b: out["접수시작"] = b.isoformat()
        if e: out["접수마감"] = e.isoformat()
    m = re.search(r"(공급호수|공급세대|모집호수|모집세대|공급\s*규모|공급물량|모집인원)[^0-9]{0,12}([\d,]+)\s*(세대|호|가구|명)", t)
    if m:
        out["공급호수"] = int(m.group(2).replace(",", ""))
    m = re.search(r"(당첨자\s*발표|예비입주자\s*발표|서류심사대상자\s*발표|발표)[^0-9]{0,12}" + DATE, t)
    if m:
        d = ymd(*m.group(2, 3, 4))
        if d: out["당첨발표"] = d.isoformat()
    return out


def main():
    today = datetime.now(KST).date()
    since = today - timedelta(days=150)
    items = []
    for kind, path in LISTS.items():
        for cp in range(1, 6):
            page = get(f"{BASE}{path}?cp={cp}")
            got = list(rows(page))
            if not got: break
            old = 0
            for cells, links in got:
                _, typ, title, posted, announce, status = cells[:6]
                title = title.lstrip("-> ").strip()
                if not re.match(r"\d{4}-\d{2}-\d{2}", posted): continue
                if posted < since.isoformat(): old += 1; continue
                view = next((l for l in links if "/view?" in l), "")
                if not view: continue
                sid = re.search(r"seq=(\d+)", view)
                items.append({"구분": kind, "유형": typ, "공고명": title, "공고일": posted,
                              "발표일": announce if re.match(r"\d{4}-", announce) else "",
                              "상태": status, "view": BASE + view.split("&cp=")[0] + f"&supplyType={'publicLease' if kind == '임대' else 'publicSale'}",
                              "seq": sid.group(1) if sid else ""})
            if old == len(got): break
            time.sleep(0.5)
    # 진행 중(모집중) 공고와 아직 발표 전인 분양 공고만 상세 조회
    keep = [n for n in items if n["상태"] == "모집중" or (n["구분"] == "분양" and (n["발표일"] or "") >= today.isoformat())]
    out = []
    for n in keep:
        try:
            page = get(n["view"])
        except Exception as e:
            print("상세 실패:", n["공고명"], e); continue
        body = re.search(r"상세\s*정보(.*?)(목록</a>|id=\"footer\"|<footer)", page, re.S)
        d = parse_detail(body.group(1) if body else page, n["공고일"])
        out.append({
            "id": f"SH-{n['구분']}-{n['seq']}", "구분": n["구분"], "유형": n["유형"], "공고명": n["공고명"],
            "공급기관": "SH", "시도": "서울특별시", "모집공고일": n["공고일"],
            "접수시작": d["접수시작"], "접수마감": d["접수마감"],
            "당첨발표": d["당첨발표"] or n["발표일"], "총공급호수": d["공급호수"],
            "SH상태": n["상태"], "공고원문URL": n["view"], "문의": "SH 콜센터 1600-3456",
        })
        time.sleep(0.5)
    os.makedirs(DATA, exist_ok=True)
    json.dump({"collected_at": datetime.now(KST).isoformat(), "count": len(out), "items": out},
              open(os.path.join(DATA, "sh_notices.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"SH 목록 {len(items)}건 중 진행 공고 {len(out)}건 저장")


if __name__ == "__main__":
    main()
