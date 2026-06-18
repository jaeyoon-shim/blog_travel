# 네이버 여행 블로그 자동화 시스템 — TravelBlog Pro

## 📋 프로젝트 개요

여행 사진을 업로드하면 **EXIF GPS + Vision AI** 분석을 통해 자동으로 네이버 블로그 포스트를 생성하고 발행하는 자동화 시스템.

### 핵심 파일

| 파일 | 줄 수 | 역할 |
|------|-------|------|
| `blog_auto.py` | ~1,950 | GUI 메인 (5단계 워크플로우) |
| `core.py` | ~2,450 | AI 초안 생성 엔진 (프롬프트, 사진 분석, 경로) |
| `posters.py` | ~1,500 | 네이버 블로그 발행 (Selenium, 블록 변환) |

---

## 🔄 버전 히스토리

### v1.0 ~ v2.3 (2026-02-19 ~ 02-24)
- 키워드 기반 블로그 자동화 → **여행 사진 기반으로 전면 전환**
- GPS + Vision AI 하이브리드 분석 구현
- Google Maps API 연동 (POI 정확도 향상)
- SEO 경쟁 분석 (네이버 상위 10개 블로그)
- 5탭 GUI 구현, 발행 시스템 구축

### v3.0 (2026-02-25)
- SaaS 스타일 UI 전면 리디자인 (스텝 인디케이터, 카드 레이아웃)
- Google Maps 경로 연동 (구간별 이동수단 선택)
- base64 이미지 인코딩 (브라우저 호환성)
- 복수 참고 블로그 스타일 분석

### v5~v6 (2026-02-25)
- 네이버 블로그 Selenium 자동 발행 완성
- 이미지 클립보드 방식 (win32clipboard)
- 발행 다이얼로그, 태그 입력, 공개 설정
- HTML → blocks 변환 시스템

### v7 (2026-02-25)
- EXIF 방향(회전) 보정
- STEP 순서 변경, 통합본 요약 포스팅
- html_to_blocks 재작성
- GIL 크래시 수정, 상세 로딩 표시

### v8 (2026-02-25 ~ 02-27) — 현재 버전
- 구글맵 링크 연동 수정 (map_link 블록)
- STEP 2 장소별 메모란 추가
- **디자인 전면 업그레이드** (아래 상세)

---

## 🎨 v8 디자인 업그레이드 상세

### 요청 기반 (참고: weeeunjee 블로그 스타일)

사용자가 실제 인기 여행 블로거의 디자인을 참고하여 요청한 사항:

#### 1. 세련된 블로그 디자인 시스템

**색상 체계:**
- `#8B9467` (올리브 그린) — 섹션 라벨, 포인트 강조
- `#3d3d3d` — 제목
- `#555` — 본문
- `#999` — 부제/태그라인
- `#d4d4d4` — 구분선

**타이포그래피:**
- `letter-spacing: 3px` (영문 라벨)
- `letter-spacing: 8px` (구분선)
- `line-height: 2.0` (본문 넓은 줄간격)
- `font-size: 0.8em` (라벨) / `0.92em` (본문) / `1.3em` (제목)

#### 2. 장소별 구분선
```
─ ─ ─ ─ ─ ─ ─
```
- 장소 전환, 인트로/아웃트로, 꿀팁 전후에 삽입
- `_insert_separator()` 메서드: 네이버 에디터 구분선 버튼 or 텍스트 폴백

#### 3. 블록 에디터 신규 블록 타입

| 블록 타입 | 설명 | 발행 방식 |
|-----------|------|-----------|
| `separator` | 구분선 (`─ ─ ─`) | `_insert_separator()` |
| `styled_label` | 색상+작은 라벨 (PLACE 1, TRAVEL TIPS) | `_paste_styled_text()` |
| `heading` | 장소 제목 (`<h2 data-place>`) | `_paste_styled_text(bold=True)` |

---

## ⚠️ 해결된 주요 버그 목록

### 1. NameError: free variable 'e' (blog_auto.py)
**증상:** `except Exception as e:` → `lambda` 안에서 `{e}` 참조 시 NameError  
**원인:** Python 3.x에서 except 블록 종료 시 변수 `e`가 삭제됨  
**수정:** 3곳 모두 `err_msg = str(e)` 으로 캡처 후 lambda에서 `err_msg` 참조
```python
# ❌ Before
except Exception as e:
    self.root.after(0, lambda: self.gen_lbl.config(text=f"❌ {e}"))

# ✅ After
except Exception as e:
    err_msg = str(e)
    self.root.after(0, lambda: self.gen_lbl.config(text=f"❌ {err_msg}"))
```

### 2. NameError: name '번호' is not defined (core.py)
**증상:** 프롬프트 f-string 안에서 `PLACE {번호}` → Python 변수로 해석  
**수정:** `PLACE {번호}` → `PLACE N` 으로 변경 (AI가 자동 채번)

### 3. 구글맵 OG 카드 문제 (core.py, posters.py)
**증상:** 네이버 에디터에 구글맵 URL 삽입 시 OG 링크카드 자동 생성
```
__https://www.google.com/maps/search/....__
Google Maps
Find local businesses, view maps and get driving directions...
www.google.com
```
**근본 원인:** 네이버 SE3 에디터가 URL을 감지하면 무조건 OG 카드로 변환. `_paste_hyperlink`이 네이버에서 작동하지 않아 URL이 텍스트로 노출됨  
**수정 (최종):** 구글맵 URL을 HTML에 **아예 넣지 않도록** 변경
- `_photo_html()`: `📍 장소명` 텍스트만 표시 (URL 없음)
- `_insert_route_guides()`: `📍 A → B 경로` 텍스트만 표시 (URL 없음)
- OG 카드가 원천적으로 생성되지 않음

### 4. 이동경로 위치 오류 (core.py)
**증상:** 경로 블록이 PLACE 2의 `<div>` 내부에 삽입됨  
**수정:** `_insert_route_guides`에서 `PLACE N` 라벨이 있는 `<div>` 시작점 **앞에** 경로 삽입

### 5. 사진→설명 패턴 위반 (core.py)
**증상:** 누락 사진 자동 삽입 시 사진이 연속 배치됨 (설명 텍스트 없이)  
**수정:** 자동 삽입 시 마지막 `</figure>` 뒤의 `</p>` (설명 텍스트) 뒤까지 찾아서 `<br/>` + 사진 삽입

### 6. AI가 구글맵 HTML 직접 삽입 (core.py)
**증상:** AI가 프롬프트 무시하고 구글맵 URL을 HTML에 직접 넣음 → 코드의 자동 삽입과 중복  
**수정:**
- 프롬프트 규칙 6번: "구글맵/이동경로 HTML을 **절대 넣지 마세요**"
- 시스템 메시지: "절대 구글맵 URL이나 이동경로 HTML을 넣지 마세요 - 자동 삽입됩니다"
- `gmap_note` 변수 완전 제거

### 7. Directions API REQUEST_DENIED
**증상:** Google Directions API 호출 시 REQUEST_DENIED 응답  
**원인:** API 키 권한 또는 Directions API 미활성화  
**조치:** fallback 직선거리 계산으로 정상 동작, 사용자에게 Google Cloud Console 확인 안내

---

## 📐 현재 프롬프트 구조 (AI 초안 생성)

### ★★★ 가장 중요한 구조 규칙 ★★★

```
1️⃣ 인트로
   ✈ {지역} 여행기 ✈
   📍 코스 요약
   소개글 2~3줄
   ─ ─ ─ ─ ─ ─ ─

2️⃣ 장소별 섹션 (반복) — 순서 엄수!
   (A) 장소 헤더: PLACE N + 장소명 한글 (현지어)
   (B) ★ 장소 소개글 3~4줄 (필수!) ★
   (C) 사진 + 사진설명 2~3줄 (반복)
   (D) 구글맵 — 넣지 않음 (코드 자동)
   (E) 구분선 ─ ─ ─
   (F) 이동경로 — 넣지 않음 (코드 자동)

3️⃣ TRAVEL TIPS
   ✔ 팁 4개

4️⃣ 아웃트로
   마무리 인사 + ✈ 다음 여행기에서 또 만나요 ✈
```

### 필수 규칙 9가지

1. **장소명:** 반드시 "한글 (현지어)" — 로마자 금지
2. **말투:** 친근한 구어체 (~했어요, ~더라고요)
3. **장소 소개글 3~4줄 필수** — 장소 헤더 바로 아래, 사진 위
4. **사진마다 2~3줄 설명** — 오감 자극 표현
5. **사진 배치:** N장 = [PHOTO:] N개 정확히
6. **구글맵/경로 HTML 절대 금지** — 코드 자동 삽입
7. **구분선:** 장소 전환마다 `─ ─ ─`
8. **색상/크기 일관성:** #8B9467, #555, #3d3d3d, line-height:2.0
9. **정확성:** 데이터에 없는 사실 지어내지 않기

---

## 🏗️ 시스템 아키텍처

### 5단계 워크플로우

```
STEP 1: 사진 선택 + 분석
  └─ EXIF GPS 추출 → Google Geocode → Vision AI 장면 설명
  └─ 일별/장소별/코스별 자동 그루핑

STEP 2: 구조 미리보기 + 편집
  └─ 장소별 메모란 (AI 초안에 반영)
  └─ 네이버 경쟁 블로그 SEO 분석
  └─ 참고 블로그 스타일 분석

STEP 3: AI 초안 생성
  └─ 감성 후기형 / 정보 가이드형 / 감성+정보 혼합형
  └─ 프롬프트: 사진 데이터 + SEO + 스타일 + 디자인 규칙
  └─ 사진 삽입: [PHOTO:파일명] → base64 figure 태그
  └─ 지도: 장소 마지막 사진 뒤 📍 장소명 텍스트
  └─ 경로: 장소 사이에 이동 경로 카드 자동 삽입

STEP 4: 블록 에디터
  └─ HTML → blocks 변환 (text, image, separator, styled_label, heading, route, map_link)
  └─ 드래그 앤 드롭 순서 변경
  └─ 텍스트 인라인 편집
  └─ AI 수정 요청 (선택 블록)

STEP 5: 발행
  └─ Selenium 네이버 에디터 자동 입력
  └─ 이미지: 클립보드 방식 (win32clipboard)
  └─ 텍스트: 가운데 정렬, 색상, 크기 적용
  └─ 태그, 공개설정, 발행 버튼 클릭
```

### 사진 → 블로그 데이터 흐름

```
사진 EXIF
  ├─ GPS (lat, lon) → Google Geocode → 장소명 (한글/현지어)
  ├─ DateTimeOriginal → 일별 그루핑, 경로 출발시간
  └─ Orientation → EXIF 방향 보정

Vision AI
  └─ 장면 설명 (scene_description) + 음식명 (food_name)

Google Places API
  └─ 장소별 특징 검색 (place_features)

Google Directions API
  └─ 장소간 이동시간, 거리, 경로 단계
  └─ fallback: 직선거리 계산
```

---

## 📝 수정 시 반드시 확인할 체크리스트

### AI 프롬프트 (core.py `_build_prompt`)
- [ ] 장소 소개글 3~4줄이 구조에 명시되어 있는가?
- [ ] 구글맵/경로 HTML 금지 규칙이 있는가?
- [ ] 사진→설명→사진→설명 패턴이 명시되어 있는가?
- [ ] 색상 체계 (#8B9467, #555, #3d3d3d) 일관성
- [ ] f-string 안의 중괄호가 이스케이프되었는가? (`{{` `}}` 또는 리터럴)

### 사진/지도 삽입 (core.py `_insert_photos_with_map`)
- [ ] 구글맵 URL이 HTML에 포함되지 않는가? (OG 카드 방지)
- [ ] 경로 URL이 HTML에 포함되지 않는가?
- [ ] 누락 사진 삽입 시 기존 사진-설명 흐름을 끊지 않는가?
- [ ] 장소 마지막 사진에만 `📍 장소명` 텍스트 표시

### 경로 삽입 (core.py `_insert_route_guides`)
- [ ] 경로가 PLACE 라벨 `<div>` **앞에** 삽입되는가? (내부 X)
- [ ] URL이 없는 텍스트만 표시되는가?

### 블록 변환 (posters.py `html_to_blocks`)
- [ ] separator, styled_label, heading 블록 정상 감지
- [ ] map_link 블록이 URL 없이도 동작하는가?

### 발행 (posters.py `post`)
- [ ] `_paste_hyperlink` 실패 시 텍스트만 표시되는가?
- [ ] URL이 에디터에 직접 입력되지 않는가? (OG 카드 방지)
- [ ] lambda 안에서 `e` 직접 참조하지 않는가?

### GUI (blog_auto.py)
- [ ] `except Exception as e` → `err_msg = str(e)` 패턴 사용
- [ ] f-string에 이스케이프 안 된 `{변수}` 없는가?

---

## 🔧 환경 설정

### .env 파일
```
OPENAI_API_KEY=sk-...
GOOGLE_MAPS_API_KEY=AIza...
NAVER_ID=네이버아이디
NAVER_PW=네이버비밀번호
```

### 필요 패키지
```
pip install openai selenium Pillow python-dotenv requests
pip install pyperclip  # 클립보드
# Windows만: pip install pywin32  (win32clipboard)
```

### Google Cloud Console
- **필수 활성화 API:**
  - Geocoding API
  - Places API
  - Directions API (경로 기능, 없으면 fallback 직선거리)
  - Maps Embed API (현재 미사용)

---

## 🐛 알려진 제한사항

1. **네이버 SE3 에디터 하이퍼링크:** 프로그래밍적 링크 삽입이 불안정 → URL 대신 텍스트만 사용
2. **Directions API REQUEST_DENIED:** API 키 권한 확인 필요, fallback으로 동작
3. **AI 프롬프트 준수율:** GPT가 구글맵 URL을 직접 넣거나 소개글을 빠뜨리는 경우 있음 → 프롬프트 강화로 대응
4. **네이버 에디터 글씨 크기/색상:** 자동화 안정성 100% 보장 불가 → 수동 확인 권장
