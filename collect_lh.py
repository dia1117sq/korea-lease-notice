"""LH 분양임대공고문 수집기 (B552555/lhLeaseNoticeInfo1)

사용법:  python3 collect_lh.py [조회일수=60] [--all]   (--all: 상가·토지 포함)
결과:    data/lh_notices.json, data/lh_notices.csv, data/lh_new_YYYYMMDD.json
※ PAN_ID / SPL_INF_TP_CD / CCR_CNNT_SYS_DS_CD / UPP_AIS_TP_CD / AIS_TP_CD 는
  LH 공급정보·상세정보 API를 부를 때 그대로 넣는 키라서 보존합니다.
"""
import csv, json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta
from collect_myhome import load_key, HERE, DATA, KST

URL = "https://apis.data.go.kr/B552555/lhLeaseNoticeInfo1/lhLeaseNoticeInfo1"
ROWS = 100
HOUSING = {"분양주택", "임대주택", "주거복지", "신혼희망타운"}   # 상가·토지 제외


def fetch(key, page, st, ed):
    qs = urllib.parse.urlencode({"serviceKey": key, "PG_SZ": ROWS, "PAGE": page,
                                 "PAN_ST_DT": st, "PAN_ED_DT": ed})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(f"{URL}?{qs}", timeout=30) as r:
                data = json.load(r)
            for block in data:
                if "dsList" in block:
                    return block["dsList"] or []
            return []
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)


def d(s):
    s = (s or "").replace(".", "").strip()
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else ""


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    days = int(args[0]) if args else 60
    include_all = "--all" in sys.argv
    key = load_key()
    now = datetime.now(KST)
    st, ed = (now - timedelta(days=days)).strftime("%Y%m%d"), now.strftime("%Y%m%d")

    raw, page = [], 1
    while True:
        batch = fetch(key, page, st, ed)
        raw += batch
        total = int(batch[0]["ALL_CNT"]) if batch else 0
        if not batch or len(raw) >= total:
            break
        page += 1

    rows = []
    for it in raw:
        if not include_all and it.get("UPP_AIS_TP_NM") not in HOUSING:
            continue
        rows.append({
            "id": f"LH-{it['PAN_ID']}",
            "공고명": it.get("PAN_NM", "").strip(),
            "대분류": it.get("UPP_AIS_TP_NM", ""),
            "유형": it.get("AIS_TP_CD_NM", ""),
            "지역": it.get("CNP_CD_NM", ""),
            "공고일": d(it.get("PAN_NT_ST_DT")),
            "마감일": d(it.get("CLSG_DT")),
            "상태": it.get("PAN_SS", ""),
            "URL": it.get("DTL_URL", ""),
            "모바일URL": it.get("DTL_URL_MOB", ""),
            "PAN_ID": it.get("PAN_ID"),
            "SPL_INF_TP_CD": it.get("SPL_INF_TP_CD"),
            "CCR_CNNT_SYS_DS_CD": it.get("CCR_CNNT_SYS_DS_CD"),
            "UPP_AIS_TP_CD": it.get("UPP_AIS_TP_CD"),
            "AIS_TP_CD": it.get("AIS_TP_CD"),
        })

    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, "lh_notices.json")
    old_ids = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old_ids = {r["id"] for r in json.load(f)["items"]}
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"collected_at": now.isoformat(), "range": [st, ed], "count": len(rows),
                   "items": rows}, f, ensure_ascii=False, indent=1)
    if rows:
        with open(os.path.join(DATA, "lh_notices.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader(); w.writerows(rows)
    new = [r for r in rows if r["id"] not in old_ids] if old_ids else []
    if new:
        with open(os.path.join(DATA, f"lh_new_{now:%Y%m%d}.json"), "w", encoding="utf-8") as f:
            json.dump(new, f, ensure_ascii=False, indent=1)
    print(f"LH 전체 {len(raw)}건 중 주택 {len(rows)}건 저장 / 신규 {len(new)}건"
          + ("" if old_ids else " (첫 실행: 기준선 저장)"))


if __name__ == "__main__":
    main()
