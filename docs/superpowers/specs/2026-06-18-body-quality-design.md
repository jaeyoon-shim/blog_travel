# 본문 묘사 품질 + 이름 정확화 설계

작성일: 2026-06-18
대상: `D:\project\blog_writer2` (TravelBlog Pro)
관련: [SPEC.md](../../../SPEC.md), 이전 이터 `2026-06-18-post-quality-upgrade-design.md`

---

## 1. 문제 정의 (확인 완료)

실제 생성물(`기타큐슈 여행기: 아늑한 맛집 탐방`) 본문 점검 결과:

- **묘사 천편일률·뜬구름**: 세 장소 설명이 전부 "아늑한 분위기/여유로운 시간/편안한 공간/신선한 재료". 구체성·오감 디테일 없음.
- **사실 환각**: "모던한 인테리어", "신선한 재료로 만든 샌드위치", "일본식 커피 전문점" 등 알 수 없는 사실 날조.
- **사진 설명 동어반복**: 사진 내용을 그대로 받아쓰기.
- **꿀팁 일반론**: 장소 무관한 보편 팁.
- **간판 환각 → 같은 자리 분리**: 같은 GPS(33.8837) 식탁 사진 3장이 Giraffe Monochrome / **뚜레쥬르** / 도우토르로 분리.
  - **근본 원인**: `analyze_photos`에서 Vision `visible_name`(간판읽기)이 **무조건 최우선**이라, 환각 간판명(뚜레쥬르=한국 베이커리 체인)이 정확한 Places POI를 덮어씀.
- **디자인 레이아웃은 양호** → 변경 안 함.

## 2. 결정 사항

- 묘사 성격: **사실 근거 + 오감 디테일** (안 보이는 사실 생성 금지).
- 이름 충돌: **Places 우선 + 교차검증** (visible_name은 Places 후보와 일치할 때만 채택).
- 디자인 레이아웃: **유지**.

## 3. 컴포넌트 설계

### ① 이름 해석 강화 — 간판 환각 차단 (`PhotoAnalyzer`)

**우선순위 변경** (`analyze_photos`, GPS 있을 때):
```
gps_is_poi(구글 시설명) → 그대로 사용 (신뢰), visible_name 무시
else → _resolve_poi(lat,lon,scene_type,visible_name):
        · _places_nearby 후보 1회 조회(GPS 반올림 캐시)
        · visible_name이 후보 이름과 퍼지일치 → 그 후보 채택(교차검증)
        · 아니면 _pick_best_poi(타입↔거리 랭킹)
        · 후보 없음 → None
   None이면 → visible_name(있으면, poi_resolved=False) → _make_place_name 폴백
```
- 기존 `visible_name` 최우선 분기 **제거**. 환각 간판명이 Places를 못 덮어씀.
- **신규** `_resolve_poi(lat,lon,scene_type,visible_name=None)`: 후보 캐시 + 교차검증 + 랭킹 통합. 기존 `_resolve_poi_name`은 **삭제**하고 `analyze_photos`가 `_resolve_poi`를 직접 호출(이전 이터의 호출부 1곳 교체). 후보 캐시는 `_places_nearby` 결과를 GPS 반올림 키로 보관해 visible_name 교차검증과 랭킹이 같은 후보셋을 공유.
- **신규** `_name_match(a,b)`: 공백/대소문자 정규화 후 부분일치 또는 글자겹침≥0.6.
- 같은 GPS(반올림 동일) → 같은 캐시 → **동일 이름** → 같은 자리 1장소 보장.

### ② 묘사 품질 — 근거 기반 + 반복 제거 (`_build_prompt`)

**근거 데이터 주입**: 방문 장소 목록/사진 참고 데이터에 사진별
- Vision `scene_description`(실제 관찰), `food_name`, Places `primaryType`(있으면)
를 명시적으로 포함.

**프롬프트 규칙 추가**:
- (사실) "사진에 실제 보이는 것 + 제공된 장소 정보만 묘사. 보이지 않는 인테리어/재료/원산지/특정 메뉴를 지어내지 말 것."
- (반복) "장소마다 표현을 다르게. '아늑한·여유로운·편안한·신선한 재료·완벽한 장소' 같은 상투어 반복 금지."
- (사진설명) "각 사진 설명은 그 사진의 구체적 내용(scene_description)을 반영. 다른 사진과 같은 문장 금지."
- (꿀팁) "일반론 대신 장소 유형 기반 구체 팁. 모르면 개수를 줄여라(최소 2개)."

### ③ 디자인 — 유지
레이아웃/색/구분선/위키박스 등 변경 없음.

## 4. 데이터 흐름

```
analyze_photos
  └ GPS & not is_poi → _resolve_poi(lat,lon,scene,visible_name)
        ├ visible_name ↔ 후보 퍼지일치 → 그 후보
        ├ 아니면 _pick_best_poi
        └ 후보없음 → None → (visible_name|_make_place_name)
  ↓ location_name(같은 GPS=동일), poi_resolved
generate_drafts → _build_prompt(근거주입 + 사실/반복/사진/꿀팁 규칙) → _call_ai
```

## 5. 에러 처리 & 테스트

### 에러 처리
- Places 실패/빈결과 → visible_name(있으면) 또는 동네명 폴백. 생성 중단 없음.
- 교차검증은 후보가 있을 때만; 없으면 랭킹/폴백.

### 테스트
- **유닛**
  - `_name_match`: "뚜레쥬르" vs ["Giraffe Monochrome","스케상우동"] → 불일치(False). "Giraffe" vs "Giraffe Monochrome" → True.
  - `_resolve_poi`: visible_name 일치 후보 채택 / 불일치 시 무시하고 랭킹 / 후보없음 None. (`_places_nearby` monkeypatch)
  - 같은 GPS 2회 호출 → 캐시 동일 결과.
- **E2E**(우오마치 3장 재생성, 발행 X)
  - 같은 GPS 3장 → **1장소**(뚜레쥬르 분리 없음).
  - 3개 장소 설명에 상투어("아늑한") 3연속 동일 반복 없음(서로 다른 표현).
  - 날조 사실("모던한 인테리어" 등) 휴리스틱 미검출.
  - 사진 캡션/설명이 scene_description 키워드 반영.

## 6. 범위 밖
- 디자인 레이아웃 재설계, 섹션 순서 변경.
- 사용자 메모(place_memos) 기반 작성(이미 지원, 별도).
