"""
네이버 블로그 자동 업로드 테스트 스크립트 v6
=============================================
[v6 — 발행 설정 + 태그 개선 + 제목 중복 수정]
  발행 옵션: --visibility public|private|neighbor
  예약발행: --schedule "2025-03-15 10:00"
  태그: 에디터 + 발행 다이얼로그 양쪽에서 시도
  제목: 입력 후 Enter로 본문 분리

[사용법]
  pip install selenium pyperclip pywin32 Pillow python-dotenv
  python test_naver_upload.py --test                             # 임시저장
  python test_naver_upload.py --test --publish                   # 전체공개 발행
  python test_naver_upload.py --test --publish --visibility private  # 비공개 발행
  python test_naver_upload.py --test --publish --schedule "2025-03-15 10:00"  # 예약
"""

import os, sys, time, io, logging, argparse
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/naver_upload.log", encoding="utf-8", mode="a")
    ]
)
logger = logging.getLogger(__name__)

DEBUG_DIR = Path("logs/debug")
DEBUG_DIR.mkdir(parents=True, exist_ok=True)

SELENIUM_PROFILE_DIR = Path("selenium_profile")
SELENIUM_PROFILE_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# .env
# ============================================================
def load_env():
    try:
        from dotenv import load_dotenv
        for p in [Path(".env"), Path("../.env")]:
            if p.exists():
                load_dotenv(p); logger.info(f"  .env: {p.resolve()}"); return
        load_dotenv()
    except ImportError:
        logger.warning("pip install python-dotenv")


# ============================================================
# 클립보드 (win32clipboard 직접)
# ============================================================
def clipboard_set_image(image_path):
    """이미지 → 클립보드 CF_DIB"""
    import win32clipboard
    from PIL import Image

    img = Image.open(image_path)
    max_dim = 1920
    if max(img.size) > max_dim:
        ratio = max_dim / max(img.size)
        img = img.resize((int(img.size[0]*ratio), int(img.size[1]*ratio)), Image.LANCZOS)

    output = io.BytesIO()
    img.convert("RGB").save(output, "BMP")
    bmp_data = output.getvalue()[14:]

    win32clipboard.OpenClipboard()
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardData(win32clipboard.CF_DIB, bmp_data)
    win32clipboard.CloseClipboard()
    logger.info(f"    📋 이미지→클립보드: {Path(image_path).name} ({len(bmp_data)//1024}KB)")


def clipboard_set_text(text):
    """텍스트 → 클립보드 CF_UNICODETEXT"""
    import win32clipboard
    win32clipboard.OpenClipboard()
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
    win32clipboard.CloseClipboard()


# ============================================================
# 테스트 데이터
# ============================================================
def find_test_images():
    search_dirs = [Path("logs/debug"), Path("test_images"), Path(".")]
    exts = ("*.png", "*.jpg", "*.jpeg")
    found = []
    for d in search_dirs:
        if d.exists():
            for ext in exts:
                found.extend(sorted(d.glob(ext)))
        if len(found) >= 3:
            break
    if not found:
        return create_dummy_images()
    result = [str(f) for f in found[:3]]
    logger.info(f"  테스트 이미지 {len(result)}장: {[Path(p).name for p in result]}")
    return result


def create_dummy_images():
    from PIL import Image, ImageDraw, ImageFont
    test_dir = Path("test_images"); test_dir.mkdir(exist_ok=True)
    images = []
    for i, (c, t) in enumerate([("#2196F3","Cafe"),("#4CAF50","Temple"),("#FF9800","Food")]):
        p = test_dir / f"test_{i+1}.jpg"
        img = Image.new("RGB", (800, 600), c)
        d = ImageDraw.Draw(img)
        try: font = ImageFont.truetype("arial.ttf", 40)
        except: font = ImageFont.load_default()
        d.text((250, 260), f"Photo {i+1}: {t}", fill="white", font=font)
        img.save(str(p), quality=85)
        images.append(str(p))
    return images


def generate_test_data():
    """
    실제 core.py가 생성하는 것과 동일한 구조의 테스트 데이터:
    - region-intro (지역소개)
    - course-line (코스라인)
    - 장소별: h2 소제목 + 본문 + 사진 + 구글맵 지도 링크
    - 장소→장소 이동 경로 카드 (거리/시간/이동수단)
    - travel-tips (여행 꿀팁)
    - outro (마무리)
    - 구분선, 볼드 등 실전 서식
    """
    images = find_test_images()

    blocks = []

    # ── 1) 지역 소개 (제목과 중복되지 않게) ──
    blocks.append({"type": "text", "content": (
        "도쿄는 전통과 현대가 공존하는 매력적인 도시입니다.\n"
        "이번 여행에서는 시부야, 아사쿠사, 츠키지를 돌아보며\n"
        "도쿄의 다양한 매력을 느껴봤어요."
    )})

    # ── 2) 코스 라인 ──
    blocks.append({"type": "text", "content": (
        "📍 여행 코스\n"
        "시부야 카페 → 아사쿠사 센소지 → 츠키지 시장"
    )})

    # ── 3) 구분선 ──
    blocks.append({"type": "text", "content": "━━━━━━━━━━━━━━━━━━━━"})

    # ── 4) 장소 1: 시부야 카페 ──
    blocks.append({"type": "text", "content": (
        "☕ 시부야 카페 (渋谷カフェ)\n\n"
        "첫 번째로 방문한 곳은 시부야의 작은 카페였어요.\n"
        "따뜻한 라떼 한 잔으로 여행의 시작을 알렸습니다.\n\n"
        "시부야 스크램블 교차로가 한눈에 내려다보이는 2층 창가석에 앉았는데,\n"
        "사람들이 물결처럼 오가는 모습이 정말 인상적이었어요.\n\n"
        "카페 라떼는 진한 에스프레소에 부드러운 우유 거품이 올라가\n"
        "한 모금 마시면 여행의 피로가 싹 풀리는 맛이었습니다."
    )})
    if len(images) >= 1:
        blocks.append({"type": "image", "path": images[0]})
    # 구글맵 링크 (place 형태 - 네이버 미리보기 지원)
    blocks.append({"type": "text", "content": (
        "📍 위치: 도쿄 시부야구\n"
        "🔗 구글 지도에서 보기:\n"
        "https://www.google.com/maps/place/35.6595,139.7004/@35.6595,139.7004,16z"
    )})

    # ── 5) 이동 경로 카드 (시부야 → 아사쿠사) ──
    blocks.append({"type": "route", "content": (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🚌 이동  시부야 카페 → 아사쿠사 센소지\n\n"
        "📏 12.5km  ⏱️ 약 35분 (대중교통)\n\n"
        "🚶 시부야역 → 긴자선 탑승\n"
        "🚌 긴자선 → 아사쿠사역 (30분)\n"
        "🚶 아사쿠사역 → 센소지 (도보 5분)"
    ), "origin": (35.6595, 139.7004), "destination": (35.7148, 139.7967),
       "mode": "transit",
       "departure_time": "2024:11:15 10:30:00",  # 사진 EXIF 시간 (테스트용)
       "link_text": "📍 구글맵에서 대중교통 경로 상세 보기 →",
       "link_url": "https://www.google.com/maps/dir/35.6595,139.7004/35.7148,139.7967/data=!4m2!4m1!3e3"
    })

    # ── 6) 장소 2: 아사쿠사 센소지 ──
    blocks.append({"type": "text", "content": (
        "⛩️ 아사쿠사 센소지 (浅草寺)\n\n"
        "두 번째 장소는 도쿄에서 가장 오래된 절, 센소지입니다.\n"
        "카미나리몬(雷門)의 거대한 빨간 등불 앞에서 기념사진을 찍었어요.\n\n"
        "나카미세 거리를 걸으며 센베이와 닌교야키도 맛봤는데,\n"
        "바삭한 센베이의 간장 향이 코끝을 자극했습니다.\n\n"
        "본당까지 이어지는 길에는 관광객과 현지인이 어우러져\n"
        "활기찬 분위기가 느껴졌어요."
    )})
    if len(images) >= 2:
        blocks.append({"type": "image", "path": images[1]})
    blocks.append({"type": "text", "content": (
        "📍 위치: 도쿄 타이토구 아사쿠사\n"
        "🔗 구글 지도에서 보기:\n"
        "https://www.google.com/maps/place/35.7148,139.7967/@35.7148,139.7967,16z"
    )})

    # ── 7) 이동 경로 카드 (아사쿠사 → 츠키지) ──
    blocks.append({"type": "route", "content": (
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🚌 이동  아사쿠사 센소지 → 츠키지 시장\n\n"
        "📏 5.2km  ⏱️ 약 20분 (대중교통)\n\n"
        "🚶 아사쿠사역 → 도에이 아사쿠사선 탑승\n"
        "🚌 히가시긴자역 하차 (15분)\n"
        "🚶 히가시긴자역 → 츠키지 시장 (도보 5분)"
    ), "origin": (35.7148, 139.7967), "destination": (35.6654, 139.7707),
       "mode": "transit",
       "departure_time": "2024:11:15 13:00:00",  # 사진 EXIF 시간 (테스트용)
       "link_text": "📍 구글맵에서 대중교통 경로 상세 보기 →",
       "link_url": "https://www.google.com/maps/dir/35.7148,139.7967/35.6654,139.7707/data=!4m2!4m1!3e3"
    })

    # ── 8) 장소 3: 츠키지 시장 ──
    blocks.append({"type": "text", "content": (
        "🍣 츠키지 시장 (築地市場)\n\n"
        "마지막으로 들른 곳은 츠키지 시장이에요.\n"
        "신선한 해산물 덮밥이 정말 일품이었습니다!\n\n"
        "참치 대뱃살 덮밥을 주문했는데,\n"
        "입에 넣는 순간 살살 녹는 식감이 잊을 수 없었어요.\n\n"
        "시장 골목을 누비며 다마고야키, 호타테구이 등\n"
        "다양한 길거리 음식도 즐겼습니다."
    )})
    if len(images) >= 3:
        blocks.append({"type": "image", "path": images[2]})
    blocks.append({"type": "text", "content": (
        "📍 위치: 도쿄 주오구 츠키지\n"
        "🔗 구글 지도에서 보기:\n"
        "https://www.google.com/maps/place/35.6654,139.7707/@35.6654,139.7707,16z"
    )})

    # ── 9) 구분선 ──
    blocks.append({"type": "text", "content": "━━━━━━━━━━━━━━━━━━━━"})

    # ── 10) 여행 꿀팁 ──
    blocks.append({"type": "text", "content": (
        "🚆 여행 꿀팁!\n\n"
        "1. 도쿄 메트로 24시간권(600엔)을 구매하면 교통비를 아낄 수 있어요.\n"
        "2. 센소지는 오전 6시부터 개방되니 이른 아침에 방문하면 한적해요.\n"
        "3. 츠키지 시장은 점심 전에 가야 줄이 짧습니다.\n"
        "4. 시부야 스크램블 교차로는 스타벅스 2층에서 내려다보는 게 포인트!\n"
        "5. 현금을 넉넉히 준비하세요. 시장 노점은 카드 결제가 안 되는 곳이 많아요."
    )})

    # ── 11) 마무리 ──
    blocks.append({"type": "text", "content": (
        "다음에 또 오고 싶은 도쿄, 꼭 다시 올게요! ✈️\n\n"
        "도쿄 여행이 처음이신 분들에게 이 코스를 강력 추천합니다.\n"
        "전통과 미식, 그리고 도시의 활기를 한 번에 느낄 수 있거든요.\n\n"
        "궁금한 점이 있으시면 댓글로 남겨주세요! 😊"
    )})

    return {
        "title": "[테스트] 도쿄 2박3일 여행기 ☕⛩️🍣 시부야·아사쿠사·츠키지 완벽 코스",
        "blocks": blocks,
        "tags": ["도쿄여행", "일본여행", "도쿄카페", "센소지", "츠키지시장",
                 "시부야", "도쿄맛집", "일본2박3일", "도쿄여행코스", "아사쿠사"]
    }


# ============================================================
# Chrome 드라이버
# ============================================================
def create_driver():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    opts = Options()
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )
    profile_path = str(SELENIUM_PROFILE_DIR.resolve())
    opts.add_argument(f"--user-data-dir={profile_path}")
    logger.info(f"  프로필: {profile_path}")

    driver = webdriver.Chrome(options=opts)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
    })
    return driver


def ss(driver, name):
    try:
        p = DEBUG_DIR / f"naver_{name}_{int(time.time())}.png"
        driver.save_screenshot(str(p))
        logger.info(f"  📸 {p.name}")
    except: pass


# ============================================================
# 네이버 로그인
# ============================================================
def naver_login(driver):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    import pyperclip

    nid = os.environ.get("NAVER_USERNAME", "")
    npw = os.environ.get("NAVER_PASSWORD", "")
    if not nid or not npw:
        logger.error("❌ .env에 NAVER_USERNAME/NAVER_PASSWORD 없음")
        return False

    logger.info(f"  🔑 로그인: {nid[:3]}***")
    driver.get("https://nid.naver.com/nidlogin.login")
    time.sleep(2)

    try:
        el = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#id")))
        el.click(); time.sleep(0.5)
        pyperclip.copy(nid)
        el.send_keys(Keys.CONTROL, 'v'); time.sleep(1)

        pw = driver.find_element(By.CSS_SELECTOR, "#pw")
        pw.click(); time.sleep(0.5)
        pyperclip.copy(npw)
        pw.send_keys(Keys.CONTROL, 'v'); time.sleep(1)

        for s in ["#log\\.login", ".btn_login", "#btn_login",
                   ".btn_global[type='submit']"]:
            try: driver.find_element(By.CSS_SELECTOR, s).click(); break
            except: continue
        time.sleep(3)

        url = driver.current_url
        if "captcha" in url or "2step" in url or "nidlogin" in url:
            ss(driver, "need_manual")
            logger.warning("\n" + "="*50)
            logger.warning("  ⚠️ 캡차/2단계 인증 → 브라우저에서 직접 완료 (90초)")
            logger.warning("="*50)
            time.sleep(90)

        driver.get("https://www.naver.com"); time.sleep(2)
        if "nidlogin" not in driver.current_url:
            logger.info("  ✅ 로그인 성공!")
            return True
        logger.error("  ❌ 로그인 실패"); return False
    except Exception as e:
        logger.error(f"  ❌ {e}"); return False


def is_logged_in(driver):
    driver.get("https://blog.naver.com/GoBlogWrite.naver")
    time.sleep(4)
    return "nidlogin" not in driver.current_url and "login" not in driver.current_url


# ============================================================
# 팝업: "작성 중인 글이 있습니다"
# ============================================================
def close_draft_popup(driver):
    """mainFrame 내부에서 팝업 닫기"""
    logger.info("  🔧 팝업 확인...")
    result = driver.execute_script("""
        var buttons = document.querySelectorAll('button');
        for (var i = 0; i < buttons.length; i++) {
            var txt = buttons[i].textContent.trim();
            if (txt === '취소' || txt.indexOf('새로') >= 0) {
                buttons[i].click();
                return 'closed:' + txt;
            }
        }
        var popup = document.querySelector('.se-popup-wrap');
        if (popup && popup.offsetParent !== null) {
            var btns = popup.querySelectorAll('button');
            if (btns.length > 0) { btns[0].click(); return 'closed:popup-btn'; }
        }
        return 'none';
    """)
    if result and 'closed' in str(result):
        logger.info(f"    ✅ 팝업 닫음: {result}")
        time.sleep(1.5)
    else:
        logger.info(f"    ℹ️ 팝업 없음")
    time.sleep(0.5)


# ============================================================
# ★ 제목 입력 — __se-node span
# ============================================================
def input_title(driver, title):
    """
    실제 구조 (콘솔 확인):
    <div class="se-title-text se-is-empty">
      <p class="se-text-paragraph">
        <span class="__se-node"></span>
        <span class="se-placeholder">제목</span>
      </p>
    </div>
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    logger.info(f"\n📝 제목: {title[:40]}...")

    # Step 1: __se-node를 클릭해서 포커스
    try:
        se_node = driver.find_element(By.CSS_SELECTOR, ".se-title-text .__se-node")
        se_node.click()
        time.sleep(0.5)
        logger.info("  ✅ __se-node 클릭")
    except Exception as e:
        logger.warning(f"  __se-node 클릭 실패: {e}")
        # 폴백: 제목 영역 자체 클릭
        try:
            title_area = driver.find_element(By.CSS_SELECTOR, ".se-title-text")
            title_area.click()
            time.sleep(0.5)
        except:
            logger.error("  ❌ 제목 영역 못 찾음")
            return False

    # Step 2: 클립보드로 제목 붙여넣기
    clipboard_set_text(title)
    time.sleep(0.3)

    try:
        # 현재 포커스된 요소에 Ctrl+V
        active = driver.switch_to.active_element
        active.send_keys(Keys.CONTROL, 'v')
        time.sleep(0.5)
    except:
        # 폴백: ActionChains
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(driver).key_down(Keys.CONTROL).send_keys('v') \
            .key_up(Keys.CONTROL).perform()
        time.sleep(0.5)

    # Step 3: 확인 — 제목이 입력되었는지
    result = driver.execute_script("""
        var node = document.querySelector('.se-title-text .__se-node');
        if (node) return node.textContent;
        var para = document.querySelector('.se-title-text .se-text-paragraph');
        if (para) return para.textContent;
        return '';
    """)

    if result and len(result.strip()) > 0:
        logger.info(f"  ✅ 제목 입력 확인: '{result[:30]}...'")
        # ★ 제목 입력 후 본문으로 확실히 이동 (Enter → Tab)
        try:
            active = driver.switch_to.active_element
            active.send_keys(Keys.ENTER)
            time.sleep(0.3)
        except:
            pass
        return True

    # Step 4: 클립보드 실패 시 → JS 직접 삽입 + 에디터 동기화
    logger.info("  클립보드 실패 → JS 직접 삽입...")
    result = driver.execute_script("""
        var title = arguments[0];
        var titleModule = document.querySelector('.se-title-text');
        if (!titleModule) return 'ERR:no-module';

        var seNode = titleModule.querySelector('.__se-node');
        if (!seNode) return 'ERR:no-node';

        // 텍스트 삽입
        seNode.textContent = title;
        // se-is-empty 제거
        titleModule.classList.remove('se-is-empty');
        // placeholder 숨기기
        var ph = titleModule.querySelector('.se-placeholder, .__se_placeholder');
        if (ph) ph.style.display = 'none';
        // 이벤트
        var p = titleModule.querySelector('.se-text-paragraph');
        if (p) {
            p.dispatchEvent(new Event('input', {bubbles:true}));
            p.dispatchEvent(new Event('keyup', {bubbles:true}));
        }
        return 'OK:' + seNode.textContent.substring(0, 20);
    """, title)

    logger.info(f"  JS 결과: {result}")
    if result and result.startswith('OK'):
        logger.info(f"  ✅ 제목 JS 입력 성공")
        return True

    logger.error("  ❌ 제목 입력 실패")
    return False


# ============================================================
# 본문 포커스
# ============================================================
def focus_body(driver):
    """본문 편집 영역에 포커스 (제목 아래)"""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    result = driver.execute_script("""
        // 제목이 아닌 첫 번째 se-text-paragraph 찾기
        var paras = document.querySelectorAll('.se-text-paragraph');
        for (var i = 0; i < paras.length; i++) {
            if (!paras[i].closest('.se-title-text')) {
                paras[i].click();
                paras[i].focus();
                return 'OK:para-' + i;
            }
        }
        // 못 찾으면 se-content 클릭
        var c = document.querySelector('.se-content, .se-main-container');
        if (c) { c.click(); return 'OK:container'; }
        return 'FAIL';
    """)
    logger.info(f"  본문 포커스: {result}")

    if result and 'FAIL' in result:
        # 제목에서 Tab으로 이동
        try:
            el = driver.find_element(By.CSS_SELECTOR, ".se-title-text")
            el.click(); time.sleep(0.3)
            el.send_keys(Keys.TAB); time.sleep(0.5)
        except:
            pass

    time.sleep(0.3)


# ============================================================
# 텍스트/이미지 삽입
# ============================================================
def paste_text(driver, text):
    """텍스트 붙여넣기"""
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.action_chains import ActionChains

    actions = ActionChains(driver)
    for line in text.split('\n'):
        if line.strip():
            clipboard_set_text(line.strip())
            time.sleep(0.15)
            actions.key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
            time.sleep(0.2)
        actions.send_keys(Keys.ENTER).perform()
        time.sleep(0.1)
    actions.send_keys(Keys.ENTER).perform()
    time.sleep(0.2)


def paste_image(driver, image_path):
    """이미지 클립보드 붙여넣기"""
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.action_chains import ActionChains

    if not os.path.exists(image_path):
        logger.warning(f"    ⚠️ 없음: {image_path}")
        return False

    clipboard_set_image(image_path)
    time.sleep(0.5)

    # Ctrl+V
    actions = ActionChains(driver)
    actions.key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
    time.sleep(1)

    # 업로드 대기
    size_mb = os.path.getsize(image_path) / (1024 * 1024)
    wait = max(5, min(15, int(size_mb * 4) + 5))
    logger.info(f"    ⏳ 업로드 대기 {wait}초...")
    time.sleep(wait)

    # 이미지 삽입 확인
    try:
        cnt = driver.execute_script(
            "return document.querySelectorAll('.se-component.se-image, .se-image-resource, img[src*=\"postfiles\"]').length")
        logger.info(f"    이미지 요소 {cnt}개 감지")
    except:
        pass

    # 다음 줄
    actions.send_keys(Keys.ENTER).perform()
    time.sleep(0.5)
    return True


# ============================================================
# ★ 저장/발행 — mainFrame 내부 (콘솔 확인 결과)
# ============================================================
def save_or_publish(driver, publish=False, visibility="public", schedule=None, tags=None):
    """
    콘솔 확인 결과:
      저장: button.save_btn__bzc5B  (mainFrame 내부)
      발행: button.publish_btn__m9KHH (mainFrame 내부)

    visibility: "public" | "private" | "neighbor" (이웃공개)
    schedule: None (즉시) | "2025-03-15 10:00" (예약발행 시간)
    tags: 발행 다이얼로그 내 태그 재시도용
    """
    from selenium.webdriver.common.by import By

    # ★ 저장/발행 버튼은 mainFrame 내부!
    # (이전 v4에서 default_content로 전환했던 것이 실패 원인)
    # 현재 mainFrame에 있으면 그대로, 아니면 전환

    if not publish:
        # === 임시저장 ===
        logger.info("\n💾 임시저장...")

        # 1차: 정확한 클래스
        saved = False
        for sel in ["button.save_btn__bzc5B",
                     "button[data-click-area='tpb.save']",
                     "button[class*='save_btn']"]:
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                if el.is_displayed():
                    el.click()
                    logger.info(f"  ✅ 저장 클릭: {sel}")
                    saved = True
                    time.sleep(3)
                    break
            except:
                continue

        # 2차: JS로 텍스트 검색
        if not saved:
            result = driver.execute_script("""
                var buttons = document.querySelectorAll('button');
                for (var i = 0; i < buttons.length; i++) {
                    if (buttons[i].textContent.trim() === '저장') {
                        buttons[i].click();
                        return 'saved';
                    }
                }
                return 'not-found';
            """)
            logger.info(f"  JS 저장: {result}")
            if result == 'saved':
                saved = True
                time.sleep(3)

        # 3차: Ctrl+S
        if not saved:
            from selenium.webdriver.common.keys import Keys
            from selenium.webdriver.common.action_chains import ActionChains
            logger.info("  버튼 실패 → Ctrl+S...")
            ActionChains(driver).key_down(Keys.CONTROL).send_keys('s') \
                .key_up(Keys.CONTROL).perform()
            time.sleep(3)

        # 저장 확인 토스트/팝업 닫기
        try:
            driver.execute_script("""
                var btns = document.querySelectorAll('button');
                for (var i = 0; i < btns.length; i++) {
                    var t = btns[i].textContent.trim();
                    if (t === '확인' || t === 'OK') {
                        btns[i].click(); break;
                    }
                }
            """)
        except:
            pass
        time.sleep(1)

    else:
        # === 발행 ===
        logger.info("\n🚀 발행...")

        # ── Step 1: 발행 버튼 1차 클릭 (발행 설정 다이얼로그 열기) ──
        clicked = False
        for sel in ["button.publish_btn__m9KHH",
                     "button[data-click-area='tpb.publish']",
                     "button[class*='publish_btn']"]:
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                if el.is_displayed():
                    el.click()
                    logger.info(f"  ✅ 발행 1차 클릭 (다이얼로그 열기): {sel}")
                    clicked = True
                    time.sleep(3)
                    break
            except:
                continue

        if not clicked:
            result = driver.execute_script("""
                var buttons = document.querySelectorAll('button');
                for (var i = 0; i < buttons.length; i++) {
                    if (buttons[i].textContent.trim() === '발행') {
                        buttons[i].click(); return 'clicked';
                    }
                }
                return 'not-found';
            """)
            logger.info(f"  JS 발행 1차: {result}")
            time.sleep(3)

        ss(driver, "publish_dialog")

        # ── Step 2: 발행 다이얼로그 설정 ──

        # 2-A) 공개 설정
        visibility_map = {
            "public": "전체공개",
            "private": "비공개",
            "neighbor": "서로이웃공개",
            "이웃공개": "이웃공개",
        }
        target_label = visibility_map.get(visibility, "전체공개")
        logger.info(f"  📋 공개 설정: {target_label}")

        vis_result = driver.execute_script("""
            var targetText = arguments[0];

            // 1) input[type=radio] 직접 찾기 — 가장 확실
            var radios = document.querySelectorAll('input[type="radio"]');
            for (var i = 0; i < radios.length; i++) {
                var label = radios[i].closest('label') || radios[i].parentElement;
                if (label && label.textContent.indexOf(targetText) >= 0) {
                    radios[i].click();
                    return 'radio-click:' + label.textContent.trim().substring(0,20);
                }
            }

            // 2) label 텍스트 indexOf 매칭
            var labels = document.querySelectorAll('label');
            for (var i = 0; i < labels.length; i++) {
                if (labels[i].textContent.indexOf(targetText) >= 0) {
                    labels[i].click();
                    return 'label-click:' + labels[i].textContent.trim().substring(0,20);
                }
            }

            // 3) span/div textContent에서 찾기
            var elems = document.querySelectorAll('span, div');
            for (var i = 0; i < elems.length; i++) {
                var t = elems[i].textContent.trim();
                if (t === targetText && elems[i].offsetParent !== null) {
                    elems[i].click();
                    return 'elem-click:' + t;
                }
            }

            // 디버그: 모든 라디오 정보
            var debug = [];
            for (var i = 0; i < radios.length; i++) {
                var p = radios[i].parentElement;
                debug.push(p ? p.textContent.trim().substring(0,30) : '(no parent)');
            }
            return 'not-found:radios=' + debug.join('|');
        """, target_label)
        logger.info(f"  공개 설정 결과: {vis_result}")
        time.sleep(1)

        # 2-B) 발행 다이얼로그 내 태그 입력
        if tags:
            logger.info(f"  🏷️ 다이얼로그 태그 {len(tags)}개 입력...")
            from selenium.webdriver.common.keys import Keys

            # 태그 편집 영역 찾기 — 여러 셀렉터 시도
            tag_result = driver.execute_script("""
                // 1) input placeholder
                var inputs = document.querySelectorAll('input');
                for (var i = 0; i < inputs.length; i++) {
                    var ph = (inputs[i].placeholder || '').toLowerCase();
                    if (ph.indexOf('태그') >= 0 || ph.indexOf('tag') >= 0) {
                        inputs[i].scrollIntoView({block:'center'});
                        inputs[i].click();
                        inputs[i].focus();
                        return 'input:' + (inputs[i].placeholder || '').substring(0,30);
                    }
                }
                // 2) "태그 편집" 레이블 옆 영역
                var labels = document.querySelectorAll('label, span, div, dt, th');
                for (var i = 0; i < labels.length; i++) {
                    if (labels[i].textContent.trim().indexOf('태그') >= 0) {
                        var container = labels[i].closest('div, tr, dl');
                        if (container) {
                            var inp = container.querySelector('input, textarea, [contenteditable]');
                            if (inp) {
                                inp.scrollIntoView({block:'center'});
                                inp.click();
                                inp.focus();
                                return 'label-adj:' + labels[i].textContent.trim().substring(0,20);
                            }
                        }
                    }
                }
                // 3) contenteditable 태그 영역
                var editables = document.querySelectorAll('[contenteditable="true"]');
                for (var i = 0; i < editables.length; i++) {
                    if (editables[i].textContent.indexOf('#') >= 0 ||
                        editables[i].className.indexOf('tag') >= 0) {
                        editables[i].scrollIntoView({block:'center'});
                        editables[i].click();
                        editables[i].focus();
                        return 'editable:tag';
                    }
                }
                return 'not-found';
            """)
            logger.info(f"    태그란: {tag_result}")

            if 'not-found' not in str(tag_result):
                time.sleep(0.3)
                active = driver.switch_to.active_element
                for t in tags[:10]:
                    clipboard_set_text(t)
                    active.send_keys(Keys.CONTROL, 'v')
                    time.sleep(0.2)
                    active.send_keys(Keys.ENTER)
                    time.sleep(0.3)
                logger.info(f"    ✅ 다이얼로그 태그 {len(tags[:10])}개 입력")
            else:
                logger.warning("    ⚠️ 태그 입력란 못 찾음")

        # 2-C) 예약 발행 설정
        if schedule:
            logger.info(f"  📅 예약발행: {schedule}")
            # "예약" 라디오 클릭
            driver.execute_script("""
                var labels = document.querySelectorAll('label, span, div');
                for (var i = 0; i < labels.length; i++) {
                    if (labels[i].textContent.trim() === '예약') {
                        labels[i].click();
                        return 'clicked';
                    }
                }
            """)
            time.sleep(1)

            # 예약 시간 입력 (날짜/시간 필드)
            from selenium.webdriver.common.keys import Keys
            schedule_inputs = driver.find_elements(
                By.CSS_SELECTOR, "input[type='text'], input[type='date'], input[type='time']")
            for inp in schedule_inputs:
                try:
                    ph = inp.get_attribute("placeholder") or ""
                    val = inp.get_attribute("value") or ""
                    if "날짜" in ph or "date" in ph.lower() or "-" in val:
                        # 날짜 부분
                        date_part = schedule.split(" ")[0] if " " in schedule else schedule
                        inp.clear(); inp.send_keys(date_part)
                        logger.info(f"    날짜: {date_part}")
                    elif "시" in ph or "time" in ph.lower() or ":" in val:
                        # 시간 부분
                        time_part = schedule.split(" ")[1] if " " in schedule else "10:00"
                        inp.clear(); inp.send_keys(time_part)
                        logger.info(f"    시간: {time_part}")
                except:
                    continue
            time.sleep(0.5)

        time.sleep(1)
        ss(driver, "publish_settings")

        # ── Step 3: 최종 "발행" 확인 버튼 클릭 ──
        #   콘솔 확인: button.confirm_btn__WEaBq (data-testid="seOnePublishBtn")
        #   위치: mainFrame 내부

        confirmed = False

        # 1차: 정확한 셀렉터
        for sel in ["button.confirm_btn__WEaBq",
                     "button[data-testid='seOnePublishBtn']",
                     "button[data-click-area='tpb*i.publish']",
                     "button[class*='confirm_btn']"]:
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                if el.is_displayed():
                    el.click()
                    logger.info(f"  ✅ 발행 확인 클릭: {sel}")
                    confirmed = True
                    time.sleep(3)
                    break
            except:
                continue

        # 2차: JS 폴백
        if not confirmed:
            result = driver.execute_script("""
                // seOnePublishBtn 찾기
                var btn = document.querySelector('[data-testid="seOnePublishBtn"]');
                if (btn) { btn.click(); return 'confirmed:testid'; }
                // confirm_btn 클래스 찾기
                btn = document.querySelector('button[class*="confirm_btn"]');
                if (btn && btn.offsetParent !== null) { btn.click(); return 'confirmed:class'; }
                // 텍스트 "발행" 중 마지막 것 (다이얼로그 버튼)
                var buttons = document.querySelectorAll('button');
                var last = null;
                for (var i = 0; i < buttons.length; i++) {
                    if (buttons[i].textContent.trim() === '발행' && buttons[i].offsetParent !== null)
                        last = buttons[i];
                }
                if (last) { last.click(); return 'confirmed:last-publish'; }
                return 'not-found';
            """)
            logger.info(f"  JS 발행 확인: {result}")
            if 'confirmed' in str(result):
                confirmed = True
                time.sleep(3)

        if confirmed:
            logger.info("  ✅ 발행 완료!")
        else:
            logger.warning("  ⚠️ 발행 확인 버튼 못 찾음 — 수동 확인 필요")

        time.sleep(3)

    return True


# ============================================================
# 메인 업로드 로직
# ============================================================
def upload_to_naver(post_data, save_only=True, visibility="public", schedule=None):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC

    title = post_data["title"]
    blocks = post_data["blocks"]
    tags = post_data.get("tags", [])

    t_cnt = sum(1 for b in blocks if b['type'] == 'text')
    i_cnt = sum(1 for b in blocks if b['type'] == 'image')
    r_cnt = sum(1 for b in blocks if b['type'] == 'route')
    logger.info("=" * 60)
    logger.info(f"🚀 업로드: {title}")
    logger.info(f"  블록 {len(blocks)}개 (텍스트 {t_cnt}, 이미지 {i_cnt}, 경로 {r_cnt})")
    logger.info("=" * 60)

    # ── 경로 이미지 사전 생성 ──
    route_images = {}
    if r_cnt > 0:
        logger.info(f"\n🗺️ 경로 이미지 {r_cnt}개 사전 생성...")
        try:
            from route_map_capture import capture_route_image
            google_key = os.environ.get("GOOGLE_MAPS_API_KEY")
            route_img_dir = str(DEBUG_DIR / "route_images")
            os.makedirs(route_img_dir, exist_ok=True)

            for idx, block in enumerate(blocks):
                if block["type"] != "route":
                    continue
                origin = block.get("origin")
                destination = block.get("destination")
                mode = block.get("mode", "transit")
                if not origin or not destination:
                    continue

                img_path = os.path.join(route_img_dir,
                    f"route_{idx:03d}_{origin[0]:.4f}_{destination[0]:.4f}.png")
                result = capture_route_image(
                    origin=origin, destination=destination,
                    mode=mode, output_path=img_path,
                    google_key=google_key,
                    departure_time=block.get("departure_time"))
                if result:
                    route_images[idx] = result
                    logger.info(f"  ✅ 경로 {idx}: {result}")
                else:
                    logger.warning(f"  ⚠️ 경로 {idx}: 이미지 생성 실패")
        except ImportError:
            logger.warning("  ⚠️ route_map_capture 모듈 없음 → 경로 이미지 생략")
        except Exception as e:
            logger.warning(f"  ⚠️ 경로 이미지 생성 오류: {e}")

    driver = create_driver()

    try:
        # ── 로그인 ──
        logger.info("\n🔐 로그인 확인...")
        if is_logged_in(driver):
            logger.info("  ✅ 이미 로그인됨")
        else:
            if not naver_login(driver):
                return {"success": False, "reason": "로그인 실패"}
            driver.get("https://blog.naver.com/GoBlogWrite.naver")
            time.sleep(5)

        # ── iframe ──
        try:
            WebDriverWait(driver, 15).until(
                EC.frame_to_be_available_and_switch_to_it((By.ID, 'mainFrame')))
            logger.info("  ✅ mainFrame")
        except:
            logger.info("  ℹ️ mainFrame 없음")
        time.sleep(3)
        ss(driver, "01_editor")

        # ── 팝업 ──
        close_draft_popup(driver)
        time.sleep(1)
        close_draft_popup(driver)
        time.sleep(1)
        ss(driver, "02_popup")

        # ── 제목 ──
        if not input_title(driver, title):
            ss(driver, "title_fail")
            return {"success": False, "reason": "제목 입력 실패"}
        ss(driver, "03_title")

        # ── 본문 ──
        logger.info("\n📄 본문 영역...")
        focus_body(driver)
        time.sleep(0.5)
        ss(driver, "04_body")

        # ── 블록 ──
        logger.info("\n📝 블록 삽입...")
        for i, block in enumerate(blocks):
            btype = block["type"]
            logger.info(f"\n  [{i+1}/{len(blocks)}] {btype.upper()}")

            if btype == "text":
                paste_text(driver, block["content"])
                logger.info(f"    ✅ 텍스트 ({len(block['content'])}자)")

            elif btype == "image":
                ok = paste_image(driver, block["path"])
                logger.info(f"    {'✅' if ok else '❌'} 이미지")
                ss(driver, f"05_img{i}")

            elif btype == "route":
                # 1) 경로 안내 텍스트
                paste_text(driver, block["content"])
                logger.info(f"    ✅ 경로 텍스트")

                # 2) 경로 이미지 (사전 생성된 것)
                route_img = route_images.get(i)
                if route_img and os.path.exists(route_img):
                    ok = paste_image(driver, route_img)
                    logger.info(f"    {'✅' if ok else '❌'} 경로 지도 이미지")
                    ss(driver, f"05_route{i}")

                # 3) 상세보기 링크
                link_text = block.get("link_text", "")
                link_url = block.get("link_url", "")
                if link_text and link_url:
                    paste_text(driver, f"{link_text}\n{link_url}")
                    logger.info(f"    ✅ 상세보기 링크")

        ss(driver, "06_done")

        # ── 태그: 발행 다이얼로그에서만 입력 (에디터 본문 오염 방지) ──
        # (이전: 에디터 하단에서 태그 입력 시도 → 본문에 텍스트로 들어가는 문제)
        logger.info(f"\n🏷️ 태그 {len(tags)}개 → 발행 다이얼로그에서 입력")

        ss(driver, "07_save")

        # ── ★ 저장/발행 (mainFrame 내부) ──
        save_or_publish(driver, publish=not save_only,
                        visibility=visibility, schedule=schedule, tags=tags)
        ss(driver, "08_final")

        logger.info("\n" + "=" * 60)
        logger.info("✅ 완료! 브라우저 확인")
        logger.info(f"  스크린샷: {DEBUG_DIR.resolve()}")
        logger.info("=" * 60)

        input("\n⏎ Enter → 브라우저 닫기...")
        return {"success": True}

    except Exception as e:
        ss(driver, "error")
        logger.error(f"\n❌ {e}", exc_info=True)
        input("\n⏎ Enter → 종료...")
        return {"success": False, "reason": str(e)}
    finally:
        try: driver.quit()
        except: pass


# ============================================================
# 메인
# ============================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--publish", action="store_true", help="발행 (기본: 임시저장)")
    parser.add_argument("--visibility", type=str, default="public",
                        choices=["public", "private", "neighbor"],
                        help="공개 설정: public(전체공개), private(비공개), neighbor(이웃공개)")
    parser.add_argument("--schedule", type=str, default=None,
                        help="예약발행 시간 (예: '2025-03-15 10:00'). 미지정시 즉시발행")
    args = parser.parse_args()

    vis_labels = {"public": "전체공개", "private": "비공개", "neighbor": "이웃공개"}

    print("""
╔══════════════════════════════════════════════════════╗
║  네이버 블로그 자동 업로드 v6 🚀                    ║
║                                                      ║
║  --publish              발행 (기본: 임시저장)        ║
║  --visibility public    전체공개 (기본)              ║
║  --visibility private   비공개                       ║
║  --visibility neighbor  이웃공개                     ║
║  --schedule "날짜 시간" 예약발행                     ║
╚══════════════════════════════════════════════════════╝
    """)

    load_env()
    nid = os.environ.get("NAVER_USERNAME", "")
    if not nid:
        print("❌ .env에 NAVER_USERNAME 없음!")
        return

    print(f"  계정: {nid[:3]}***")
    mode_str = "발행" if args.publish else "임시저장"
    if args.publish:
        mode_str += f" ({vis_labels.get(args.visibility, args.visibility)})"
        if args.schedule:
            mode_str += f" / 예약: {args.schedule}"
    print(f"  모드: {mode_str}")
    print()
    input("Enter로 시작...")

    post_data = generate_test_data()
    result = upload_to_naver(post_data, save_only=not args.publish,
                             visibility=args.visibility, schedule=args.schedule)
    print(f"\n{'✅ 성공' if result['success'] else '❌ 실패: ' + result.get('reason','')}")


if __name__ == "__main__":
    main()
