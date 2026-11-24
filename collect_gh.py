"""GH(경기주택도시공사) 임대 공고 수집 — GH주택청약·임대센터(apply.gh.or.kr) 목록·상세 페이지

공식 API가 없어 GH주택청약·임대센터의 '임대주택 청약공고', '매입임대 청약공고' 목록을 읽습니다.
상세 페이지는 목록에서 넘겨주는 값(POST)으로만 열려서, 같은 세션 쿠키로 요청합니다.
사용법:  python3 collect_gh.py
결과:    data/gh_notices.json  (접수예정·접수중이거나 마감일이 지나지 않은 공고)
"""
import html, http.cookiejar, json, os, re, time, urllib.parse, urllib.request
from datetime import datetime, timedelta
from collect_myhome import DATA, KST

BASE = "https://apply.gh.or.kr"
LISTS = {  # 목록 경로 → 상세 경로
    "/sb/sr/sr7150/selectPbancRentHouseList.do": "/sb/sr/sr7150/selectPbancDetailView.do",
    "/sb/sr/sr7155/selectPbancRentHouseList.do": "/sb/sr/sr7155/selectPbancDetailView.do",
}
UA = "Mozilla/5.0 (compatible; korea-lease-notice/1.0; +https://dia1117sq.github.io/korea-lease-notice/)"
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

SIGUN_SIDO = {"인천": "인천광역시", "서울": "서울특별시"}


def req(path, data=None, referer=None):
    headers = {"User-Agent": UA}
    if referer: headers["Referer"] = BASE + referer
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    for attempt in range(3):
        try:
            with opener.open(urllib.request.Request(BASE + path, data=body, headers=headers), timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            if attempt == 2: raise
            time.sleep(3)


def text(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<(script|style).*?</\1>|<[^>]+>", " ", s, flags=re.S))).strip()


def rows(page):
    body = page[page.find("<tbody"):]
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
        a = re.search(r'data-previewYn="(\w*)"\s*data-pbancNo="(\d+)"\s*data-pbancKndCd="(\w*)"\s*data-bizTyNm="([^"]*)"', tr)
        cells = [text(c) for c in re.findall(r"<td[^>]*>(.*?)(?=<td|</tr>|$)", tr, re.S)]
        if a and len(cells) >= 8:
            yield a.groups(), cells


DATE = r"(20\d\d)\.(\d\d)\.(\d\d)"


def iso(m, i=1):
    return f"{m.group(i)}-{m.group(i + 1)}-{m.group(i + 2)}"


def parse_detail(page):
    t = text(page[page.find("sub_content"):])
    out = {"접수시작": "", "접수마감": "", "공급호수": 0, "당첨발표": "", "주소": [], "단지": []}
    m = re.search(r"(온라인접수기간|인터넷접수기간|현장접수기간|접수기간|신청기간)\s*:\s*" + DATE + r"[^~]{0,8}~\s*" + DATE, t)
    if m:
        out["접수시작"], out["접수마감"] = iso(m, 2), iso(m, 5)
    m = re.search(r"(당첨자\s*발표일|서류제출대상자\s*발표일|발표일)\s*:\s*" + DATE, t)
    if m:
        out["당첨발표"] = iso(m, 2)
    for name, addr, n in re.findall(r"지구명\s*(.*?)\s*소재지\s*(.*?)\s*전용면적.*?모집호수\s*([\d,]+)", t):
        out["단지"].append({"단지명": name, "주소": addr, "공급호수": int(n.replace(",", ""))})
    out["공급호수"] = sum(d["공급호수"] for d in out["단지"])
    if not out["공급호수"]:
        s = sum(int(x) for x in re.findall(r"\d+\.\d+\s+(\d+)\s+(?:공고문 확인|[\d,]+)", t))
        out["공급호수"] = s
    return out


def main():
    today = datetime.now(KST).date().isoformat()
    since = (datetime.now(KST).date() - timedelta(days=60)).isoformat()
    items = []
    for lpath, dpath in LISTS.items():
        for page_no in range(1, 4):
            page = req(lpath, {"pageIndex": page_no}) if page_no > 1 else req(lpath)
            got = list(rows(page))
            if not got: break
            old = 0
            for (preview, no, knd, biz), cells in got:
                _, typ, title, area = cells[:4]
                rest = [c for c in cells[4:] if c]
                dates = [c for c in rest if re.fullmatch(r"\d{4}-\d{2}-\d{2}", c)]
                posted = dates[0] if dates else ""
                deadline = dates[1] if len(dates) > 1 else ""
                state = next((c for c in rest if c in ("공고중", "접수중", "접수마감")), "")
                if posted and posted < since: old += 1; continue
                if state == "접수마감" or (deadline and deadline < today): continue
                if not state and not deadline: continue          # 상시·운영기관 모집(마감일 없음)은 제외
                items.append({"no": no, "knd": knd, "biz": biz, "preview": preview, "유형": typ,
                              "공고명": title, "지역": area, "공고일": posted, "마감일": deadline,
                              "상태": state, "list": lpath, "detail": dpath})
            if old == len(got): break
            time.sleep(0.5)
    out = []
    for n in items:
        try:
            page = req(n["detail"], {"previewYn": n["preview"] or "N", "pbancNo": n["no"], "pbancKndCd": n["knd"],
                                     "bizTyNm": n["biz"], "pageIndex": 1}, referer=n["list"])
            d = parse_detail(page)
        except Exception as e:
            print("상세 실패:", n["공고명"], e); d = parse_detail("")
        addr = " ".join(x["주소"] for x in d["단지"])
        sido = next((v for k, v in SIGUN_SIDO.items() if addr.startswith(k) or n["지역"].startswith(k)), "경기도")
        out.append({
            "id": f"GH-{n['no']}", "구분": "임대", "유형": n["유형"], "공고명": n["공고명"],
            "공급기관": "GH", "시도": sido, "시군구": n["지역"] if n["지역"] != "경기도" else "",
            "모집공고일": n["공고일"], "접수시작": d["접수시작"], "접수마감": d["접수마감"] or n["마감일"],
            "당첨발표": d["당첨발표"], "총공급호수": d["공급호수"], "단지": d["단지"],
            "GH상태": n["상태"], "공고원문URL": BASE + n["list"], "문의": "GH 콜센터 1588-0466",
        })
        time.sleep(0.5)
    os.makedirs(DATA, exist_ok=True)
    json.dump({"collected_at": datetime.now(KST).isoformat(), "count": len(out), "items": out},
              open(os.path.join(DATA, "gh_notices.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"GH 진행 공고 {len(out)}건 저장")


if __name__ == "__main__":
    main()
