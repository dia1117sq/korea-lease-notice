"""인스타그램 릴스 예약 게시 (Instagram API with Instagram Login)

사용법:
  python3 post_reels.py <영상URL>|<캡션파일>|<HH:MM> [<영상URL>|<캡션파일>|<HH:MM> ...]
  예) python3 post_reels.py "https://.../reel_1.mp4|video/caption_1.txt|07:00" "https://.../reel_2.mp4|video/caption_2.txt|07:10"

동작:
  1) 모든 영상을 먼저 Instagram에 올려 처리(컨테이너 생성 → FINISHED 대기)
  2) 각 시각(KST)이 되면 순서대로 게시 (시각이 이미 지났으면 바로 게시)

환경변수: IG_USER_ID, IG_ACCESS_TOKEN, (선택) IG_API_VERSION, DRY_RUN=1
"""
import json, os, sys, time, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
USER = os.environ.get("IG_USER_ID", "").strip()
TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()
DRY = os.environ.get("DRY_RUN") == "1"
VER = os.environ.get("IG_API_VERSION", "v25.0")
# 토큰 종류에 따라 주소가 다름: Instagram 로그인 토큰(IG...) → graph.instagram.com, Facebook/시스템 사용자 토큰(EAA...) → graph.facebook.com
HOST = "graph.facebook.com" if TOKEN.startswith("EAA") else "graph.instagram.com"
API = f"https://{HOST}/{VER}"


def call(method, url, data=None, quiet=False):
    data = dict(data or {}); data["access_token"] = TOKEN
    q = urllib.parse.urlencode(data)
    req = urllib.request.Request(url + ("?" + q if method == "GET" else ""),
                                 data=None if method == "GET" else q.encode(), method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        msg = f"Instagram API 오류 {e.code}: {e.read().decode(errors='replace')[:500]}"
        if not quiet: print("::error::" + msg.replace("\n", " "))
        raise SystemExit(msg)


def log(*a):
    print(datetime.now(KST).strftime("[%H:%M:%S]"), *a, flush=True)


def check_url(url):
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=30) as r:
        ct, ln = r.headers.get("Content-Type"), r.headers.get("Content-Length")
    log("영상 주소 확인:", url, ct, ln)
    if "video/mp4" not in (ct or ""):
        raise SystemExit(f"영상 주소의 형식이 mp4가 아닙니다: {ct}")


def check():
    """게시하지 않고 토큰·계정·게시 한도만 확인 (결과는 GitHub 실행 화면의 알림으로 표시)"""
    if not USER or not TOKEN:
        print("::error::IG_USER_ID 또는 IG_ACCESS_TOKEN Secret이 비어 있습니다"); sys.exit(1)
    kind = "Facebook(통합 로그인) 토큰" if HOST == "graph.facebook.com" else "Instagram 로그인 토큰"
    try:
        me = call("GET", f"{API}/{USER}", {"fields": "username,name"})
        lim = call("GET", f"{API}/{USER}/content_publishing_limit", {"fields": "quota_usage,config"})
    except SystemExit as e:
        print(f"::error::토큰 확인 실패 ({kind}, {HOST}): {e}"); sys.exit(1)
    d = (lim.get("data") or [{}])[0]
    total = (d.get("config") or {}).get("quota_total", "?")
    print(f"::notice::토큰 확인 성공 — 계정 @{me.get('username')} / {kind} / 24시간 게시 한도 {d.get('quota_usage', 0)}/{total}")
    try:
        media = call("GET", f"{API}/{USER}/media", {"fields": "id,media_product_type,timestamp,permalink", "limit": "5"})
        items = media.get("data") or []
        print(f"::notice::최근 게시물 {len(items)}건: " + " | ".join(
            f"{m.get('media_product_type')} {m.get('timestamp', '')[:16]} {m.get('permalink', '')}" for m in items))
    except SystemExit:
        pass


def refresh_token():
    if HOST != "graph.instagram.com":
        return   # 시스템 사용자·Facebook 장기 토큰은 이 방식으로 연장하지 않음
    """장기 토큰(60일) 만료일을 늘림. 토큰 문자열이 바뀌면 GitHub Secret 갱신이 필요하다고 알림."""
    try:
        r = call("GET", "https://graph.instagram.com/refresh_access_token", {"grant_type": "ig_refresh_token"})
    except SystemExit as e:
        log("토큰 갱신 건너뜀:", e); return
    days = int(r.get("expires_in", 0)) // 86400
    log(f"토큰 갱신 완료: 앞으로 약 {days}일 유효")
    if r.get("access_token") and r["access_token"] != TOKEN:
        print("::warning::Instagram 토큰 문자열이 바뀌었습니다. 저장소 Secret IG_ACCESS_TOKEN 을 새 값으로 바꿔야 할 수 있습니다.")


# 인스타그램 음악: IG_MUSIC=off 이면 끔, 비우면 아래 검색어를 날짜마다 돌려 가며 사용, 다른 값이면 그 검색어로 찾음
MUSIC = os.environ.get("IG_MUSIC", "").strip()
MUSIC_QUERIES = ["lofi", "chill", "acoustic", "piano", "jazz", "bright", "upbeat", "calm"]


def pick_music():
    """Instagram Audio API에서 게시용으로 허용된 음악 1곡 고르기 (Facebook 로그인 토큰 전용). 실패하면 None."""
    if MUSIC.lower() == "off" or HOST != "graph.facebook.com":
        return None
    day = datetime.now(KST).timetuple().tm_yday
    queries = [MUSIC] if MUSIC else [MUSIC_QUERIES[day % len(MUSIC_QUERIES)], ""]
    for q in queries:
        params = {"audio_type": "music", "user_id": USER}
        if q: params["search_query"] = q
        try:
            r = call("GET", f"{API}/ig_audio", params, quiet=True)
        except SystemExit as e:
            print(f"::warning::음악 검색 실패: {e}"); continue
        tracks = [a for a in (r.get("audio") or r.get("data") or []) if (a.get("duration_in_ms") or 0) >= 30000 or not a.get("duration_in_ms")]
        if tracks:
            a = tracks[day % len(tracks)]
            name = f"{a.get('title', '')} - {a.get('display_artist', '')}".strip(" -")
            aid = a.get("audio_id") or a.get("id")
            log(f"음악 선택 ('{q or '인기곡'}'): {name} ({aid})")
            return aid, name
    return None


def create(video_url, caption, music=None):
    data = {"media_type": "REELS", "video_url": video_url, "caption": caption, "share_to_feed": "true"}
    if music:
        data["audio_configuration"] = json.dumps({"audio_id": music[0], "audio_volume": 100, "video_volume": 1})
        try:
            r = call("POST", f"{API}/{USER}/media", data, quiet=True)
            print(f"::notice::배경 음악: {music[1]}")
            return r["id"]
        except SystemExit as e:
            print(f"::warning::음악을 붙여 올리기 실패, 음악 없이 다시 시도: {e}")
            data.pop("audio_configuration")
    r = call("POST", f"{API}/{USER}/media", data)
    return r["id"]


def wait_ready(cid, limit=20 * 60):
    t0 = time.time()
    while time.time() - t0 < limit:
        r = call("GET", f"{API}/{cid}", {"fields": "status_code,status"})
        st = r.get("status_code")
        if st == "FINISHED":
            return
        if st in ("ERROR", "EXPIRED"):
            raise SystemExit(f"영상 처리 실패: {r}")
        time.sleep(15)
    raise SystemExit("영상 처리가 20분 안에 끝나지 않았습니다")


def wait_until(hhmm):
    h, m = map(int, hhmm.split(":"))
    now = datetime.now(KST)
    at = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if at > now:
        log(f"{hhmm}까지 대기 ({int((at - now).total_seconds() // 60)}분)")
        time.sleep((at - now).total_seconds())


def already_posted(caption, hours=14):
    """같은 첫 줄 캡션의 게시물이 최근 몇 시간 안에 있으면 True (예약·수동 실행이 겹쳐도 두 번 올리지 않음)"""
    head = caption.strip().splitlines()[0].strip() if caption.strip() else ""
    try:
        media = call("GET", f"{API}/{USER}/media", {"fields": "caption,timestamp", "limit": "10"})
    except SystemExit:
        return False
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    for m in media.get("data") or []:
        ts = datetime.strptime(m.get("timestamp", "1970-01-01T00:00:00+0000"), "%Y-%m-%dT%H:%M:%S%z")
        if ts >= since and (m.get("caption") or "").strip().splitlines()[:1] == [head]:
            return True
    return False


def main():
    if sys.argv[1:2] == ["check"]:
        return check()
    jobs = [a.split("|") for a in sys.argv[1:]]
    if not jobs:
        raise SystemExit(__doc__)
    if not DRY and (not USER or not TOKEN):
        raise SystemExit("IG_USER_ID / IG_ACCESS_TOKEN 이 설정되지 않았습니다 (저장소 Settings → Secrets)")
    for url, cap, _ in jobs:
        check_url(url)
    if DRY:
        for url, cap, at in jobs:
            log(f"[미리보기] {at} 게시 예정: {url}\n" + open(cap, encoding="utf-8").read()[:200])
        if USER and TOKEN:
            m = pick_music()
            print(f"::notice::시험 실행 음악 선택: {m[1] if m else '없음(음악 없이 게시)'}")
        print(f"::notice::시험 실행: 게시하지 않음 (영상 {len(jobs)}편 준비 완료)")
        return
    refresh_token()
    todo = []
    for url, cap, at in jobs:
        if already_posted(open(cap, encoding="utf-8").read()):
            print(f"::notice::이미 게시된 영상이라 건너뜀 ({at}): {url}")
        else:
            todo.append((url, cap, at))
    music = pick_music() if todo else None          # PART 1·2 같은 음악
    ready = []
    for url, cap, at in todo:                      # 1) 미리 업로드·처리
        cid = create(url, open(cap, encoding="utf-8").read(), music)
        log("업로드 시작:", url, "→", cid)
        ready.append((cid, at))
    for cid, _ in ready:
        wait_ready(cid); log("처리 완료:", cid)
    for cid, at in ready:                          # 2) 정해진 시각에 게시
        wait_until(at)
        r = call("POST", f"{API}/{USER}/media_publish", {"creation_id": cid})
        log(f"게시 완료 ({at}): 미디어 ID {r.get('id')}")
        print(f"::notice::인스타그램 게시 완료 ({at}) — 미디어 ID {r.get('id')}")


if __name__ == "__main__":
    main()
