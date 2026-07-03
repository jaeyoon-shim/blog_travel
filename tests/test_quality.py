# -*- coding: utf-8 -*-
"""글 퀄리티 업그레이드 — 순수 로직 유닛테스트"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import Config, PhotoAnalyzer, TripStructurer, TravelBlogGenerator, TripPlanner, ReceiptReader, StyleAnalyzer, NaverBlogAnalyzer
from posters import NaverSeleniumPoster, summarize_publish_results


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


def test_build_prompt_directives_section():
    g = TravelBlogGenerator(Config())
    photos = [{"location_name": "고쿠라 성", "file_name": "a.jpg",
               "gps": {"lat": 33.88, "lon": 130.87}}]
    style = {"name": "감성", "desc": "감성적"}
    p = g._build_prompt(photos, "요약", "코스", "기타큐슈", "", "그룹", "제목", style, "", "",
                        place_directives={"고쿠라 성": "야경 사진 위주로 강조해줘"})
    assert "장소별 필수 지시" in p and "야경 사진 위주" in p and "우선" in p
    p2 = g._build_prompt(photos, "요약", "코스", "기타큐슈", "", "그룹", "제목", style, "", "")
    assert "장소별 필수 지시" not in p2


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


# ── 계획 검수: photo_id 안정성 ──
def test_photo_id_stable():
    a = TripPlanner._photo_id("uploads/IMG_0003.jpg")
    b = TripPlanner._photo_id("uploads/IMG_0003.jpg")
    c = TripPlanner._photo_id("uploads/IMG_0004.jpg")
    assert a == b              # 같은 파일 → 같은 ID (재분석 안정)
    assert a != c
    assert a.startswith("p")


# ── 계획 검수: Day 배정 + 새벽 4시 컷오프 ──
def test_assign_day_cutoff():
    assert TripPlanner._assign_day("2026:06:22 14:30:00") == "2026-06-22"
    assert TripPlanner._assign_day("2026:06:23 01:00:00") == "2026-06-22"
    assert TripPlanner._assign_day("2026:06:23 04:00:00") == "2026-06-23"
    assert TripPlanner._assign_day("") is None
    assert TripPlanner._assign_day("날짜아님") is None


# ── 계획 검수: 초안 합성 ──
def _pr(fp, exif, name, conf, lat=None, lon=None):
    r = {"file_path": fp, "file_name": fp.split("/")[-1], "exif_date": exif,
         "location_name": name, "name_confident": conf, "region": "홋카이도",
         "vision": {"scene_type": "관광지"}}
    if lat is not None:
        r["gps"] = {"lat": lat, "lon": lon}
    return r

def test_build_draft_days_and_unconfident_name_blanked():
    photos = [
        _pr("u/a.jpg", "2026:06:22 10:00:00", "오타루 운하", True, 43.19, 140.99),
        _pr("u/b.jpg", "2026:06:22 11:00:00", "동네 카페", False, 43.19, 140.99),
        _pr("u/c.jpg", "2026:06:23 09:00:00", "삿포로 TV타워", True, 43.06, 141.35),
        _pr("u/d.jpg", "", "", False),   # 날짜 미상
    ]
    plan = TripPlanner.build_draft(photos, free_mode=True)
    assert plan["free_mode"] is True
    assert plan["region"] == "홋카이도"
    day_dates = [d["date"] for d in plan["days"]]
    assert "2026-06-22" in day_dates and "2026-06-23" in day_dates
    assert len(plan["undated_photo_ids"]) == 1
    for day in plan["days"]:
        for s in day["stops"]:
            assert s["stop_id"] and isinstance(s["photo_ids"], list)
    names = {s["name"]: s["name_source"]
             for d in plan["days"] for s in d["stops"]}
    assert "오타루 운하" in names and names["오타루 운하"] == "auto"
    # 무료모드: 확신 없어도 GPS 중립 장소명이 있으면 채워짐(auto), 사용자가 수정
    assert "동네 카페" in names and names["동네 카페"] == "auto"


def test_build_draft_merges_same_name_and_no_mutation():
    photos = [
        _pr("u/x.jpg", "2026:06:22 09:00:00", "스타벅스 삿포로", True),
        _pr("u/y.jpg", "2026:06:22 18:00:00", "스타벅스 삿포로", True),
    ]
    plan = TripPlanner.build_draft(photos)
    stops = plan["days"][0]["stops"]
    same = [s for s in stops if s["name"] == "스타벅스 삿포로"]
    assert len(same) == 1 and len(same[0]["photo_ids"]) == 2
    # 입력 dict가 변형되지 않아야 함 (_pid 누출 금지)
    assert "_pid" not in photos[0]


# ── 영수증: 금액·통화 파싱 ──
def test_parse_amount():
    assert ReceiptReader._parse_amount("合計 ¥2,000") == (2000, "JPY")
    assert ReceiptReader._parse_amount("합계 12,000원") == (12000, "KRW")
    assert ReceiptReader._parse_amount("₩12,000") == (12000, "KRW")
    assert ReceiptReader._parse_amount("Total $15.00") == (15, "USD")
    assert ReceiptReader._parse_amount("영수증") == (None, "")


# ── 영수증: 가게명↔장소명 교차검증 제안 ──
def test_receipt_crosscheck_name():
    assert ReceiptReader.crosscheck_name("小樽硝子", "오타루 운하") is False
    assert ReceiptReader.crosscheck_name("스타벅스 삿포로점", "스타벅스") is True
    assert ReceiptReader.crosscheck_name("스타벅스", "") is False
    assert ReceiptReader.crosscheck_name("", "스타벅스") is False


# ── 생성: 별점·가격 한 줄 조립(코드가 HTML 조립) ──
def _gen():
    return TravelBlogGenerator(Config())

def test_format_meta_line():
    g = _gen()
    line = g._format_meta_line(rating=4.5, amount=2000, currency="JPY",
                               show_rating=True, show_price=True)
    assert "4.5" in line and "¥2,000" in line
    assert "http" not in line   # URL 절대 없음(SE3 링크카드 방지)
    assert g._format_meta_line(4.5, 2000, "JPY", False, False) == ""
    only_rating = g._format_meta_line(4.5, 2000, "JPY", True, False)
    assert "4.5" in only_rating and "2,000" not in only_rating
    assert g._format_meta_line(None, None, "", True, True) == ""


# ── 생성 배선: 확정 plan → 생성기 그룹 ──
def test_groups_from_plan():
    photos = [
        _pr("u/a.jpg", "2026:06:22 10:00:00", "오타루 운하", True),
        _pr("u/b.jpg", "2026:06:22 11:00:00", "동네 카페", False),
    ]
    plan = TripPlanner.build_draft(photos)
    st = plan["days"][0]["stops"][0]   # 확신 장소 "오타루 운하"
    st["name"] = "오타루 운하 본점"; st["name_source"] = "user"
    st["events"] = ["산책"]; st["feeling"] = "로맨틱"; st["rating"] = 4.5
    groups = TripPlanner.groups_from_plan(plan, photos)
    assert len(groups) == 1
    g = groups[0]
    assert g["place_memos"]["오타루 운하 본점"].startswith("사건:")
    assert g["place_meta"]["오타루 운하 본점"]["rating"] == 4.5
    assert any(p["location_name"] == "오타루 운하 본점" for p in g["photos"])
    assert photos[0]["location_name"] == "오타루 운하"   # 원본 비변형(덮어쓰기는 복사본에만)


# ── 생성: 별점·가격 줄을 장소 섹션에 주입 ──
def test_insert_meta_lines():
    g = _gen()
    g._current_place_meta = {"오타루 운하": {"rating": 4.5, "amount": 2000,
        "currency": "JPY", "show_rating": True, "show_price": True}}
    out = g._insert_meta_lines("<h2>오타루 운하</h2><p>본문</p>")
    assert "⭐ 4.5" in out and "¥2,000" in out
    assert "http" not in out                       # URL 없음
    assert out.index("⭐") > out.index("</h2>")     # 헤딩 뒤에 삽입
    # 매칭되는 헤딩 없으면 원문 그대로(조용히 생략)
    g._current_place_meta = {"없는장소XYZ": {"rating": 3.0, "amount": None,
        "currency": "", "show_rating": True, "show_price": True}}
    assert g._insert_meta_lines("<h2>오타루 운하</h2>") == "<h2>오타루 운하</h2>"
    # 메타 없으면 그대로
    g._current_place_meta = {}
    assert g._insert_meta_lines("<h2>x</h2>") == "<h2>x</h2>"


# ── 영수증↔장소 자동 매칭 ──
def test_match_receipts_to_stops():
    photos = [
        _pr("u/a.jpg", "2026:06:22 10:00:00", "스타벅스 삿포로", True),
        _pr("u/c.jpg", "2026:06:23 09:00:00", "오타루 운하", True),
    ]
    plan = TripPlanner.build_draft(photos)
    receipts = [
        {"store_name": "스타벅스", "amount": 600, "currency": "JPY", "date": "2026-06-22", "image_path": "x"},
        {"store_name": "알수없는가게", "amount": 1000, "currency": "JPY", "date": "2026-06-22", "image_path": "y"},
    ]
    plan2, un = TripPlanner.match_receipts_to_stops(plan, receipts)
    sb = [s for d in plan2["days"] for s in d["stops"] if s["name"] == "스타벅스 삿포로"][0]
    assert sb["receipt"] and sb["receipt"]["amount"] == 600   # 이름 일치 -> 배정
    assert len(un) == 1 and un[0]["store_name"] == "알수없는가게"  # 미배정
    assert plan2["unmatched_receipts"] == un
    # 재실행 멱등성: 같은 입력 재매칭해도 동일
    plan3, un2 = TripPlanner.match_receipts_to_stops(plan2, receipts)
    sb3 = [s for d in plan3["days"] for s in d["stops"] if s["name"] == "스타벅스 삿포로"][0]
    assert sb3["receipt"]["amount"] == 600 and len(un2) == 1


def test_match_receipts_to_stops_ambiguous_tie_stays_unmatched():
    # 두 곳 모두 이름이 일치하고 날짜 정보 없음(동점) -> 추측하지 않고 미배정
    photos = [
        _pr("u/a.jpg", "2026:06:22 10:00:00", "카페 A점", True),
        _pr("u/b.jpg", "2026:06:23 10:00:00", "카페 B점", True),
    ]
    plan = TripPlanner.build_draft(photos)
    receipts = [{"store_name": "카페", "amount": 500, "currency": "JPY", "date": "", "image_path": "z"}]
    plan2, un = TripPlanner.match_receipts_to_stops(plan, receipts)
    assert all(s["receipt"] is None for d in plan2["days"] for s in d["stops"])
    assert len(un) == 1


def test_receipt_crosscheck_name_rejects_single_char():
    # 한 글자 부분일치는 우연 매칭 위험 -> False
    assert ReceiptReader.crosscheck_name("가", "가나다 식당") is False


# ── 생성 파이프라인 스모크 테스트: AI 호출은 monkeypatch, 코드조립 불변식만 확인 ──
def test_generate_drafts_smoke_no_network(monkeypatch):
    import types, json as _json
    photos = [
        _pr("u/a.jpg", "2026:06:22 10:00:00", "오타루 운하", True, 43.19, 140.99),
        _pr("u/b.jpg", "2026:06:23 09:00:00", "삿포로 TV타워", True, 43.06, 141.35),
    ]
    g = TravelBlogGenerator(Config())
    g.google_key = ""  # 경로 조회(_fetch_route_data)가 네트워크 없이 조기 반환하도록

    def fake_create(**kwargs):
        msgs = kwargs.get("messages", [])
        sys_msg = msgs[0]["content"] if len(msgs) > 1 else ""
        if sys_msg.startswith("정확한 지역 백과사전"):
            content = _json.dumps({"intro": "홋카이도 소개", "specialties": [], "foods": [], "spots": []})
        elif sys_msg.startswith("인기 여행 블로거"):
            content = _json.dumps({"title": "홋카이도 여행기",
                                    "content": "<h2>오타루</h2><p>운하가 아름다웠다.</p>"})
        else:
            content = "오타루 운하: 낭만적인 운하 산책로.\n삿포로 TV타워: 전망대에서 도심 조망."
        return types.SimpleNamespace(choices=[types.SimpleNamespace(
            message=types.SimpleNamespace(content=content))])

    monkeypatch.setattr(g.client.chat.completions, "create", fake_create)

    group = {"photos": photos, "label": "전체", "course_line": ""}
    drafts = g.generate_drafts(group, "전체", trip_title="홋카이도 여행",
                                selected_structure="감성 후기형")
    assert len(drafts) == 1
    post = drafts[0]
    assert post["title"] and post["content"]
    assert "홋카이도 소개" in post["content"]  # 위키 박스가 코드로 최상단 삽입됐는지(핵심 설계 원칙)
    assert "http://" not in post["content"] and "https://" not in post["content"]  # URL 미누출 불변식
    assert post["style"] == "감성 후기형"


# ── 같은 위치(GPS) 사진 묶기 ──
def test_stops_group_by_gps_when_unnamed():
    # 이름 없는(name_confident=False) 두 사진이 같은 GPS → 한 stop
    photos = [
        _pr("u/a.jpg", "2026:06:22 10:00:00", "카페", False, 43.1901, 140.9902),
        _pr("u/b.jpg", "2026:06:22 10:05:00", "노포", False, 43.1902, 140.9903),  # ~같은 위치
        _pr("u/c.jpg", "2026:06:22 12:00:00", "먼곳",  False, 43.2500, 141.3500),  # 다른 위치
    ]
    plan = TripPlanner.build_draft(photos)
    stops = plan["days"][0]["stops"]
    # a,b 는 한 stop(사진 2장), c 는 별도 stop
    sizes = sorted(len(s["photo_ids"]) for s in stops)
    assert sizes == [1, 2], sizes
    # 확신 이름이 있으면 이름으로 묶임(기존 유지)
    photos2 = [
        _pr("u/x.jpg", "2026:06:22 09:00:00", "스타벅스", True, 1.0, 1.0),
        _pr("u/y.jpg", "2026:06:22 18:00:00", "스타벅스", True, 9.0, 9.0),  # 이름 같으면 위치 달라도 묶임
    ]
    st2 = TripPlanner.build_draft(photos2)["days"][0]["stops"]
    assert len(st2) == 1 and len(st2[0]["photo_ids"]) == 2


def test_stops_fill_neutral_name_when_unconfident():
    photos = [
        _pr("u/a.jpg", "2026:06:22 10:00:00", "오타루 카페", False, 43.10, 140.10),  # 무확신 + 중립명 + gps
        _pr("u/b.jpg", "2026:06:22 12:00:00", "", False),                          # 이름·gps 없음 → 비움
    ]
    plan = TripPlanner.build_draft(photos)
    stops = plan["days"][0]["stops"]
    byname = {s["name"]: s["name_source"] for s in stops}
    assert byname.get("오타루 카페") == "auto"       # 중립명 채워짐
    assert "" in byname and byname[""] == "none"     # 진짜 빈 것만 none


# ── 재생성 시 사용자 편집 보존·병합 ──
def test_merge_user_edits():
    photos = [
        _pr("u/a.jpg", "2026:06:22 10:00:00", "오타루 운하", True),
        _pr("u/c.jpg", "2026:06:23 09:00:00", "삿포로 TV타워", True),
    ]
    old = TripPlanner.build_draft(photos)
    s = old["days"][0]["stops"][0]
    s["name"] = "오타루 운하 본점"; s["name_source"] = "user"
    s["events"] = ["운하 산책"]; s["feeling"] = "로맨틱"; s["rating"] = 4.5
    # 재분석 → 편집 없는 새 초안 (같은 사진들이라 photo_id 동일)
    new = TripPlanner.build_draft(photos)
    TripPlanner.merge_user_edits(new, old)
    st0 = new["days"][0]["stops"][0]
    assert st0["name"] == "오타루 운하 본점" and st0["name_source"] == "user"
    assert st0["events"] == ["운하 산책"] and st0["feeling"] == "로맨틱" and st0["rating"] == 4.5
    # 편집 없던 Day2는 그대로
    st1 = new["days"][1]["stops"][0]
    assert st1["name"] == "삿포로 TV타워" and st1["rating"] is None


# ── Task 1: 문체 프로파일 → 프롬프트 조각 ──
def _style_ctx(profile):
    # _style_context는 self를 쓰지 않는 순수 로직 → 언바운드 호출로 테스트
    return TravelBlogGenerator._style_context(TravelBlogGenerator.__new__(TravelBlogGenerator), profile)


def test_style_context_from_profile():
    profile = {
        "tone": "친근 구어체",
        "person": "1인칭 혼잣말체",
        "sentence_length": "짧고 끊어치는 리듬",
        "ending_patterns": ["~더라고요", "~었어요"],
        "emoji_usage": "ㅎㅎ 가볍게 문단당 1회",
        "rhetorical_habits": ["'근데'로 화제 전환"],
        "donts": ["격식체 금지"],
        "examples": ["아 이거지 싶더라고요", "기다린 보람 있었어요!"],
        # 표절 방지 회귀용: 원문 문단은 절대 조각에 실리면 안 됨
        "sample_paragraphs": ["이것은매우긴원문문단으로절대프롬프트에통째로들어가면안되는내용ABCDEF"],
    }
    ctx = _style_ctx(profile)
    assert "친근 구어체" in ctx
    assert "~더라고요" in ctx
    assert "아 이거지 싶더라고요" in ctx
    # 원문 문단 통째 주입 금지(표절 방지)
    assert "절대프롬프트에통째로들어가면안되는내용ABCDEF" not in ctx
    # 예시는 최대 2개
    assert ctx.count('"') == 4


def test_style_context_empty():
    assert _style_ctx(None) == ""
    assert _style_ctx({}) == ""
    assert _style_ctx({"tone": ""}) == ""


# ── Task 2: StyleAnalyzer 정규식 폴백 프로파일 ──
def test_extract_profile_regex_fallback():
    sa = StyleAnalyzer(None)  # config 없음 → 정규식 폴백
    p = sa.extract_profile("첫날은 살살 돌았어요. 라멘이 진짜 맛있더라고요. 웨이팅 있었어요.")
    assert p["extracted_by"] == "regex_fallback"
    assert p["tone"]                       # 톤이 채워짐
    assert isinstance(p["ending_patterns"], list)
    assert isinstance(p["examples"], list)


# ── Task 3: StyleAnalyzer LLM 문체 추출 + 정규화 ──
def test_normalize_profile_caps():
    raw = {
        "tone": "  친근  ",
        "ending_patterns": ["~요", "~죠", "~네요", "~더라", "~군", "~구나", "~잖아"],  # 7개
        "examples": ["문장1", "문장2", "문장3"],   # 3개
        "rhetorical_habits": "질문형 도입",          # 문자열도 허용
    }
    p = StyleAnalyzer._normalize_profile(raw)
    assert p["tone"] == "친근"                       # strip
    assert len(p["ending_patterns"]) == 6            # 6개로 캡
    assert len(p["examples"]) == 2                   # 2개로 캡(표절 방지)
    assert p["rhetorical_habits"] == ["질문형 도입"]  # str→list
    assert p["extracted_by"] == "llm"


def test_extract_profile_uses_llm_when_valid(monkeypatch):
    class FakeCfg:
        def is_valid(self): return True
        def get(self, *a): return "sk-test"
    sa = StyleAnalyzer(FakeCfg())
    fixture = {"tone": "감성체", "ending_patterns": ["~네요"], "examples": ["예시"],
               "extracted_by": "llm", "warning": None}
    monkeypatch.setattr(sa, "_extract_profile_llm", lambda text: fixture)
    p = sa.extract_profile("아무 긴 텍스트 " * 10)
    assert p is fixture
    assert p["extracted_by"] == "llm"


def test_thin_text_warning(monkeypatch):
    sa = StyleAnalyzer(None)  # 정규식 폴백(네트워크 없음)
    monkeypatch.setattr(sa, "_scrape", lambda url: {
        "title": "t", "headings": [], "paragraphs": ["아주 짧은 글"], "image_count": 0})
    p = sa.analyze("http://example.com")
    assert p["warning"]                    # 200자 미만 → 경고 세팅
    assert p["source_urls"] == ["http://example.com"]
    assert p["extracted_by"] == "regex_fallback"


def test_extract_keywords_stopwords():
    titles = ["후쿠오카 여행 갔다왔어요 진짜 좋았어요", "후쿠오카 맛집 라멘 후기 정말 추천"]
    descs = ["오늘 다녀온 후쿠오카 텐진 맛집 그리고 라멘"]
    kws = NaverBlogAnalyzer._extract_keywords(titles, descs, "후쿠오카 여행")
    assert "라멘" in kws and "맛집" in kws        # 실질 키워드는 살아남음
    assert "후쿠오카" not in kws                   # 검색 키워드 자신(부분 포함) 제외
    assert "진짜" not in kws and "정말" not in kws  # 불용어 제외
    assert "그리고" not in kws and "오늘" not in kws
    assert len(kws) <= 15


def test_extract_core_tags():
    analysis = {"common_keywords": ["라멘", "맛집", "온천", "야경", "카페"]}
    tags = TravelBlogGenerator.extract_core_tags(analysis, "후쿠오카")
    assert "후쿠오카" in tags and "후쿠오카여행" in tags
    assert "후쿠오카맛집" in tags            # 맛집 신호 있음 → 조합 태그
    assert 3 <= len(tags) <= 5
    # analysis 없음 → region 최소 태그
    assert TravelBlogGenerator.extract_core_tags(None, "삿포로") == ["삿포로", "삿포로여행"]
    # 둘 다 없음 → 빈 리스트 (조용히 생략)
    assert TravelBlogGenerator.extract_core_tags(None, "") == []


def test_merge_tags():
    core = ["후쿠오카", "후쿠오카여행", "라멘"]
    ai = ["# 후쿠오카", "야타이", "텐진", "라멘 ", "야경", "온천", "신사", "공원", "카페", "쇼핑"]
    merged = TravelBlogGenerator.merge_tags(ai, core)
    assert merged[:3] == core                       # 핵심 태그 우선 배치
    assert len(merged) <= 10                        # 상한
    norm = [t.replace(" ", "").replace("#", "") for t in merged]
    assert len(norm) == len(set(norm))              # 정규화 기준 중복 없음("# 후쿠오카"/"라멘 " 제거됨)
    # 빈 입력 안전
    assert TravelBlogGenerator.merge_tags(None, []) == []
    assert TravelBlogGenerator.merge_tags(["a"], None) == ["a"]


def test_seo_check_warnings():
    analysis = {"common_keywords": ["라멘", "맛집"],
                "avg_analysis": {"avg_chars": 4000}}
    # 문제 3종: 제목에 지역명 없음 / 분량 60% 미만 / 태그에 지역명 없음
    post = {"title": "겨울 바다와 라멘 한 그릇",
            "content": "<p>" + ("가나다라마바사아" * 100) + "</p>",   # 800자 = 4000의 20%
            "tags": ["라멘", "야경"]}
    warns = TravelBlogGenerator.seo_check(post, analysis, "후쿠오카")
    assert len(warns) == 3
    assert any("제목" in w for w in warns)
    assert any("분량" in w for w in warns)
    assert any("태그" in w for w in warns)
    # 문제 없음 → 빈 리스트
    good = {"title": "후쿠오카 여행 라멘 총정리",
            "content": "<p>" + ("가나다라마바사아" * 500) + "</p>",   # 4000자
            "tags": ["후쿠오카", "라멘"]}
    assert TravelBlogGenerator.seo_check(good, analysis, "후쿠오카") == []
    # analysis 없음 → 빈 리스트 (검증 스킵)
    assert TravelBlogGenerator.seo_check(post, None, "후쿠오카") == []


def test_optimize_title_pick_and_fallback(monkeypatch):
    import types, json as _json
    g = TravelBlogGenerator(Config())
    na = {"top_titles": ["기타큐슈 여행 코스 총정리", "기타큐슈 맛집 BEST 5"],
          "common_keywords": ["라멘", "맛집"], "avg_title_length": 20}
    post = {"title": "고요한 신성함의 기록", "content": "<p>" + "본문" * 200 + "</p>"}
    captured = {}
    def fake_create(**k):
        captured["prompt"] = k["messages"][0]["content"]
        return types.SimpleNamespace(choices=[types.SimpleNamespace(
            message=types.SimpleNamespace(content=_json.dumps({"titles": [
                "너무길다" * 20,                      # 45자 초과 → 탈락
                "감성 여행기",                        # 지역명 없음 → 탈락
                "기타큐슈 라멘 여행 코스 총정리"]})))])  # 통과 → 채택
    monkeypatch.setattr(g.client.chat.completions, "create", fake_create)
    t = g.optimize_title(post, na, "기타큐슈")
    assert t == "기타큐슈 라멘 여행 코스 총정리"
    assert "기타큐슈 여행 코스 총정리" in captured["prompt"]   # 실측 상위 제목이 근거로 포함
    # 전부 탈락 → None (기존 제목 유지용)
    def all_bad(**k):
        return types.SimpleNamespace(choices=[types.SimpleNamespace(
            message=types.SimpleNamespace(content=_json.dumps({"titles": ["지역명없는제목"]})))])
    monkeypatch.setattr(g.client.chat.completions, "create", all_bad)
    assert g.optimize_title(post, na, "기타큐슈") is None
    # 분석 없음 → None (호출 안 함)
    assert g.optimize_title(post, None, "기타큐슈") is None


def test_naver_context_no_map_directive():
    na = {"keyword": "후쿠오카 여행", "top_titles": ["t1"], "common_keywords": ["라멘"],
          "avg_analysis": {"avg_chars": 4000, "avg_images": 15, "avg_videos": 0,
                           "map_ratio": 0.8, "common_sections": []}}
    g = TravelBlogGenerator.__new__(TravelBlogGenerator)
    ctx = TravelBlogGenerator._naver_context(g, na)
    assert "지도 삽입 필수" not in ctx           # 불변식 충돌 문구 제거됨
    assert "넣지" in ctx                          # "본문에 절대 넣지 말 것" 안내로 대체


def test_summarize_publish_results():
    ok = {"success": True, "url": "http://blog.naver.com/x/1"}
    fail = {"success": False, "reason": "session not created: Chrome instance exited"}
    # 전부 성공 → done
    s, msg = summarize_publish_results([ok, ok], ["글1", "글2"])
    assert s == "done" and "2" in msg
    # 일부 실패 → error + 실패 글 제목·사유 노출 (허위 "완료" 금지)
    s, msg = summarize_publish_results([ok, fail], ["글1", "글2"])
    assert s == "error" and "글2" in msg and "session not created" in msg
    # 전부 실패 → error
    s, msg = summarize_publish_results([fail], ["글1"])
    assert s == "error"
    # 빈 입력 안전
    s, msg = summarize_publish_results([], [])
    assert s == "error"


def test_number_places():
    f = TravelBlogGenerator._number_places
    html = ('<p style="letter-spacing:3px">PLACE N</p><p>본문</p>'
            '<p style="letter-spacing:3px">PLACE N</p>')
    out = f(html)
    assert "PLACE 1" in out and "PLACE 2" in out and "PLACE N" not in out
    # 이미 채번된 것은 무변경
    done = '<p>PLACE 1</p><p>PLACE 2</p>'
    assert f(done) == done
    # PLACE 없음 → 무변경, 빈 입력 안전
    assert f("<p>그냥 본문</p>") == "<p>그냥 본문</p>"
    assert f("") == ""


def test_html_to_blocks_no_markdown_heading():
    from posters import html_to_blocks
    html = ('<h3 style="text-align:center">📍 오사카시 여행 전 꼭 알아야 할 핵심 정보</h3>'
            '<p>오사카시는 일본의 간사이 지방에 위치한 대도시입니다.</p>'
            '<h2>여행 꿀팁</h2>')
    blocks = html_to_blocks(html)
    texts = [b.get("content", "") for b in blocks if b.get("type") == "text"]
    # 마크다운 리터럴이 텍스트 블록에 남지 않는다 (## 노출 버그 회귀 방지)
    assert not any(t.strip().startswith("#") for t in texts)
    assert not any("##" in t for t in texts)
    heads = [b for b in blocks if b.get("type") == "heading"]
    assert any("핵심 정보" in h.get("content", "") for h in heads)
    assert any("여행 꿀팁" in h.get("content", "") for h in heads)


def test_region_desc_uses_naver_evidence(monkeypatch):
    import types, json as _json
    g = TravelBlogGenerator(Config())
    captured = {}
    fake = types.SimpleNamespace(choices=[types.SimpleNamespace(
        message=types.SimpleNamespace(content=_json.dumps(
            {"intro": "소개", "specialties": [], "foods": [], "spots": []})))])
    def fake_create(**k):
        captured["messages"] = k["messages"]; return fake
    monkeypatch.setattr(g.client.chat.completions, "create", fake_create)
    na = {"common_keywords": ["료칸", "카메노이호텔"], "top_titles": ["기타큐슈 여행기 총정리"]}
    g._generate_region_desc("기타큐슈", na)
    user = captured["messages"][1]["content"]
    assert "료칸" in user and "실측 참고" in user and "무시" in user
    # 근거 미전달 → 기존 프롬프트 그대로 (회귀)
    g._generate_region_desc("기타큐슈")
    user2 = captured["messages"][1]["content"]
    assert "실측 참고" not in user2


def test_region_desc_tips_access(monkeypatch):
    import types, json as _json
    g = TravelBlogGenerator(Config())
    fake = types.SimpleNamespace(choices=[types.SimpleNamespace(
        message=types.SimpleNamespace(content=_json.dumps({
            "intro": "소개", "specialties": [], "foods": ["라멘"], "spots": [],
            "tips": ["겨울엔 방한 필수"], "access": ["공항에서 지하철 30분"]})))])
    monkeypatch.setattr(g.client.chat.completions, "create", lambda **k: fake)
    box = g._generate_region_desc("기타큐슈")
    assert "💡" in box and "방한" in box
    assert "🚌" in box and "지하철" in box
    # 빈 배열이면 행 생략
    fake2 = types.SimpleNamespace(choices=[types.SimpleNamespace(
        message=types.SimpleNamespace(content=_json.dumps({
            "intro": "소개", "specialties": [], "foods": [], "spots": [],
            "tips": [], "access": []})))])
    monkeypatch.setattr(g.client.chat.completions, "create", lambda **k: fake2)
    box2 = g._generate_region_desc("기타큐슈")
    assert "💡" not in box2 and "🚌" not in box2


# ── F2: 피드백 재작성 — 자산 잠금(_protect_assets/_restore_assets) ──
_ASSET_HTML = (
    '<p>인트로 문장.</p>'
    '<div style="background:#f7f8f3;border:1px solid #e3e7d8">위키박스 내용</div>'
    '<p>본문 A</p>'
    '<figure style="text-align:center"><img src="data:image/jpeg;base64,AAAA"/></figure>'
    '<p>본문 B</p>'
    '<div style="background:linear-gradient(135deg,#eef6ff,#f0f4ff)">'
    '<div style="font-weight:bold">🚶 이동 A → B</div>'
    '<div style="color:#6b7280">10분</div></div>'
    '<p>마무리</p>'
)


def test_protect_restore_roundtrip():
    text, assets = TravelBlogGenerator._protect_assets(_ASSET_HTML)
    assert len(assets) == 3                      # 위키박스 + figure + 경로카드
    assert "base64" not in text                  # 무거운 자산이 텍스트에서 제거됨
    assert "[KEEP_1]" in text and "[KEEP_3]" in text
    assert "본문 A" in text and "본문 B" in text  # 본문은 남음
    restored = TravelBlogGenerator._restore_assets(text, assets)
    assert restored == _ASSET_HTML               # 무손실 왕복


def test_restore_rejects_missing_token():
    text, assets = TravelBlogGenerator._protect_assets(_ASSET_HTML)
    # 토큰 삭제 → 거부
    assert TravelBlogGenerator._restore_assets(text.replace("[KEEP_2]", ""), assets) is None
    # 토큰 중복 → 거부
    assert TravelBlogGenerator._restore_assets(text + "[KEEP_1]", assets) is None
    # None 입력 안전
    assert TravelBlogGenerator._restore_assets(None, assets) is None


# ── F2: 피드백 재작성 — revise_draft LLM 연동 ──
def test_revise_draft_llm_wiring(monkeypatch):
    import types
    g = TravelBlogGenerator(Config())
    captured = {}
    def fake_create(**k):
        captured["prompt"] = k["messages"][0]["content"]
        # AI가 본문만 고치고 KEEP 토큰은 유지한 응답을 모사
        text, _ = TravelBlogGenerator._protect_assets(_ASSET_HTML)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(
            message=types.SimpleNamespace(content=text.replace("본문 A", "더 감성적인 본문 A")))])
    monkeypatch.setattr(g.client.chat.completions, "create", fake_create)
    post = {"content": _ASSET_HTML, "tags": ["기타큐슈"], "title": "제목"}
    out = g.revise_draft(post, "더 감성적으로", None)
    assert out is not None
    assert "더 감성적인 본문 A" in out["content"]
    assert "base64,AAAA" in out["content"]            # 자산 복원됨
    assert "피드백" in captured["prompt"] and "더 감성적으로" in captured["prompt"]
    assert "KEEP" in captured["prompt"]               # 토큰 유지 규칙 포함
    # 빈 피드백 → None
    assert g.revise_draft(post, "  ", None) is None
    # AI가 토큰을 삭제한 응답 → None (원본 무손상)
    def bad_create(**k):
        return types.SimpleNamespace(choices=[types.SimpleNamespace(
            message=types.SimpleNamespace(content="토큰 다 날린 응답"))])
    monkeypatch.setattr(g.client.chat.completions, "create", bad_create)
    assert g.revise_draft(post, "피드백", None) is None


# ── G1: 초안 파일 저장/복원 (app.py) ──
def test_drafts_save_load_roundtrip(tmp_path, monkeypatch):
    import app as app_mod
    monkeypatch.setitem(app_mod.state, "plan", {"trip_title": "테스트 여행"})
    monkeypatch.setattr(app_mod, "_plan_dir", lambda: str(tmp_path))
    app_mod.state["group_states"] = {0: {"drafts": [{"title": "t", "content": "<p>c</p>", "tags": ["a"]}]}}
    app_mod._save_drafts(0)
    app_mod.state["group_states"] = {}
    loaded = app_mod._load_saved_drafts(0)
    assert loaded and loaded[0]["title"] == "t"
    assert app_mod._load_saved_drafts(99) is None   # 없는 그룹 → None


def test_plan_draft_resets_session(monkeypatch, tmp_path):
    """새 계획 확정 = 새 원고 세션: 이전 여행의 초안·SEO 근거가 남지 않는다(오사카→도쿄 혼입 버그)."""
    import app as app_mod
    import core as core_mod
    # 이전 여행(오사카) 잔재
    app_mod.state["photo_results"] = [{"file_name": "a.jpg"}]
    app_mod.state["group_states"] = {0: {"drafts": [{"title": "오사카 초안"}]}}
    app_mod.state["naver_analysis"] = {"keyword": "오사카 여행"}
    app_mod.state["plan"] = None
    monkeypatch.setattr(app_mod, "_plan_dir", lambda: str(tmp_path))
    d = tmp_path / "drafts"; d.mkdir()
    (d / "group_0.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(core_mod.TripPlanner, "build_draft",
                        staticmethod(lambda pr, free_mode=False: {"trip_title": "", "days": [], "region": ""}))
    c = app_mod.app.test_client()
    r = c.post('/api/plan/draft', json={"overwrite": True})
    assert r.status_code == 200
    assert app_mod.state["group_states"] == {}          # 이전 초안 메모리 제거
    assert app_mod.state["naver_analysis"] is None       # 이전 지역 SEO 근거 제거
    assert not d.exists()                                 # 이전 초안 파일 제거


# ── H1: 여행=프로젝트 저장/로드 (app.py) ──
def test_project_save_load_roundtrip(monkeypatch, tmp_path):
    import app as app_mod
    monkeypatch.setattr(app_mod, "_plan_dir", lambda: str(tmp_path))
    app_mod.state.update({
        "photo_paths": ["uploads/a.jpg"],
        "photo_results": [{"file_name": "a.jpg", "gps": {"lat": 1, "lon": 2}}],
        "naver_analysis": {"keyword": "오사카 여행"},
        "style_analysis": {"tone": "친근"},
        "receipts": [{"store_name": "가게"}],
        "published_gis": {0},
        "completed": {1, 2},
    })
    app_mod._save_project()
    assert (tmp_path / "project.json").exists()
    # 세션 클리어 후 로드 복원
    app_mod.state.update({"photo_paths": [], "photo_results": [], "naver_analysis": None,
                          "style_analysis": None, "receipts": [], "published_gis": set(),
                          "completed": set()})
    ok = app_mod._load_project_data(str(tmp_path))
    assert ok
    assert app_mod.state["photo_results"][0]["file_name"] == "a.jpg"
    assert app_mod.state["naver_analysis"]["keyword"] == "오사카 여행"
    assert app_mod.state["published_gis"] == {0}
    assert app_mod.state["completed"] == {1, 2}


def test_plan_dir_unique_untitled():
    import app as app_mod
    old_plan, old_dir = app_mod.state.get("plan"), app_mod.state.get("_plan_dir")
    app_mod.state["plan"] = {"trip_title": ""}
    app_mod.state["_plan_dir"] = None
    d = app_mod._plan_dir()
    assert "여행_" in d and "untitled" not in d      # 자동 이름 부여
    assert app_mod._plan_dir() == d                   # 같은 세션에선 일관(캐시)
    app_mod.state["plan"], app_mod.state["_plan_dir"] = old_plan, old_dir
