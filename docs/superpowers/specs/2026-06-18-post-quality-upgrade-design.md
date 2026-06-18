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

이번 이터레이션은 **매장명 정확화 + 일정/경로 정상화 + AI 환각 차단**에 집중. 본문 묘사 품질·전체 구조/디자인 재설계는 범위 밖(별도 이터).

- 그룹화는 **지역+시간 기반 일정(세그먼트)** 모델로 재정의(§4②). 세그먼트는 *경로 위치 결정·장소 묶음*에 사용하며, 가시 산출물은 **세그먼트 경계의 이동 안내**뿐(별도 장식 헤더/섹션 재설계는 범위 밖).

### 핵심 설계 원칙
- **API가 켜지면 자동 정확화**, **안 켜져 있어도 최악 증상(가짜이름·헛경로)은 즉시 제거**되는 구조(graceful degradation).

---

## 3. 사전 확인된 환경 제약 (Verified Constraints)

2026-06-18 실측:
- ✅ Geocoding API: 활성 (현재 GPS→주소 동작)
- ✅ **Places API (New) `searchNearby`: 활성·검증 완료** (키 제한에 추가 후). 우오마치 좌표에서 실제 상호 10건 한글 반환(예: "샌드위치 팩토리 OCM"/sandwich_shop, "스케상우동 우오마치점"). **languageCode=ko로 한글 직접 반환 → 별도 번역 불필요.**
- ❌ Directions API: `REQUEST_DENIED` (경로 *지도 이미지*용 — 본 작업은 경로 위치 판정만 하므로 불필요)

→ 매장명 자동 정확화 즉시 가동 가능.

---

## 4. 컴포넌트 설계 (Components)

### ① PlaceResolver — 실제 상호명 해석 (신규)
- **위치**: `core.py`의 `PhotoAnalyzer` 신규 메서드 `_resolve_poi_name()`. 기존 `_gps_to_addr` 바로 뒤 흐름에 통합(별도 모듈로 분리하지 않음 — geocoding 로직과 응집).
- **트리거**: geocoding 결과 `is_poi=False`일 때만 호출(POI면 그대로 사용).
- **입력**: `(lat, lon, scene_type)` — scene_type은 Vision 결과(카페/맛집/관광지 등).
- **처리**: Places API (New) `places:searchNearby`
  - endpoint: `POST https://places.googleapis.com/v1/places:searchNearby`
  - header: `X-Goog-Api-Key`, `X-Goog-FieldMask: places.displayName,places.primaryType,places.location,places.id`
  - body: `locationRestriction.circle`(반경 100~150m), `includedTypes`(scene_type→Places type 매핑), `maxResultCount: 10`, `languageCode: "ko"`
  - FieldMask: `places.displayName,places.primaryType,places.location,places.id`
- **선택(랭킹) 로직**: 후보 중 **① Vision scene_type ↔ Places primaryType 일치** 우선, 그 다음 **② GPS 거리 가까운 순**. 매핑 예: 카페→{cafe, bakery, coffee_shop}, 맛집/음식→{restaurant, *_restaurant, sandwich_shop, izakaya}, 관광지→{tourist_attraction, point_of_interest}, 쇼핑→{store, shopping_mall, discount_store}. 일치 후보 없으면 최근접 POI.
- **출력**: `{poi_name, poi_id, poi_type, poi_resolved: True}` 또는 실패 시 `None`. displayName이 한글이므로 `_translate_to_korean` 불필요.
- **캐시**: GPS 소수 4자리 반올림 키로 세션 캐시(같은 좌표 중복 호출 방지).
- **Fallback**: API 차단/결과없음/예외 → 기존 동네명 기반 이름 유지 + `poi_resolved=False` 플래그를 photo_result에 기록.

### ② 2단계 그룹화 — POI 중복 제거 + 일정(세그먼트) 묶음
- **위치**: `TripStructurer` (1184~), `_group_by_place`(1243) 및 신규 세그먼트 로직.

**2-a. POI 중복 제거 (같은 자리)**
- 그룹 키: `poi_id`(있으면) 또는 `정규화 상호명 + 반올림좌표(약 50m)`.
- 같은 POI/같은 자리 사진을 **한 장소(place)** 로 병합 → `둥부르/두번/도시락` 분할 제거.

**2-b. 일정(세그먼트) 묶음 (지역+시간)**
- **세그먼트 경계 규칙**: 시간순 정렬 후, 연속 장소 사이에서 **city/region이 바뀌거나 날짜(EXIF date)가 바뀌면** 새 세그먼트 시작. 그 외에는 같은 세그먼트.
- 같은 도시·같은 날이면 **거리가 멀어도 한 일정** (예: 교토의 은각사·금각사·후시미 이나리 = "교토 일정"). 도시 변경(오사카→교토) 또는 날짜 변경 시에만 새 일정.
- city/region은 geocoding 필드 사용. **한글 정규화**(`_koreanize_region`)된 값으로 비교/표시.
- city/region 결측(GPS 없음)이면 → 날짜만으로 세그먼트(또는 단일 세그먼트) 폴백.
- 산출물: `segments = [{region, date, label(예 "교토 일정"), places:[...]}]` — 시간순.

### ③ 경로 — 세그먼트 사이만 표시
- **위치**: `TravelBlogGenerator._fetch_route_data` / `_insert_route_guides` (1928~, 2071~)
- **규칙**:
  - **세그먼트 내부(같은 일정)**: 장소 간 이동 경로 카드 **생략**. 장소를 시간순 섹션으로만 나열(같은 동선으로 취급).
  - **세그먼트 경계(지역/날짜 이동)**: 이전 세그먼트 → 다음 세그먼트로의 **이동만** 경로/안내 표시(예: "오사카 → 교토 이동").
- **API 독립**: 세그먼트 판정·경로 위치 결정은 좌표/시간/지역만 사용 → Directions API 없이도 헛경로 제거 즉시 동작. (세그먼트 간 경로 *지도 이미지*는 Directions/Static Maps 활성 시에만 추가 렌더)
- 기존 "연속 장소마다 경로 삽입" 로직을 위 세그먼트 기반으로 대체(평면 300m 거리게이트 폐기 — 그건 교토 사찰을 잘못 분리함).

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
TripStructurer
  ├ 2-a POI 중복 제거 (poi_id/상호명+50m → 한 장소)
  └ 2-b 세그먼트 묶음 (city/region·date 경계 → [{region,date,label,places}])
  ↓
generate_drafts
  ├ _build_prompt  (장소목록 주입 + 가짜이름 금지 + poi_resolved 표시)
  ├ _insert_route_guides  (세그먼트 내부=경로 생략 / 세그먼트 경계=이동만 표시)
  └ _call_ai → content
```

예시(오사카·교토 2박):
```
세그먼트1 [오사카, 2/11]: 도톤보리, 신사이바시        ← 내부 경로 없음
   ⇒ 오사카 → 교토 이동                              ← 세그먼트 경계 경로
세그먼트2 [교토, 2/12]: 은각사, 금각사, 후시미 이나리   ← 8~10km씩 떨어져도 내부 경로 없음(한 일정)
```

---

## 6. 에러 처리 & 검증 (Error Handling & Testing)

### 에러 처리
- Places API 모든 실패(403/REQUEST_DENIED/타임아웃/빈결과)는 **조용히 fallback** + 1회 warning 로그. 글 생성은 절대 중단되지 않음.
- 캐시로 차단 상태에서 반복 호출/지연 최소화.

### 테스트
- **유닛**
  - PlaceResolver: 정상 응답(mock)→상호명 추출 / 403·빈결과→`None` fallback / 캐시 적중.
  - POI 중복 제거: 같은 poi_id(또는 50m 내) 3장→1장소.
  - 세그먼트 묶음:
    - 오사카 2장 + 교토 3장(같은 날 다른 날) → city 변경 시 세그먼트 분리.
    - **교토 은각사/금각사/후시미(8~10km 이격, 같은 날) → 1세그먼트**(거리로 안 쪼개짐).
    - 같은 도시 다른 날 → 날짜로 세그먼트 분리.
    - city 결측 → 날짜 폴백.
  - 경로: 세그먼트 내부 경로 0건, 세그먼트 경계만 경로 1건.
- **E2E**(기타큐슈 사진 재생성)
  - 생성된 모든 `data-place` 장소명 ⊆ 해석된 장소 집합 (지어낸 이름 0건).
  - 같은자리(같은 세그먼트) 사진 사이 경로 블록 0건.
  - (Places 활성 시) 동네명 대신 실제 상호명 등장.

---

## 7. 의존성 & 사용자 액션 (Dependencies)

- ✅ **완료(2026-06-18)**: Places API (New) 활성화 + API 키 제한에 추가 → 실측 통과. 코드는 기존 `.env`의 `GOOGLE_MAPS_API_KEY`를 `X-Goog-Api-Key`로 사용.
- 비용 통제: GPS 반올림 캐시로 "장소 수"만큼만 호출. 콘솔 Budgets/Quota 권장.
- (보안) 키가 채팅에 노출됨 → 작업 후 키 재발급 권장.
- 폴백은 그대로 유지: 향후 차단/오류/결과없음 시 동네명 폴백 + `poi_resolved=False`.

## 8. 범위 밖 (Out of Scope)
- 본문 사진 설명/장소 소개 묘사 품질 개선
- 글 전체 구조·섹션 순서·디자인 재설계
- Directions API 기반 경로 *지도 이미지* 품질(활성화는 사용자 몫)
