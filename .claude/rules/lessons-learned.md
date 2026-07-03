# Lessons Learned

프로젝트 작업 중 얻은 교훈과 미적용 백로그. (전역 규칙: 에이전트 실수/교훈은 여기 기록)

---

## 2026-06-22 ~ 06-24 — 무료 모드 전환 + 발행 검증

### 교훈

1. **외부 발행의 공개설정은 "안전 기본값"이어야 한다 (안전 버그)**
   - `_set_visibility`의 `vis_map`이 영문 키(`private`/`public`)만 인식했는데, 앱 기본값은 한글 `"비공개"` → 매핑 실패 → 폴백이 **`전체공개`**(공개!)였다.
   - 즉 사용자가 "비공개"를 골라도 **전체공개로 발행**되는 사고 위험.
   - **교훈**: 되돌리기 어려운 외부 작업(발행 등)에서 알 수 없는 입력은 **가장 안전한 값(비공개)** 으로 폴백. 기본값을 절대 "공개"로 두지 말 것. → `_visibility_target()`로 추출 + 한글/영문 인식 + unknown→비공개.

2. **폴백 경로는 주 경로와 "동일한 데이터 계약"을 채워야 한다 (무료 모드의 조용한 품질 저하)**
   - Google Maps → Nominatim 폴백 시 `_nominatim_geocode`가 `city/region/country`를 안 채워(`_google_geocode`는 채움) → 지역 감지 실패 → 위키 박스가 "홋카이도 삿포로" 환각.
   - 또 POI 확정 시 번역 스킵 로직이 "Google Places=한글명" 전제 → Nominatim 원문 일본어(`篠崎八幡神社`)가 제목/본문 누출.
   - **교훈**: 폴백을 추가하면, 폴백이 반환하는 dict가 주 경로와 **같은 필드 계약**을 만족하는지, 그리고 그 값을 소비하는 **모든 다운스트림**을 점검할 것.

3. **LLM에 "개수 할당"을 강요하면 환각한다**
   - 위키 박스 프롬프트의 `specialties/foods/spots 각 3~5개`가 환각 주원인(개수 채우려 인접지 명소를 지어냄).
   - **교훈**: `0~N개, 확실한 것만, 없으면 빈 배열` + `temperature=0`. 개수 하한을 두지 말 것.

4. **Windows cp949 콘솔에서 이모지 로그 크래시** (미해결, 백로그 #6)
   - `logger.info("✅ ...")` / `print("🔬 ...")`가 `UnicodeEncodeError`로 스크립트를 죽인다.
   - 임시 회피: 스크립트 진입부 `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`.

5. **네트워크/Selenium 로직에서 순수 결정 부분을 staticmethod로 추출 → 유닛테스트**
   - `_pick_admin`(주소→행정구역), `_dedupe_separators`(구분선 정규화), `_visibility_target`(공개설정 매핑) 추출로 네트워크 없이 회귀 테스트 가능해짐. `tests/test_quality.py` 관례 활용.

### 검증된 사실
- 무료 모드(Google 키 비활성화)에서 전체 파이프라인 정상 + 실제 네이버 **비공개 발행 성공**.
- 자동 로그인은 네이버 보안에 막힘 → `selenium_profile` 세션 + 수동 로그인 폴백(180초)으로 통과. 한 번 로그인하면 세션 저장.

### 미적용 백로그
- **#4 무료 모드 가시성**: 무료 모드일 때 로그 배너 + UI에 "상호명 정확도 낮음, 검수 권장" 노출. (지금은 조용히 품질 저하)
- **#6 로그 인코딩**: 로깅 핸들러/스트림에 UTF-8 + `errors="replace"` 적용 (Windows 안정성).
- **리팩터**: "장소 이름 해석" 책임이 6개 메서드(`_nominatim_geocode`/`_google_geocode`/`_make_place_name`/`_translate_to_korean`/`_koreanize_region`/`_detect_region`)에 분산. `core.py` 2,600줄 God-class 2개. AI 작업 전 `/refactor-audit` 권장.
- 상세 리뷰: `docs/reviews/2026-06-22-free-mode-review.md`

---

## 2026-06-30 — 계획 검수 단계 추가

1. **계획 검수(plan review)가 생성의 단일 진실원**: 분석 완료 후 TripPlanner가 초안을 만들고, 사용자가 일정/장소명/사건/느낌/별점/영수증을 검수·확정하면 `plans/<title>/plan.json`이 생성된다. 이후 generate, /api/seo 등 모든 다운스트림은 이 plan을 참조해야 한다(`_active_groups`가 plan 기반 그룹을 봐야 /api/groups·/api/blocks·generate 간 gi 정합이 유지됨).

2. **함정 — 그룹 소스 불일치**: plan 흐름에서 `/api/groups`, `/api/blocks`, `generate`가 모두 같은 그룹 소스(`_active_groups`)를 봐야 gi 인덱스가 맞는다. 한 곳이라도 원래 `state["groups"]`를 직접 참조하면 프론트 목록과 생성 그룹이 어긋난다.

3. **영수증 이미지 발행 제외**: 영수증 사진은 개인정보이므로 발행 블록에서 제외. 파일명은 `werkzeug.utils.secure_filename`으로 정제. 별점·가격은 코드가 HTML 조립(`_format_meta_line`), URL은 포함하지 않는다.

4. **🔴 서빙되는 UI 파일은 `static/index.html`이다 (루트 `index.html` 아님)**: `app.py`의 `/`는 `send_from_directory('static','index.html')`. 루트 `index.html`은 서빙 안 되는 레거시 중복본. UI 작업은 **반드시 `static/index.html`** 에 한다. (이번에 서브에이전트가 CLAUDE.md의 모호한 "index.html" 표기를 믿고 루트를 고쳐 전부 무효가 됐다 → static/로 포팅해 해결.) CLAUDE.md의 표기도 정정 필요.

5. **🔴 단일 인라인 `<script>`의 구문오류 1개 = SPA 전체 사망**: `static/index.html`은 거대한 단일 인라인 스크립트라, 어디든 구문오류(예: `updateSettingsPreview`의 짝 없는 `}`)가 하나 있으면 **모든 함수·리스너가 미정의**되어 화면이 정적 스켈레톤만 남는다(콘솔에 조용히 죽기도). 발견 당시 이 오류는 **기존부터 존재**(이 작업과 무관)해 웹 UI가 통째로 안 돌고 있었다.
   - **교훈**: UI 변경은 유닛/코드리뷰만으로 부족 — **실제 브라우저 렌더 확인 필수**(`/browse`로 스크린샷). 정적 검증으로 `node -e "new (require('vm').Script)(scriptSrc)"`(V8=브라우저 파서)로 인라인 스크립트 파싱을 검사할 수 있다. (`node --check`는 CJS 래퍼 때문에 오탐 위치를 주지만, vm.Script는 정확.)

6. **영수증 UX = 업로드 단계에서 사진과 함께 + 자동 매칭**: 영수증은 1단계에서 별도 영역(`#rdz`→`/api/receipts/upload`)으로 올려 즉시 OCR, `state["receipts"]`에 보관. 계획 초안 시 `TripPlanner.match_receipts_to_stops`로 **가게명↔장소명 일치(+같은 날짜)** 인 stop에 자동 배정(추측 안 함, 실패분은 `plan["unmatched_receipts"]`). 2단계 장소 카드에서 매칭 표시+재배정, 상단 "미배정 영수증"칸에서 드롭다운으로 배정. 카드별 개별 첨부는 폐기.

7. **`/browse` 테스트 함정 3개**: (a) `browse js`는 **격리 월드**라 페이지 전역(go/render 등) 접근 불가 → DOM은 읽히지만 함수 호출은 안 됨. 네비게이션은 실제 `browse click`으로. (b) Chrome은 **특정 포트(5060/5061=SIP 등)를 ERR_UNSAFE_PORT로 차단** → 로컬 테스트 서버는 8088 등 안전 포트 사용. (c) flex 행에서 `<select>`(긴 옵션)는 최소너비가 커져 옆 `<span>`을 0폭으로 만들어 글자 세로깨짐 → 세로 스택 또는 select `max-width`. (d) 시드 서버를 여러 포트에 남기면 SO_REUSEADDR로 **옛 서버가 응답**해 혼란 → 재검증 전 `taskkill //F //IM python.exe`로 정리.

8. **검수 화면 편의기능 배치(2026-07-01)**: 썸네일은 `/api/photos`에 `pid` 추가해 stop.photo_ids와 매칭(썸네일·힌트·지도). 같은 위치 무명 사진은 `_stops_for_day`에서 **GPS 반올림(~110m) 클러스터**로 묶음. **지도는 검수 UI에만**(OSM iframe + 구글맵 링크, 키 불필요) — **발행 HTML엔 절대 미포함**(불변식). 편집 자동저장은 `#planRoot`에 delegated `input` 리스너 + 디바운스 savePlan. 테마는 `:root` 변수라 팔레트만 바꾸면 전역 반영(상아색+연두). 전체발행은 `/api/publish_all`(그룹별 blocks 수집) — 되돌리기 어려우니 `confirm()` 필수.

9. **자가 QA(2026-07-01) — 프론트 "조용한 실패" 3종**: (a) **미선언 전역 참조**: `renderS4`가 백엔드 전역명 `state`(`state?.group_states`)를 참조 → ReferenceError로 **편집화면 전체가 안 그려짐**(생성 후 편집 불가, 치명적). 프론트/백엔드 전역명 겹침 주의. (b) **폴링 콜백이 error 미처리**: `doGen`/`doGenAll`의 `startPoll`이 `done`만 처리 → 생성 실패해도 조용히 사라져 "생성 안 됨"으로 보임. `status==='error'`·빈 초안 시 alert. (c) **`/api/profiles/<name>`가 함수 인자 `n`**(→`name`) 500 + `goSettings`가 설정(0) 아닌 프로필선택(-1)로 감. **교훈**: 인라인 `<script>`는 구문 OK여도 **런타임 미선언 참조/에러 무처리로 조용히 죽음** → `/browse`로 각 스텝 실제 렌더 + 실제 생성(E2E)까지 확인. 생성 파이프라인은 `init_engine()` 후 실제 OpenAI로 검증(초안·사진삽입·`<p>¥2,000</p>` 코드조립·URL 미누출 확인).

---

## 2026-07-02 — B(문체 따라하기) 구현 + 매니지먼트 관찰

1. **`.gitignore`의 앵커 없는 `plans/`가 `docs/superpowers/plans/`를 삼킴**: 루트 런타임 산출물(`plans/<title>/plan.json`)용 규칙 `plans/`가 앵커가 없어 CLAUDE.md가 커밋하라고 지시한 `docs/superpowers/plans/`까지 무시했다(specs는 무사, plans만 막힘). → `/plans/`로 루트 앵커링해 해결. **교훈**: gitignore 규칙은 의도 범위에 맞게 `/` 앵커링. `git check-ignore <path>`로 오탐 확인.

2. **문체 주입 = "규칙+예시", 원문 통째 금지(표절 불변식)**: `_style_context`는 LLM이 뽑은 규칙 JSON + **예시 문장 1~2개 상한**만 프롬프트에 넣는다. 원문 문단 통째 주입은 표절/복붙 위험이라 폐기. 회귀 테스트가 "긴 원문 문단이 조각에 안 실림"을 assert. 무료모드는 정규식 폴백(`extracted_by="regex_fallback"`), 폴백 어미는 여전히 파편기라 최소보장용.

3. **모델 라우팅 첫 적용(subagent-driven)**: 구현 subagent=sonnet, per-task 리뷰·최종 전체리뷰=메인루프(최고모델) 직접. 작고 완전히 테스트된 태스크는 리뷰어 subagent 남발 대신 컨트롤러가 diff 직접 검증(토큰 절감). **subagent는 부모 모델 상속 안 함 → Agent 호출마다 `model` 명시 필수.**

4. **subagent 세션 한도 중도 사망 대비**: 구현 subagent가 세션 한도로 커밋 전에 죽을 수 있다(Task5에서 발생 — 파일 편집은 됐으나 미커밋). **교훈**: subagent 보고를 믿지 말고 `git status`/`git show`로 실제 반영·커밋 여부 확인. 작은 배선은 컨트롤러가 이어받아 검증·커밋.

5. **post dict에 필드 추가 시 `/api/drafts` 직렬화도 함께 (E2E 테스트에서 발견)**: `/api/drafts/<gi>`는 **화이트리스트 직렬화**(title/content/tags/meta/hashtags만)라, `generate_drafts`가 post에 `seo_warnings`를 넣어도 API 응답에서 빠져 UI 배지가 안 떴다. 백엔드 단위테스트·회귀 전부 통과했는데 실제 E2E에서만 드러남. **교훈**: post 스키마 확장 시 소비 지점 3곳(generate_drafts→/api/drafts 직렬화→프론트) 전부 점검. 계획 단계에서 "데이터가 지나가는 모든 관문"을 나열할 것.

6. **포트 5000에 옛 서버 3개 중첩(#7d 재발)**: bash에서 `powershell -Command "... \"name='python.exe'\" ..."` 이스케이프가 깨져 Stop-Process가 **조용히 실패** → 11시/14시/16시 서버 3개가 SO_REUSEADDR로 같이 리스닝, 옛 코드가 응답해 "count=10인데 방문 3개, 불용어 미적용"처럼 보였다. **교훈**: 재시작 후 반드시 `netstat -ano | grep :5000 | grep LISTENING | wc -l`이 **1인지 확인**. 죽일 땐 PID를 netstat에서 직접 뽑아 `taskkill //F //PID`.

7. **발행 브라우저는 반드시 poster.close()로 닫는다 (강제종료 금지)**: 발행 Chrome을 안 닫으면 selenium_profile 잠금으로 다음 발행 전멸("session not created"), 잠금을 taskkill로 강제 해제하면 **네이버 세션이 무효화**되어 다음 발행에서 수동 로그인(180초)이 다시 필요해진다. 또한 발행이 낳은 **chromedriver가 Flask의 5000 리스닝 소켓을 상속**한 채 살아남아, 서버를 죽여도 유령 리스너가 포트를 잡는다(HTTP 000). → 2026-07-03 수정: 발행 task `finally: poster.close()`(정상 종료라 세션 보존+소켓 해제). 검증: 연속 2건 발행 성공, 2번째는 로그인 생략, chromedriver 0.

8. **curl로 한글 테스트 시 인코딩 2종 함정**: (a) `-F "photos=@한글파일.jpg"` → 멀티파트 파일명 깨져 "파일이 없습니다"(브라우저 업로드는 무관). ASCII 사본으로 테스트. (b) `-d '{"title":"한글"}'` → body가 cp949로 나가 Flask가 400 (utf-8 디코드 실패). UTF-8로 저장한 파일을 `--data-binary @file`로 보낼 것.

---

## 2026-07-03 — I라운드: 참고 포스트 퀄리티 업그레이드

1. **잘 된 남의 포스트는 DOM으로 실측 분석하라**: /browse로 참고 포스트(blog.naver.com/eng1470)의 `se-component` 시퀀스를 추출하니 "구분선→이모지 헤더→사진 콜라주+캡션→본문→구글맵 OG 카드→↑↑위치↑↑" 정형 패턴이 바로 드러났다. 텍스트만 읽어서는 콜라주/oglink 구조를 알 수 없다. 네이버 블로그는 iframe(`mainFrame`)이라 `frame --name mainFrame` 전환 필요.

2. **불변식 완화는 "이유"를 기준으로**: "구글맵 URL 절대 금지"의 이유는 본문 중 URL의 *비의도적* 카드 변환이었다. 참고 포스트는 반대로 독립 블록 URL로 카드를 *의도적으로* 유도한다 — 불변식을 "본문 텍스트 내 URL 금지 + 독립 블록 카드는 코드가 유도"로 정밀화(사용자 승인). AI 프롬프트의 URL 금지는 유지.

3. **에디터 빈 줄에서 Shift+Home은 무선택**: `_paste_map_card` 변환 실패 폴백에서 Enter로 새 빈 줄에 내려온 상태로 Shift+Home+Delete 하면 아무것도 안 지워져 URL 원문이 발행물에 남는다. Backspace로 URL 줄 끝에 복귀 후 선택·삭제해야 함. (subagent 구현을 diff 리뷰로 잡아낸 케이스 — 발행 경로는 키 시퀀스를 커서 위치 기준으로 시뮬레이션하며 리뷰할 것.)

4. **스펙의 매칭 키워드는 실제 데이터 enum과 대조**: `_expand_tags` 스펙이 영문 키워드(restaurant/cafe)만 나열했는데 실데이터 `vision.scene_type`은 한글 enum(맛집/신사/사찰)이라 그대로면 무동작이었다. fast-worker가 발견·보정. 매칭 로직 스펙을 쓸 때 실제 필드 값 도메인을 함께 명시할 것.

5. **PIL Image.open은 with로**: Windows에서 핸들이 안 닫혀 임시파일 os.remove가 PermissionError. `with Image.open(p) as src:` 필수.
