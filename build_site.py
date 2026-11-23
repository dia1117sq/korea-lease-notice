"""통합 공고(data/merged.json) → 정적 웹사이트(site/index.html) 생성

사용법:  python3 build_site.py
- 접수중·접수예정 공고 + 최근 30일 내 마감 공고를 포함합니다.
- 결과 파일 하나(site/index.html)로 동작하며, 그대로 아무 정적 호스팅에 올리면 됩니다.
"""
import hashlib, json, os
from datetime import datetime, timedelta
from collect_myhome import DATA, HERE, KST

OUT = os.path.join(HERE, "site", "index.html")
# 방문자 통계(GoatCounter) 코드 → https://korea-lease.goatcounter.com 관리자 화면 (빈 값이면 통계 끔)
GOATCOUNTER = os.environ.get("GOATCOUNTER_CODE", "korea-lease")


def main():
    m = json.load(open(os.path.join(DATA, "merged.json"), encoding="utf-8"))
    now = datetime.now(KST)
    cut = (now - timedelta(days=30)).strftime("%Y-%m-%d")
    items = []
    for n in m["items"]:
        if n["접수상태"] == "접수마감" and (n["접수마감"] or "") < cut:
            continue
        n = dict(n)
        n["k"] = "n" + hashlib.md5(n["id"].encode()).hexdigest()[:10]
        items.append(n)
    payload = json.dumps({"updated": now.strftime("%Y-%m-%d %H:%M"), "today": now.strftime("%Y-%m-%d"),
                          "items": items}, ensure_ascii=False).replace("</", "<\\/")
    tpl = open(os.path.join(HERE, "site_template.html"), encoding="utf-8").read()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    html = tpl.replace("/*__DATA__*/null", payload).replace("/*__GC__*/\"\"", json.dumps(GOATCOUNTER))
    if GOATCOUNTER:
        html = html.replace("<!--__ANALYTICS__-->",
            '<script>window.goatcounter={no_onload:true}</script>\n'
            f'<script data-goatcounter="https://{GOATCOUNTER}.goatcounter.com/count" async src="//gc.zgo.at/count.js"></script>')
    open(OUT, "w", encoding="utf-8").write(html)
    print(f"site/index.html 생성: 공고 {len(items)}건, {os.path.getsize(OUT)//1024}KB")


if __name__ == "__main__":
    main()
