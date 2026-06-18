"""
TravelBlog Pro v2.2 - 블로그 발행 모듈
════════════════════════════════════════
방법 1 (기본/안전): 클립보드 복사 + 브라우저 자동 오픈
  - HTML을 클립보드에 복사 -> 사용자가 Ctrl+V로 붙여넣기
  - 계정 제재 위험 0%

방법 2 (Selenium): 기존 Chrome 프로필 재사용
  - 이미 로그인된 Chrome 프로필 활용 (로그인 과정 생략)
  - 주의: Chrome을 모두 닫은 상태에서만 작동
  - 주의: 네이버 자동화 탐지 위험 -> 개인 용도 한정
════════════════════════════════════════
"""
import os, time, re, logging, platform, webbrowser
from pathlib import Path

logger = logging.getLogger(__name__)
DEBUG_DIR = Path("logs/debug")
DEBUG_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# 유틸
# ============================================================
def _html_to_text(html):
    """HTML -> 순수 텍스트 (스마트에디터 붙여넣기용)"""
    t = re.sub(r'<h2[^>]*>(.*?)</h2>', r'\n\n# \1\n', html)
    t = re.sub(r'<h3[^>]*>(.*?)</h3>', r'\n## \1\n', t)
    t = re.sub(r'<p[^>]*>(.*?)</p>', r'\1\n\n', t)
    t = re.sub(r'<li[^>]*>(.*?)</li>', r'- \1\n', t)
    t = re.sub(r'<figure[^>]*>.*?</figure>', '', t, flags=re.DOTALL)
    t = re.sub(r'<br\s*/?>', '\n', t)
    t = re.sub(r'<[^>]+>', '', t)
    return re.sub(r'\n{3,}', '\n\n', t).strip()


def html_to_blocks(html_content, photos=None):
    """
    core.py HTML → 네이버 에디터용 blocks 리스트 변환

    전략: HTML을 순차 파싱하여 figure/img → image, 경로div → route, 나머지 → text
    사진 매칭: <img alt="장소명"> alt 텍스트 + 순서 기반
    """
    blocks = []
    if not html_content:
        return blocks

    import re as _re

    # 사진 매핑 준비: alt → file_path, 순서 인덱스 → file_path
    photo_paths = []
    photo_by_alt = {}  # alt키워드 → file_path
    if photos:
        for p in photos:
            fp = p.get("file_path", "")
            if fp:
                photo_paths.append(fp)
                # 장소명, 파일명으로 매핑
                loc = p.get("location_name", "")
                fn = p.get("file_name", "")
                if loc:
                    photo_by_alt[loc] = photo_by_alt.get(loc, [])
                    photo_by_alt[loc].append(fp)
                if fn:
                    photo_by_alt[fn] = [fp]

    # ── 특수 요소 위치 기록 ──
    special_ranges = []
    used_paths = set()

    def _match_photo(img_tag_text):
        """img 태그에서 alt 텍스트로 사진 매칭"""
        alt_m = _re.search(r'alt=["\']([^"\']*)["\']', img_tag_text)
        alt = alt_m.group(1) if alt_m else ""

        # alt 텍스트로 매칭
        if alt:
            for key, paths in photo_by_alt.items():
                if key in alt or alt in key:
                    for fp in paths:
                        if fp not in used_paths:
                            used_paths.add(fp)
                            return fp

        # 순서 기반 폴백
        for fp in photo_paths:
            if fp not in used_paths:
                used_paths.add(fp)
                return fp
        return None

    # 1) <figure>...<img>...</figure>
    for m in _re.finditer(
        r'<figure[^>]*>.*?</figure>',
        html_content, _re.DOTALL | _re.IGNORECASE):
        src_m = _re.search(r'src=["\']([^"\']+)["\']', m.group())
        if not src_m:
            continue
        src = src_m.group(1)
        path = None
        if 'data:image' in src or 'data:' in src or src.startswith('file:'):
            path = _match_photo(m.group())
        elif os.path.exists(src):
            path = src
            used_paths.add(src)
        if path:
            special_ranges.append((m.start(), m.end(),
                {"type": "image", "path": path}))

    # 2) 단독 <img> (figure 밖)
    for m in _re.finditer(
        r'<img[^>]*src=["\']([^"\']+)["\'][^>]*/?>',
        html_content, _re.IGNORECASE):
        if any(s <= m.start() < e for s, e, _ in special_ranges):
            continue
        src = m.group(1)
        path = None
        if 'data:image' in src or 'data:' in src or src.startswith('file:'):
            path = _match_photo(m.group())
        elif os.path.exists(src):
            path = src
            used_paths.add(src)
        if path:
            special_ranges.append((m.start(), m.end(),
                {"type": "image", "path": path}))

    # 3-1) 구분선 패턴 감지 (─ ─ ─ 또는 ━━━ 등)
    for m in _re.finditer(
        r'<p[^>]*>[\s]*[─━\-─]{2,}[\s─━\-─ ]*</p>',
        html_content, _re.DOTALL | _re.IGNORECASE):
        if not any(s <= m.start() < e for s, e, _ in special_ranges):
            special_ranges.append((m.start(), m.end(),
                {"type": "separator"}))

    # 3-2) 스타일 힌트 보존: PLACE N / TRAVEL TIPS 등 영문 라벨
    for m in _re.finditer(
        r'<p[^>]*style="[^"]*(?:letter-spacing|color:#8B9467)[^"]*"[^>]*>'
        r'(.*?)</p>',
        html_content, _re.DOTALL | _re.IGNORECASE):
        if not any(s <= m.start() < e for s, e, _ in special_ranges):
            inner = _re.sub(r'<[^>]+>', '', m.group(1)).strip()
            if inner and len(inner) < 50:
                # 짧은 스타일 라벨 → styled_label 블록
                # 스타일 속성 추출
                style_m = _re.search(r'style="([^"]*)"', m.group())
                style_str = style_m.group(1) if style_m else ""
                color_m = _re.search(r'color:\s*(#[0-9a-fA-F]{3,6})', style_str)
                color = color_m.group(1) if color_m else ""
                special_ranges.append((m.start(), m.end(),
                    {"type": "styled_label", "content": inner,
                     "color": color, "style": style_str}))

    # 3-3) h2 with data-place → heading 블록 (스타일 보존)
    for m in _re.finditer(
        r'<h2[^>]*data-place="([^"]*)"[^>]*(?:style="([^"]*)")?[^>]*>(.*?)</h2>',
        html_content, _re.DOTALL | _re.IGNORECASE):
        if not any(s <= m.start() < e for s, e, _ in special_ranges):
            place = m.group(1)
            style_str = m.group(2) or ""
            title_text = _re.sub(r'<[^>]+>', '', m.group(3)).strip()
            special_ranges.append((m.start(), m.end(),
                {"type": "heading", "content": title_text,
                 "place": place, "style": style_str}))
    # 3) 경로 카드 감지 (중첩 div 포함)
    #    패턴: <div style="background:linear-gradient...">..내부 div들..</div>
    for m in _re.finditer(
        r'<div[^>]*style="[^"]*(?:background|linear-gradient)[^"]*"[^>]*>'
        r'([\s\S]*?)</div>\s*(?:</div>)*\s*\n',
        html_content, _re.IGNORECASE):
        inner = m.group(1)
        if ('이동' in inner and '→' in inner and
            any(icon in inner for icon in ['🚶', '🚌', '🚗', '🚲'])):
            if any(s <= m.start() < e for s, e, _ in special_ranges):
                continue
            # 전체 경로 div를 잡기 위해 마지막 </div>까지 확장
            full_html = m.group()
            # 내부 div 개수 맞추기
            open_count = full_html.count('<div')
            close_count = full_html.count('</div>')
            if open_count > close_count:
                # 부족한 </div> 수만큼 뒤에서 더 찾기
                rest = html_content[m.end():]
                end_pos = m.end()
                needed = open_count - close_count
                for _ in range(needed):
                    idx = rest.find('</div>')
                    if idx >= 0:
                        end_pos += idx + len('</div>')
                        rest = html_content[end_pos:]
                    else:
                        break
                full_html = html_content[m.start():end_pos]
                special_ranges.append((m.start(), end_pos,
                    {"type": "_route_raw", "html": full_html}))
            else:
                special_ranges.append((m.start(), m.end(),
                    {"type": "_route_raw", "html": full_html}))

    # 4) iframe 지도 + 구글맵 링크 → map_link 블록으로 보존
    #    패턴: <div>...<iframe src="maps">...</iframe></div>\n<p>...<a href="maps">📍</a></p>
    for m in _re.finditer(
        r'<div[^>]*>.*?<iframe[^>]*src=["\']([^"\']*google\.com/maps[^"\']*)["\'][^>]*>'
        r'.*?</iframe>.*?</div>'
        r'(?:\s*<p[^>]*>\s*<a[^>]*href=["\']'
        r'(https://(?:www\.)?google\.com/maps[^"\']*)["\'][^>]*>.*?</a>\s*</p>)?',
        html_content, _re.DOTALL | _re.IGNORECASE):
        if any(s <= m.start() < e for s, e, _ in special_ranges):
            continue
        # 링크 URL 추출 (그룹2가 없으면 iframe src에서 좌표 추출)
        link_url = m.group(2) if m.group(2) else ""
        if not link_url:
            # iframe src에서 좌표 추출하여 링크 생성
            iframe_src = m.group(1)
            coord_m = _re.search(r'[?&]q=([0-9.-]+,[0-9.-]+)', iframe_src)
            if coord_m:
                link_url = f"https://www.google.com/maps?q={coord_m.group(1)}"
        if link_url:
            special_ranges.append((m.start(), m.end(),
                {"type": "map_link", "url": link_url,
                 "content": "📍 구글 지도에서 보기"}))
        else:
            special_ranges.append((m.start(), m.end(), {"type": "_skip"}))

    # 5) 단독 iframe (위에서 안 잡힌 것) → 제거
    for m in _re.finditer(
        r'<iframe[^>]*>.*?</iframe>',
        html_content, _re.DOTALL | _re.IGNORECASE):
        if not any(s <= m.start() < e for s, e, _ in special_ranges):
            special_ranges.append((m.start(), m.end(), {"type": "_skip"}))

    # 6) 구글맵 링크 단독 (<a href="google.com/maps">📍 ...</a>) → map_link
    for m in _re.finditer(
        r'<(?:p|a)[^>]*>(?:\s*<a[^>]*href=["\']'
        r'(https://(?:www\.)?google\.com/maps[^"\']*)["\'][^>]*>'
        r'(.*?)</a>\s*(?:</p>)?|'
        r'<a[^>]*href=["\']'
        r'(https://(?:www\.)?google\.com/maps[^"\']*)["\'][^>]*>'
        r'(.*?)</a>)',
        html_content, _re.DOTALL | _re.IGNORECASE):
        if any(s <= m.start() < e for s, e, _ in special_ranges):
            continue
        url = m.group(1) or m.group(3)
        txt = m.group(2) or m.group(4) or ""
        txt = _re.sub(r'<[^>]+>', '', txt).strip()
        if url:
            special_ranges.append((m.start(), m.end(),
                {"type": "map_link", "url": url,
                 "content": txt or "📍 구글 지도에서 보기"}))

    # 정렬
    special_ranges.sort(key=lambda x: x[0])

    # ── 순차 처리: 특수 요소 사이의 텍스트 → text 블록 ──
    pos = 0
    for start, end, block_data in special_ranges:
        if start > pos:
            text_html = html_content[pos:start]
            text = _html_to_text_with_links(text_html).strip()
            if text and len(text) > 2:
                blocks.append({"type": "text", "content": text})

        if block_data["type"] == "image":
            blocks.append(block_data)
        elif block_data["type"] == "map_link":
            blocks.append(block_data)
        elif block_data["type"] == "separator":
            blocks.append({"type": "separator"})
        elif block_data["type"] == "styled_label":
            blocks.append(block_data)
        elif block_data["type"] == "heading":
            blocks.append(block_data)
        elif block_data["type"] == "_route_raw":
            route_block = _parse_route_block(
                block_data["html"], html_content[end:end+500], photos)
            if route_block:
                blocks.append(route_block)
        pos = end

    # 마지막 텍스트
    if pos < len(html_content):
        text = _html_to_text_with_links(html_content[pos:]).strip()
        if text and len(text) > 2:
            blocks.append({"type": "text", "content": text})

    # ── 남은 사진 삽입 (매칭 안 된 것) ──
    remaining = [fp for fp in photo_paths if fp not in used_paths]
    if remaining and photos:
        # 장소명 기준으로 텍스트 블록 뒤에 삽입
        place_to_remaining = {}
        for p in photos:
            loc = p.get("location_name", "")
            fp = p.get("file_path", "")
            if loc and fp in remaining:
                place_to_remaining.setdefault(loc, []).append(fp)

        new_blocks = []
        inserted_extra = set()
        for b in blocks:
            new_blocks.append(b)
            if b["type"] == "text":
                for loc, fps in place_to_remaining.items():
                    if loc in b["content"]:
                        for fp in fps:
                            if fp not in inserted_extra:
                                new_blocks.append({"type": "image", "path": fp})
                                inserted_extra.add(fp)
        blocks = new_blocks

        # 최종 미매칭 → 끝에 추가
        for fp in remaining:
            if fp not in inserted_extra:
                blocks.append({"type": "image", "path": fp})

    logger.info(f"  HTML→blocks: {len(blocks)}개 "
                f"(텍스트 {sum(1 for b in blocks if b['type']=='text')}, "
                f"이미지 {sum(1 for b in blocks if b['type']=='image')}, "
                f"구분선 {sum(1 for b in blocks if b['type']=='separator')}, "
                f"제목 {sum(1 for b in blocks if b['type']=='heading')}, "
                f"라벨 {sum(1 for b in blocks if b['type']=='styled_label')}, "
                f"지도 {sum(1 for b in blocks if b['type']=='map_link')}, "
                f"경로 {sum(1 for b in blocks if b['type']=='route')})")
    return blocks


def _html_to_text_with_links(html):
    """HTML → 텍스트 변환 (네이버 에디터 최적화)
    - 구글맵 링크: map_link 블록에서 처리하므로 텍스트에서 완전 제거
    - 구분선: 별도 블록으로 처리하므로 제거
    - 스타일 라벨 (PLACE N, TRAVEL TIPS): 별도 블록으로 처리하므로 제거
    """
    t = html
    # 구글맵 링크 → 완전 제거 (map_link 블록에서 별도 처리)
    t = re.sub(
        r'<a[^>]*href=["\']https://(?:www\.)?google\.com/maps[^"\']*["\'][^>]*>'
        r'.*?</a>',
        '', t, flags=re.DOTALL | re.IGNORECASE)
    # "📍 구글 지도에서 보기" 등 잔여 텍스트도 제거
    t = re.sub(r'📍\s*구글\s*지도에서\s*보기', '', t)
    t = re.sub(r'📍\s*지도에서\s*보기', '', t)
    t = re.sub(r'📍\s*경로\s*보기\s*→?', '', t)
    # 구분선 텍스트 제거 (separator 블록으로 처리됨)
    t = re.sub(r'[─━]{2,}[\s─━ ]*', '', t)
    # 스타일 라벨 (letter-spacing 포함 p태그) 제거 (styled_label 블록으로 처리됨)
    t = re.sub(
        r'<p[^>]*style="[^"]*letter-spacing[^"]*"[^>]*>.*?</p>',
        '', t, flags=re.DOTALL | re.IGNORECASE)
    # h2 with data-place 제거 (heading 블록으로 처리됨)
    t = re.sub(
        r'<h2[^>]*data-place="[^"]*"[^>]*>.*?</h2>',
        '', t, flags=re.DOTALL | re.IGNORECASE)
    # 다른 <a> 태그는 텍스트만
    t = re.sub(r'<a[^>]*>(.*?)</a>', r'\1', t, flags=re.DOTALL)
    t = re.sub(r'<h2[^>]*>(.*?)</h2>', r'\n\n# \1\n', t)
    t = re.sub(r'<h3[^>]*>(.*?)</h3>', r'\n## \1\n', t)
    t = re.sub(r'<p[^>]*>(.*?)</p>', r'\1\n\n', t, flags=re.DOTALL)
    t = re.sub(r'<li[^>]*>(.*?)</li>', r'- \1\n', t, flags=re.DOTALL)
    t = re.sub(r'<ol[^>]*>(.*?)</ol>', r'\1', t, flags=re.DOTALL)
    t = re.sub(r'<ul[^>]*>(.*?)</ul>', r'\1', t, flags=re.DOTALL)
    t = re.sub(r'<br\s*/?>', '\n', t)
    t = re.sub(r'<[^>]+>', '', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    return t.strip()


def _parse_route_block(route_html, after_html, photos=None):
    """경로 div HTML → route 블록 변환"""
    content_text = _html_to_text_with_links(route_html)

    # GPS 좌표 추출
    coords = re.findall(r'(\d+\.\d{4,}),\s*(\d+\.\d{4,})', route_html + after_html)
    origin = None
    destination = None
    if len(coords) >= 2:
        origin = (float(coords[0][0]), float(coords[0][1]))
        destination = (float(coords[1][0]), float(coords[1][1]))

    # 경로 URL 추출
    dir_url_match = re.search(
        r'(https://www\.google\.com/maps/dir/[^\s<"\']+)',
        route_html + after_html)
    link_url = dir_url_match.group(1) if dir_url_match else ""

    # URL에서 좌표 (본문에 없으면)
    if not origin and link_url:
        url_coords = re.findall(r'(\d+\.\d{4,}),(\d+\.\d{4,})', link_url)
        if len(url_coords) >= 2:
            origin = (float(url_coords[0][0]), float(url_coords[0][1]))
            destination = (float(url_coords[1][0]), float(url_coords[1][1]))

    # departure_time
    dep_time = None
    if photos and origin:
        for p in photos:
            gps = p.get("gps")
            if gps and abs(gps.get("lat", 0) - origin[0]) < 0.01:
                dep_time = p.get("exif_date", "") or gps.get("date", "")
                if dep_time: break

    block = {
        "type": "route",
        "content": re.sub(r'https://\S+', '', content_text).strip(),
        "mode": "transit",
        "link_text": "📍 경로 보기 →",
        "link_url": link_url,
    }
    if origin: block["origin"] = origin
    if destination: block["destination"] = destination
    if dep_time: block["departure_time"] = dep_time
    return block


def _find_chrome_profile():
    """기존 Chrome 사용자 프로필 경로 찾기"""
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
    else:
        base = Path.home() / ".config" / "google-chrome"
    if base.exists():
        return str(base)
    return ""


# ============================================================
# 방법 1: 클립보드 + 브라우저 자동 오픈 (안전)
# ============================================================
class ClipboardPoster:
    """
    클립보드에 HTML 복사 -> 블로그 글쓰기 페이지 자동 오픈.
    사용자가 Ctrl+V (또는 Cmd+V)로 붙여넣으면 끝.
    """
    def __init__(self, platform_name):
        self.platform_name = platform_name  # "naver" or "tistory"

    def post(self, data, blog_name=""):
        title = data.get("title", "")
        content = data.get("content", "")
        tags = data.get("tags", [])

        # ── 1. 클립보드에 텍스트 복사 ──
        clipboard_text = self._build_clipboard_text(title, content, tags)
        clip_ok = False
        try:
            import pyperclip
            pyperclip.copy(clipboard_text)
            clip_ok = True
        except ImportError:
            try:
                import tkinter as tk
                r = tk.Tk(); r.withdraw()
                r.clipboard_clear()
                r.clipboard_append(clipboard_text)
                r.update(); r.destroy()
                clip_ok = True
            except:
                pass

        if not clip_ok:
            return {"success": False,
                    "reason": "클립보드 복사 실패 (pip install pyperclip)"}

        # ── 2. 글쓰기 페이지 브라우저로 열기 ──
        if self.platform_name == "naver":
            url = "https://blog.naver.com/GoBlogWrite.naver"
        elif self.platform_name == "tistory":
            url = (f"https://{blog_name}.tistory.com/manage/newpost"
                   if blog_name else "https://www.tistory.com/auth/login")
        else:
            url = ""
        if url:
            webbrowser.open(url)

        # ── 3. 태그 파일 저장 ──
        tag_dir = Path("posts"); tag_dir.mkdir(exist_ok=True)
        tag_file = tag_dir / f"tags_{int(time.time())}.txt"
        tag_file.write_text(", ".join(tags), encoding="utf-8")

        tag_preview = ", ".join(tags[:5])
        logger.info(f"[{self.platform_name}] 클립보드 복사 완료")
        return {
            "success": True, "url": url, "method": "clipboard",
            "message": (
                f"📋 본문이 클립보드에 복사되었습니다!\n"
                f"🌐 {self.platform_name} 글쓰기 페이지가 열렸습니다.\n\n"
                f"[발행 순서]\n"
                f"  ① 제목란에 제목 입력\n"
                f"  ② 본문 영역 클릭 후 Ctrl+V (Mac: Cmd+V)\n"
                f"  ③ 태그 입력: {tag_preview}\n"
                f"  ④ 발행 버튼 클릭\n\n"
                f"💡 태그 파일: {tag_file}"
            )
        }

    def _build_clipboard_text(self, title, content, tags):
        text = _html_to_text(content)
        tag_line = " ".join(f"#{t}" for t in tags[:10])
        return f"{text}\n\n{tag_line}"

    def close(self):
        pass


# ============================================================
# 방법 2: Selenium (기존 Chrome 프로필 재사용)
# ============================================================
class _SeleniumBase:
    """Selenium 공통 기반"""
    def __init__(self, platform_name):
        self.platform_name = platform_name
        self.driver = None

    def _init_driver(self):
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options

            o = Options()
            o.add_argument("--start-maximized")
            o.add_argument("--disable-blink-features=AutomationControlled")
            o.add_experimental_option("excludeSwitches", ["enable-automation"])
            o.add_experimental_option("useAutomationExtension", False)
            o.add_argument(
                "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            )
            # 기존 Chrome 프로필 재사용
            profile = _find_chrome_profile()
            if profile:
                o.add_argument(f"--user-data-dir={profile}")
                o.add_argument("--profile-directory=Default")
                logger.info(f"Chrome 프로필: {profile}")

            self.driver = webdriver.Chrome(options=o)
            self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            })
            return True
        except Exception as e:
            logger.error(f"[{self.platform_name}] WebDriver 실패: {e}")
            return False

    def _screenshot(self, name):
        try:
            p = DEBUG_DIR / f"{self.platform_name}_{name}_{int(time.time())}.png"
            self.driver.save_screenshot(str(p))
            logger.info(f"  스크린샷: {p}")
        except: pass

    def _ensure_driver(self):
        if self.driver:
            try:
                self.driver.current_url
                return True
            except:
                try: self.driver.quit()
                except: pass
                self.driver = None
        return self._init_driver()

    def _wait_login(self, check_url_part, write_url):
        """로그인 안 되어 있으면 사용자에게 60초 수동 로그인 요청"""
        if check_url_part in self.driver.current_url:
            logger.warning(f"[{self.platform_name}] 로그인 필요 - 60초 대기")
            self._screenshot("need_login")
            print(f"\n{'='*50}")
            print(f"  {self.platform_name} 로그인이 필요합니다!")
            print(f"  브라우저에서 직접 로그인해주세요 (60초)")
            print(f"{'='*50}\n")
            time.sleep(60)
            self.driver.get(write_url)
            time.sleep(4)

    def close(self):
        if self.driver:
            try: self.driver.quit()
            except: pass
            self.driver = None


class NaverSeleniumPoster(_SeleniumBase):
    """네이버 블로그 Selenium 발행 — v6 (test_naver_upload.py 검증 완료)
    win32clipboard 직접 제어, 이미지/경로 지도 삽입 지원
    """
    SELENIUM_PROFILE_DIR = Path("selenium_profile")

    def __init__(self):
        super().__init__("naver")

    def _init_driver(self):
        """selenium_profile/ 독립 프로필 사용 (기존 Chrome과 충돌 방지)"""
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options

            self.SELENIUM_PROFILE_DIR.mkdir(exist_ok=True)

            o = Options()
            o.add_argument("--start-maximized")
            o.add_argument("--disable-blink-features=AutomationControlled")
            o.add_experimental_option("excludeSwitches", ["enable-automation"])
            o.add_experimental_option("useAutomationExtension", False)
            o.add_argument(
                "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            )
            profile_path = str(self.SELENIUM_PROFILE_DIR.resolve())
            o.add_argument(f"--user-data-dir={profile_path}")
            logger.info(f"Chrome 프로필: {profile_path}")

            self.driver = webdriver.Chrome(options=o)
            self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
                "source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            })
            return True
        except Exception as e:
            logger.error(f"[naver] WebDriver 실패: {e}")
            return False

    # ── 클립보드 유틸 (win32clipboard) ──
    @staticmethod
    def _clipboard_set_text(text):
        import win32clipboard
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
        win32clipboard.CloseClipboard()

    @staticmethod
    def _clipboard_set_image(image_path):
        """이미지 → EXIF 방향 보정 → BMP → win32clipboard CF_DIB"""
        from PIL import Image, ImageOps
        import win32clipboard
        import io

        img = Image.open(image_path)
        # EXIF orientation 보정 (세로 사진 눕힘 방지)
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
        if img.mode != 'RGB':
            img = img.convert('RGB')
        MAX = 5 * 1024 * 1024
        w, h = img.size
        while w * h * 3 > MAX:
            w, h = int(w * 0.8), int(h * 0.8)
            img = img.resize((w, h), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format='BMP')
        bmp_data = buf.getvalue()
        # BMP 파일 헤더 14바이트 건너뛰기 → DIB
        dib_data = bmp_data[14:]

        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib_data)
        win32clipboard.CloseClipboard()

    # ── 에디터 조작 ──
    def _close_draft_popup(self):
        result = self.driver.execute_script("""
            var buttons = document.querySelectorAll('button');
            for (var i = 0; i < buttons.length; i++) {
                var txt = buttons[i].textContent.trim();
                if (txt === '취소' || txt.indexOf('새로') >= 0) {
                    buttons[i].click();
                    return 'closed:' + txt;
                }
            }
            return 'none';
        """)
        if result and 'closed' in str(result):
            logger.info(f"  팝업 닫음: {result}")
            time.sleep(1.5)

    def _input_title(self, title):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys

        try:
            se_node = self.driver.find_element(By.CSS_SELECTOR, ".se-title-text .__se-node")
            se_node.click(); time.sleep(0.5)
        except:
            try:
                self.driver.find_element(By.CSS_SELECTOR, ".se-title-text").click()
                time.sleep(0.5)
            except:
                return False

        self._clipboard_set_text(title)
        time.sleep(0.3)
        active = self.driver.switch_to.active_element
        active.send_keys(Keys.CONTROL, 'v')
        time.sleep(0.5)

        result = self.driver.execute_script("""
            var node = document.querySelector('.se-title-text .__se-node');
            return node ? node.textContent : '';
        """)
        if result and len(result.strip()) > 0:
            active.send_keys(Keys.ENTER)
            time.sleep(0.3)
            return True

        # JS 폴백
        self.driver.execute_script("""
            var title = arguments[0];
            var m = document.querySelector('.se-title-text');
            if (!m) return;
            var n = m.querySelector('.__se-node');
            if (n) n.textContent = title;
            m.classList.remove('se-is-empty');
            var ph = m.querySelector('.se-placeholder');
            if (ph) ph.style.display = 'none';
            var p = m.querySelector('.se-text-paragraph');
            if (p) p.dispatchEvent(new Event('input', {bubbles:true}));
        """, title)
        return True

    def _focus_body(self):
        self.driver.execute_script("""
            var paras = document.querySelectorAll('.se-text-paragraph');
            for (var i = 0; i < paras.length; i++) {
                if (!paras[i].closest('.se-title-text')) {
                    paras[i].click(); paras[i].focus(); return;
                }
            }
            var c = document.querySelector('.se-content, .se-main-container');
            if (c) c.click();
        """)
        time.sleep(0.3)

    def _set_center_align(self):
        """네이버 에디터 가운데 정렬 설정"""
        try:
            # 방법1: 정렬 버튼 클릭
            result = self.driver.execute_script("""
                // 정렬 드롭다운 열기
                var alignBtns = document.querySelectorAll(
                    'button[data-name="align"], button[class*="align"]');
                for (var i = 0; i < alignBtns.length; i++) {
                    alignBtns[i].click();
                    break;
                }
                // 가운데 정렬 클릭
                setTimeout(function(){
                    var items = document.querySelectorAll(
                        'button[data-value="center"], li[data-value="center"],' +
                        'button[title*="가운데"], button[aria-label*="center"]');
                    for (var i = 0; i < items.length; i++) {
                        items[i].click();
                        return 'ok';
                    }
                }, 300);
                return 'attempted';
            """)
            logger.info(f"  가운데 정렬: {result}")
            time.sleep(0.5)
        except Exception as e:
            logger.warning(f"  가운데 정렬 실패: {e}")
            # 방법2: Ctrl+E (가운데 정렬 단축키)
            try:
                from selenium.webdriver.common.keys import Keys
                from selenium.webdriver.common.action_chains import ActionChains
                actions = ActionChains(self.driver)
                actions.key_down(Keys.CONTROL).send_keys('e').key_up(Keys.CONTROL).perform()
                time.sleep(0.3)
            except:
                pass

    def _paste_text(self, text):
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.common.action_chains import ActionChains
        actions = ActionChains(self.driver)
        for line in text.split('\n'):
            if line.strip():
                self._clipboard_set_text(line.strip())
                time.sleep(0.15)
                actions.key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
                time.sleep(0.2)
            actions.send_keys(Keys.ENTER).perform()
            time.sleep(0.1)
        actions.send_keys(Keys.ENTER).perform()
        time.sleep(0.2)

    def _insert_separator(self):
        """네이버 에디터에 구분선 삽입"""
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.common.action_chains import ActionChains
        try:
            # 방법1: 네이버 에디터 구분선 버튼 클릭
            result = self.driver.execute_script("""
                // 구분선 버튼 찾기
                var btns = document.querySelectorAll(
                    'button[data-name="line"], button[class*="line"],' +
                    'button[data-type="line"], button.se-toolbar-button');
                for (var i = 0; i < btns.length; i++) {
                    var title = (btns[i].title || btns[i].getAttribute('aria-label') || '').toLowerCase();
                    var text = btns[i].textContent.trim();
                    if (title.indexOf('구분선') >= 0 || title.indexOf('line') >= 0 ||
                        text.indexOf('구분선') >= 0) {
                        btns[i].click();
                        return 'button_clicked';
                    }
                }
                return 'not_found';
            """)
            if result == 'button_clicked':
                time.sleep(0.5)
                # 구분선 스타일 선택 (첫번째 = 기본 가로선)
                self.driver.execute_script("""
                    setTimeout(function(){
                        var items = document.querySelectorAll(
                            '.se-line-type-list button, .se-popup-line button,' +
                            '[class*="line_type"] button, [class*="line-item"]');
                        if (items.length > 0) items[0].click();
                    }, 300);
                """)
                time.sleep(0.5)
                logger.info("  구분선: 버튼 클릭")
                return
        except Exception as e:
            logger.debug(f"  구분선 버튼 실패: {e}")

        # 방법2: 텍스트 구분선 (─ ─ ─) 삽입
        actions = ActionChains(self.driver)
        separator_text = "─ ─ ─ ─ ─ ─ ─"
        self._clipboard_set_text(separator_text)
        time.sleep(0.1)
        actions.key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
        time.sleep(0.2)
        actions.send_keys(Keys.ENTER).perform()
        actions.send_keys(Keys.ENTER).perform()
        time.sleep(0.2)
        logger.info("  구분선: 텍스트 폴백")

    def _paste_styled_text(self, text, color="", size="normal", bold=False):
        """네이버 에디터에 스타일 텍스트 삽입
        size: 'small' (0.8em), 'normal', 'large' (1.3em)
        """
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.common.action_chains import ActionChains
        actions = ActionChains(self.driver)

        # 텍스트 입력
        self._clipboard_set_text(text)
        time.sleep(0.1)
        actions.key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
        time.sleep(0.2)

        # 방금 입력한 텍스트 전체 선택
        actions.key_down(Keys.SHIFT).key_down(Keys.HOME).key_up(Keys.HOME).key_up(Keys.SHIFT).perform()
        time.sleep(0.2)

        # 글씨 크기 변경
        if size in ("small", "large"):
            try:
                target_size = "11" if size == "small" else "24"
                self.driver.execute_script("""
                    var sizeBtn = document.querySelector(
                        'button[data-name="fontSize"], button[class*="font_size"],' +
                        '.se-toolbar-button[data-command="fontSize"]');
                    if (sizeBtn) { sizeBtn.click(); }
                """)
                time.sleep(0.5)
                self.driver.execute_script(f"""
                    var t = arguments[0];
                    var items = document.querySelectorAll(
                        '.se-popup-font-size button, [class*="font_size"] li,' +
                        '.se-font-size-list button, [data-value]');
                    for (var i = 0; i < items.length; i++) {{
                        var val = items[i].getAttribute('data-value') ||
                                  items[i].textContent.trim();
                        if (val === t || val === t + 'px') {{
                            items[i].click();
                            return 'ok';
                        }}
                    }}
                    return 'not_found';
                """, target_size)
                time.sleep(0.3)
            except Exception as e:
                logger.debug(f"  글씨크기 변경 실패: {e}")

        # 색상 변경
        if color:
            try:
                self.driver.execute_script(f"""
                    var colorBtn = document.querySelector(
                        'button[data-name="fontColor"], button[class*="font_color"],' +
                        '.se-toolbar-button[data-command="fontColor"]');
                    if (colorBtn) {{
                        colorBtn.click();
                        setTimeout(function() {{
                            var input = document.querySelector(
                                'input[type="text"][class*="color"], input[placeholder*="색상"],' +
                                'input[class*="hex"]');
                            if (input) {{
                                input.value = '{color.replace("#", "")}';
                                input.dispatchEvent(new Event('input', {{bubbles:true}}));
                                input.dispatchEvent(new Event('change', {{bubbles:true}}));
                                // 확인 버튼
                                var ok = document.querySelector(
                                    '.se-popup-color button[class*="confirm"],' +
                                    'button[class*="apply"]');
                                if (ok) ok.click();
                            }}
                        }}, 500);
                    }}
                """)
                time.sleep(1)
            except Exception as e:
                logger.debug(f"  색상 변경 실패: {e}")

        # 볼드
        if bold:
            actions.key_down(Keys.CONTROL).send_keys('b').key_up(Keys.CONTROL).perform()
            time.sleep(0.2)

        # 선택 해제 + 줄바꿈
        actions.send_keys(Keys.END).perform()
        time.sleep(0.1)
        actions.send_keys(Keys.ENTER).perform()
        actions.send_keys(Keys.ENTER).perform()
        time.sleep(0.2)

    def _paste_hyperlink(self, text, url):
        """네이버 에디터에 하이퍼링크 텍스트 삽입 (OG 카드 없이 텍스트+링크)"""
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.common.action_chains import ActionChains
        actions = ActionChains(self.driver)

        # 1) 텍스트 입력
        self._clipboard_set_text(text)
        time.sleep(0.15)
        actions.key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
        time.sleep(0.3)

        # 2) 방금 입력한 텍스트 전체 선택 (Shift+Home)
        actions.key_down(Keys.SHIFT).key_down(Keys.HOME).key_up(Keys.HOME).key_up(Keys.SHIFT).perform()
        time.sleep(0.3)

        # 3) 링크 삽입 — 방법A: 네이버 에디터 링크 버튼
        linked = False
        try:
            result = self.driver.execute_script("""
                // 링크 버튼 찾기
                var btns = document.querySelectorAll(
                    'button[data-name="link"], button[class*="link"],' +
                    'button[data-type="link"], .se-toolbar-button');
                for (var i = 0; i < btns.length; i++) {
                    var title = (btns[i].title || btns[i].getAttribute('aria-label') || '');
                    if (title.indexOf('링크') >= 0 || title.indexOf('Link') >= 0 ||
                        title.indexOf('link') >= 0) {
                        btns[i].click();
                        return 'link_btn_clicked';
                    }
                }
                return 'not_found';
            """)

            if result == 'link_btn_clicked':
                time.sleep(1)
                # URL 입력 필드 찾아서 입력
                linked = self.driver.execute_script(f"""
                    var url = arguments[0];
                    // URL 입력 필드
                    var inputs = document.querySelectorAll(
                        'input[type="text"], input[type="url"]');
                    for (var i = 0; i < inputs.length; i++) {{
                        var ph = (inputs[i].placeholder || '').toLowerCase();
                        var cls = (inputs[i].className || '').toLowerCase();
                        if (ph.indexOf('url') >= 0 || ph.indexOf('http') >= 0 ||
                            ph.indexOf('링크') >= 0 || ph.indexOf('주소') >= 0 ||
                            cls.indexOf('url') >= 0 || cls.indexOf('link') >= 0) {{
                            inputs[i].focus();
                            inputs[i].value = url;
                            inputs[i].dispatchEvent(new Event('input', {{bubbles:true}}));
                            inputs[i].dispatchEvent(new Event('change', {{bubbles:true}}));

                            // 확인 버튼 클릭
                            setTimeout(function() {{
                                var btns = document.querySelectorAll(
                                    'button[class*="confirm"], button[class*="apply"],' +
                                    'button[class*="save"], button[class*="ok"]');
                                for (var j = 0; j < btns.length; j++) {{
                                    var t = btns[j].textContent.trim();
                                    if (t === '확인' || t === '적용' || t === 'OK' ||
                                        t === '저장' || t.indexOf('확인') >= 0) {{
                                        btns[j].click();
                                        break;
                                    }}
                                }}
                            }}, 500);
                            return true;
                        }}
                    }}
                    return false;
                """, url)
                time.sleep(1)
                if linked:
                    logger.info(f"  하이퍼링크: '{text}' → {url[:50]}")
        except Exception as e:
            logger.debug(f"  링크 버튼 방식 실패: {e}")

        if not linked:
            # 방법B: Ctrl+K (일반적인 링크 단축키)
            try:
                actions.key_down(Keys.CONTROL).send_keys('k').key_up(Keys.CONTROL).perform()
                time.sleep(1)
                # URL 입력
                active = self.driver.switch_to.active_element
                self._clipboard_set_text(url)
                time.sleep(0.1)
                active.send_keys(Keys.CONTROL, 'v')
                time.sleep(0.3)
                active.send_keys(Keys.ENTER)
                time.sleep(0.5)
                linked = True
                logger.info(f"  하이퍼링크(Ctrl+K): '{text}' → {url[:50]}")
            except Exception as e:
                logger.debug(f"  Ctrl+K 방식 실패: {e}")

        if not linked:
            # 방법C: 폴백 — 텍스트만 표시 (링크 없이)
            logger.warning(f"  하이퍼링크 실패, 텍스트만 표시: {text}")

        # 선택 해제 + 줄바꿈
        actions.send_keys(Keys.END).perform()
        time.sleep(0.1)
        actions.send_keys(Keys.ENTER).perform()
        actions.send_keys(Keys.ENTER).perform()
        time.sleep(0.3)

    def _paste_image(self, image_path):
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.common.action_chains import ActionChains
        if not os.path.exists(image_path):
            return False
        self._clipboard_set_image(image_path)
        time.sleep(0.5)
        actions = ActionChains(self.driver)
        actions.key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
        time.sleep(1)
        size_mb = os.path.getsize(image_path) / (1024 * 1024)
        wait = max(5, min(15, int(size_mb * 4) + 5))
        time.sleep(wait)
        actions.send_keys(Keys.ENTER).perform()
        time.sleep(0.5)
        return True

    def _set_visibility(self, visibility="public"):
        vis_map = {"public": "전체공개", "private": "비공개",
                   "neighbor": "서로이웃공개"}
        target = vis_map.get(visibility, "전체공개")
        result = self.driver.execute_script("""
            var t = arguments[0];
            var radios = document.querySelectorAll('input[type="radio"]');
            for (var i = 0; i < radios.length; i++) {
                var label = radios[i].closest('label') || radios[i].parentElement;
                if (label && label.textContent.indexOf(t) >= 0) {
                    radios[i].click();
                    return 'ok:' + label.textContent.trim().substring(0,20);
                }
            }
            var labels = document.querySelectorAll('label');
            for (var i = 0; i < labels.length; i++) {
                if (labels[i].textContent.indexOf(t) >= 0) {
                    labels[i].click();
                    return 'label:' + labels[i].textContent.trim().substring(0,20);
                }
            }
            return 'not-found';
        """, target)
        logger.info(f"  공개 설정 ({target}): {result}")
        time.sleep(0.5)

    def _input_tags_in_dialog(self, tags):
        from selenium.webdriver.common.keys import Keys
        result = self.driver.execute_script("""
            var inputs = document.querySelectorAll('input');
            for (var i = 0; i < inputs.length; i++) {
                var ph = (inputs[i].placeholder || '').toLowerCase();
                if (ph.indexOf('태그') >= 0 || ph.indexOf('tag') >= 0) {
                    inputs[i].scrollIntoView({block:'center'});
                    inputs[i].click(); inputs[i].focus();
                    return 'found';
                }
            }
            return 'not-found';
        """)
        if 'found' in str(result):
            time.sleep(0.3)
            active = self.driver.switch_to.active_element
            for t in tags[:10]:
                self._clipboard_set_text(t)
                active.send_keys(Keys.CONTROL, 'v')
                time.sleep(0.2)
                active.send_keys(Keys.ENTER)
                time.sleep(0.3)
            logger.info(f"  태그 {len(tags[:10])}개 입력")

    # ── 메인 발행 ──
    def post(self, data, visibility="public", schedule=None):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        if not self._ensure_driver():
            return {"success": False,
                    "reason": "WebDriver 실패"}

        title = data.get("title", "")
        blocks = data.get("blocks", [])
        tags = data.get("tags", [])

        # HTML content → blocks 변환 (blocks가 없으면)
        if not blocks and data.get("content"):
            blocks = html_to_blocks(data["content"], data.get("photos", []))

        try:
            write_url = "https://blog.naver.com/GoBlogWrite.naver"
            self.driver.get(write_url)
            time.sleep(4)

            # 로그인 확인
            if "nidlogin" in self.driver.current_url or "login" in self.driver.current_url:
                self._try_login()
                if "nidlogin" in self.driver.current_url:
                    return {"success": False, "reason": "로그인 실패"}
                self.driver.get(write_url)
                time.sleep(5)

            # iframe
            try:
                WebDriverWait(self.driver, 15).until(
                    EC.frame_to_be_available_and_switch_to_it((By.ID, 'mainFrame')))
            except: pass
            time.sleep(3)

            # 팝업 닫기
            self._close_draft_popup()
            self._screenshot("editor")

            # 제목
            self._input_title(title)
            self._screenshot("title")

            # 본문
            self._focus_body()
            time.sleep(0.5)

            # 가운데 정렬 설정
            self._set_center_align()
            time.sleep(0.3)

            # 경로 이미지 사전 생성
            route_images = self._generate_route_images(blocks)

            # 블록 삽입
            for i, block in enumerate(blocks):
                btype = block.get("type", "text")
                if btype == "text":
                    self._paste_text(block["content"])
                elif btype == "image":
                    self._paste_image(block["path"])
                    self._screenshot(f"img{i}")
                elif btype == "separator":
                    self._insert_separator()
                elif btype == "styled_label":
                    # 색상 있는 작은 라벨 (PLACE 1, TRAVEL TIPS 등)
                    color = block.get("color", "#8B9467")
                    self._paste_styled_text(block["content"], color=color, size="small")
                elif btype == "heading":
                    # 장소 제목 (크고 굵게)
                    self._paste_styled_text(block["content"], size="large", bold=True)
                elif btype == "map_link":
                    url = block.get("url", "")
                    content = block.get("content", "📍 지도에서 보기")
                    if url:
                        self._paste_hyperlink(content, url)
                elif btype == "route":
                    self._paste_text(block["content"])
                    route_img = route_images.get(i)
                    if route_img and os.path.exists(route_img):
                        self._paste_image(route_img)
                    link_text = block.get("link_text", "")
                    link_url = block.get("link_url", "")
                    if link_text and link_url:
                        self._paste_hyperlink(link_text, link_url)

            self._screenshot("done")

            # 발행
            clicked = False
            for sel in ["button.publish_btn__m9KHH",
                        "button[data-click-area='tpb.publish']",
                        "button[class*='publish_btn']"]:
                try:
                    el = self.driver.find_element(By.CSS_SELECTOR, sel)
                    if el.is_displayed():
                        el.click(); clicked = True; break
                except: continue
            if not clicked:
                self.driver.execute_script("""
                    var bs = document.querySelectorAll('button');
                    for (var i=0;i<bs.length;i++)
                        if (bs[i].textContent.trim()==='발행'){bs[i].click();return;}
                """)
            time.sleep(3)

            # 공개 설정
            self._set_visibility(visibility)

            # 태그
            if tags:
                self._input_tags_in_dialog(tags)

            # 예약 발행
            if schedule:
                self.driver.execute_script("""
                    var labels = document.querySelectorAll('label, span, div');
                    for (var i=0;i<labels.length;i++)
                        if (labels[i].textContent.trim()==='예약'){labels[i].click();return;}
                """)
                time.sleep(1)

            time.sleep(1)
            self._screenshot("publish_settings")

            # 최종 확인 버튼
            confirmed = False
            for sel in ["button.confirm_btn__WEaBq",
                        "button[data-testid='seOnePublishBtn']",
                        "button[class*='confirm_btn']"]:
                try:
                    el = self.driver.find_element(By.CSS_SELECTOR, sel)
                    if el.is_displayed():
                        el.click(); confirmed = True; break
                except: continue
            if not confirmed:
                self.driver.execute_script("""
                    var btn = document.querySelector('[data-testid="seOnePublishBtn"]');
                    if (btn) { btn.click(); return; }
                    btn = document.querySelector('button[class*="confirm_btn"]');
                    if (btn) { btn.click(); return; }
                    var bs = document.querySelectorAll('button');
                    var last = null;
                    for (var i=0;i<bs.length;i++)
                        if (bs[i].textContent.trim()==='발행' && bs[i].offsetParent!==null) last=bs[i];
                    if (last) last.click();
                """)
            time.sleep(3)
            self._screenshot("published")

            # 발행 후 글 URL 추출
            post_url = ""
            try:
                time.sleep(2)
                cur = self.driver.current_url
                # 네이버 블로그 글 URL 패턴
                if "/blog/" in cur or "blog.naver.com" in cur:
                    post_url = cur
                else:
                    # 발행 후 리디렉션 대기
                    time.sleep(3)
                    cur = self.driver.current_url
                    if "blog.naver.com" in cur:
                        post_url = cur
            except: pass

            logger.info(f"  네이버 발행 완료: '{title}' → {post_url or '(URL 미확인)'}")
            return {"success": True, "url": post_url, "method": "selenium"}

        except Exception as e:
            self._screenshot("error")
            return {"success": False, "reason": str(e)}

    def _try_login(self):
        """selenium_profile에 저장된 쿠키로 자동 로그인 시도"""
        import pyperclip
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys

        nid = os.environ.get("NAVER_USERNAME", "")
        npw = os.environ.get("NAVER_PASSWORD", "")
        if not nid or not npw:
            logger.warning("  .env에 NAVER_USERNAME/NAVER_PASSWORD 없음 → 수동 로그인 필요")
            self._screenshot("need_login")
            print("\n" + "="*50)
            print("  네이버 로그인이 필요합니다! 브라우저에서 직접 로그인 (90초)")
            print("="*50 + "\n")
            time.sleep(90)
            return

        try:
            el = self.driver.find_element(By.CSS_SELECTOR, "#id")
            el.click(); time.sleep(0.5)
            pyperclip.copy(nid)
            el.send_keys(Keys.CONTROL, 'v'); time.sleep(1)

            pw = self.driver.find_element(By.CSS_SELECTOR, "#pw")
            pw.click(); time.sleep(0.5)
            pyperclip.copy(npw)
            pw.send_keys(Keys.CONTROL, 'v'); time.sleep(1)

            for s in ["#log\\.login", ".btn_login", "#btn_login"]:
                try: self.driver.find_element(By.CSS_SELECTOR, s).click(); break
                except: continue
            time.sleep(3)

            if "captcha" in self.driver.current_url or "2step" in self.driver.current_url:
                print("  ⚠️ 캡차/2단계 인증 → 브라우저에서 완료 (90초)")
                time.sleep(90)
        except Exception as e:
            logger.warning(f"  자동 로그인 실패: {e}")

    def _generate_route_images(self, blocks):
        """route 블록의 경로 이미지 사전 생성"""
        route_images = {}
        route_blocks = [(i, b) for i, b in enumerate(blocks) if b.get("type") == "route"]
        if not route_blocks:
            return route_images
        try:
            from route_map_capture import capture_route_image
            google_key = os.environ.get("GOOGLE_MAPS_API_KEY")
            route_dir = str(DEBUG_DIR / "route_images")
            os.makedirs(route_dir, exist_ok=True)

            for idx, block in route_blocks:
                origin = block.get("origin")
                dest = block.get("destination")
                if not origin or not dest:
                    continue
                img_path = os.path.join(route_dir,
                    f"route_{idx:03d}_{origin[0]:.4f}_{dest[0]:.4f}.png")
                result = capture_route_image(
                    origin=origin, destination=dest,
                    mode=block.get("mode", "transit"),
                    output_path=img_path, google_key=google_key,
                    departure_time=block.get("departure_time"))
                if result:
                    route_images[idx] = result
        except ImportError:
            logger.warning("  route_map_capture 모듈 없음 → 경로 이미지 생략")
        except Exception as e:
            logger.warning(f"  경로 이미지 생성 오류: {e}")
        return route_images


class TistorySeleniumPoster(_SeleniumBase):
    """티스토리 Selenium 발행"""
    def __init__(self, blog_name=""):
        super().__init__("tistory")
        self.blog = blog_name

    def post(self, data):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        if not self.blog:
            return {"success": False, "reason": "tistory.blog_name 미설정"}
        if not self._ensure_driver():
            return {"success": False,
                    "reason": "WebDriver 실패. Chrome을 모두 닫고 재시도하세요."}

        title = data.get("title", "")
        content = data.get("content", "")
        tags = data.get("tags", [])

        try:
            write_url = f"https://{self.blog}.tistory.com/manage/newpost"
            self.driver.get(write_url)
            time.sleep(4)

            self._wait_login("auth/login", write_url)
            self._wait_login("accounts.kakao", write_url)
            self._screenshot("write_page")

            # ── 제목 ──
            for sel in ["#post-title-inp", ".tit_post input",
                        "[placeholder*='제목']", "#title"]:
                try:
                    ti = WebDriverWait(self.driver, 5).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, sel)))
                    ti.clear(); ti.send_keys(title)
                    logger.info(f"  제목 OK: {sel}"); break
                except: continue

            # ── HTML 모드 ──
            for sel in [".btn_html", "button[data-mode='html']",
                        ".btn_switch", "//button[contains(text(),'HTML')]"]:
                try:
                    if sel.startswith("//"):
                        self.driver.find_element(By.XPATH, sel).click()
                    else:
                        self.driver.find_element(By.CSS_SELECTOR, sel).click()
                    time.sleep(1); logger.info(f"  HTML 모드: {sel}"); break
                except: continue

            # ── 본문 (HTML) ──
            entered = False
            for sel in ["#html-editor-container textarea",
                        ".CodeMirror textarea", "#content",
                        "textarea.te_edit_area", "textarea"]:
                try:
                    el = self.driver.find_element(By.CSS_SELECTOR, sel)
                    if el.tag_name == 'textarea':
                        el.clear(); el.send_keys(content)
                    else:
                        self.driver.execute_script(
                            "arguments[0].innerHTML=arguments[1];", el, content)
                    entered = True; logger.info(f"  본문 OK: {sel}"); break
                except: continue
            if not entered:
                try:
                    self.driver.execute_script("""
                        if(document.querySelector('.CodeMirror'))
                            document.querySelector('.CodeMirror').CodeMirror.setValue(arguments[0]);
                    """, content)
                    entered = True; logger.info("  본문 OK: CodeMirror JS")
                except: pass

            # ── 태그 ──
            if tags:
                for tsel in ["#tagText", "input.tag_input", "[placeholder*='태그']"]:
                    try:
                        el = self.driver.find_element(By.CSS_SELECTOR, tsel)
                        for tag in tags[:10]:
                            el.send_keys(tag); el.send_keys(Keys.RETURN)
                            time.sleep(0.2)
                        break
                    except: continue

            time.sleep(1); self._screenshot("before_publish")

            # ── 발행 ──
            for sel in ["#publish-layer-btn", ".btn_publish", "#save-button",
                        "button.btn_save", "button.publish_btn",
                        "//button[contains(text(),'발행')]",
                        "//button[contains(text(),'완료')]"]:
                try:
                    if sel.startswith("//"):
                        pb = WebDriverWait(self.driver, 5).until(
                            EC.element_to_be_clickable((By.XPATH, sel)))
                    else:
                        pb = WebDriverWait(self.driver, 5).until(
                            EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
                    pb.click(); time.sleep(2)
                    for csel in ["#publish-btn", ".btn_ok", ".btn_submit",
                                 "//button[contains(text(),'공개')]",
                                 "//button[contains(text(),'확인')]"]:
                        try:
                            if csel.startswith("//"):
                                self.driver.find_element(By.XPATH, csel).click()
                            else:
                                self.driver.find_element(By.CSS_SELECTOR, csel).click()
                            time.sleep(3); break
                        except: continue
                    self._screenshot("published")
                    logger.info(f"  티스토리 발행 완료: '{title}'")
                    return {"success": True,
                            "url": f"https://{self.blog}.tistory.com",
                            "method": "selenium"}
                except: continue

            self._screenshot("publish_fail")
            return {"success": False, "reason": "발행 실패 - logs/debug 확인"}
        except Exception as e:
            self._screenshot("error")
            return {"success": False, "reason": str(e)}


# ============================================================
# 통합 래퍼 -- blog_auto.py에서 사용
# ============================================================
class NaverPoster:
    """네이버 통합 발행기 (clipboard / selenium 선택)"""
    def __init__(self, config):
        self.config = config
        self._clipboard = ClipboardPoster("naver")
        self._selenium = None  # 지연 초기화

    def post(self, data, method="clipboard", visibility="public", schedule=None):
        if method == "selenium":
            if not self._selenium:
                self._selenium = NaverSeleniumPoster()
            return self._selenium.post(data, visibility=visibility, schedule=schedule)
        else:
            return self._clipboard.post(data)

    def close(self):
        if self._selenium:
            self._selenium.close()


class TistoryPoster:
    """티스토리 통합 발행기 (clipboard / selenium 선택)"""
    def __init__(self, config):
        self.config = config
        self.blog = config.get("tistory", "blog_name") or ""
        self._clipboard = ClipboardPoster("tistory")
        self._selenium = None

    def post(self, data, method="clipboard"):
        if method == "selenium":
            if not self._selenium:
                self._selenium = TistorySeleniumPoster(self.blog)
            return self._selenium.post(data)
        else:
            return self._clipboard.post(data, blog_name=self.blog)

    def close(self):
        if self._selenium:
            self._selenium.close()
