"""LH 공고별 공급정보(주택형·면적·세대수·보증금·임대료/분양가) 추가 수집

사용법:  python3 enrich_lh_supply.py      (collect_lh.py 실행 후)
대상:    data/lh_notices.json 중 접수마감이 아닌 공고
결과:    data/lh_supply.json  {공고id: {"공고명":..., "공급": [ {한글항목: 값}, ... ]}}
         이미 받은 공고는 다시 부르지 않습니다(호출량 절약).
"""
import json, os, sys, time, urllib.parse, urllib.request
from collect_myhome import load_key, DATA

URL = "https://apis.data.go.kr/B552555/lhLeaseNoticeSplInfo1/getLeaseNoticeSplInfo1"
KEYS = ["PAN_ID", "SPL_INF_TP_CD", "CCR_CNNT_SYS_DS_CD", "UPP_AIS_TP_CD", "AIS_TP_CD"]


def fetch(key, n):
    qs = urllib.parse.urlencode({"serviceKey": key, **{k: n[k] for k in KEYS}})
    with urllib.request.urlopen(f"{URL}?{qs}", timeout=15) as r:
        data = json.load(r)
    merged = {}
    for block in data:
        merged.update(block)
    out = []
    # 응답은 dsList01, dsList02 ... 와 각각의 한글 항목명 dsList01Nm ... 로 옴
    for k, v in merged.items():
        if k.startswith("dsList") and not k.endswith("Nm") and isinstance(v, list):
            names = (merged.get(k + "Nm") or [{}])[0]
            out += [{names.get(f, f): val for f, val in row.items()} for row in v]
    return out


def main():
    key = load_key()
    notices = json.load(open(os.path.join(DATA, "lh_notices.json"), encoding="utf-8"))["items"]
    path = os.path.join(DATA, "lh_supply.json")
    store = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    targets = [n for n in notices if n["상태"] != "접수마감" and n["id"] not in store]
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 40   # 1회 최대 호출 수
    remaining = len(targets) - min(limit, len(targets))
    targets = targets[:limit]
    ok = 0
    for n in targets:
        try:
            store[n["id"]] = {"공고명": n["공고명"], "공급": fetch(key, n)}
            ok += 1
            if ok % 10 == 0:
                json.dump(store, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        except Exception as e:
            print("실패:", n["공고명"], e)
        time.sleep(0.2)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=1)
    print(f"공급정보 {ok}/{len(targets)}건 추가 (누적 {len(store)}건, 남은 대상 {remaining}건)")


if __name__ == "__main__":
    main()
