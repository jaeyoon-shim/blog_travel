# TravelBlog Pro — 기능명세 · 구조도 · 스펙

> 네이버 여행 블로그 자동화 시스템 (Web Edition v10)
> 여행 사진을 업로드하면 **EXIF GPS + Vision AI** 분석 → 감성 원고 자동 생성 → 네이버 블로그 자동 발행까지 수행하는 풀스택 자동화 도구.
> 본 문서 기준일: 2026-06-18

---

## 1. 개요 (Overview)

| 항목 | 내용 |
|------|------|
| 목적 | 여행 사진 → 장소·동선 자동 인식 → SEO 최적화 블로그 원고 생성 → 네이버 자동 발행 |
| 핵심 차별점 | GPS 역지오코딩 + Vision AI 하이브리드 장소 인식, 구글맵 경로 자동 삽입, 디자인 시스템 내장, 클립보드 기반 캡차 우회 발행 |
| 형태 | Flask 웹 서버(`app.py`) + 단일 페이지 UI(`index.html`) + 데스크톱 GUI 변형(`blog_auto.py`) |
| 입력 | 여행 사진(JPEG, EXIF/GPS 포함 권장) |
| 출력 | 네이버 블로그 포스트(자동 발행) + 로컬 저장본(`posts/`) |
| AI 모델 | OpenAI `gpt-4o-mini` (텍스트 + Vision) |

---

## 2. 시스템 구조도 (Architecture)

### 2.1 컴포넌트 다이어그램

```
┌──────────────────────────────────────────────────────────────────┐
│                         Browser (index.html)                       │
│   5-Step SPA UI — 업로드 → 분석 → 그룹/SEO → 생성 → 발행            │
└───────────────────────────────┬──────────────────────────────────┘
                                 │ REST + 폴링(/api/status)
┌───────────────────────────────▼──────────────────────────────────┐
│                          app.py (Flask)                            │
│   라우트 26종 · 전역 state · settings.json · 백그라운드 Thread      │
└───────┬───────────────────────┬──────────────────────────┬────────┘
        │                       │                          │
┌───────▼────────┐   ┌──────────▼───────────┐   ┌──────────▼─────────┐
│   core.py      │   │      posters.py       │   │  route_map_        │
│ (AI 엔진)      │   │  (네이버/티스토리 발행) │   │  capture.py        │
│                │   │                       │   │ (경로 지도 캡처)    │
│ Config         │   │ html_to_blocks        │   └────────────────────┘
│ PhotoAnalyzer  │   │ NaverSeleniumPoster   │
│ TripStructurer │   │ ClipboardPoster       │   ┌────────────────────┐
│ TravelBlog     │   │ TistorySeleniumPoster │   │  외부 API           │
│   Generator    │   │ NaverPoster/Tistory   │   │ OpenAI, Google Maps │
│ NaverBlog      │   └───────────────────────┘   │ Naver 검색, Nominatim│
│   Analyzer     │                                └────────────────────┘
│ StyleAnalyzer  │
│ LocalSaver     │
└────────────────┘
```

### 2.2 5단계 워크플로우 (데이터 흐름)

```
[STEP 1] 사진 업로드        POST /api/upload      → state.photo_paths
            │
[STEP 2] 사진 분석          POST /api/analyze     → PhotoAnalyzer.analyze_photos()
            │                                       · EXIF(촬영시각/GPS) 추출
            │                                       · GPS 역지오코딩(구글→Nominatim)
            │                                       · Vision AI 장면/음식 인식
            │                                       · 한글 장소명 번역
            │                                     → state.photo_results
            │                                     → TripStructurer.structure()
            │                                       (by_day / by_place / by_course)
            │
[STEP 3] 그룹 선택 + SEO    POST /api/seo,/style  → NaverBlogAnalyzer / StyleAnalyzer
            │                                       · 상위 블로그 제목패턴/구성 분석
            │                                       · 참고 URL 문체 분석
            │
[STEP 4] 원고 생성          POST /api/generate    → TravelBlogGenerator.generate_drafts()
            │               POST /api/generate_all  · 지역 위키 박스 생성(최상단)
            │                                        · 장소별 소개 검색
            │                                        · 프롬프트 빌드 → AI 호출
            │                                        · 사진 삽입 + 구글맵/경로 자동 삽입
            │                                      → drafts[] (HTML content)
            │
[STEP 5] 미리보기 + 발행    POST /api/publish     → html_to_blocks() → NaverPoster.post()
                            POST /api/publish_all   · Selenium 로그인(클립보드 캡차 우회)
                                                    · 제목/본문/이미지/태그 입력
                                                    · 공개설정 → 발행
                                                  → LocalSaver.save() (posts/)
```

---

## 3. 모듈 상세 명세

### 3.1 `core.py` — AI 엔진 (~2,520줄)

#### `Config`
환경설정 단일 진실원. `.env` + `config.json` 병합 로드.
- `DEFAULTS` / `ENV_MAP`(OPENAI_API_KEY, OPENAI_MODEL, GOOGLE_MAPS_API_KEY, NAVER_* 등)
- `get(*keys)`, `is_valid()`, `get_status()`

#### `StyleAnalyzer`
참고 블로그 URL → 문체(tone)·종결어미(endings)·구조 분석.
- `analyze(url)` → `{tone, common_endings, structure_summary, sample}`
- `_detect_tone()`, `_detect_endings()`

#### `NaverBlogAnalyzer`
키워드 기반 상위 블로그 SEO 분석.
- `analyze(keyword, count=5)` — 네이버 검색 API 또는 크롤링
- `_analyze_blog_page()`, `_infer_sections()`, `_aggregate_structures()`, `_detect_patterns()`, `_seo_tips()`

#### `PhotoAnalyzer` — 사진 분석 핵심
- `scan_folder(path)` / `analyze_photos(paths, progress_cb, result_cb)` — 배치 분석
- EXIF: `_extract_exif()`, `_dms()`, `_exif_to_epoch()`
- 역지오코딩: `_gps_to_addr()` → `_google_geocode()` → `_nominatim_geocode()` (폴백 체인)
- 장소명: `_make_place_name()`, `_translate_to_korean()`, `_batch_translate()`, `_guess_type()`
- Vision: `_vision_with_gps()`, `_vision()` — 장면/음식 인식
- 그룹화: `group_by_day()`

#### `TripStructurer`
여행 동선 구조화 — `structure()` → `{by_day, by_place, by_course}`
- `_group_by_day/place/course()`, `_haversine()` (좌표 거리)

#### `TravelBlogGenerator` — 원고 생성 핵심
- `generate_drafts(group, label, trip_title, naver_analysis, style_analysis)` — 스타일별 초안 N개
- `_detect_region()` → `_generate_region_desc()` **★ 지역 위키 박스 생성(소개+특산품/먹거리/관광지)**
- `_search_place_intros()` — 장소별 3줄 소개
- `_build_prompt()` — 디자인 규칙 내장 HTML 프롬프트
- `_call_ai()` — OpenAI 호출 + `_insert_photos_with_map()`
- 경로: `_fetch_route_data()`, `_insert_route_guides()` — 구간별 이동수단/경로지도
- `_photo_html()`, `_photo_summary()`, `_fetch_place_detail()`, `_naver_context()`, `_style_context()`

#### `LocalSaver`
`posts/` 폴더에 결과 저장 — `save(data, keyword)`

---

### 3.2 `app.py` — Flask 백엔드 (REST API)

전역 `state` dict로 세션 상태 관리, 무거운 작업은 `threading.Thread`(daemon) + `/api/status` 폴링.

| 라우트 | 메서드 | 기능 |
|--------|--------|------|
| `/` | GET | index.html 서빙 |
| `/api/settings` | GET/POST | 설정 조회/저장(settings.json) |
| `/api/settings/raw` | GET | 원본 설정 |
| `/api/profiles` `/<name>` `/save` | GET/POST/DELETE | 설정 프로필 관리 |
| `/api/status` | GET | 진행률 폴링(progress) |
| `/api/upload` | POST | 사진 업로드 → uploads/ |
| `/api/analyze` | POST | 사진 분석(백그라운드) |
| `/api/photos` `/rename` `/update` | GET/POST | 분석결과 조회·장소명 수정 |
| `/api/groups` | GET | 동선 그룹 조회 |
| `/api/seo` | POST | 상위블로그 SEO 분석 |
| `/api/style` | POST | 참고URL 문체 분석 |
| `/api/generate` `/generate_all` | POST | 원고 생성(단건/일괄, 백그라운드) |
| `/api/drafts/<gi>` `/blocks/<gi>/<di>` | GET | 초안/블록 조회 |
| `/api/preview` | POST | 미리보기 HTML |
| `/api/publish` `/publish_all` | POST | 네이버 발행(단건/일괄, 백그라운드) |
| `/api/save` | POST | 로컬 저장 |
| `/uploads/<file>` | GET | 업로드 이미지 서빙 |

보조: `load_settings()`, `save_settings()`, `init_engine()`, `blocks_to_html()`, `_apply_settings_to_generator()`

---

### 3.3 `posters.py` — 발행 엔진 (~1,520줄)

#### HTML 변환
- `html_to_blocks(html, photos)` — AI 생성 HTML → 네이버 에디터 블록 배열
  (text / image / separator / route / map / styled 등)
- `_html_to_text()`, `_html_to_text_with_links()`, `_parse_route_block()`

#### `NaverSeleniumPoster` (핵심 발행기)
클립보드 기반 캡차 우회. 발행 순서:
```
1. GoBlogWrite 진입 → 로그인 확인(_try_login: 클립보드 ID/PW 붙여넣기)
2. mainFrame iframe 진입 → 임시저장 팝업 닫기
3. 제목 입력(_input_title)
4. 본문 포커스(_focus_body) + 가운데정렬(_set_center_align)
5. 경로 이미지 사전 생성(_generate_route_images)
6. 블록 순회 삽입:
   · text → _paste_text / _paste_styled_text
   · image → _clipboard_set_image → _paste_image
   · separator → _insert_separator
   · link → _paste_hyperlink
7. 공개설정(_set_visibility) → 태그(_input_tags_in_dialog) → 발행
```
- 클립보드: `_clipboard_set_text()`, `_clipboard_set_image()` (win32clipboard)

#### 기타
- `ClipboardPoster` — 수동 붙여넣기 폴백
- `TistorySeleniumPoster` — 티스토리 발행
- `NaverPoster` / `TistoryPoster` — 파사드(`post(data, method, visibility, schedule)`)

---

## 4. 데이터 모델

### 4.1 `photo_result` (사진 1장 분석 결과)
```jsonc
{
  "file_name": "IMG_001.jpg", "file_path": "uploads/IMG_001.jpg",
  "gps": [lat, lon], "epoch": 1700000000,
  "location_name": "다자이후 텐만구", "location_name_local": "太宰府天満宮",
  "city": "후쿠오카", "region": "후쿠오카",
  "scene_type": "관광지", "scene_description": "...", "food_name": "",
  "vision": { "scene_type": "...", "mood": "..." }
}
```

### 4.2 `post` (생성된 초안)
```jsonc
{
  "title": "...", "content": "<위키박스><본문 HTML>",
  "tags": ["..."], "style": "감성", "region_desc": "<위키박스 HTML>",
  "course_line": "...", "group_label": "...", "photo_results": [...]
}
```

### 4.3 `settings.json` (UI 설정) / `config.json` (시스템 설정)
- `settings.json`: `blog_style`, `design.accent_color(#8B9467)`, `ref_urls`, `api`, `custom_prompt`
- `config.json`: `openai`, `naver`, `tistory`, `unsplash`, `google`, `settings`

---

## 5. 신규 기능 명세 — 지역 위키 박스 (2026-06-18)

> 원격 `blog_travel`의 `get_wiki_info()` 개념을 로컬 디자인 시스템에 맞춰 이식·강화.

| 항목 | 명세 |
|------|------|
| 함수 | `TravelBlogGenerator._generate_region_desc(region_hint)` |
| 입력 | 감지된 지역명(`_detect_region()` 결과) |
| 처리 | GPT에 JSON 요청 → `{intro, specialties[3-5], foods[3-5], spots[3-5]}` → **코드에서 HTML 박스 조립** |
| 출력 | 디자인 시스템(`#8B9467`, 중앙정렬, 라운드 박스) HTML, 글 **최상단** prepend |
| 가드 | 지역 미정/위치 오류/여행지/API 실패 시 `""` 반환 → 박스 생략, 본문 생성은 정상 |
| 설계 이유 | AI에 형식을 맡기지 않고 코드 조립 → 형식 붕괴 방지(구글맵 자동삽입과 동일 철학) |

박스 구조:
```
TRAVEL WIKI
📍 {지역} 여행 전 꼭 알아야 할 핵심 정보
{5줄 소개}
🎁 특산품  A · B · C
🍽 먹거리  A · B · C · D
🗺 관광지  A · B · C · D
```

---

## 6. 설정 · 의존성 · 실행

### 6.1 의존성 (`requirements.txt`)
`openai>=1.0` · `python-dotenv` · `selenium>=4.15` · `pyperclip` · `Pillow` · `beautifulsoup4` · `flask>=3.0` · `flask-cors`
(Windows 발행 시 추가: `pywin32`(win32clipboard), Chrome + chromedriver)

### 6.2 환경변수 (`.env`)
`OPENAI_API_KEY`(필수) · `OPENAI_MODEL` · `GOOGLE_MAPS_API_KEY` · `NAVER_ID` · `NAVER_PW` · `NAVER_CLIENT_ID/SECRET`(검색API)

### 6.3 실행
```bash
venv\Scripts\python.exe app.py     # → http://localhost:<port>
```

---

## 7. 제약 · 주의사항

- **네이버 React 에디터**: JS click이 아닌 **Selenium/ActionChains click** 필수(동기 이벤트 트리거). 본문 포커스는 반드시 Selenium click.
- **클립보드 발행**: 발행 중 OS 클립보드 점유 — 발행 동안 다른 복붙 금지.
- **GPS 없는 사진**: 역지오코딩 불가 → 장소 "미확인", Vision만으로 작성.
- **위치/지역 감지 실패 시**: 위키 박스·구글맵 자동 생략(에러 아님).
- **AI 콘텐츠 품질**: 위키 박스 카테고리(특산품 vs 먹거리)에 GPT 혼동 여지 — 프롬프트 제약으로 보정 가능.
- **발행 안정성**: 임시저장 팝업/iframe 타이밍 의존 → `time.sleep` 다수. 네이버 DOM 변경 시 셀렉터 점검 필요.

---

## 8. 파일 인덱스

| 파일 | 줄수(약) | 역할 |
|------|---------|------|
| `app.py` | 670 | Flask 백엔드 · REST API · 상태관리 |
| `core.py` | 2,520 | AI 엔진(사진분석·동선·원고생성) |
| `posters.py` | 1,520 | 네이버/티스토리 발행 · HTML→블록 |
| `index.html` | — | 5단계 SPA UI |
| `blog_auto.py` | 1,950 | 데스크톱 GUI 변형(Tkinter) |
| `route_map_capture.py` | — | 경로 지도 이미지 캡처 |
| `test_naver_upload.py` | — | 네이버 업로드 테스트 |
| `config.example.json` | — | 시스템 설정 템플릿 |
| `README.md` | — | 버전 히스토리(v1~v8) |
| `SPEC.md` | — | 본 문서 |
