# 본문 묘사 품질 + 이름 정확화 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans 또는 subagent-driven-development. Steps use `- [ ]`.

**Goal:** Vision 간판 환각을 차단(Places 우선+교차검증)하고, 본문 묘사를 사실 근거+오감 디테일로 끌어올린다(날조·상투어 반복 제거).

**Architecture:** `core.py` `PhotoAnalyzer`(이름 해석)·`TravelBlogGenerator._build_prompt`(묘사 규칙) 보강. 순수 로직(이름매칭/교차검증)은 pytest, 묘사는 E2E.

**Tech Stack:** Python 3.10, OpenAI, Google Places API(New), pytest.

---

### Task 1: `_name_match` 헬퍼 (PhotoAnalyzer)

**Files:** Modify `core.py`; Test `tests/test_quality.py`

- [ ] **Step 1 (failing test)**:
```python
def test_name_match():
    pa = _pa()
    assert pa._name_match("Giraffe", "Giraffe Monochrome") is True
    assert pa._name_match("기린 모노크롬", "기린모노크롬") is True
    assert pa._name_match("뚜레쥬르", "Giraffe Monochrome") is False
    assert pa._name_match("뚜레쥬르", "스케상우동 우오마치점") is False
    assert pa._name_match("", "x") is False
```
- [ ] **Step 2**: 실행 → FAIL
- [ ] **Step 3 (impl)** — PhotoAnalyzer에 추가:
```python
def _name_match(self, a, b):
    """장소명 퍼지 일치 (공백/대소문자 무시, 부분일치 또는 글자겹침≥0.6)"""
    if not a or not b:
        return False
    na = re.sub(r'\s+', '', a).lower()
    nb = re.sub(r'\s+', '', b).lower()
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    sa, sb = set(na), set(nb)
    return len(sa & sb) / max(1, min(len(sa), len(sb))) >= 0.6
```
- [ ] **Step 4**: PASS
- [ ] **Step 5**: commit `feat(core): 장소명 퍼지 일치 헬퍼`

---

### Task 2: `_resolve_poi` 교차검증 + 후보 캐시 (`_resolve_poi_name` 대체)

**Files:** Modify `core.py`; Test `tests/test_quality.py` (기존 cache 테스트 갱신)

- [ ] **Step 1 (tests)** — 기존 `test_resolve_uses_cache_and_ranking`를 아래로 교체:
```python
def test_resolve_poi_crosscheck_and_cache(monkeypatch):
    pa = _pa()
    cands = [
        {"name": "Giraffe Monochrome", "primaryType": "restaurant", "lat": 33.8838, "lon": 130.8799},
        {"name": "스케상우동 우오마치점", "primaryType": "japanese_restaurant", "lat": 33.8837, "lon": 130.8800},
    ]
    calls = {"n": 0}
    def fake(la, lo, radius=150):
        calls["n"] += 1; return list(cands)
    monkeypatch.setattr(pa, "_places_nearby", fake)
    # visible_name 환각("뚜레쥬르") → 후보와 불일치 → 무시하고 랭킹(최근접/타입)
    r = pa._resolve_poi(33.883734, 130.879971, "맛집", visible_name="뚜레쥬르")
    assert r["name"] in ("Giraffe Monochrome", "스케상우동 우오마치점")
    # visible_name이 후보와 일치 → 그 후보 채택
    r2 = pa._resolve_poi(33.883734, 130.879971, "맛집", visible_name="스케상우동")
    assert r2["name"] == "스케상우동 우오마치점"
    # 같은 GPS → 후보 캐시 1회만 조회
    assert calls["n"] == 1
    # 후보 없음 → None
    monkeypatch.setattr(pa, "_places_nearby", lambda *a, **k: [])
    assert pa._resolve_poi(35.0, 135.0, "카페") is None
```
- [ ] **Step 2**: FAIL
- [ ] **Step 3 (impl)** — `_resolve_poi_name`을 아래로 **교체**:
```python
def _places_nearby_cached(self, lat, lon):
    ck = (round(lat, 4), round(lon, 4))
    if ck not in self._poi_cache:
        self._poi_cache[ck] = self._places_nearby(lat, lon)
    return self._poi_cache[ck]

def _resolve_poi(self, lat, lon, scene_type, visible_name=None):
    """좌표→실제 상호. Places 후보(캐시) 중 ①visible_name 교차검증 일치 후보,
    없으면 ②타입↔거리 랭킹. 후보 없으면 None."""
    cands = self._places_nearby_cached(lat, lon)
    if not cands:
        return None
    if visible_name:
        for c in cands:
            if self._name_match(visible_name, c.get("name", "")):
                logger.info(f"  🏪 POI(간판일치): {c['name']}")
                return c
    best = self._pick_best_poi(cands, scene_type, lat, lon)
    if best:
        logger.info(f"  🏪 POI: {best['name']} ({best['primaryType']})")
    return best
```
  (주의: `_poi_cache`가 이제 "후보 리스트"를 저장 — 이전엔 best 1개를 저장했음. 의미 변경 OK)
- [ ] **Step 4**: PASS (전체 `pytest -q`)
- [ ] **Step 5**: commit `feat(core): Places 우선+간판 교차검증 POI 해석(_resolve_poi)`

---

### Task 3: `analyze_photos` 우선순위 변경 — 간판 환각 차단

**Files:** Modify `core.py` (analyze_photos, GPS 분기)

- [ ] **Step 1 (impl)** — 현재 `if visible_name / elif gps_is_poi / else` 블록을 교체:
```python
                if gps_location:
                    if gps_is_poi:
                        # 구글이 시설명 확인 → 신뢰 (간판읽기 무시)
                        r["location_name"] = gps_location
                        r["poi_resolved"] = True
                    else:
                        # Places 우선 + visible_name 교차검증 (환각 간판명 차단)
                        poi = self._resolve_poi(exif["lat"], exif["lon"], scene_type, visible_name) if r.get("gps") else None
                        if poi:
                            r["location_name"] = poi["name"]
                            r["poi_id"] = poi.get("id", "")
                            r["poi_resolved"] = True
                        elif visible_name:
                            r["location_name"] = visible_name
                            r["poi_resolved"] = False
                        else:
                            r["location_name"] = self._make_place_name(gps_location, gps_local, scene_type)
                            r["poi_resolved"] = False

                    r["location_name_local"] = gps_local
                    if scene_type:
                        r["vision"]["place_type"] = scene_type
```
  (그 아래 `else:` (gps_location 없음) 분기는 그대로 둔다)
- [ ] **Step 2 (E2E 라이브 확인)**: 우오마치 3장 analyze → 3장 모두 동일 location_name(뚜레쥬르 사라짐). (Task 5에서 검증)
- [ ] **Step 3**: `pytest -q` PASS (회귀 없음)
- [ ] **Step 4**: commit `fix(core): 간판읽기보다 Places POI 우선 — 환각 상호명 차단`

---

### Task 4: `_build_prompt` — 근거 기반 묘사 + 반복/날조 차단

**Files:** Modify `core.py` (`_build_prompt`)

- [ ] **Step 1**: 사진 참고 데이터 직전(또는 places_str 근처)에 근거 강조 + 규칙 블록 추가. 반환 f-string 내 `[사진 참고 데이터]` 위에 삽입:
```python
        ground_rule = (
            "\n[묘사 원칙 — 반드시 지킬 것]\n"
            "- 사진에 실제로 보이는 것과 위 장소 정보만 묘사하세요.\n"
            "- 보이지 않는 인테리어/원산지/재료/특정 메뉴/영업정보를 지어내지 마세요.\n"
            "  (예: '모던한 인테리어','신선한 재료로 만든','일본식 커피 전문점' 같은 미확인 단정 금지)\n"
            "- 장소·사진마다 표현을 다르게 쓰세요. 상투어 반복 금지:\n"
            "  '아늑한','여유로운','편안한','신선한 재료','완벽한 장소','잊을 수 없는'.\n"
            "- 사진 설명은 그 사진의 구체적 장면을 오감으로 묘사(색·질감·맛·소리). 다른 사진과 같은 문장 금지.\n"
        )
```
  그리고 f-string의 `[사진 참고 데이터]:` 바로 위에 `{ground_rule}` 삽입.
- [ ] **Step 2**: 꿀팁 규칙(3️⃣ TRAVEL TIPS 안내, 1650 부근)에 한 줄 추가: "일반론 금지 — 장소 유형 기반 구체 팁만. 마땅치 않으면 2개로 줄여라."
- [ ] **Step 3 (test)** — 규칙 포함 확인:
```python
def test_prompt_has_grounding_rules():
    from core import Config, TravelBlogGenerator
    g = TravelBlogGenerator(Config())
    photos = [{"location_name": "Giraffe Monochrome", "file_name": "a.jpg", "gps": {"lat": 33.88, "lon": 130.87}}]
    style = {"name": "감성", "desc": "d"}
    p = g._build_prompt(photos, "요약", "코스", "기타큐슈", "", "그룹", "제목", style, "", "")
    assert "지어내지 마세요" in p and "상투어 반복 금지" in p
```
- [ ] **Step 4**: `pytest -q` PASS
- [ ] **Step 5**: commit `fix(core): 본문 묘사 근거기반+반복/날조 차단 프롬프트`

---

### Task 5: E2E 재생성 검증 (발행 없이)

**Files:** 임시 `_e2e_body.py` (실행 후 삭제)

- [ ] **Step 1**: 우오마치 3장 analyze→generate(감성). 검증:
  - location_name 3장 **동일**(뚜레쥬르/도우토르 분리 없음) → 1 PLACE
  - 본문에 상투어("아늑한") 3회 이상 반복 안 됨(완화 기준: 동일 상투어 ≤2)
  - 날조 표현("모던한 인테리어","신선한 재료로 만든") 미검출
  - data-place ⊆ location_name 집합 (환각 0)
- [ ] **Step 2**: 출력 검토 → PASS 후 임시파일 삭제
- [ ] **Step 3**: 변경 없으면 commit 생략

---

## Self-Review
- 스펙 §3① → Task1+2+3, §3② → Task4, §3③(디자인) → 변경 없음(설계대로). §5 테스트 → Task1/2 유닛 + Task5 E2E.
- 타입/시그니처: `_name_match`(T1)→`_resolve_poi`(T2)→analyze 호출(T3) 일관. 기존 `_resolve_poi_name` 제거에 따라 기존 테스트(T2 Step1) 교체 포함.
- 플레이스홀더 없음.
