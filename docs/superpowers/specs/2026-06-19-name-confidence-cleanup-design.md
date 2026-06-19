# 신뢰 기반 매장명 + 제목/위키 정리 + 스크럽 설계

작성일: 2026-06-19
대상: `D:\project\blog_writer2`
관련: 이전 `2026-06-18-body-quality-design.md`

## 1. 문제 (데이터로 확인)
- 실제 가게는 **도토루(Doutor)** 인데 "Giraffe Monochrome"으로 발행됨.
- **근본 원인**: 사진 GPS(33.8837,130.8800) 반경 60/150m Places 후보에 **도토루가 없음**. GPS가 도토루 위치에 안 찍힘(드리프트). 자동 랭킹은 최근접 Giraffe(16m)나 타입매칭 Betsubara(24m,cafe)를 고를 뿐 — **어떤 자동 방식도 도토루를 못 맞춤**.
- 제목·상단에 불필요 텍스트: 제목에 추정 영문상호("Monochrome"), 상단 "TRAVEL WIKI" 영문 라벨.
- (이월) 날조 어구·상투어 반복, 위키 박스 타지역 명소 환각(아소산=구마모토).

## 2. 결정
- **불확실하면 중립표기 + 사용자 확정**. 신뢰 기준 엄격: `gps_is_poi` 또는 간판 교차검증만 신뢰. 나머지는 중립 "{동네} {유형}" + 사용자가 실명 입력.
- 제목에 비신뢰 상호명(특히 영문) 금지. "TRAVEL WIKI" 라벨 제거.
- 결정적 스크럽(날조/상투어) + 위키 보수화.

## 3. 컴포넌트

### ① 신뢰 기반 매장명 (`PhotoAnalyzer`)
- `_resolve_poi(lat,lon,scene_type,visible_name)` **단순화**: visible_name이 Places 후보와 `_name_match`일 때 그 후보 반환(신뢰), 아니면 **None**. (타입/최근접 추측은 더 이상 이름으로 안 씀)
- `analyze_photos` GPS 분기:
  - `gps_is_poi` → gps_location, `poi_resolved=True`, `name_confident=True`
  - else `_resolve_poi` 성공 → 그 이름, `name_confident=True`
  - else → `_make_place_name`(중립 "{동네} {유형}"), `poi_resolved=False`, `name_confident=False`
- `_pick_best_poi`/`_vision_to_places_types`는 유지(테스트/향후용)하나 이름 결정 경로에선 미사용.

### ② 제목·위키 라벨 정리
- `_generate_region_desc`: `<p>TRAVEL WIKI</p>` 라벨 **제거**(헤딩만 유지).
- 제목 정리: 그룹에 `name_confident` 장소가 없으면 제목에 그 상호명 금지.
  - 프롬프트 규칙 추가 + 결정적 `_scrub_title(title, bad_names)`: 비신뢰 location_name 제거 + 남은 라틴문자 런(≥3) 제거 + 구두점/공백 정리.

### ③ 결정적 스크럽 (`_scrub_content`)
- `_call_ai`에서 content/ title 생성 직후 적용.
- 날조 수식구 제거(정규식): "신선한 재료로 만든", "엄선된 재료로", "정성껏 만든", "모던한 인테리어", "세련된 인테리어", "일본식 커피 전문점" 등 → 수식구만 삭제 후 공백 정리.
- 상투어 캡: ["아늑한","여유로운","편안한","완벽한"] 각 **2회 초과분의 형용사만 제거**(예: "아늑한 분위기"→"분위기").

### ④ 위키 사실성 (`_generate_region_desc` 프롬프트)
- "정확히 아는 것만. 불확실하면 항목을 비워라. **해당 지역에 실제로 있는 것만 — 인접 현/타지역 명소 금지**(예: 아소산은 구마모토)." 부정 예시 인용 없이 카테고리 규칙.

## 4. 테스트
- 유닛:
  - `_resolve_poi`: visible_name 일치→후보, 불일치/없음→None.
  - `_scrub_content`: 날조구 제거+문장정상, 상투어 3회→2회, 정상문 불변.
  - `_scrub_title`: 비신뢰명/라틴 제거 후 깔끔, 신뢰명은 보존.
  - `_generate_region_desc`: 출력에 "TRAVEL WIKI" 없음.
- E2E(우오마치 3장): location_name 중립("우오마치 카페" 류), 제목에 영문상호 없음, 본문 "TRAVEL WIKI" 없음, 날조0, 상투어 각≤2.

## 5. 범위 밖
- 외부 위키/Wikipedia API 연동(다음 이터). 디자인 레이아웃 재설계.

## 6. Task (구현 순서)
1. `_generate_region_desc`: TRAVEL WIKI 라벨 제거 + 위키 보수화 프롬프트.
2. `_resolve_poi` 단순화(교차검증 전용) + analyze_photos 신뢰 분기 + `name_confident`.
3. `_scrub_content`(날조/상투어) + `_call_ai` 적용.
4. `_scrub_title`(비신뢰명/라틴 제거) + `_call_ai`에서 group 비신뢰명으로 적용 + 프롬프트 제목규칙.
5. 테스트 갱신/추가 + E2E.
