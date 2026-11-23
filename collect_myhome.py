"""마이홈포털 공공주택 모집공고 수집기 (국토교통부 HWSPR02)

사용법:  python3 collect_myhome.py
결과:
  data/notices.json       전체 공고 (임대+분양, 정규화)
  data/notices.csv        같은 내용 CSV (엑셀용)
  data/new_YYYYMMDD.json  지난 실행 이후 새로 생긴 공고 (영상/SNS 대상)
"""
import csv, json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

BASE = "https://apis.data.go.kr/1613000/HWSPR02"
OPS = {"임대": "rsdtRcritNtcList", "분양": "ltRsdtRcritNtcList"}
ROWS = 100
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
KST = timezone(timedelta(hours=9))


def load_key():
    if os.environ.get("DATA_GO_KR_KEY"):
        return os.environ["DATA_GO_KR_KEY"]
    with open(os.path.join(HERE, ".env"), encoding="utf-8") as f:
        for line in f:
            if line.startswith("DATA_GO_KR_KEY="):
                return line.split("=", 1)[1].strip()
    sys.exit("DATA_GO_KR_KEY 가 없습니다 (.env 확인)")


def fetch(op, key, page):
    qs = urllib.parse.urlencode({"serviceKey": key, "pageNo": page, "numOfRows": ROWS})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(f"{BASE}/{op}?{qs}", timeout=30) as r:
                body = json.load(r)["response"]
            if body["header"]["resultCode"] != "00":
                raise RuntimeError(body["header"])
            return body["body"]
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(2)


def fetch_all(op, key):
    items, page = [], 1
    while True:
        body = fetch(op, key, page)
        batch = body.get("item") or []
        if isinstance(batch, dict):
            batch = [batch]
        items += batch
        if not batch or len(items) >= int(body.get("totalCount", 0)):
            return items
        page += 1


def d(s):
    s = (s or "").strip()
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 else ""


def status(begin, end, today):
    if begin and today < begin:
        return "접수예정"
    if end and today > end:
        return "접수마감"
    return "접수중" if begin else "확인필요"


def normalize(kind, it, today):
    begin, end = d(it.get("beginDe")), d(it.get("endDe"))
    return {
        "id": f"{kind}-{it.get('pblancId')}-{it.get('houseSn')}",
        "구분": kind,
        "공고명": it.get("pblancNm", "").strip(),
        "공고상태": it.get("sttusNm", ""),          # 일반공고 / 정정공고
        "공급기관": it.get("suplyInsttNm", ""),
        "공급유형": it.get("suplyTyNm", ""),        # 임대만: 국민임대, 행복주택, 매입임대 ...
        "주택유형": it.get("houseTyNm", ""),
        "단지명": it.get("hsmpNm", ""),
        "시도": it.get("brtcNm", ""),
        "시군구": it.get("signguNm", ""),
        "주소": (it.get("fullAdres") or "").strip(),
        "공급호수": it.get("sumSuplyCo"),
        "모집공고일": d(it.get("rcritPblancDe")),
        "접수시작": begin,
        "접수마감": end,
        "당첨발표": d(it.get("przwnerPresnatnDe")),
        "접수상태": status(begin, end, today),
        "임대보증금": it.get("rentGtn"),
        "월임대료": it.get("mtRntchrg"),
        "계약금": it.get("enty"),
        "중도금": it.get("prtpay"),
        "잔금": it.get("surlus"),
        "난방": it.get("heatMthdNm", ""),
        "문의": it.get("refrnc", ""),
        "공고원문URL": it.get("url", ""),
        "마이홈URL": it.get("pcUrl", ""),
        "모바일URL": it.get("mobileUrl", ""),
        "정정전공고ID": it.get("beforePblancId", ""),
    }


def main():
    key = load_key()
    now = datetime.now(KST)
    today = now.strftime("%Y-%m-%d")
    os.makedirs(DATA, exist_ok=True)

    rows = []
    for kind, op in OPS.items():
        raw = fetch_all(op, key)
        rows += [normalize(kind, it, today) for it in raw]
        print(f"{kind}: {len(raw)}건")
    rows.sort(key=lambda r: r["모집공고일"], reverse=True)

    path = os.path.join(DATA, "notices.json")
    old_ids = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            old_ids = {r["id"] for r in json.load(f)["items"]}

    with open(path, "w", encoding="utf-8") as f:
        json.dump({"collected_at": now.isoformat(), "count": len(rows), "items": rows},
                  f, ensure_ascii=False, indent=1)
    with open(os.path.join(DATA, "notices.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    new = [r for r in rows if r["id"] not in old_ids] if old_ids else []
    if new:
        with open(os.path.join(DATA, f"new_{now:%Y%m%d}.json"), "w", encoding="utf-8") as f:
            json.dump(new, f, ensure_ascii=False, indent=1)
    print(f"총 {len(rows)}건 저장 / 신규 {len(new)}건" + ("" if old_ids else " (첫 실행: 기준선 저장)"))


if __name__ == "__main__":
    main()
