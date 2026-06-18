# 글 퀄리티 업그레이드 — 매장명 정확화 · 경로 정상화 · 환각 차단

작성일: 2026-06-18
대상: `D:\project\blog_writer2` (TravelBlog Pro 웹에디션)
관련: [SPEC.md](../../../SPEC.md), `core.py`, `posters.py`

---

## 1. 문제 정의 (Problem)

실발행 글(blog.naver.com/turetle008/224319981338)에서 두 가지 품질 결함 확인:

1. **방문 매장명이 이상함** — 사진 3장이 모두 같은 GPS(우오마치, 33.883734/130.879971)인데 결과 글에서 서로 다른 가게(`둥부르 → 두번 → 도시락`)로 나뉨.
2. **경로가 이상함** — 같은 자리 사진들 사이에 의미 없는 이동 경로가 삽입됨(+ Directions API 미활성으로 REQUEST_DENIED).

### 근본 원인 (Root Cause)
- **매장명**: 구글 Geocoding이 실제 가게가 아닌 **동네(locality "Uomachi")** 까지만 반환(`is_poi=False`). `_make_place_name()`이 "우오마치 카페" 같은 막연한 이름을 만들고, AI가 섹션을 나누려 **상호명을 지어냄**(환각).
- **경로**: 같은/근접 GPS 사진이 별개 장소로 분리(`_group_by_place`) → 장소 간 경로 자동 삽입 로직이 헛경로 생성.

---

## 2. 범위 (Scope)

이번 이터레이션은 **두 근본 수정 + AI 환각 차단**에 집중. 본문 묘사 품질·전체 구조/디자인은 범위 밖(별도 이터).

### 핵심 설계 원칙
- **API가 켜지면 자동 정확화**, **안 켜져 있어도 최악 증상(가짜이름·헛경로)은 즉시 제거**되는 구조(graceful degradation).

---

## 3. 사전 확인된 환경 제약 (Verified Constraints)

2026-06-18 실측:
- ✅ Geocoding API: 활성 (현재 GPS→주소 동작)
- ❌ Places API (legacy): `REQUEST_DENIED` — "legacy API not enabled"
- ❌ Places API (New) `searchNearby`: HTTP 403 `API_KEY_SERVICE_BLOCKED`
- ❌ Directions API: `REQUEST_DENIED` (경로 조회)

→ 매장명 자동 정확화 풀가동에는 **사용자 액션 필요**(§7).

---

## 4. 컴포넌트 설계 (Components)

### ① PlaceResolver — 실제 상호명 해석 (신규)
- **위치**: `core.py`의 `PhotoAnalyzer` 신규 메서드 `_resolve_poi_name()`. 기존 `_gps_to_addr` 바로 뒤 흐름에 통합(별도 모듈로 분리하지 않음 — geocoding 로직과 응집).
- **트리거**: geocoding 결과 `is_poi=False`일 때만 호출(POI면 그대로 사용).
- **입력**: `(lat, lon, scene_type)` — scene_type은 Vision 결과(카페/맛집/관광지 등).
- **처리**: Places API (New) `places:searchNearby`
  - endpoint: `POST https://places.googleapis.com/v1/places:searchNearby`
  - header: `X-Goog-Api-Key`, `X-Goog-FieldMask: places.displayName,places.primaryType,places.location,places.id`
  - body: `locationRestriction.circle`(반경 100m), `includedTypes`(scene_type→Places type 매핑), `maxResultCount: 8`, `languageCode: "ko"`
  - 선택: 가장 가까운(거리) 결과 중 scene_type 타입 일치 우선.
- **출력**: `{poi_name, poi_id, poi_type, poi_resolved: True}` 또는 실패 시 `None`.
- **캐시**: GPS 소수 4자리 반올림 키로 세션 캐시(같은 좌표 중복 호출 방지).
- **Fallback**: API 차단/결과없음/예외 → 기존 동네명 기반 이름 유지 + `poi_resolved=False` 플래그를 photo_result에 기록.

### ② POI 그룹 중복 제거
- **위치**: `TripStructurer._group_by_place` (1243~)
- **변경**: 그룹 키를 `poi_id`(있으면) 또는 `정규화 상호명 + 반올림좌표`로 사용 → 같은 POI 사진을 한 그룹으로 병합. 같은자리 분할(`둥부르/두번/도시락`) 제거.

### ③ 경로 거리 게이트
- **위치**: `TravelBlogGenerator._fetch_route_data` / `_insert_route_guides` (1928~, 2071~)
- **변경**: 연속 장소 쌍에 대해 `_haversine`(이미 존재, 1315) 거리 계산.
  - 동일 `poi_id` 또는 거리 < **300m**(기본 임계, 상수화) → 경로 **완전 생략**(가이드·지도·API 호출 모두 skip).
  - 임계 이상만 경로 표시.
- **API 독립**: 거리 계산은 좌표만 사용 → Directions API 없이도 헛경로 제거 즉시 동작. (경로 *지도 이미지*는 Directions/Static Maps 활성 시에만 추가 렌더)

### ④ AI 가짜이름 차단
- **위치**: `TravelBlogGenerator._build_prompt` (1579~)
- **변경**: 프롬프트에 명시 규칙 추가
  - "장소명은 반드시 아래 [방문 장소 목록]에 제공된 이름만 사용한다. 목록에 없는 새 가게/상호명을 지어내지 말 것."
  - "`<h2 data-place="...">`의 장소명은 제공된 목록 이름과 **정확히 일치**해야 한다."
  - `poi_resolved=False`인 장소는 "동네 기반 일반 명칭"임을 컨텍스트로 표시 → AI가 과도하게 구체화하지 않도록.

---

## 5. 데이터 흐름 (Data Flow)

```
analyze_photos
  └ _gps_to_addr → is_poi?
        ├ True  → poi_name 그대로, poi_resolved=True
        └ False → PlaceResolver._resolve_poi_name(lat,lon,scene_type)
                     ├ 성공 → poi_name=상호명, poi_resolved=True
                     └ 실패/차단 → _make_place_name(동네+type), poi_resolved=False
  ↓ (photo_result에 poi_id/poi_resolved 기록)
TripStructurer._group_by_place  (poi_id/상호명 기준 그룹 병합)
  ↓
generate_drafts
  ├ _build_prompt  (장소목록 주입 + 가짜이름 금지 + poi_resolved 표시)
  ├ _fetch_route_data / _insert_route_guides  (거리<300m or 동일POI → 경로 생략)
  └ _call_ai → content
```

---

## 6. 에러 처리 & 검증 (Error Handling & Testing)

### 에러 처리
- Places API 모든 실패(403/REQUEST_DENIED/타임아웃/빈결과)는 **조용히 fallback** + 1회 warning 로그. 글 생성은 절대 중단되지 않음.
- 캐시로 차단 상태에서 반복 호출/지연 최소화.

### 테스트
- **유닛**
  - PlaceResolver: 정상 응답(mock)→상호명 추출 / 403·빈결과→`None` fallback / 캐시 적중.
  - 거리 게이트: 동일좌표·<300m→생략, ≥300m→유지 (haversine 경계값).
  - 그룹 중복: 같은 poi_id 3장→1그룹.
- **E2E**(기타큐슈 사진 재생성)
  - 생성된 모든 `data-place` 장소명 ⊆ 해석된 장소 집합 (지어낸 이름 0건).
  - 같은자리 사진 사이 경로 블록 0건.
  - (Places 활성 시) 동네명 대신 실제 상호명 등장.

---

## 7. 의존성 & 사용자 액션 (Dependencies)

- **선택(매장명 풀가동용)**: Google Cloud Console에서
  1. **Places API (New)** 활성화
  2. 해당 API 키의 **API 제한**에 Places API (New) 추가(또는 제한 해제)
- 미적용 시: ③④는 그대로 작동(헛경로·가짜이름 제거), 매장명은 동네명 안전 폴백.

## 8. 범위 밖 (Out of Scope)
- 본문 사진 설명/장소 소개 묘사 품질 개선
- 글 전체 구조·섹션 순서·디자인 재설계
- Directions API 기반 경로 *지도 이미지* 품질(활성화는 사용자 몫)
