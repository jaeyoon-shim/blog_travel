# TravelBlog Pro — 전체 워크플로우 가이드

> 6단계 흐름의 화면·기능·사용자 입력·API·산출물 총정리.
> 기준일: **2026-07-03** (커밋 `862666d`). 모듈/클래스 상세는 `SPEC.md`(구조), 이력은 `README.md`/`docs/*진행내역*.md` 참고.

## 전체 흐름 한눈에

```
STEP1 설정 → STEP2 업로드 → STEP3 계획검수 → STEP4 AI생성 → STEP5 편집(피드백) → STEP6 발행
(계정/스타일)  (사진+영수증)   (1차 수정)      (가안 생성)    (2차 수정→최종본)   (검수·발행)
```

- 무거운 작업(분석/생성/재작성/발행)은 전부 **백그라운드 스레드 + `/api/status` 폴링**.
- 상태는 서버 메모리(`state`) — **서버 재시작 시 업로드/초안 소실**(계획은 `plans/<제목>/plan.json` 파일로 보존).
- 기존 프로필이 있으면 STEP1은 자동 로드되고 STEP2로 바로 진입.

---

## STEP 1 — 설정 (계정·스타일 프로필)

| 구분 | 내용 |
|---|---|
| 기능 | 프로필(계정별 설정 묶음) 저장/불러오기/삭제. 블로그 스타일·디자인·API·커스텀 프롬프트 관리 |
| **사용자 입력** | 프로필명 · 말투(친근 구어체/정중 존댓말/캐주얼)·톤·이모지 수준·사진설명/장소소개 분량 · 꿀팁/아웃트로 포함 여부 · 포인트 색/구분선/장소 라벨 · OpenAI/Google/네이버 키 · 발행 방식(selenium/clipboard)·기본 공개설정 · 추가 지시/금지 표현/필수 키워드 · 참고 블로그 URL 목록 |
| API | `GET/POST /api/settings`, `GET /api/profiles`, `GET/POST/DELETE /api/profiles/<name>`, `POST /api/profiles/save` |
| 산출물 | `settings.json`, `profiles/<name>.json` |
| 비고 | API 키는 응답에서 마스킹. `.env`가 있으면 키는 .env 우선 |

## STEP 2 — 업로드 (사진 + 영수증)

| 구분 | 내용 |
|---|---|
| 기능 | 사진 다중 업로드 → **사진 분석**(EXIF GPS → 역지오코딩 → Vision AI → POI 간판 교차검증). 영수증은 업로드 즉시 OCR |
| **사용자 입력** | 여행 사진 여러 장(JPEG, **GPS EXIF 권장** — 없으면 장소 인식 제한) · (선택) 영수증 이미지 — 가게명/금액/날짜 자동 인식, STEP3에서 장소에 자동 매칭 · [🔍 사진 분석 시작] 클릭 |
| API | `POST /api/upload`(multipart `photos`), `POST /api/receipts/upload`, `POST /api/analyze` → 폴링 |
| 산출물 | `uploads/` 파일, `state.photo_results`(사진 1장 = photo_result dict), `state.receipts` |
| 비고 | 무료 모드(Google 키 없음)면 Nominatim 폴백 — 상호명 정확도 낮음 배너 표시. 재진입 시 업로드 상태 복원 |

## STEP 3 — 계획검수 (일자별 기획 / 기획 수정 = 유저 1차 수정)

| 구분 | 내용 |
|---|---|
| 기능 | 분석 결과로 **일정 초안(plan)** 자동 생성 → 사람이 검수·확정. 이 plan이 이후 모든 생성의 단일 진실원 |
| **사용자 입력** | *일자별 기획 탭*: 장소 카드마다 이름 수정 · 있었던 일(사건) · 느낌 · 글 지시사항 · 별점 · 영수증 배정/재배정 — *기획 수정 탭*: 장소 🔗합치기/✂분리 · 사진 이동/제외 — *여행 설정*: 여행 제목 · 참고 블로그 URL(+[🔍 스타일 분석] = 문체 프로파일 추출) |
| API | `POST /api/plan/draft`(초안), `GET/POST /api/plan`(저장 — **plan dict를 래핑 없이 POST**), `/api/plan/stop/move`, `/api/plan/exclude`, `/api/plan/receipt`, `POST /api/style`(문체) |
| 산출물 | `plans/<제목>/plan.json`, `state.style_analysis`(문체 프로파일) |
| 비고 | 편집은 디바운스 자동저장 + 수동 저장. 지도(OSM)는 검수 화면 전용 — 발행물에는 절대 미포함. 같은 위치 무명 사진은 GPS로 자동 묶임 |

## STEP 4 — AI 생성 (가안)

| 구분 | 내용 |
|---|---|
| 기능 | plan 기반 그룹(Day)별 **가안 생성**. 생성 시 자동: ① SEO 분석 미실행이면 자동 1회 확보 → ② 지역 위키박스(실측 키워드 근거) → ③ 사진·경로·가격줄 코드 조립 → ④ 핵심 태그 병합(지역명 선두 보장) → ⑤ SEO 검증 경고 부착 → ⑥ PLACE 채번 |
| **사용자 입력** | 그룹(Day) 선택 · 글 스타일(감성 후기형/정보 가이드형/코스 추천형) 택1 · (선택) [상위 글 분석 실행] SEO 수동 실행 · 장소별 메모 · [생성] 또는 [전체 생성] |
| API | `POST /api/generate` `{group_index, title, structure, place_memos, route_modes}`, `POST /api/generate_all`, `POST /api/seo`(opt-in) → 폴링 |
| 산출물 | `state.group_states[gi].drafts[]` (post dict: title/content/tags/hashtags/seo_warnings/region…) |
| 비고 | 불변식: **형식(위키박스·지도·경로·가격)은 코드가 조립, AI는 본문만**. 구글맵 URL은 HTML에 절대 미포함 |

## STEP 5 — 편집 (유저 2차 수정 → 최종본)

| 구분 | 내용 |
|---|---|
| 기능 | 가안 확인 → **✍️ 피드백으로 다듬기**(자연어 피드백 → AI가 최종본 재작성, 반복 가능) → 블록 단위 미세 조정 → 실시간 미리보기 |
| **사용자 입력** | ⚠️ SEO 점검 경고 확인(제목 키워드/분량/태그 — 참고용, 발행 안 막음) · **피드백 텍스트**(예: "더 감성적으로 / 2일차 늘려줘") + [✨ 최종본 재작성](confirm 필요 — 블록 수동 편집 초기화됨) · 제목 수정 · 블록 이동↑↓/삭제×/텍스트·구분선 추가/내용 편집 |
| API | `GET /api/drafts/<gi>`, `GET /api/blocks/<gi>/<di>`, `POST /api/revise` `{gi, di, feedback}` → 폴링, `POST /api/preview` |
| 산출물 | 갱신된 draft(content/tags/seo_warnings), 편집된 blocks |
| 비고 | 재작성은 **자산 잠금**: 사진·위키박스·경로카드는 AI가 못 건드림. 실패 시 원본 무손상. 권장 순서: **피드백 재작성 먼저 → 블록 미세조정은 마지막** |

## STEP 6 — 발행 (검수·발행)

| 구분 | 내용 |
|---|---|
| 기능 | 네이버 자동 발행(단건/전체) 또는 로컬 저장. 영수증 이미지는 발행에서 자동 제외(개인정보) |
| **사용자 입력** | 공개설정(기본 **비공개** — 알 수 없는 값도 비공개로 폴백) · 발행 방식 · [발행] 또는 [전체 발행](confirm 필수) · 세션 풀렸으면 뜨는 Chrome 창에서 **180초 내 네이버 로그인**(1회 하면 저장됨) |
| API | `POST /api/publish` `{title, blocks, tags, visibility}`, `POST /api/publish_all` `{groups:[{title,blocks,tags}], visibility}`, `POST /api/save`(로컬) → 폴링 |
| 산출물 | 네이버 포스트 URL(진행 메시지에 표시), `posts/*.html`(로컬 저장) |
| 비고 | **발행 중 클립보드 점유 — 복사/붙여넣기 금지**. 발행 후 브라우저 자동 종료(연속 발행 안전). 실패 시 "실패 N개·성공 M개 — 제목: 사유"로 정직 보고 |

---

## 자주 겪는 상황

| 상황 | 원인/대처 |
|---|---|
| 생성이 평소보다 10~20초 느림 | SEO 분석 자동 확보 중("지역 상위 블로그 분석 중...") — 정상 |
| 위키박스/지도 없음 | 지역 감지 실패 시 조용히 생략(에러 아님). GPS 있는 사진인지 확인 |
| 발행에서 "로그인 실패" | 네이버 세션 만료 — 발행 재시도 후 뜨는 창에서 직접 로그인(180초) |
| 서버 재시작 후 초안 사라짐 | state는 인메모리. plan은 파일 보존 — STEP2부터 다시(사진 재업로드→분석) |
| "상호명 정확도 낮음" 배너 | 무료 모드(Google 키 없음). 계획검수에서 이름 직접 확인 권장 |
