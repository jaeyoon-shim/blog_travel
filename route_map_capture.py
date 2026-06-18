"""
구글맵 경로 이미지 생성 모듈
==============================
방법1: Google Static Maps API (API 키 있을 때) — 빠르고 깔끔
방법2: Selenium 스크린샷 (API 키 없을 때) — 실제 화면 캡처

사용:
    from route_map_capture import capture_route_image

    # API 키 있으면 Static Maps, 없으면 Selenium 폴백
    img_path = capture_route_image(
        origin=(35.6595, 139.7004),
        destination=(35.7148, 139.7967),
        mode="transit",
        output_path="route_shibuya_asakusa.png",
        google_key="AIza...",           # None이면 Selenium
        selenium_driver=None,           # 기존 드라이버 재활용 가능
    )
"""

import os
import time
import logging

logger = logging.getLogger(__name__)


# ============================================================
# departure_time 파싱
# ============================================================
def _parse_departure_time(departure_time):
    """
    다양한 형식의 출발 시간 → Unix epoch (int)

    지원:
      - None → None
      - int (이미 epoch) → 그대로
      - "2024:05:25 14:30:00" (EXIF 형식)
      - "2024-05-25 14:30:00"
      - "2024-05-25"

    과거 시간이면 같은 요일+시간으로 다음주 날짜로 변환
    (Google Directions API는 과거 시간을 거부)
    """
    if departure_time is None:
        return None
    if isinstance(departure_time, (int, float)):
        epoch = int(departure_time)
        # 과거 시간 체크
        import datetime as _dt
        if epoch < int(_dt.datetime.now().timestamp()):
            return _shift_to_next_week(epoch)
        return epoch

    # 문자열 파싱
    import re
    import datetime as _dt
    m = re.match(r'(\d{4})[:\-/](\d{2})[:\-/](\d{2})\s*(\d{2})?:?(\d{2})?:?(\d{2})?',
                 str(departure_time))
    if not m:
        logger.warning(f"  departure_time 파싱 실패: {departure_time}")
        return None

    try:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hour = int(m.group(4)) if m.group(4) else 12
        minute = int(m.group(5)) if m.group(5) else 0
        second = int(m.group(6)) if m.group(6) else 0
        dt = _dt.datetime(year, month, day, hour, minute, second)
        epoch = int(dt.timestamp())

        if epoch < int(_dt.datetime.now().timestamp()):
            return _shift_to_next_week(epoch)
        return epoch
    except Exception as e:
        logger.warning(f"  departure_time 변환 실패: {departure_time}: {e}")
        return None


def _shift_to_next_week(epoch):
    """과거 epoch → 같은 요일/시간의 다음주 날짜로 변환"""
    import datetime as _dt
    dt = _dt.datetime.fromtimestamp(epoch)
    now = _dt.datetime.now()
    days_ahead = 7 - (now.weekday() - dt.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    future_dt = now.replace(
        hour=dt.hour, minute=dt.minute, second=0, microsecond=0
    ) + _dt.timedelta(days=days_ahead)
    logger.info(f"  📅 과거 시간 → 다음주 같은 요일: {dt.strftime('%Y-%m-%d %H:%M')} → {future_dt.strftime('%Y-%m-%d %H:%M')}")
    return int(future_dt.timestamp())


# ============================================================
# 방법1: Google Static Maps API
# ============================================================
def _static_maps_image(origin, destination, mode, output_path, google_key,
                       waypoints=None, size="640x400", zoom=None,
                       path_color="0x4285F4", path_weight=4,
                       departure_time=None):
    """
    Google Static Maps API로 경로 이미지 생성

    origin/destination: (lat, lon) 튜플
    mode: driving|walking|transit|bicycling
    waypoints: [(lat,lon), ...] 중간 경유지
    departure_time: Unix epoch (int) — transit/driving에서 사용
    """
    import urllib.request
    import urllib.parse

    # Directions API로 경로 polyline 가져오기
    dir_params = {
        "origin": f"{origin[0]},{origin[1]}",
        "destination": f"{destination[0]},{destination[1]}",
        "mode": mode,
        "key": google_key,
    }
    # departure_time 추가 (transit, driving만 지원)
    if departure_time and mode in ("transit", "driving"):
        dir_params["departure_time"] = str(departure_time)
        logger.info(f"  ⏰ Directions API departure_time: {departure_time}")

    dir_url = f"https://maps.googleapis.com/maps/api/directions/json?{urllib.parse.urlencode(dir_params)}"

    import json
    try:
        req = urllib.request.Request(dir_url, headers={"User-Agent": "TravelBlog/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())

        if data.get("status") != "OK" or not data.get("routes"):
            logger.warning(f"Directions API 실패: {data.get('status')}")
            return _static_maps_fallback(origin, destination, output_path, google_key, size)

        # 인코딩된 polyline 추출
        polyline = data["routes"][0]["overview_polyline"]["points"]

    except Exception as e:
        logger.warning(f"Directions API 오류: {e}")
        return _static_maps_fallback(origin, destination, output_path, google_key, size)

    # Static Maps URL 구성
    params = {
        "size": size,
        "maptype": "roadmap",
        "path": f"enc:{polyline}",
        "markers": [
            f"color:red|label:A|{origin[0]},{origin[1]}",
            f"color:blue|label:B|{destination[0]},{destination[1]}",
        ],
        "key": google_key,
        "language": "ko",
    }

    # markers는 여러 개이므로 수동 URL 조립
    base = "https://maps.googleapis.com/maps/api/staticmap?"
    parts = [
        f"size={size}",
        "maptype=roadmap",
        f"path=color:{path_color}|weight:{path_weight}|enc:{polyline}",
        f"markers=color:red%7Clabel:A%7C{origin[0]},{origin[1]}",
        f"markers=color:blue%7Clabel:B%7C{destination[0]},{destination[1]}",
        f"language=ko",
        f"key={google_key}",
    ]

    # 중간 경유지
    if waypoints:
        for idx, wp in enumerate(waypoints):
            label = chr(65 + idx + 1)  # B, C, D...
            parts.append(f"markers=color:green%7Clabel:{label}%7C{wp[0]},{wp[1]}")

    static_url = base + "&".join(parts)

    # 이미지 다운로드
    try:
        req = urllib.request.Request(static_url, headers={"User-Agent": "TravelBlog/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            img_data = resp.read()

        with open(output_path, 'wb') as f:
            f.write(img_data)

        # 유효한 이미지인지 확인
        if len(img_data) < 1000:
            logger.warning(f"Static Maps 응답 너무 작음 ({len(img_data)} bytes)")
            return None

        logger.info(f"✅ Static Maps 경로 이미지: {output_path} ({len(img_data)//1024}KB)")
        return output_path

    except Exception as e:
        logger.error(f"Static Maps 다운로드 실패: {e}")
        return None


def _static_maps_fallback(origin, destination, output_path, google_key, size="640x400"):
    """경로 polyline 없이 출발/도착 마커만 표시하는 폴백"""
    import urllib.request

    base = "https://maps.googleapis.com/maps/api/staticmap?"
    parts = [
        f"size={size}",
        "maptype=roadmap",
        f"markers=color:red%7Clabel:A%7C{origin[0]},{origin[1]}",
        f"markers=color:blue%7Clabel:B%7C{destination[0]},{destination[1]}",
        f"language=ko",
        f"key={google_key}",
    ]
    url = base + "&".join(parts)

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TravelBlog/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            img_data = resp.read()
        with open(output_path, 'wb') as f:
            f.write(img_data)
        logger.info(f"✅ Static Maps (마커만): {output_path}")
        return output_path
    except Exception as e:
        logger.error(f"Static Maps 폴백 실패: {e}")
        return None


# ============================================================
# 방법2: Selenium 스크린샷
# ============================================================
def _selenium_screenshot(origin, destination, mode, output_path,
                         driver=None, close_driver=False,
                         wait_seconds=8, viewport_width=800, viewport_height=600,
                         departure_time=None):
    """
    Selenium으로 구글맵 경로 페이지를 열어 스크린샷

    driver: 기존 Selenium WebDriver (None이면 새로 생성)
    close_driver: True면 캡처 후 드라이버 종료
    departure_time: Unix epoch (int) — URL에 추가 가능
    """
    created_driver = False

    try:
        if driver is None:
            driver = _create_headless_driver(viewport_width, viewport_height)
            created_driver = True

        # 구글맵 경로 URL
        mode_idx = {"driving": "0", "bicycling": "1",
                    "transit": "3", "walking": "2"}.get(mode, "3")
        url = (
            f"https://www.google.com/maps/dir/"
            f"{origin[0]},{origin[1]}/"
            f"{destination[0]},{destination[1]}/"
            f"data=!4m2!4m1!3e{mode_idx}"
        )

        logger.info(f"  🌐 구글맵 경로 열기: {url[:80]}...")
        driver.get(url)
        time.sleep(wait_seconds)

        # 동의 팝업 닫기 (EU/한국 등)
        _close_consent_popup(driver)
        time.sleep(1)

        # 사이드 패널 최소화 (가능한 경우)
        _minimize_sidebar(driver)
        time.sleep(1)

        # 스크린샷
        driver.save_screenshot(output_path)

        # 이미지 크롭 (지도 영역만 추출)
        cropped = _crop_map_area(output_path, output_path)

        file_size = os.path.getsize(output_path)
        logger.info(f"✅ Selenium 스크린샷: {output_path} ({file_size//1024}KB)")
        return output_path

    except Exception as e:
        logger.error(f"Selenium 스크린샷 실패: {e}")
        return None
    finally:
        if created_driver and close_driver:
            try:
                driver.quit()
            except:
                pass


def _create_headless_driver(width=800, height=600):
    """경로 캡처 전용 headless Chrome 드라이버"""
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument(f"--window-size={width},{height}")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    opts.add_argument("--lang=ko")

    driver = webdriver.Chrome(options=opts)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
    })
    return driver


def _close_consent_popup(driver):
    """구글 동의 팝업/쿠키 배너 닫기"""
    try:
        driver.execute_script("""
            // "모두 동의" / "Accept all" 버튼 찾기
            var buttons = document.querySelectorAll('button');
            for (var i = 0; i < buttons.length; i++) {
                var t = buttons[i].textContent.trim().toLowerCase();
                if (t.indexOf('동의') >= 0 || t.indexOf('accept') >= 0 ||
                    t.indexOf('agree') >= 0 || t.indexOf('consent') >= 0) {
                    buttons[i].click();
                    return 'closed';
                }
            }
            // form[action*="consent"] 내 submit
            var form = document.querySelector('form[action*="consent"]');
            if (form) {
                var btn = form.querySelector('button[type="submit"], input[type="submit"]');
                if (btn) { btn.click(); return 'form-closed'; }
            }
            return 'none';
        """)
    except:
        pass


def _minimize_sidebar(driver):
    """구글맵 사이드 패널 축소 시도"""
    try:
        driver.execute_script("""
            // 사이드 패널 닫기 버튼
            var close = document.querySelector('[aria-label="Close"], .close-button');
            if (close) { close.click(); return; }
            // 패널 최소화
            var panel = document.querySelector('#directions-searchbox-0');
            if (panel) panel.style.display = 'none';
            // 검색 패널 숨기기
            var search = document.querySelector('#omnibox-singlebox');
            if (search) search.style.display = 'none';
        """)
    except:
        pass


def _crop_map_area(input_path, output_path):
    """스크린샷에서 지도 영역만 크롭 (상단 검색바 제외)"""
    try:
        from PIL import Image
        img = Image.open(input_path)
        w, h = img.size

        # 상단 약 15% 잘라내기 (검색바/UI 영역)
        top_crop = int(h * 0.10)
        # 좌측 사이드패널 있으면 잘라내기 (약 35%)
        left_crop = int(w * 0.30) if w > 1000 else 0

        cropped = img.crop((left_crop, top_crop, w, h))
        cropped.save(output_path, quality=90)
        logger.info(f"  ✂️ 크롭: {w}x{h} → {cropped.size[0]}x{cropped.size[1]}")
        return output_path
    except Exception as e:
        logger.warning(f"  크롭 실패 (원본 유지): {e}")
        return input_path


# ============================================================
# 통합 인터페이스
# ============================================================
def capture_route_image(origin, destination, mode="transit",
                        output_path=None, google_key=None,
                        selenium_driver=None, waypoints=None,
                        size="640x400", departure_time=None):
    """
    구글맵 경로 이미지 생성 (통합)

    Parameters:
        origin: (lat, lon) 출발지
        destination: (lat, lon) 도착지
        mode: "transit" | "driving" | "walking" | "bicycling"
        output_path: 저장 경로 (None이면 자동 생성)
        google_key: Google Maps API 키 (None이면 Selenium 사용)
        selenium_driver: 기존 Selenium 드라이버 (재활용)
        waypoints: [(lat, lon), ...] 중간 경유지
        size: Static Maps 이미지 크기
        departure_time: 출발 시간 (epoch int, EXIF 문자열, 또는 None)

    Returns:
        str: 생성된 이미지 파일 경로 (실패 시 None)
    """
    if output_path is None:
        output_path = f"route_{origin[0]:.4f}_{destination[0]:.4f}_{mode}.png"

    # departure_time 변환 (문자열 → epoch)
    dep_epoch = _parse_departure_time(departure_time)

    # 디렉토리 생성
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    dep_info = f" 출발:{departure_time}" if departure_time else ""
    logger.info(f"🗺️ 경로 이미지 생성: ({origin[0]:.4f},{origin[1]:.4f}) → ({destination[0]:.4f},{destination[1]:.4f}) [{mode}]{dep_info}")

    # 방법1: API 키가 있으면 Static Maps
    if google_key:
        logger.info("  📡 Static Maps API 사용")
        result = _static_maps_image(
            origin, destination, mode, output_path,
            google_key, waypoints, size,
            departure_time=dep_epoch)
        if result:
            return result
        logger.warning("  Static Maps 실패 → Selenium 폴백")

    # 방법2: Selenium 스크린샷
    logger.info("  🖥️ Selenium 스크린샷 사용")
    result = _selenium_screenshot(
        origin, destination, mode, output_path,
        driver=selenium_driver, close_driver=(selenium_driver is None),
        departure_time=dep_epoch)
    return result


def capture_route_images_batch(route_segments, output_dir="route_images",
                               google_key=None, selenium_driver=None):
    """
    여러 구간의 경로 이미지를 일괄 생성

    Parameters:
        route_segments: [
            {
                "from_name": "시부야 카페",
                "to_name": "아사쿠사 센소지",
                "origin": (35.6595, 139.7004),
                "destination": (35.7148, 139.7967),
                "mode": "transit",
            },
            ...
        ]

    Returns:
        dict: {"시부야 카페→아사쿠사 센소지": "route_images/route_001.png", ...}
    """
    os.makedirs(output_dir, exist_ok=True)
    results = {}

    # Selenium 사용 시 드라이버 하나로 재활용
    shared_driver = None
    if not google_key and selenium_driver is None:
        try:
            shared_driver = _create_headless_driver()
        except Exception as e:
            logger.warning(f"Selenium 드라이버 생성 실패: {e}")

    try:
        for idx, seg in enumerate(route_segments):
            from_name = seg.get("from_name", f"출발{idx}")
            to_name = seg.get("to_name", f"도착{idx}")
            route_key = f"{from_name}→{to_name}"

            output_path = os.path.join(output_dir, f"route_{idx+1:03d}_{from_name}_{to_name}.png")
            # 파일명 정리 (특수문자 제거)
            output_path = output_path.replace(" ", "_")
            for ch in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
                output_path = output_path.replace(ch, '_')

            result = capture_route_image(
                origin=seg["origin"],
                destination=seg["destination"],
                mode=seg.get("mode", "transit"),
                output_path=output_path,
                google_key=google_key,
                selenium_driver=shared_driver or selenium_driver,
            )

            if result:
                results[route_key] = result
            else:
                logger.warning(f"  ⚠️ {route_key} 경로 이미지 실패")

            time.sleep(1)  # API 레이트 리밋 방지

    finally:
        if shared_driver:
            try:
                shared_driver.quit()
            except:
                pass

    logger.info(f"🗺️ 경로 이미지 {len(results)}/{len(route_segments)}개 생성 완료")
    return results


# ============================================================
# 테스트
# ============================================================
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # 테스트 구간
    segments = [
        {
            "from_name": "시부야 카페",
            "to_name": "아사쿠사 센소지",
            "origin": (35.6595, 139.7004),
            "destination": (35.7148, 139.7967),
            "mode": "transit",
        },
        {
            "from_name": "아사쿠사 센소지",
            "to_name": "츠키지 시장",
            "origin": (35.7148, 139.7967),
            "destination": (35.6654, 139.7707),
            "mode": "transit",
        },
    ]

    google_key = os.environ.get("GOOGLE_MAPS_API_KEY")

    if google_key:
        print(f"✅ API 키 있음 → Static Maps 사용")
    else:
        print(f"ℹ️ API 키 없음 → Selenium 스크린샷")

    results = capture_route_images_batch(segments, google_key=google_key)
    for k, v in results.items():
        print(f"  {k}: {v}")
