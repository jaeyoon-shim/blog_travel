# 글 퀄리티 업그레이드 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** 매장명을 Places API(New)로 실제 상호명화하고, 지역+날짜 일정(세그먼트) 기반으로 헛경로를 제거하며, AI의 가짜 상호명 생성을 차단해 글 품질을 올린다.

**Architecture:** `core.py` 단일 파일 내 `PhotoAnalyzer`(POI 해석)·`TripStructurer`(세그먼트)·`TravelBlogGenerator`(경로/프롬프트) 보강. 순수 로직(타입매핑·POI랭킹·세그먼트분할)은 pytest 유닛테스트, 통합은 E2E 재생성으로 검증.

**Tech Stack:** Python 3.10, OpenAI, Google Places API (New) `places:searchNearby`, pytest.

---

### Task 1: pytest 스캐폴드

**Files:** Create `tests/test_quality.py`; Modify `requirements.txt`

- [ ] **Step 1**: `requirements.txt`에 `pytest>=8.0` 추가
- [ ] **Step 2**: `tests/test_quality.py` 생성 (이후 태스크가 채움). 임시 sanity:
```python
def test_sanity():
    assert True
```
- [ ] **Step 3**: `venv\Scripts\python.exe -m pytest tests/test_quality.py -q` → PASS
- [ ] **Step 4**: commit `test: pytest 스캐폴드`

---

### Task 2: Vision→Places 타입 매핑 (`PhotoAnalyzer._vision_to_places_types`)

**Files:** Modify `core.py` (PhotoAnalyzer); Test `tests/test_quality.py`

- [ ] **Step 1 (failing test)**:
```python
from core import Config, PhotoAnalyzer
def _pa(): return PhotoAnalyzer(Config())
def test_vision_type_map():
    pa=_pa()
    assert "cafe" in pa._vision_to_places_types("카페")
    assert "restaurant" in pa._vision_to_places_types("맛집")
    assert pa._vision_to_places_types("듣보유형")==[]   # 미지정→빈
```
- [ ] **Step 2**: 실행 → FAIL (no attr)
- [ ] **Step 3 (impl)**: PhotoAnalyzer에 추가:
```python
def _vision_to_places_types(self, scene_type):
    s = (scene_type or "").strip()
    M = {
        "카페": ["cafe","bakery","coffee_shop"],
        "맛집": ["restaurant","sandwich_shop","ramen_restaurant","japanese_restaurant","cafe","bakery"],
        "음식": ["restaurant","cafe"], "식당": ["restaurant"],
        "관광지": ["tourist_attraction","historical_landmark","point_of_interest"],
        "신사": ["place_of_worship","shrine","tourist_attraction"],
        "사찰": ["place_of_worship","buddhist_temple","tourist_attraction"],
        "거리": ["tourist_attraction","point_of_interest"],
        "시장": ["market","supermarket","store"],
        "쇼핑": ["store","shopping_mall","department_store"],
    }
    for k, v in M.items():
        if k in s: return v
    return []
```
- [ ] **Step 4**: 실행 → PASS
- [ ] **Step 5**: commit `feat(core): Vision scene_type→Places type 매핑`

---

### Task 3: POI 랭킹 (`PhotoAnalyzer._pick_best_poi`)

**Files:** Modify `core.py`; Test `tests/test_quality.py`

- [ ] **Step 1 (failing test)**:
```python
def test_pick_best_poi_type_then_distance():
    pa=_pa()
    cands=[
        {"name":"먼 카페","primaryType":"cafe","lat":33.8900,"lon":130.8800},
        {"name":"가까운 약국","primaryType":"pharmacy","lat":33.8838,"lon":130.8800},
        {"name":"가까운 샌드위치","primaryType":"sandwich_shop","lat":33.88374,"lon":130.87998},
    ]
    best=pa._pick_best_poi(cands,"맛집",33.883734,130.879971)
    assert best["name"]=="가까운 샌드위치"   # 타입일치 우선
    assert pa._pick_best_poi([], "카페",0,0) is None
```
- [ ] **Step 2**: FAIL
- [ ] **Step 3 (impl)**:
```python
def _pick_best_poi(self, candidates, scene_type, lat, lon):
    if not candidates: return None
    keys = self._vision_to_places_types(scene_type)
    def score(c):
        pt = c.get("primaryType","") or ""
        match = any(k in pt for k in keys) if keys else False
        try: dist = TripStructurer._haversine(lat,lon,float(c["lat"]),float(c["lon"]))
        except (TypeError,ValueError,KeyError): dist = 9e9
        return (0 if match else 1, dist)
    return sorted(candidates, key=score)[0]
```
- [ ] **Step 4**: PASS
- [ ] **Step 5**: commit `feat(core): POI 후보 랭킹(타입일치→거리)`

---

### Task 4: Places 조회 + 해석 통합 (`_places_nearby`, `_resolve_poi_name`, analyze 흐름)

**Files:** Modify `core.py` (PhotoAnalyzer.__init__, analyze_photos:571-575, batch translate:596-607)

- [ ] **Step 1**: `PhotoAnalyzer.__init__`에 캐시 추가: `self._poi_cache = {}`
- [ ] **Step 2 (thin HTTP)**: 추가
```python
def _places_nearby(self, lat, lon, radius=150):
    if not self.google_api_key: return []
    body = json.dumps({"maxResultCount":10,
        "locationRestriction":{"circle":{"center":{"latitude":lat,"longitude":lon},"radius":float(radius)}},
        "languageCode":"ko"}).encode()
    req = urllib.request.Request("https://places.googleapis.com/v1/places:searchNearby",
        data=body, method="POST",
        headers={"Content-Type":"application/json","X-Goog-Api-Key":self.google_api_key,
                 "X-Goog-FieldMask":"places.displayName,places.primaryType,places.location,places.id"})
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            d = json.loads(resp.read().decode())
        out=[]
        for p in d.get("places",[]):
            loc=p.get("location",{}) or {}
            out.append({"name":(p.get("displayName") or {}).get("text",""),
                        "primaryType":p.get("primaryType",""),"id":p.get("id",""),
                        "lat":loc.get("latitude"),"lon":loc.get("longitude")})
        return [o for o in out if o["name"]]
    except Exception as e:
        logger.warning(f"  ⚠️ Places 조회 실패: {e}"); return []

def _resolve_poi_name(self, lat, lon, scene_type):
    ck=(round(lat,4),round(lon,4))
    if ck in self._poi_cache: return self._poi_cache[ck]
    best=self._pick_best_poi(self._places_nearby(lat,lon), scene_type, lat, lon)
    self._poi_cache[ck]=best
    if best: logger.info(f"  🏪 POI: {best['name']} ({best['primaryType']})")
    return best
```
- [ ] **Step 3 (wire analyze_photos 571-575 else 분기)**: 교체
```python
                    else:
                        # 주소만 → Places로 실제 상호 조회, 실패 시 동네명 폴백
                        poi = self._resolve_poi_name(exif["lat"], exif["lon"], scene_type) if r.get("gps") else None
                        if poi:
                            r["location_name"]=poi["name"]; r["poi_id"]=poi.get("id",""); r["poi_resolved"]=True
                        else:
                            r["location_name"]=self._make_place_name(gps_location, gps_local, scene_type)
                            r["poi_resolved"]=False
```
  그리고 visible_name·gps_is_poi 분기 끝에 `r["poi_resolved"]=True` 표기(간판/구글POI도 정확). 미해석 기본값은 False.
- [ ] **Step 4 (번역 스킵)**: 596-599 foreign_items 루프에 `if r.get("poi_resolved"): continue` 추가 → "샌드위치 팩토리 OCM"의 OCM이 번역으로 깨지지 않게.
- [ ] **Step 5 (라이브 검증)**: `_probe`로 우오마치 좌표 resolve → 실제 상호명 반환 확인(이미 API 검증됨). 단위테스트는 `_places_nearby`를 monkeypatch:
```python
def test_resolve_uses_cache_and_ranking(monkeypatch):
    pa=_pa()
    monkeypatch.setattr(pa,"_places_nearby",lambda la,lo,radius=150:[
        {"name":"샌드위치 팩토리 OCM","primaryType":"sandwich_shop","lat":33.8837,"lon":130.8799}])
    r1=pa._resolve_poi_name(33.883734,130.879971,"맛집")
    assert r1["name"]=="샌드위치 팩토리 OCM"
    # 캐시: _places_nearby 다시 안 부름
    monkeypatch.setattr(pa,"_places_nearby",lambda *a,**k:(_ for _ in ()).throw(AssertionError("호출됨")))
    assert pa._resolve_poi_name(33.883734,130.879971,"맛집")["name"]=="샌드위치 팩토리 OCM"
```
- [ ] **Step 6**: `pytest -q` PASS
- [ ] **Step 7**: commit `feat(core): Places API(New)로 실제 상호명 해석 + 캐시/폴백`

---

### Task 5: 일정(세그먼트) 분할 (`TripStructurer.segment_index`)

**Files:** Modify `core.py` (TripStructurer); Test `tests/test_quality.py`

- [ ] **Step 1 (failing test)** — 교토 3사찰=1세그먼트, 오사카→교토=새 세그먼트:
```python
from core import TripStructurer as TS
def test_segment_index():
    meta=[("오사카","2024-02-11"),("오사카","2024-02-11"),
          ("교토","2024-02-12"),("교토","2024-02-12"),("교토","2024-02-12")]
    assert TS.segment_index(meta)==[0,0,1,1,1]   # 교토 3곳(멀어도) 한 세그먼트
    # 같은 도시 다른 날 → 분리
    assert TS.segment_index([("교토","2024-02-12"),("교토","2024-02-13")])==[0,1]
    # 지역 결측 → 이어붙임
    assert TS.segment_index([("","d"),("","d")])==[0,0]
```
- [ ] **Step 2**: FAIL
- [ ] **Step 3 (impl)** — TripStructurer에 staticmethod 추가:
```python
@staticmethod
def segment_index(places_meta):
    """[(region,date)] 순서 → 세그먼트 id 리스트. region/date 변경 시 새 세그먼트."""
    ids=[]; cur=0
    for i,(reg,day) in enumerate(places_meta):
        if i==0: ids.append(0); continue
        preg,pday=places_meta[i-1]
        if (reg and preg and reg!=preg) or (day and pday and day!=pday):
            cur+=1
        ids.append(cur)
    return ids
```
- [ ] **Step 4**: PASS
- [ ] **Step 5**: commit `feat(core): 지역+날짜 일정(세그먼트) 분할`

---

### Task 6: 경로 — 세그먼트 내부 생략 (`_insert_route_guides`, `_fetch_route_data`)

**Files:** Modify `core.py` (TravelBlogGenerator)

- [ ] **Step 1 (helper + test)** — 장소별 (region,date) 추출 + 같은세그먼트 판정:
```python
def test_same_segment_suppresses_route():
    from core import TravelBlogGenerator as G
    g=G.__new__(G)   # API 없이 메서드만
    a=[{"city":"교토","day_date":"2024-02-12"}]
    b=[{"city":"교토","day_date":"2024-02-12"}]
    c=[{"city":"오사카","day_date":"2024-02-11"}]
    assert g._same_segment(a,b) is True    # 같은 교토·같은 날 → 경로 생략
    assert g._same_segment(a,c) is False   # 도시 다름 → 경로 표시
```
- [ ] **Step 2**: FAIL
- [ ] **Step 3 (impl)** — TravelBlogGenerator에 추가:
```python
def _place_seg(self, photos):
    for p in photos or []:
        reg = p.get("city") or p.get("region") or ""
        day = p.get("day_date") or (p.get("exif_date","") or "")[:10]
        if reg or day:
            return (self._koreanize_region(reg) if reg else "", day)
    return ("","")

def _same_segment(self, from_photos, to_photos):
    fr=self._place_seg(from_photos); to=self._place_seg(to_photos)
    if fr==("","") or to==("",""): return False
    return fr==to
```
- [ ] **Step 4**: `_insert_route_guides` 루프 안(2129~), route 생성 직전에:
```python
            if self._same_segment(from_photos, to_photos):
                continue   # 같은 일정 내부 이동 → 경로 카드 생략
```
  (역순 루프 `for i in range(len(places)-1,0,-1):` 바로 다음 줄, from/to_photos 정의 이후)
- [ ] **Step 5**: `_fetch_route_data`(1928~)에서도 연속쌍 같은세그먼트면 `continue`로 Directions 호출 스킵(노이즈/비용 감소).
- [ ] **Step 6**: `pytest -q` PASS
- [ ] **Step 7**: commit `fix(core): 같은 일정(세그먼트) 내부 경로 생략`

---

### Task 7: AI 가짜 상호명 차단 (`_build_prompt`)

**Files:** Modify `core.py` (`_build_prompt` 장소목록·필수규칙)

- [ ] **Step 1**: 방문 장소 목록 블록(1577~ `places_str`) 아래에 규칙 문구 추가:
```python
        place_rule = (
            "\n★★★ 장소명 규칙(필수) ★★★\n"
            "- 위 [방문 장소 목록]에 있는 이름만 사용하세요.\n"
            "- 목록에 없는 새 가게/상호명을 절대 지어내지 마세요.\n"
            "- <h2 data-place=\"...\">의 장소명은 목록의 이름과 정확히 일치해야 합니다.\n"
        )
```
  그리고 반환 f-string의 장소목록 직후에 `{place_rule}` 삽입.
- [ ] **Step 2**: 필수규칙 1번(장소명 규칙, 1674~) 보강: "목록에 없는 상호명 금지" 한 줄 추가.
- [ ] **Step 3 (검증)**: 단위테스트로 `_build_prompt` 출력에 규칙 문구 포함 확인:
```python
def test_prompt_has_no_invent_rule():
    from core import Config, TravelBlogGenerator
    g=TravelBlogGenerator(Config())
    photos=[{"location_name":"샌드위치 팩토리 OCM","file_name":"a.jpg","gps":{"lat":33.88,"lon":130.87}}]
    style={"name":"감성","desc":"d"}
    p=g._build_prompt(photos,"요약","코스","기타큐슈","",("기타큐슈",""),style,"","")
    assert "지어내지" in p and "정확히 일치" in p
```
  (인자 시그니처는 실제 `_build_prompt`에 맞춰 조정 — region_desc 위치 포함)
- [ ] **Step 4**: `pytest -q` PASS
- [ ] **Step 5**: commit `fix(core): AI가 장소명 지어내기 금지(제공 목록만 사용)`

---

### Task 8: E2E 재생성 검증 (발행 없이)

**Files:** 임시 `_e2e_quality.py` (실행 후 삭제)

- [ ] **Step 1**: 우오마치 사진 3장 분석→generate_drafts(감성, 발행X). 검증:
  - 모든 `data-place` ⊆ 해석된 location_name 집합 (지어낸 이름 0)
  - location_name이 실제 상호(예 "…OCM"/"…우동") — 동네명 아님
  - 같은 세그먼트(같은날·같은도시) 사진 사이 경로 카드 0
- [ ] **Step 2**: 결과 출력/검토 → PASS 확인 후 임시파일 삭제
- [ ] **Step 3**: commit (코드 변경 없으면 생략)

---

## Self-Review 메모
- 스펙 §4①②③④ 각각 Task4/Task5+Task6/Task6/Task7 대응. POI 중복제거는 location_name 공유로 자연 달성(Task4) + 세그먼트(Task5).
- 타입/시그니처 일관: `_vision_to_places_types`(T2)→`_pick_best_poi`(T3)→`_resolve_poi_name`(T4); `segment_index`(T5)와 `_same_segment/_place_seg`(T6)는 동일 (region,date) 개념.
- 플레이스홀더 없음. 모든 코드 단계에 실제 코드 포함.
