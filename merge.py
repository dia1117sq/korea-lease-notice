"""세 출처(마이홈·LH·청약홈)를 공고 단위 하나의 목록으로 합치고 중복 제거

사용법:  python3 merge.py      (수집 스크립트 실행 후)
결과:
  data/merged.json / merged.csv   통합 공고 목록 (사이트용)
  data/merged_new_YYYYMMDD.json   지난 통합 이후 새로 생긴 공고 (SNS 영상 대상)

중복 기준
  - 마이홈 ↔ LH: 공고 URL의 LH 공고번호(panId)가 같으면 같은 공고 (마이홈 단지 여러 줄 → 단지 목록으로 묶음)
  - 마이홈 분양 ↔ 청약홈: 모집공고일·시도가 같고 단지명이 겹치면 같은 공고
"""
import csv, json, os, re
from datetime import datetime
from collect_myhome import DATA, KST

J = lambda n: json.load(open(os.path.join(DATA, n), encoding="utf-8"))["items"]
pan = lambda u: (re.search(r"panId=([^&]+)", u or "") or [None, None])[1]
EXCLUDE = ("어린이집", "상가", "토지")   # 주택이 아닌 LH 공고 유형
SIDO = {"서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시", "인천": "인천광역시",
        "광주": "광주광역시", "대전": "대전광역시", "울산": "울산광역시", "세종": "세종특별자치시",
        "경기": "경기도", "강원": "강원특별자치도", "충북": "충청북도", "충남": "충청남도",
        "전북": "전북특별자치도", "전남": "전라남도", "경북": "경상북도", "경남": "경상남도",
        "제주": "제주특별자치도"}


def core(name):
    name = re.sub(r"\[.*?\]|\(.*?\)|[^0-9A-Za-z가-힣]", "", name or "")
    return re.sub(r"(공공분양|민영|입주자모집공고|입주자모집|모집공고|공고)$", "", name)


CORR = re.compile(r"\[\s*정정\s*(공고)?\s*\]|\(\s*정정\s*(공고)?\s*\)|정정공고")


def is_correction(n):
    return n.get("공고상태") == "정정공고" or bool(CORR.search(n["공고명"] or ""))


def norm_title(t):
    return re.sub(r"\s+", "", CORR.sub("", t or ""))


def similar(a, b):
    a, b = core(a), core(b)
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    return any(a[i:i + 4] in b for i in range(len(a) - 3))


def status(b, e, today):
    if b and today < b: return "접수예정"
    if e and today > e: return "접수마감"
    return "접수중" if b else "확인필요"


def main():
    now = datetime.now(KST); today = now.strftime("%Y-%m-%d")
    mh, lh, ah = J("notices.json"), J("lh_notices.json"), J("applyhome_notices.json")
    supply_path = os.path.join(DATA, "lh_supply.json")
    supply = json.load(open(supply_path, encoding="utf-8")) if os.path.exists(supply_path) else {}
    lh_by = {r["PAN_ID"]: r for r in lh}
    out = {}

    # 1) 마이홈: 공고 단위로 묶기
    mh_key = {}        # (구분, 마이홈 공고ID) → 통합 공고 key
    corrections = []   # (구분, 정정 공고 key, 정정 전 마이홈 공고ID)
    for r in mh:
        p = pan(r["공고원문URL"])
        key = f"LH-{p}" if p else f"MH-{r['구분']}-{r['id'].split('-')[1]}"
        mh_key[(r["구분"], r["id"].split("-")[1])] = key
        if r.get("정정전공고ID"):
            corrections.append((r["구분"], key, r["정정전공고ID"]))
        n = out.get(key)
        if not n:
            n = out[key] = {
                "id": key, "출처": ["마이홈"], "구분": r["구분"],
                "유형": r["공급유형"] or ("공공분양" if r["구분"] == "분양" else ""),
                "공급기관": r["공급기관"], "공고명": r["공고명"], "공고상태": r["공고상태"],
                "시도": r["시도"], "시군구": r["시군구"],
                "모집공고일": r["모집공고일"], "접수시작": r["접수시작"], "접수마감": r["접수마감"],
                "당첨발표": r["당첨발표"], "총공급호수": 0, "단지": [],
                "공고원문URL": r["공고원문URL"], "마이홈URL": r["마이홈URL"], "청약홈URL": "",
                "문의": r["문의"],
            }
        n["단지"].append({k: r[k] for k in ["단지명", "주소", "주택유형", "공급호수", "임대보증금",
                                             "월임대료", "계약금", "중도금", "잔금", "난방"]})
        n["총공급호수"] += int(r["공급호수"] or 0)
        n["접수시작"] = min(filter(None, [n["접수시작"], r["접수시작"]]), default="")
        n["접수마감"] = max(filter(None, [n["접수마감"], r["접수마감"]]), default="")
        if n["시도"] != r["시도"]:
            n["시도"] = "여러 지역"

    # 2) LH: 마이홈에 있으면 정보 보강, 없으면 새 공고
    for p, r in lh_by.items():
        if any(x in r["유형"] for x in EXCLUDE):
            continue
        key = f"LH-{p}"
        n = out.get(key)
        if n:
            n["출처"].append("LH"); n["LH상태"] = r["상태"]
        else:
            n = out[key] = {
                "id": key, "출처": ["LH"], "구분": "분양" if r["대분류"] in ("분양주택", "신혼희망타운") else "임대",
                "유형": r["유형"], "공급기관": "LH", "공고명": r["공고명"], "공고상태": "",
                "시도": r["지역"], "시군구": "", "모집공고일": r["공고일"], "접수시작": "",
                "접수마감": r["마감일"], "당첨발표": "", "총공급호수": 0, "단지": [],
                "공고원문URL": r["URL"], "마이홈URL": "", "청약홈URL": "", "문의": "LH 콜센터 1600-1004",
                "LH상태": r["상태"],
            }
        sp = supply.get(key, {}).get("공급")
        if sp:
            n["주택형"] = sp

    # 3) 청약홈: 마이홈 분양과 겹치면 보강, 아니면 새 공고
    mh_bun = [n for n in out.values() if n["구분"] == "분양"]
    near = lambda a, b: bool(a and b) and abs((datetime.fromisoformat(a) - datetime.fromisoformat(b)).days) <= 3
    for r in ah:
        sido = SIDO.get(r["지역"], r["지역"])
        hit = next((n for n in mh_bun if near(n["모집공고일"], r["모집공고일"]) and n["시도"] in (sido, "전국")
                    and (similar(r["주택명"], n["공고명"]) or any(similar(r["주택명"], d["단지명"]) for d in n["단지"]))), None)
        sched = {k: r[k] for k in ["특별공급접수", "1순위(해당지역)", "2순위(해당지역)", "계약", "입주예정"]}
        if hit:
            hit["출처"].append("청약홈"); hit["청약홈URL"] = r["청약홈URL"]; hit["청약일정"] = sched
            continue
        out[r["id"]] = {
            "id": r["id"], "출처": ["청약홈"], "구분": "임대" if "임대" in (r["분양/임대"] + r["구분"]) else "분양",
            "유형": f"{r['구분']} {r['세부구분']}".strip(), "공급기관": r["시행사"], "공고명": r["주택명"],
            "공고상태": "", "시도": sido, "시군구": "", "모집공고일": r["모집공고일"],
            "접수시작": r["접수시작"], "접수마감": r["접수마감"], "당첨발표": r["당첨발표"],
            "총공급호수": r["총공급세대"] or 0,
            "단지": [{"단지명": r["주택명"], "주소": r["주소"], "공급호수": r["총공급세대"]}],
            "공고원문URL": r["홈페이지"], "마이홈URL": "", "청약홈URL": r["청약홈URL"], "문의": r["문의"],
            "시공사": r["시공사"], "청약일정": sched,
        }

    # 4) 정정공고가 나오면 이전 공고는 숨김
    #   a) 마이홈의 정정 전 공고ID 사슬
    replaced = {}
    for kind, key, before in corrections:
        old_key = mh_key.get((kind, before))
        if old_key and old_key != key and old_key in out:
            replaced[old_key] = key
    #   b) ID 연결이 없는 경우: [정정공고]를 뺀 공고명 + 시도가 같은 묶음에서 가장 최근 정정공고만 남김
    groups = {}
    for k, n in out.items():
        if k not in replaced:
            groups.setdefault((norm_title(n["공고명"]), n["시도"]), []).append(n)
    for g in groups.values():
        if len(g) > 1 and any(is_correction(n) for n in g):
            keep = max(g, key=lambda n: (n["모집공고일"] or "", is_correction(n), n["id"]))
            for n in g:
                if n is not keep and (n["모집공고일"] or "") <= (keep["모집공고일"] or ""):
                    replaced[n["id"]] = keep["id"]
    for k in replaced:
        out.pop(k, None)

    rows = list(out.values())
    for n in rows:
        n["출처"] = sorted(set(n["출처"]))
        st = status(n["접수시작"], n["접수마감"], today)
        if n["출처"] == ["LH"]:   # LH 단독 공고는 접수시작일이 없어 LH 상태를 따름
            st = {"접수마감": "접수마감", "접수중": "접수중"}.get(n.get("LH상태"), "접수예정" if st != "접수마감" else st)
        n["접수상태"] = st
        n["D-day"] = (datetime.strptime(n["접수마감"], "%Y-%m-%d").date() - now.date()).days if n["접수마감"] else None
    rows.sort(key=lambda n: (n["접수상태"] == "접수마감", n["접수마감"] or "9999"))

    path = os.path.join(DATA, "merged.json")
    old = {n["id"] for n in json.load(open(path, encoding="utf-8"))["items"]} if os.path.exists(path) else set()
    json.dump({"generated_at": now.isoformat(), "count": len(rows), "items": rows},
              open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    cols = ["id", "출처", "구분", "유형", "공급기관", "공고명", "시도", "시군구", "총공급호수", "모집공고일",
            "접수시작", "접수마감", "D-day", "당첨발표", "접수상태", "공고원문URL", "마이홈URL", "청약홈URL", "문의"]
    with open(os.path.join(DATA, "merged.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader()
        for n in rows:
            w.writerow({**n, "출처": "+".join(n["출처"])})
    new = [n for n in rows if n["id"] not in old and n["접수상태"] != "접수마감"] if old else []
    if new:
        json.dump(new, open(os.path.join(DATA, f"merged_new_{now:%Y%m%d}.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, indent=1)
    print(f"정정으로 대체된 이전 공고 {len(replaced)}건 제외")
    print(f"통합 {len(rows)}건 (진행중·예정 {sum(n['접수상태'] != '접수마감' for n in rows)}건) / 신규 {len(new)}건"
          + ("" if old else " (첫 실행: 기준선 저장)"))


if __name__ == "__main__":
    main()
