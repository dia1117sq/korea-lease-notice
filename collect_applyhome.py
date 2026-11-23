"""청약홈 분양정보 수집기 (한국부동산원, api.odcloud.kr)

사용법:  python3 collect_applyhome.py [모집공고일 기준 조회일수=60]
결과:    data/applyhome_notices.json / .csv, data/applyhome_new_YYYYMMDD.json
"""
import csv, json, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timedelta
from collect_myhome import load_key, DATA, KST

BASE = "https://api.odcloud.kr/api/ApplyhomeInfoDetailSvc/v1/"
OPS = {
    "APT": "getAPTLttotPblancDetail",
    "APT잔여세대": "getRemndrLttotPblancDetail",
    "오피스텔/도시형/민간임대": "getUrbtyOfctlLttotPblancDetail",
    "공공지원민간임대": "getPblPvtRentLttotPblancDetail",
    "임의공급": "getOPTLttotPblancDetail",
}
ROWS = 500


def fetch(op, key, page, since):
    qs = urllib.parse.urlencode({"serviceKey": key, "page": page, "perPage": ROWS,
                                 "cond[RCRIT_PBLANC_DE::GTE]": since})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(BASE + op + "?" + qs, timeout=30) as r:
                return json.load(r)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)


def nd(v):
    v = (v or "").replace("-", "").replace(".", "").strip()
    return f"{v[:4]}-{v[4:6]}-{v[6:8]}" if len(v) == 8 else v


def status(b, e, today):
    if b and today < b: return "접수예정"
    if e and today > e: return "접수마감"
    return "접수중" if b else "확인필요"


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    key = load_key()
    now = datetime.now(KST); today = now.strftime("%Y-%m-%d")
    since = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = []
    for kind, op in OPS.items():
        page, got = 1, []
        while True:
            d = fetch(op, key, page, since)
            got += d.get("data") or []
            if not d.get("data") or len(got) >= d.get("matchCount", 0):
                break
            page += 1
        print(f"{kind}: {len(got)}건")
        for it in got:
            it = {k: (nd(v) if isinstance(v, str) and (k.endswith("DE") or k.endswith("_DE")) else v)
                  for k, v in it.items()}
            b = it.get("RCEPT_BGNDE") or it.get("SUBSCRPT_RCEPT_BGNDE") or it.get("SPSPLY_RCEPT_BGNDE") or ""
            e = it.get("RCEPT_ENDDE") or it.get("SUBSCRPT_RCEPT_ENDDE") or it.get("GNRL_RNK2_ETC_AREA_ENDDE") or it.get("GNRL_RNK1_ETC_AREA_ENDDE") or ""
            rows.append({
                "id": f"AH-{kind}-{it.get('HOUSE_MANAGE_NO')}-{it.get('PBLANC_NO')}",
                "구분": kind,
                "주택명": it.get("HOUSE_NM", ""),
                "세부구분": it.get("HOUSE_DTL_SECD_NM") or it.get("SEARCH_HOUSE_SECD_NM") or "",
                "분양/임대": it.get("RENT_SECD_NM", ""),
                "지역": it.get("SUBSCRPT_AREA_CODE_NM", ""),
                "주소": it.get("HSSPLY_ADRES", ""),
                "총공급세대": it.get("TOT_SUPLY_HSHLDCO"),
                "모집공고일": it.get("RCRIT_PBLANC_DE", ""),
                "특별공급접수": f"{it.get('SPSPLY_RCEPT_BGNDE') or ''}~{it.get('SPSPLY_RCEPT_ENDDE') or ''}".strip("~"),
                "1순위(해당지역)": it.get("GNRL_RNK1_CRSPAREA_RCPTDE") or "",
                "2순위(해당지역)": it.get("GNRL_RNK2_CRSPAREA_RCPTDE") or "",
                "접수시작": b, "접수마감": e,
                "접수상태": status(b, e, today),
                "당첨발표": it.get("PRZWNER_PRESNATN_DE") or "",
                "계약": f"{it.get('CNTRCT_CNCLS_BGNDE') or ''}~{it.get('CNTRCT_CNCLS_ENDDE') or ''}".strip("~"),
                "입주예정": it.get("MVN_PREARNGE_YM") or "",
                "시행사": it.get("BSNS_MBY_NM", ""), "시공사": it.get("CNSTRCT_ENTRPS_NM", ""),
                "분양가상한제": it.get("PARCPRC_ULS_AT", ""),
                "문의": it.get("MDHS_TELNO", ""),
                "청약홈URL": it.get("PBLANC_URL", ""), "홈페이지": it.get("HMPG_ADRES", ""),
                "HOUSE_MANAGE_NO": it.get("HOUSE_MANAGE_NO"), "PBLANC_NO": it.get("PBLANC_NO"),
            })
    rows.sort(key=lambda r: r["모집공고일"], reverse=True)
    os.makedirs(DATA, exist_ok=True)
    path = os.path.join(DATA, "applyhome_notices.json")
    old = {r["id"] for r in json.load(open(path, encoding="utf-8"))["items"]} if os.path.exists(path) else set()
    json.dump({"collected_at": now.isoformat(), "since": since, "count": len(rows), "items": rows},
              open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if rows:
        with open(os.path.join(DATA, "applyhome_notices.csv"), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    new = [r for r in rows if r["id"] not in old] if old else []
    if new:
        json.dump(new, open(os.path.join(DATA, f"applyhome_new_{now:%Y%m%d}.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    print(f"총 {len(rows)}건 저장 / 신규 {len(new)}건" + ("" if old else " (첫 실행: 기준선 저장)"))


if __name__ == "__main__":
    main()
