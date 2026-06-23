# -*- coding: utf-8 -*-
"""글 퀄리티 업그레이드 — 순수 로직 유닛테스트"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import Config, PhotoAnalyzer, TripStructurer, TravelBlogGenerator
from posters import NaverSeleniumPoster


def _pa():
    return PhotoAnalyzer(Config())


# ── Task 2: Vision→Places 타입 매핑 ──
def test_vision_type_map():
    pa = _pa()
    assert "cafe" in pa._vision_to_places_types("카페")
    assert "restaurant" in pa._vision_to_places_types("맛집")
    assert pa._vision_to_places_types("듣보유형") == []
    assert pa._vision_to_places_types("") == []


# ── Task 3: POI 랭킹 ──
def test_pick_best_poi_type_then_distance():
    pa = _pa()
    cands = [
        {"name": "먼 카페", "primaryType": "cafe", "lat": 33.8900, "lon": 130.8800},
        {"name": "가까운 약국", "primaryType": "pharmacy", "lat": 33.8838, "lon": 130.8800},
        {"name": "가까운 샌드위치", "primaryType": "sandwich_shop", "lat": 33.88374, "lon": 130.87998},
    ]
    best = pa._pick_best_poi(cands, "맛집", 33.883734, 130.879971)
    assert best["name"] == "가까운 샌드위치"   # 타입일치 우선
    assert pa._pick_best_poi([], "카페", 0, 0) is None


# ── 장소명 퍼지 일치 ──
def test_name_match():
    pa = _pa()
    assert pa._name_match("Giraffe", "Giraffe Monochrome") is True
    assert pa._name_match("기린 모노크롬", "기린모노크롬") is True
    assert pa._name_match("뚜레쥬르", "Giraffe Monochrome") is False
    assert pa._name_match("뚜레쥬르", "스케상우동 우오마치점") is False
    assert pa._name_match("", "x") is False


# ── 신뢰 기반: 간판 교차검증만 신뢰, 추측은 None ──
def test_resolve_poi_crosscheck_only(monkeypatch):
    pa = _pa()
    cands = [
        {"name": "Giraffe Monochrome", "primaryType": "restaurant", "lat": 33.8838, "lon": 130.8799},
        {"name": "스케상우동 우오마치점", "primaryType": "japanese_restaurant", "lat": 33.8837, "lon": 130.8800},
    ]
    calls = {"n": 0}
    def fake(la, lo, radius=150):
        calls["n"] += 1
        return list(cands)
    monkeypatch.setattr(pa, "_places_nearby", fake)
    # 간판 없음 → 추측 안 함 → None (네트워크 조회도 안 함)
    assert pa._resolve_poi(33.883734, 130.879971, "맛집") is None
    assert calls["n"] == 0
    # 환각 간판 불일치 → None
    assert pa._resolve_poi(33.883734, 130.879971, "맛집", visible_name="뚜레쥬르") is None
    # 간판 일치 → 그 후보
    r = pa._resolve_poi(33.883734, 130.879971, "맛집", visible_name="스케상우동")
    assert r["name"] == "스케상우동 우오마치점"
    # 같은 GPS → 후보 캐시 1회만
    assert calls["n"] == 1


# ── 결정적 스크럽 ──
def test_scrub_content():
    g = TravelBlogGenerator.__new__(TravelBlogGenerator)
    out = g._scrub_content("신선한 재료로 만든 샌드위치와 모던한 인테리어가 좋아요.")
    assert "신선한 재료로 만든" not in out and "모던한 인테리어" not in out
    assert "샌드위치" in out
    out2 = g._scrub_content("아늑한 곳 아늑한 자리 아늑한 분위기 아늑한 시간")
    assert out2.count("아늑한") == 2


def test_scrub_title():
    g = TravelBlogGenerator.__new__(TravelBlogGenerator)
    assert g._scrub_title("기타큐슈의 아늑한 카페, Giraffe Monochrome", ["우오마치 카페"]) == "기타큐슈의 아늑한 카페"
    t = g._scrub_title("우오마치 카페 탐방기", ["우오마치 카페"])
    assert "우오마치 카페" not in t and t.strip() != ""
    assert g._scrub_title("기타큐슈 카페 여행", []) == "기타큐슈 카페 여행"


# ── 위키 박스: TRAVEL WIKI 라벨 제거 ──
def test_region_desc_no_wiki_label(monkeypatch):
    import types, json as _json
    g = TravelBlogGenerator(Config())
    fake = types.SimpleNamespace(choices=[types.SimpleNamespace(
        message=types.SimpleNamespace(content=_json.dumps(
            {"intro": "기타큐슈 소개", "specialties": ["a"], "foods": ["b"], "spots": ["c"]})))])
    monkeypatch.setattr(g.client.chat.completions, "create", lambda **k: fake)
    box = g._generate_region_desc("기타큐슈")
    assert "TRAVEL WIKI" not in box and "기타큐슈" in box


# ── Task 5: 일정(세그먼트) 분할 ──
def test_segment_index_kyoto_temples_one_segment():
    meta = [("오사카", "2024-02-11"), ("오사카", "2024-02-11"),
            ("교토", "2024-02-12"), ("교토", "2024-02-12"), ("교토", "2024-02-12")]
    assert TripStructurer.segment_index(meta) == [0, 0, 1, 1, 1]


def test_segment_index_same_city_other_day_splits():
    assert TripStructurer.segment_index([("교토", "2024-02-12"), ("교토", "2024-02-13")]) == [0, 1]


def test_segment_index_missing_region_joins():
    assert TripStructurer.segment_index([("", "d"), ("", "d")]) == [0, 0]


# ── Task 6: 같은 세그먼트 경로 생략 판정 ──
def test_same_segment_suppresses_route():
    g = TravelBlogGenerator.__new__(TravelBlogGenerator)  # API 없이 메서드만
    a = [{"city": "교토", "day_date": "2024-02-12"}]
    b = [{"city": "교토", "day_date": "2024-02-12"}]
    c = [{"city": "오사카", "day_date": "2024-02-11"}]
    assert g._same_segment(a, b) is True
    assert g._same_segment(a, c) is False
    assert g._same_segment([{}], [{}]) is False  # 정보 부족 → 경로 표시


# ── Task 7: 가짜이름 차단 규칙 프롬프트 포함 ──
def test_prompt_has_no_invent_rule():
    g = TravelBlogGenerator(Config())
    photos = [{"location_name": "샌드위치 팩토리 OCM", "file_name": "a.jpg",
               "gps": {"lat": 33.88, "lon": 130.87}}]
    style = {"name": "감성", "desc": "감성적"}
    p = g._build_prompt(photos, "요약", "코스", "기타큐슈", "", "그룹", "제목", style, "", "")
    assert "지어내지" in p and "정확히 일치" in p


def test_prompt_has_grounding_rules():
    g = TravelBlogGenerator(Config())
    photos = [{"location_name": "Giraffe Monochrome", "file_name": "a.jpg",
               "gps": {"lat": 33.88, "lon": 130.87}}]
    style = {"name": "감성", "desc": "감성적"}
    p = g._build_prompt(photos, "요약", "코스", "기타큐슈", "", "그룹", "제목", style, "", "")
    assert "단정하지 마세요" in p and "반복하지 마세요" in p and "오감으로" in p


# ── 무료 모드: Nominatim 주소 → 행정구역(city/region/country) ──
def test_pick_admin():
    # city/province 직접 매칭
    assert PhotoAnalyzer._pick_admin(
        {"city": "기타큐슈시", "province": "후쿠오카현", "country": "일본"}
    ) == ("기타큐슈시", "후쿠오카현", "일본")
    # city 없으면 town → county 순 폴백, region은 state 폴백
    assert PhotoAnalyzer._pick_admin({"town": "유후인", "state": "오이타현"}) == ("유후인", "오이타현", "")
    assert PhotoAnalyzer._pick_admin({"county": "군지역"})[0] == "군지역"
    # 빈 주소 → 모두 빈 문자열 (지역 미감지 → 위키 박스 생략 가드와 연결)
    assert PhotoAnalyzer._pick_admin({}) == ("", "", "")


# ── 구분선(─) 연속 중복 정규화 ──
def test_dedupe_separators():
    sep = '<p style="text-align:center;color:#d4d4d4;letter-spacing:8px">─ ─ ─ ─ ─ ─ ─</p>'
    full = "─ ─ ─ ─ ─ ─ ─"
    # 인접 2개 → 1개
    assert TravelBlogGenerator._dedupe_separators(sep + "\n" + sep).count(full) == 1
    # 인접 3개(<br>·공백 섞임) → 1개
    assert TravelBlogGenerator._dedupe_separators(sep + "<br/>" + sep + "  " + sep).count(full) == 1
    # 본문이 사이에 끼면(비인접) 둘 다 보존
    assert TravelBlogGenerator._dedupe_separators(sep + "<p>본문</p>" + sep).count(full) == 2
    # 단일 구분선 → 그대로
    assert TravelBlogGenerator._dedupe_separators(sep).count(full) == 1


# ── 발행 공개설정: 한글 인식 + 안전 기본값(알 수 없으면 비공개) ──
def test_visibility_target_safe_default():
    f = NaverSeleniumPoster._visibility_target
    assert f("private") == "비공개"
    assert f("비공개") == "비공개"          # 앱 기본값이 한글 → 공개로 떨어지던 버그
    assert f("public") == "전체공개"
    assert f("전체공개") == "전체공개"
    assert f("neighbor") == "서로이웃공개"
    # 알 수 없는/빈 값 → 안전하게 비공개 (실수로 전체공개 발행되는 사고 방지)
    assert f("") == "비공개"
    assert f("garbage") == "비공개"
    assert f(None) == "비공개"
