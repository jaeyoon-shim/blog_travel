# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

TravelBlog Pro — 여행 사진(EXIF GPS + Vision AI)을 분석해 네이버 블로그 원고를 자동 생성·발행하는 Python 풀스택 도구. 코드/주석/문서/커밋 메시지는 한국어가 기본.

## 명령어

Windows + venv 환경. 항상 venv의 파이썬을 명시적으로 호출한다.

```bash
# 웹 서버 실행 (메인 진입점) → http://localhost:<port>
venv/Scripts/python.exe app.py

# 전체 테스트
venv/Scripts/python.exe -m pytest tests/test_quality.py -q

# 단일 테스트
venv/Scripts/python.exe -m pytest tests/test_quality.py::test_name_match -q

# 의존성 설치 (Windows 발행 시 pywin32 + Chrome/chromedriver 추가 필요)
venv/Scripts/python.exe -m pip install -r requirements.txt
```

테스트는 외부 API/네트워크/Selenium을 타지 않는 **순수 로직 유닛테스트만** 존재한다(`tests/test_quality.py`). 사진 분석·POI 해석·이름 매칭 같은 결정적 함수만 커버하며, monkeypatch로 네트워크 호출을 막는다. 신규 로직도 같은 방식(순수 함수로 분리 → monkeypatch)으로 테스트 가능하게 작성한다.

## 설정 / 시크릿

`.env`(시크릿)와 `config.json`/`settings.json`(런타임 설정)은 모두 gitignore 대상. `Config` 클래스가 `.env` + `config.json`을 병합 로드하는 **설정 단일 진실원**이다. 템플릿은 `.env.example`, `config.example.json` 참고. 필수: `OPENAI_API_KEY`. 선택: `OPENAI_MODEL`(기본 gpt-4o-mini), `GOOGLE_MAPS_API_KEY`, `NAVER_*`.

`uploads/`(여행 사진 수백 MB), `selenium_profile/`(네이버 로그인 세션 포함, 민감), `posts/`(생성 결과)도 gitignore 대상이다.

## 아키텍처

Flask 백엔드 + 단일 페이지 UI 구조. 무거운 작업은 백그라운드 스레드 + `/api/status` 폴링으로 처리한다.

- **`app.py`** — Flask REST API. 전역 `state` dict로 세션 상태 관리. 분석/생성/발행은 `threading.Thread`(daemon)로 돌리고 프론트가 `/api/status`를 폴링.
- **`core.py`** — AI 엔진(가장 큰 파일, ~2,500줄). 주요 클래스: `Config`, `PhotoAnalyzer`(EXIF·역지오코딩·Vision·POI 해석), `TripStructurer`(동선 그루핑), `TravelBlogGenerator`(프롬프트 빌드·원고 생성·위키박스/경로 삽입), `NaverBlogAnalyzer`/`StyleAnalyzer`(SEO·문체 분석), `LocalSaver`.
- **`posters.py`** — 발행 엔진. `html_to_blocks()`(AI HTML → 네이버 에디터 블록 배열)와 `NaverSeleniumPoster`(클립보드 기반 캡차 우회 발행). `NaverPoster`/`TistoryPoster`는 파사드.
- **`static/index.html`** — 5단계 SPA UI. **이 파일이 실제 서빙되는 UI**다(`app.py`의 `/`가 `send_from_directory('static','index.html')`). UI 작업은 반드시 여기서 한다. (거대 단일 인라인 `<script>`이므로 구문오류 하나로 SPA 전체가 죽는다 — 수정 후 `node vm.Script`로 파싱 검증 + `/browse`로 실제 렌더 확인.)
- `blog_auto.py`는 **레거시 Tkinter 데스크톱 GUI 변형**(웹 에디션으로 대체됨). `route_map_capture.py`는 경로 지도 캡처 유틸.

**현재 단계별 흐름·기능·사용자 입력값은 `docs/WORKFLOW.md`(최신, 권위 문서)**. 모듈/클래스 구조는 `SPEC.md`(단, 5단계 시절 기준 — 워크플로우는 WORKFLOW.md가 우선), 버전 히스토리·버그 이력은 `README.md` 참고.

### 5단계 워크플로우 (데이터 흐름)
```
업로드 → 분석(EXIF/GPS→역지오코딩→Vision AI→한글 장소명) → 그룹+SEO 선택 → 원고 생성 → 미리보기/발행
```
사진 1장 = `photo_result` dict, 생성된 초안 = `post` dict (구조는 SPEC.md §4 참고).

## 핵심 설계 원칙 — "형식은 코드가 조립, AI는 본문만"

이 프로젝트에서 가장 자주 깨지고 가장 중요한 불변식. 위반하면 발행 결과가 망가진다.

1. **AI에게 형식을 맡기지 않는다.** 지역 위키 박스, 구글맵 표시, 이동경로 카드는 모두 **코드가 HTML로 조립**해서 삽입한다(`_generate_region_desc`, `_insert_photos_with_map`, `_insert_route_guides`). AI는 인트로/장소 소개/사진 설명/팁 등 **본문 텍스트만** 생성. 프롬프트에 "구글맵/경로 HTML 절대 금지" 규칙이 명시돼 있고 시스템 메시지로도 강제한다.

2. **구글맵 URL을 HTML에 절대 넣지 않는다.** 네이버 SE3 에디터가 URL을 감지하면 무조건 OG 링크카드로 변환해버린다. 따라서 `📍 장소명`, `📍 A → B 경로` 같은 **텍스트만** 표시하고 URL은 넣지 않는다.

3. **신뢰 기반 POI 해석.** 장소명은 Places API 후보와 **간판/이름 교차검증이 일치할 때만** 채택하고, 추측이면 `None`으로 비운다(환각 방지). 관련 함수: `_resolve_poi`, `_pick_best_poi`, `_name_match`, `_vision_to_places_types`. 위치/지역 감지 실패 시 위키박스·구글맵은 **조용히 생략**(에러 아님).

## 자주 밟는 지뢰

- **프롬프트 f-string 중괄호**: `core.py`의 프롬프트는 거대한 f-string이다. 리터럴 `{`/`}`는 `{{`/`}}`로 이스케이프해야 한다. `PLACE {번호}` 같은 한글 변수명은 NameError를 유발하므로 `PLACE N`처럼 AI가 채번하게 둔다.
- **except 블록의 `e` 변수**(주로 `blog_auto.py`): Python 3에서 except 종료 시 `e`가 삭제된다. `lambda`/콜백에서 쓰려면 `err_msg = str(e)`로 먼저 캡처한 뒤 그 변수를 참조한다.
- **네이버 React 에디터**: JS click이 아니라 **Selenium/ActionChains click**이어야 동기 이벤트가 발생한다. 본문 포커스는 반드시 Selenium click. iframe/임시저장 팝업 타이밍 의존이 커서 `time.sleep`이 많고, 네이버 DOM 변경 시 셀렉터 점검이 필요하다.
- **클립보드 발행**: 발행 중 OS 클립보드를 점유한다(win32clipboard). 발행 동안 다른 복붙 금지.

## 작업 기록

설계/구현 계획 문서는 `docs/superpowers/specs/`(설계), `docs/superpowers/plans/`(구현 계획)에 날짜별로 쌓는다. 큰 기능은 여기에 먼저 설계를 남기는 흐름.
