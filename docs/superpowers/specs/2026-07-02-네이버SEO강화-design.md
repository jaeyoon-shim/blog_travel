# 네이버 SEO·핵심 태그 강화 (E) — 설계 문서

- 날짜: 2026-07-02
- 로드맵 위치: **E. 네이버 상위구조 기반 생성 강화** (sub-project, [[plan-review-feature-roadmap]])
- 사용자 요청: ① 네이버 SEO 분석 및 로직에 반영 ② 핵심 태그 추출 및 반영
- 상태: 설계 승인됨 → writing-plans로 구현계획

## 1. 배경 · 현재 상태

이미 있는 것:
- `NaverBlogAnalyzer.analyze(keyword)` — 네이버 API/크롤링으로 상위 블로그 수집 → **상위 3개** 본문 방문(모바일 URL) → 글자수·이미지·지도·섹션 구조 분석 → 평균 스펙 + 빈도 키워드(`common_keywords` 15개) + 제목 패턴.
- `/api/seo` — plan 확정 region → `"<지역> 여행"` 키워드 자동. STEP4 opt-in 버튼(`doSeo`)으로 연결(2026-07-02). 실패해도 생성 무관.
- `_naver_context` — 분석 결과를 생성 프롬프트에 `[네이버 SEO 분석]` 참고 조각으로 주입.
- 태그 — AI가 tags 7개/hashtags 5개를 자유 생성. SEO 키워드와 연결 없음.

발견된 기존 결함(이번 범위에 포함):
1. **`_naver_context`의 "지도 삽입 필수" 문구(core.py:3181)** — 상위 블로그 지도 비율 30%+면 AI에게 지도를 넣으라고 지시 → **"형식은 코드가 조립, AI는 본문만" 불변식과 정면 충돌**. AI가 지도 HTML/URL을 넣으려 시도하게 유도.
2. SEO 반영이 전부 "프롬프트 참고자료"라 AI가 무시해도 검증이 없음.

## 2. 목적 · 결정

- **반영 강도(사용자 결정): 코드가 검증·강제.** 프롬프트 참고 + 생성 후 코드가 후처리로 강제(태그 병합)·검증(경고 노출). 로드맵의 "골격은 코드가 강제, 세부는 AI".
- **태그 전략: 코드 추출 + AI 병합.** 핵심 태그 3~5개는 코드가 실측 데이터에서 추출해 항상 보장, AI 태그로 다양성 채움.
- **분석 확장: 본문 방문 3→10개.** 성공분만 집계, opt-in 격리 유지로 스크래핑 리스크 수용.

### 접근법 비교
| 접근 | 요약 | 채택 |
|---|---|---|
| **A. 분석 확장 + 코드 검증·강제 계층** | 프롬프트 참고 + 생성 후 태그 병합·SEO 검증 경고 | ✅ |
| B. 프롬프트 강화만 | 분석 확장·키워드 정제만, 강제 없음 | ✗ 반영 강도 결정과 불일치 |
| C. 자동 재생성 루프 | 검증 실패 시 AI 재생성까지 | ✗ 토큰 비용·루프 복잡성, YAGNI |

## 3. 아키텍처

```
/api/seo (opt-in) ─▶ NaverBlogAnalyzer.analyze(keyword, count=10)   ← 확장
                          │ state["naver_analysis"] (스키마 불변)
                          ▼
generate ─▶ _naver_context(참고 프롬프트, 지도문구 수정)             ← 결함 수정
   │
   ▼ 초안 생성 직후 (generate_drafts 내부, 초안별)
   ├─ extract_core_tags(analysis, region) → merge_tags → post["tags"]  ← 신규(강제)
   └─ seo_check(post, analysis) → post["seo_warnings"]                 ← 신규(검증)
                          │
                          ▼
static/index.html STEP4 초안 카드에 ⚠️ 경고 배지                      ← 신규(가시화)
```

원칙: **핵심 태그·검증은 코드가 보장, 본문 표현은 AI.** 자동 재생성 없음(경고만, 판단은 사용자).

## 4. 컴포넌트 (경계 · 책임)

- **`NaverBlogAnalyzer.analyze(keyword, count=10)`** (개선) — 검색 수집 10개, 본문 방문 `[:3]`→`[:10]`(성공분만 집계, 개별 실패 무시, 요청 간 0.3s 유지). 반환 스키마 변경 없음(기존 소비부 무영향).
- **`NaverBlogAnalyzer._extract_keywords(titles, descs, keyword)`** (staticmethod로 추출·정제) — 기존 인라인 빈도 로직을 분리. 한글 조사·불용어 제거, 검색 키워드 자체 제외. 순수함수.
- **`TravelBlogGenerator.extract_core_tags(analysis, region) -> list[str]`** (신규 staticmethod, 순수) — `common_keywords` 상위 + `{region}`, `{region}여행`, `{region}맛집`(분석에 맛집 신호 있을 때) 조합에서 **3~5개**. analysis 없으면 region 기반 최소 태그, region도 없으면 `[]`(조용히 생략).
- **`TravelBlogGenerator.merge_tags(ai_tags, core_tags, cap=10) -> list`** (신규 staticmethod, 순수) — 핵심 태그 우선 배치 + AI 태그로 채움, 정규화(공백/# 무시) 중복제거, 상한 10.
- **`TravelBlogGenerator.seo_check(post, analysis) -> list[str]`** (신규 staticmethod, 순수) — 경고 목록: ① 제목에 핵심 키워드(지역명 또는 빈도 1위) 미포함 ② 본문 텍스트 길이 < 상위 평균 60% ③ 태그에 지역명 부재. analysis 없으면 `[]`.
- **`generate_drafts`** (수정 최소) — 초안 dict 완성 직후: `post["tags"] = merge_tags(post.get("tags"), extract_core_tags(...))`, `post["seo_warnings"] = seo_check(post, naver_analysis)`.
- **`_naver_context`** (결함 수정) — `"지도 삽입 필수"` → `"지도·경로는 코드가 자동 삽입하니 본문에 절대 넣지 말 것"`.
- **`static/index.html`** — STEP4 초안 카드에 `seo_warnings` 있으면 ⚠️ 배지 + 목록.

## 5. 데이터 모델

`post` dict에 1개 필드 추가:
```json
"seo_warnings": ["제목에 '후쿠오카' 미포함", "분량 2,100자 — 상위 평균(4,800자)의 44%"]
```
빈 리스트면 UI 미표시. `naver_analysis` 스키마 불변.

## 6. 에러 처리 · 불변식

- **분석 실패/부재**: `extract_core_tags`/`seo_check` 안전 폴백(최소 태그 or 빈 경고) — 생성 절대 안 죽음. `/api/seo` opt-in이라 스크래핑 리스크는 생성 경로 밖 격리 유지.
- **개별 블로그 방문 실패**: `None` 반환 → 건너뜀. 성공 0이면 기존 `_aggregate_structures` 빈 폴백.
- **불변식 ①(형식은 코드)**: 지도 삽입 유도 문구 제거 포함. 신규 함수들은 텍스트·리스트만 다루고 HTML/URL 생성 없음.
- **불변식 ②(환각 방지)**: 핵심 태그는 실측 데이터(상위 빈도 + 확정 region)만 조합. LLM 호출 없음 — 태그 계층 전체 결정적.
- **경고는 경고**: `seo_warnings`는 발행을 막지 않음. 자동 수정/재생성 없음.

## 7. 테스트 (순수함수, 네트워크 없음 — tests/test_quality.py 관례)

- `test_extract_keywords_stopwords` — 조사·불용어·검색키워드 자신 제외.
- `test_extract_core_tags` — 빈도+region 조합 3~5개 / analysis 없음→region 최소 / 둘 다 없음→`[]`.
- `test_merge_tags` — 핵심 우선, 정규화 중복제거, 상한 10.
- `test_seo_check_warnings` — 3종 경고 각각 + analysis 없으면 `[]`.
- `test_naver_context_no_map_directive` — "지도 삽입 필수" 부재 + "넣지 말 것" 포함(불변식 회귀 방지).

## 8. 변경 범위

- `core.py`: `analyze` count 확장, `_extract_keywords` 추출, `extract_core_tags`/`merge_tags`/`seo_check` 신규, `generate_drafts` 3줄, `_naver_context` 문구.
- `static/index.html`: STEP4 경고 배지.
- `tests/test_quality.py`: 5개 테스트.

## 9. 범위 밖 (YAGNI)

- 자동 재생성 루프(접근법 C), 네이버 API 키 발급 플로우, 검색 순위 추적, Selenium 스크래핑 전환, hashtags 강제(태그만 강제 — hashtags는 AI 자유 유지).
