# sns_lease — 공공임대·분양 공고 수집

| 스크립트 | API | 내용 |
|---|---|---|
| collect_myhome.py | 국토교통부 마이홈포털 (HWSPR02) `rsdtRcritNtcList`(임대), `ltRsdtRcritNtcList`(분양) | 전국 공공임대·공공분양 공고, 접수일·보증금·월세·분양대금 |
| collect_lh.py | LH 분양임대공고문 (`lhLeaseNoticeInfo1`) | LH 공고 목록·상태 (기본: 주택만, `--all`이면 상가·토지 포함) |
| enrich_lh_supply.py | LH 공고별 공급정보 (`getLeaseNoticeSplInfo1`) | 주택형·면적·세대수·보증금·임대료 |
| collect_applyhome.py | 청약홈 분양정보 (api.odcloud.kr) | APT·잔여세대·오피스텔·공공지원민간임대·임의공급, 특공/1·2순위/당첨/계약 일정 |
| merge.py | — | 세 출처 통합·중복 제거 (LH 공고번호, 공고일±3일+지역+단지명), 접수상태·D-day 계산 |

실행: `./run_all.sh` → 결과는 `data/` (json + 엑셀용 csv).
`merge.py` 가 세 출처를 공고 단위로 합쳐 `data/merged.json`·`merged.csv` 를 만들고, 새로 생긴 진행중·예정 공고는 `data/merged_new_YYYYMMDD.json` 에 저장합니다 (SNS 영상 대상).

인증키는 `.env` 의 `DATA_GO_KR_KEY` (git에 올리지 않음). 개발계정 일일 호출 한도: LH 10,000 / 청약홈 40,000.

## 배포 (GitHub Pages)
`.github/workflows/daily.yml` 이 매일 07:43(KST)에 수집 → 통합 → `site/` 생성 → GitHub Pages 배포를 합니다.
- 저장소 Settings → Secrets and variables → Actions 에 `DATA_GO_KR_KEY` 등록
- Settings → Pages → Source: **GitHub Actions**
- Actions 탭의 daily-update → Run workflow 로 즉시 실행 가능

## 인스타그램 자동 게시 (매주 월요일)
`.github/workflows/weekly-reels.yml` — 월 06:20 시작 → 최신 공고 수집 → `make_video.py` 로 릴스 2편(공급 규모 1~5위 / 6~10위) →
사이트 `reels/` 에 영상 공개 → `post_reels.py` 가 **07:00 PART 1, 07:10 PART 2** 게시.
- 필요한 Secret: `IG_USER_ID`, `IG_ACCESS_TOKEN` (Instagram API with Instagram Login, 권한 `instagram_business_basic`, `instagram_business_content_publish`)
- 시험: Actions → weekly-reels → Run workflow (게시 체크 해제 = 영상만 생성)
- 토큰은 실행 때마다 만료 연장을 시도합니다. 실행 화면에 토큰 변경 경고가 뜨면 Secret을 새 값으로 바꿔 주세요.
- 만든 영상·캡션은 실행 화면 하단 Artifacts(reels)에서 30일간 내려받을 수 있습니다.
