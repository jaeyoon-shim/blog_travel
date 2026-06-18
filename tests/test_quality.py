# -*- coding: utf-8 -*-
"""글 퀄리티 업그레이드 — 순수 로직 유닛테스트"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import Config, PhotoAnalyzer, TripStructurer, TravelBlogGenerator


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


# ── Task 4: 해석 캐시 + 랭킹 (Places HTTP는 monkeypatch) ──
def test_resolve_uses_cache_and_ranking(monkeypatch):
    pa = _pa()
    monkeypatch.setattr(pa, "_places_nearby", lambda la, lo, radius=150: [
        {"name": "샌드위치 팩토리 OCM", "primaryType": "sandwich_shop", "lat": 33.8837, "lon": 130.8799}])
    r1 = pa._resolve_poi_name(33.883734, 130.879971, "맛집")
    assert r1["name"] == "샌드위치 팩토리 OCM"

    def _boom(*a, **k):
        raise AssertionError("캐시 미적중 — _places_nearby 재호출됨")
    monkeypatch.setattr(pa, "_places_nearby", _boom)
    assert pa._resolve_poi_name(33.883734, 130.879971, "맛집")["name"] == "샌드위치 팩토리 OCM"


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
