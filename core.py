"""
TravelBlog Pro v1.1 - 핵심 엔진
- GPS 우선 → Vision 최소화 (비용 절감)
- 장소명: 한글 정식명칭 (일본어/영어 병기)
- 참고 블로그 URL → 문체 분석
- 네이버 상위 10개 블로그 → 글 구성 자동 분석
"""
import os,sys,json,time,re,logging,base64
from datetime import datetime
from pathlib import Path
import urllib.request,urllib.parse
try:
    from dotenv import load_dotenv; load_dotenv()
except ImportError: pass

LOG_DIR=Path("logs"); LOG_DIR.mkdir(exist_ok=True)
# Windows cp949 콘솔에서 이모지 로그/print가 UnicodeEncodeError로 앱을 죽이는 것 방지
for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception: pass
logging.basicConfig(level=logging.INFO,format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.FileHandler(LOG_DIR/'travelblog.log',encoding='utf-8'),logging.StreamHandler(sys.stdout)])
logger=logging.getLogger(__name__)


class Config:
    DEFAULTS={"openai":{"api_key":"","model":"gpt-4o-mini","max_tokens":16000,"temperature":0.7},
              "naver":{"enabled":False,"username":"","password":"","client_id":"","client_secret":""},
              "tistory":{"enabled":False,"blog_name":"","kakao_email":"","kakao_password":""},
              "google":{"maps_api_key":""},
              "settings":{"blog_style":"후기형","save_locally":True}}
    ENV_MAP={"OPENAI_API_KEY":("openai","api_key"),"OPENAI_MODEL":("openai","model"),
             "NAVER_ENABLED":("naver","enabled"),"NAVER_USERNAME":("naver","username"),"NAVER_PASSWORD":("naver","password"),
             "NAVER_CLIENT_ID":("naver","client_id"),"NAVER_CLIENT_SECRET":("naver","client_secret"),
             "TISTORY_ENABLED":("tistory","enabled"),"TISTORY_BLOG_NAME":("tistory","blog_name"),
             "KAKAO_EMAIL":("tistory","kakao_email"),"KAKAO_PASSWORD":("tistory","kakao_password"),
             "GOOGLE_MAPS_API_KEY":("google","maps_api_key")}
    def __init__(self):
        self.data=json.loads(json.dumps(self.DEFAULTS))
        if os.path.exists("config.json"):
            try:
                with open("config.json",'r',encoding='utf-8') as f: fd=json.load(f)
                for s,vs in fd.items():
                    if s in self.data and isinstance(vs,dict):
                        for k,v in vs.items():
                            if v and "YOUR_" not in str(v): self.data[s][k]=v
            except: pass
        for env,(s,k) in self.ENV_MAP.items():
            v=os.getenv(env)
            if v and v.strip():
                if k=="enabled": self.data[s][k]=v.lower() in("true","1","yes")
                else: self.data[s][k]=v
    def get(self,*keys):
        r=self.data
        for k in keys:
            if isinstance(r,dict): r=r.get(k)
            else: return None
        return r
    def is_valid(self):
        k=self.get("openai","api_key"); return bool(k and k.startswith("sk-"))
    def get_status(self):
        return {"openai":self.is_valid(),
                "naver":bool(self.get("naver","enabled") and self.get("naver","username")),
                "tistory":bool(self.get("tistory","enabled") and self.get("tistory","blog_name"))}


# ============================================================
# 참고 블로그 문체 분석
# ============================================================
class StyleAnalyzer:
    """참고 블로그 URL의 문체, 구조, 톤을 분석"""

    def __init__(self, config=None):
        self.config = config

    def analyze(self, url):
        logger.info(f"📎 참고 블로그 분석: {url}")
        scraped = self._scrape(url)
        text = " ".join(scraped.get("paragraphs", []))
        profile = self.extract_profile(text, scraped.get("headings"))
        profile["source_urls"] = [url]
        profile["title"] = scraped.get("title", "")
        if len(text) < 200:
            profile["warning"] = "본문을 충분히 못 읽었습니다 — 문체 반영이 약할 수 있어요."
        logger.info(f"✅ 문체 분석 완료: {profile.get('tone','')} ({profile.get('extracted_by')})")
        return profile

    @staticmethod
    def _normalize_naver_url(url):
        """네이버 블로그 글 URL을 본문이 실제로 담긴 PostView URL로 정규화.
        blog.naver.com/<id>/<글번호>는 iframe 래퍼 페이지라 본문이 비어 있어
        그대로 긁으면 문체 분석이 정규식 폴백으로 떨어진다."""
        m = re.match(
            r'https?://(?:m\.)?blog\.naver\.com/([A-Za-z0-9_-]+)/(\d+)/?(?:[?#].*)?$',
            (url or "").strip())
        if m:
            return (f"https://blog.naver.com/PostView.naver"
                    f"?blogId={m.group(1)}&logNo={m.group(2)}")
        return url

    def _scrape(self, url):
        """URL에서 원문 문단/제목/이미지수 수집. 실패 시 빈 구조."""
        url = self._normalize_naver_url(url)
        empty = {"title": "", "headings": [], "paragraphs": [], "image_count": 0}
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            logger.warning("⚠️  pip install beautifulsoup4 필요")
            return empty
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                html = r.read().decode('utf-8', errors='ignore')
            soup = BeautifulSoup(html, 'html.parser')
            title = soup.find('title').get_text(strip=True) if soup.find('title') else ""
            headings = []
            for tag in ['h2', 'h3', 'strong', 'b']:
                for h in soup.find_all(tag):
                    t = h.get_text(strip=True)
                    if t and 5 < len(t) < 80:
                        headings.append(t)
            headings = headings[:15]
            paras = []
            for p in soup.find_all(['p', 'div', 'span']):
                t = p.get_text(strip=True)
                if 30 < len(t) < 500:
                    paras.append(t)
            paras = list(dict.fromkeys(paras))[:20]
            img_count = len([i for i in soup.find_all('img') if i.get('src', '').startswith('http')])
            return {"title": title, "headings": headings,
                    "paragraphs": paras, "image_count": img_count}
        except Exception as e:
            logger.warning(f"⚠️  분석 실패: {e}")
            return empty

    def _detect_tone(self, text):
        if not text: return "일반"
        scores = {"친근 구어체":0, "정중 존댓말":0, "캐주얼 반말":0}
        if re.findall(r'[요!]\s|더라고요|었어요|할게요|인가요|네요|잖아요', text):
            scores["친근 구어체"] += len(re.findall(r'요[.!]?\s|더라고요|었어요', text))
        if re.findall(r'습니다|됩니다|하겠습니다|드립니다', text):
            scores["정중 존댓말"] += len(re.findall(r'습니다|됩니다', text))
        if re.findall(r'[야해했된][\s.]|거든|잖아[^요]|인듯|ㅋㅋ|ㅎㅎ', text):
            scores["캐주얼 반말"] += len(re.findall(r'거든|ㅋㅋ|ㅎㅎ', text))
        return max(scores, key=scores.get) if any(v > 0 for v in scores.values()) else "친근 구어체"

    def _detect_endings(self, text):
        """자주 쓰는 문장 끝맺음 패턴"""
        endings = re.findall(r'[가-힣]+[.!?~]\s', text)
        if not endings: return ["~했어요.", "~더라고요.", "~인 것 같아요."]
        freq = {}
        for e in endings:
            # 마지막 2~4글자 추출
            match = re.search(r'([가-힣]{2,4}[.!?~])', e)
            if match:
                k = match.group(1)
                freq[k] = freq.get(k, 0) + 1
        sorted_endings = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        return [e[0] for e in sorted_endings[:5]] if sorted_endings else ["~했어요.", "~더라고요."]

    def extract_profile(self, text, headings=None):
        """원문 텍스트 → 문체 규칙 프로파일(dict).
        config가 유효하면 LLM 추출, 아니면 정규식 폴백."""
        cfg = self.config
        if cfg is not None and hasattr(cfg, "is_valid") and cfg.is_valid():
            prof = self._extract_profile_llm(text)
            if prof:
                return prof
        return self._profile_from_regex(text)

    def _profile_from_regex(self, text):
        """LLM 없이 기존 정규식 휴리스틱으로 최소 프로파일 구성."""
        return {
            "tone": self._detect_tone(text),
            "sentence_length": "",
            "ending_patterns": self._detect_endings(text),
            "emoji_usage": "",
            "rhetorical_habits": [],
            "person": "",
            "dos": [], "donts": [],
            "examples": [],
            "extracted_by": "regex_fallback",
            "warning": None,
        }

    def _extract_profile_llm(self, text):
        """LLM으로 문체 규칙 JSON 추출. 실패 시 None(폴백 유도)."""
        if not text or len(text) < 30:
            return None
        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.config.get("openai", "api_key"))
            model = self.config.get("openai", "model") or "gpt-4o-mini"
            prompt = (
                "다음은 한 블로거의 글이다. 이 사람의 '문체'만 분석해 JSON으로 출력하라. "
                "내용/사실이 아니라 말투·리듬·습관만 본다. 확실한 것만, 없으면 빈 값/빈 배열. "
                "키: tone(문장 톤 한 줄), sentence_length(문장 길이·리듬 한 줄), "
                "ending_patterns(자주 쓰는 어미 배열, 예 '~더라고요'), "
                "emoji_usage(이모지/초성 사용 습관 한 줄), "
                "rhetorical_habits(수사·도입·전환 습관 배열), person(화자 시점 한 줄), "
                "dos(살릴 특징 배열), donts(피할 것 배열), "
                "examples(문체가 잘 드러나는 짧은 문장 1~2개 배열, 한 문장씩).\n\n"
                f"[글]\n{text[:4000]}"
            )
            r = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0,
            )
            data = json.loads(r.choices[0].message.content)
        except Exception as e:
            logger.warning(f"⚠️ 문체 LLM 추출 실패: {e}")
            return None
        return self._normalize_profile(data)

    @staticmethod
    def _normalize_profile(data):
        """LLM 응답 dict를 안정 스키마로 정규화 + 상한 적용."""
        def _list(v, n):
            if isinstance(v, str):
                v = [v]
            return [str(x).strip() for x in (v or []) if str(x).strip()][:n]
        return {
            "tone": str(data.get("tone", "") or "").strip(),
            "sentence_length": str(data.get("sentence_length", "") or "").strip(),
            "ending_patterns": _list(data.get("ending_patterns"), 6),
            "emoji_usage": str(data.get("emoji_usage", "") or "").strip(),
            "rhetorical_habits": _list(data.get("rhetorical_habits"), 6),
            "person": str(data.get("person", "") or "").strip(),
            "dos": _list(data.get("dos"), 5),
            "donts": _list(data.get("donts"), 5),
            "examples": _list(data.get("examples"), 2),
            "extracted_by": "llm",
            "warning": None,
        }

    def _empty(self, url):
        return {"url":url,"title":"","headings":[],"sample_paragraphs":[],"tone":"친근 구어체",
                "common_endings":["~했어요.","~더라고요."],"heading_count":0,"paragraph_count":0,
                "image_count":0,"structure_summary":"분석 불가"}


# ============================================================
# 네이버 상위 블로그 글 구성 분석
# ============================================================
class NaverBlogAnalyzer:
    """네이버 상위 블로그 본문을 방문하여 글 구조를 상세 분석"""

    def __init__(self, config=None):
        self.config = config

    def analyze(self, keyword, count=10):
        """상위 블로그 검색 → 본문 방문 → 구조 분석"""
        logger.info(f"🔍 네이버 상위 블로그 구조 분석: '{keyword}'")

        # 1단계: 블로그 URL 수집
        blog_items = self._search_blogs(keyword, count)
        if not blog_items:
            logger.warning(f"⚠️ 블로그 검색 실패 (keyword={keyword})")
            return self._empty(keyword)

        titles = [b["title"] for b in blog_items]
        descs = [b.get("desc", "") for b in blog_items]

        # 2단계: 상위 블로그 본문 구조 분석 (최대 count개)
        blog_structures = []
        for item in blog_items[:count]:
            url = item.get("link", "")
            if url:
                struct = self._analyze_blog_page(url)
                if struct:
                    struct["title"] = item["title"]
                    blog_structures.append(struct)
                    logger.info(f"  📄 분석: {item['title'][:30]}... "
                                f"({struct['char_count']}자, 이미지 {struct['image_count']}장)")
                time.sleep(0.3)

        # 3단계: 종합 분석
        avg_analysis = self._aggregate_structures(blog_structures)

        # 키워드 분석 (불용어·검색어 자신 제외)
        common = self._extract_keywords(titles, descs, keyword)

        patterns = self._detect_patterns(titles)

        result = {
            "keyword": keyword,
            "top_titles": titles,
            "top_descriptions": descs,
            "common_keywords": common,
            "title_patterns": patterns,
            "recommended_structure": avg_analysis.get("recommended_sections", []),
            "avg_title_length": round(sum(len(t) for t in titles) / len(titles)) if titles else 30,
            "seo_tips": self._seo_tips(titles, descs),
            # ★ 새로운 상세 분석 데이터 ★
            "blog_structures": blog_structures,
            "avg_analysis": avg_analysis,
        }
        logger.info(f"✅ 블로그 구조 분석 완료: {len(blog_structures)}개 본문 분석")
        return result

    # 키워드 추출에서 걸러낼 일반어(여행 후기 상투어·부사·접속사)
    KEYWORD_STOPWORDS = {
        "있는", "있어요", "있었어요", "했어요", "하는", "합니다", "해서", "하고",
        "그리고", "그래서", "하지만", "진짜", "정말", "완전", "너무", "조금",
        "바로", "여기", "저희", "제가", "가장", "후기", "블로그", "오늘",
        "다녀왔어요", "다녀온", "갔다왔어요", "같아요", "있습니다", "추천",
    }

    @staticmethod
    def _extract_keywords(titles, descs, keyword, top_n=15):
        """제목+요약에서 연관 키워드 빈도 추출. 불용어·검색어 자신 제외. 순수함수."""
        all_text = ' '.join(list(titles) + list(descs))
        words = re.findall(r'[가-힣a-zA-Z]{2,}', all_text)
        stop = NaverBlogAnalyzer.KEYWORD_STOPWORDS
        freq = {}
        for w in words:
            if w in stop:
                continue
            if w == keyword or w in keyword or keyword in w:
                continue
            # 검색 키워드의 각 어절(예: "후쿠오카", "여행")과 겹치면 제외
            if any(w == part or w in part or part in w for part in keyword.split()):
                continue
            freq[w] = freq.get(w, 0) + 1
        ranked = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        return [w for w, _ in ranked[:top_n]]

    # ─── 블로그 검색 ───
    def _search_blogs(self, keyword, count):
        """네이버 API 또는 크롤링으로 블로그 URL 수집"""
        items = self._search_api(keyword, count)
        if not items:
            items = self._search_crawl(keyword, count)
        return items

    def _search_api(self, keyword, count):
        items = []
        try:
            cfg = self.config
            client_id = ""
            client_secret = ""
            if cfg and hasattr(cfg, 'get'):
                client_id = cfg.get("naver", "client_id") or ""
                client_secret = cfg.get("naver", "client_secret") or ""
            if not client_id:
                client_id = os.getenv("NAVER_CLIENT_ID", "")
            if not client_secret:
                client_secret = os.getenv("NAVER_CLIENT_SECRET", "")
            if not client_id or not client_secret:
                return items

            encoded = urllib.parse.quote(keyword)
            url = f"https://openapi.naver.com/v1/search/blog.json?query={encoded}&display={count}&sort=sim"
            req = urllib.request.Request(url)
            req.add_header("X-Naver-Client-Id", client_id)
            req.add_header("X-Naver-Client-Secret", client_secret)
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
            for it in data.get("items", [])[:count]:
                t = re.sub(r'<[^>]+>', '', it.get("title", "")).strip()
                d = re.sub(r'<[^>]+>', '', it.get("description", "")).strip()
                link = it.get("link", "")
                if t:
                    items.append({"title": t, "desc": d, "link": link})
            logger.info(f"  📡 API: {len(items)}개 블로그")
        except Exception as e:
            logger.warning(f"  ⚠️ API: {e}")
        return items

    def _search_crawl(self, keyword, count):
        items = []
        try:
            from bs4 import BeautifulSoup
            encoded = urllib.parse.quote(keyword)
            url = f"https://search.naver.com/search.naver?where=blog&query={encoded}&sm=tab_opt"
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                html = r.read().decode('utf-8')
            soup = BeautifulSoup(html, 'html.parser')
            for a in soup.find_all('a', href=re.compile(r'blog\.naver\.com')):
                txt = a.get_text(strip=True)
                href = a.get('href', '')
                if len(txt) >= 8 and txt not in [i["title"] for i in items]:
                    items.append({"title": txt, "desc": "", "link": href})
                if len(items) >= count:
                    break
            logger.info(f"  🔍 크롤링: {len(items)}개")
        except Exception as e:
            logger.warning(f"  ⚠️ 크롤링: {e}")
        return items

    # ─── 블로그 본문 구조 분석 ───
    def _analyze_blog_page(self, url):
        """블로그 본문 방문 → 구조 분석 (이미지, 동영상, 지도, 글자수, 섹션 구조)"""
        try:
            from bs4 import BeautifulSoup

            # 네이버 블로그 모바일 URL로 변환 (크롤링 용이)
            if "blog.naver.com" in url:
                url = url.replace("blog.naver.com", "m.blog.naver.com")

            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                              "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"})
            with urllib.request.urlopen(req, timeout=10) as r:
                html = r.read().decode('utf-8', errors='replace')
            soup = BeautifulSoup(html, 'html.parser')

            # 본문 영역 찾기
            body = (soup.find('div', class_='se-main-container') or
                    soup.find('div', id='postViewArea') or
                    soup.find('div', class_='post_ct') or
                    soup.find('div', class_='se_component_wrap') or
                    soup.find('article') or soup.find('body'))
            if not body:
                return None

            # 텍스트
            text = body.get_text(separator='\n', strip=True)
            char_count = len(text.replace('\n', '').replace(' ', ''))

            # 이미지
            images = body.find_all('img')
            img_count = len([i for i in images
                             if not any(x in (i.get('src','') + i.get('data-lazy-src',''))
                                        for x in ['logo','icon','profile','blank','emoticon'])])

            # 동영상
            videos = (body.find_all('iframe', src=re.compile(r'youtube|vimeo|naver|kakao', re.I)) +
                      body.find_all('video') +
                      body.find_all('div', class_=re.compile(r'video|player', re.I)))
            video_count = len(videos)

            # 지도
            maps = (body.find_all('iframe', src=re.compile(r'map|naver\.me|google.*map', re.I)) +
                    body.find_all('a', href=re.compile(r'map\.naver|naver\.me|google.*map', re.I)) +
                    body.find_all('div', class_=re.compile(r'map|place', re.I)))
            map_count = len(maps)

            # 헤딩/섹션 구조
            headings = []
            for tag in body.find_all(['h1','h2','h3','h4','strong','b']):
                txt = tag.get_text(strip=True)
                if 5 <= len(txt) <= 50:
                    headings.append(txt)

            # 구분선
            separators = len(body.find_all('hr')) + len(body.find_all('div', class_=re.compile(r'line|separator')))

            # 섹션 순서 추론
            sections = self._infer_sections(text, headings)

            return {
                "char_count": char_count,
                "image_count": img_count,
                "video_count": video_count,
                "map_count": map_count,
                "heading_count": len(headings),
                "headings": headings[:10],
                "separator_count": separators,
                "sections": sections,
                "has_map": map_count > 0,
                "has_video": video_count > 0,
            }
        except Exception as e:
            logger.debug(f"  블로그 분석 실패: {e}")
            return None

    def _infer_sections(self, text, headings):
        """본문 텍스트와 헤딩에서 섹션 순서 추론"""
        sections = []
        markers = {
            "인트로": ["안녕","반갑","소개","다녀왔","다녀온","방문"],
            "코스/경로": ["코스","루트","동선","일정","순서","경로"],
            "장소 후기": ["방문","구경","볼거리","관광","명소","들렀"],
            "맛집/카페": ["맛집","카페","식당","음식","메뉴","먹었","맛있"],
            "숙소": ["숙소","호텔","펜션","체크인","방","숙박"],
            "교통": ["교통","이동","버스","지하철","택시","렌트","주차"],
            "비용": ["비용","경비","가격","금액","원","만원","예산"],
            "꿀팁": ["팁","꿀팁","주의","참고","추천","준비물"],
            "지도": ["지도","위치","주소","찾아가"],
            "마무리": ["마무리","총평","소감","추천","다시","또","좋았"],
        }
        lower_text = text.lower()
        all_heads = ' '.join(headings).lower()

        for sec_name, keywords in markers.items():
            for kw in keywords:
                pos = lower_text.find(kw)
                if pos >= 0:
                    sections.append({"name": sec_name, "position": pos})
                    break
                pos2 = all_heads.find(kw)
                if pos2 >= 0:
                    sections.append({"name": sec_name, "position": pos2})
                    break

        sections.sort(key=lambda x: x["position"])
        return [s["name"] for s in sections]

    # ─── 종합 분석 ───
    def _aggregate_structures(self, structures):
        """여러 블로그 구조를 종합 분석"""
        if not structures:
            return {
                "avg_chars": 0, "avg_images": 0, "avg_videos": 0,
                "map_ratio": 0, "video_ratio": 0,
                "common_sections": [], "recommended_sections": [],
                "summary": "분석 데이터 없음"
            }

        avg_chars = round(sum(s["char_count"] for s in structures) / len(structures))
        avg_imgs = round(sum(s["image_count"] for s in structures) / len(structures))
        avg_vids = round(sum(s["video_count"] for s in structures) / len(structures), 1)
        map_ratio = sum(1 for s in structures if s["has_map"]) / len(structures)
        vid_ratio = sum(1 for s in structures if s["has_video"]) / len(structures)

        # 섹션 빈도
        from collections import Counter
        all_secs = []
        for s in structures:
            all_secs.extend(s.get("sections", []))
        sec_freq = Counter(all_secs).most_common(10)
        common_sections = [s for s, _ in sec_freq]

        # 추천 구조 생성
        recommended = []
        section_map = {
            "인트로": {"type": "인트로/인사", "desc": "인사말 + 여행 배경"},
            "코스/경로": {"type": "여행 코스/경로", "desc": "전체 동선 표시"},
            "장소 후기": {"type": "방문 장소 후기", "desc": "장소별 상세 후기 + 사진"},
            "맛집/카페": {"type": "맛집/카페", "desc": "음식점, 카페 후기"},
            "숙소": {"type": "숙소 후기", "desc": "숙소 정보, 후기"},
            "교통": {"type": "교통/이동 팁", "desc": "교통수단, 이동 방법"},
            "비용": {"type": "비용 정보", "desc": "여행 경비 정리"},
            "꿀팁": {"type": "여행 꿀팁", "desc": "실용 팁, 주의사항"},
            "지도": {"type": "구글 지도", "desc": "각 장소 지도 삽입"},
            "마무리": {"type": "마무리 인사", "desc": "감상 + 댓글 유도"},
        }
        for sec_name in common_sections:
            if sec_name in section_map:
                recommended.append(section_map[sec_name])

        summary = (f"평균 {avg_chars:,}자 / 이미지 {avg_imgs}장"
                   f"{f' / 동영상 {avg_vids}개' if avg_vids > 0 else ''}"
                   f"{' / 지도 포함' if map_ratio >= 0.5 else ''}")

        return {
            "avg_chars": avg_chars,
            "avg_images": avg_imgs,
            "avg_videos": avg_vids,
            "map_ratio": map_ratio,
            "video_ratio": vid_ratio,
            "common_sections": common_sections,
            "recommended_sections": recommended,
            "summary": summary,
        }

    def _detect_patterns(self, titles):
        p = []
        for t in titles:
            if '추천' in t: p.append("추천형")
            if '코스' in t or '일정' in t or '루트' in t: p.append("코스형")
            if '맛집' in t or '먹방' in t or '맛' in t: p.append("맛집형")
            if '후기' in t or '리뷰' in t or '솔직' in t: p.append("후기형")
            if '가이드' in t or '총정리' in t or '완벽' in t: p.append("가이드형")
            if re.search(r'\d+박\d+일|\d+일차', t): p.append("일정형")
            if re.search(r'\d+가지|\d+개|\d+선|TOP', t): p.append("리스트형")
            if '비용' in t or '가격' in t or '경비' in t: p.append("비용형")
        if p:
            from collections import Counter
            return [x for x, _ in Counter(p).most_common(4)]
        return ["후기형", "코스형"]

    def _seo_tips(self, titles, descs):
        tips = []
        if titles:
            tips.append(f"평균 제목 {sum(len(t) for t in titles)/len(titles):.0f}자")
        if any(re.search(r'\d+박\d+일', t) for t in titles):
            tips.append("'N박N일' 키워드 효과적")
        if any('2024' in t or '2025' in t or '2026' in t for t in titles):
            tips.append("연도 포함 유리")
        if any('솔직' in t or '후기' in t for t in titles):
            tips.append("'솔직 후기' 키워드 인기")
        return " | ".join(tips) if tips else ""

    def _empty(self, keyword):
        return {"keyword": keyword, "top_titles": [], "top_descriptions": [],
                "common_keywords": [], "title_patterns": ["후기형"],
                "recommended_structure": [
                    {"type": "도입부", "desc": "여행 개요"},
                    {"type": "관광명소", "desc": "방문 후기"},
                    {"type": "맛집", "desc": "먹거리 후기"},
                    {"type": "총평", "desc": "소감"}],
                "avg_title_length": 30, "seo_tips": "",
                "blog_structures": [], "avg_analysis": {}}


# ============================================================
# 사진 분석기 (GPS 우선 + Vision 최소)
# ============================================================
class PhotoAnalyzer:
    SUPPORTED={'.jpg','.jpeg','.png','.webp','.heic','.bmp','.tiff','.tif'}

    def __init__(self, config):
        self.api_key = config.get("openai","api_key")
        self.model = config.get("openai","model") or "gpt-4o-mini"
        self.google_api_key = config.get("google","maps_api_key") or ""
        from openai import OpenAI; self.client = OpenAI(api_key=self.api_key)
        self._poi_cache = {}  # (round lat,lon) → best POI dict / None
        if self.google_api_key:
            logger.info("🗺️ Google Maps API 활성화")
        else:
            logger.info("🗺️ Google Maps API 없음 → Nominatim 사용")

    # ── Places API(New) 기반 실제 상호명 해석 ──
    def _vision_to_places_types(self, scene_type):
        """Vision scene_type → Places primaryType 매칭용 키워드 목록 (없으면 [])"""
        s = (scene_type or "").strip()
        M = {
            "카페": ["cafe", "bakery", "coffee_shop"],
            "맛집": ["restaurant", "sandwich_shop", "ramen_restaurant", "japanese_restaurant", "cafe", "bakery"],
            "음식": ["restaurant", "cafe"], "식당": ["restaurant"],
            "관광지": ["tourist_attraction", "historical_landmark", "point_of_interest"],
            "신사": ["place_of_worship", "shrine", "tourist_attraction"],
            "사찰": ["place_of_worship", "buddhist_temple", "tourist_attraction"],
            "거리": ["tourist_attraction", "point_of_interest"],
            "시장": ["market", "supermarket", "store"],
            "쇼핑": ["store", "shopping_mall", "department_store"],
        }
        for k, v in M.items():
            if k in s:
                return v
        return []

    def _pick_best_poi(self, candidates, scene_type, lat, lon):
        """후보 POI 중 ① Vision 타입 일치 ② GPS 거리 가까운 순으로 최적 1개"""
        if not candidates:
            return None
        keys = self._vision_to_places_types(scene_type)
        def score(c):
            pt = c.get("primaryType", "") or ""
            match = any(k in pt for k in keys) if keys else False
            try:
                dist = TripStructurer._haversine(lat, lon, float(c["lat"]), float(c["lon"]))
            except (TypeError, ValueError, KeyError):
                dist = 9e9
            return (0 if match else 1, dist)
        return sorted(candidates, key=score)[0]

    def _places_nearby(self, lat, lon, radius=150):
        """Places API(New) searchNearby — 좌표 주변 POI 목록(한글)"""
        if not self.google_api_key:
            return []
        body = json.dumps({
            "maxResultCount": 10,
            "locationRestriction": {"circle": {"center": {"latitude": lat, "longitude": lon}, "radius": float(radius)}},
            "languageCode": "ko",
        }).encode()
        req = urllib.request.Request(
            "https://places.googleapis.com/v1/places:searchNearby",
            data=body, method="POST",
            headers={"Content-Type": "application/json", "X-Goog-Api-Key": self.google_api_key,
                     "X-Goog-FieldMask": "places.displayName,places.primaryType,places.location,places.id"})
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                d = json.loads(resp.read().decode())
            out = []
            for p in d.get("places", []):
                loc = p.get("location", {}) or {}
                out.append({"name": (p.get("displayName") or {}).get("text", ""),
                            "primaryType": p.get("primaryType", ""), "id": p.get("id", ""),
                            "lat": loc.get("latitude"), "lon": loc.get("longitude")})
            return [o for o in out if o["name"]]
        except Exception as e:
            logger.warning(f"  ⚠️ Places 조회 실패: {e}")
            return []

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

    def _places_nearby_cached(self, lat, lon):
        """좌표 주변 POI 후보(캐시) — GPS 반올림 키로 1회만 조회"""
        ck = (round(lat, 4), round(lon, 4))
        if ck not in self._poi_cache:
            self._poi_cache[ck] = self._places_nearby(lat, lon)
        return self._poi_cache[ck]

    def _resolve_poi(self, lat, lon, scene_type=None, visible_name=None):
        """신뢰 가능한 상호명만 반환: Vision 간판(visible_name)이 Places 후보와
        일치할 때 그 후보를 반환(교차검증). 아니면 None.
        GPS 최근접/타입 추측은 정확성을 보장 못 하므로 이름으로 쓰지 않는다
        (호출부에서 중립 표기로 폴백). (_pick_best_poi/_vision_to_places_types는 향후용으로 유지)"""
        if not visible_name:
            return None
        for c in self._places_nearby_cached(lat, lon):
            if self._name_match(visible_name, c.get("name", "")):
                logger.info(f"  🏪 POI(간판검증): {c['name']}")
                return c
        return None

    def scan_folder(self, folder_path):
        """폴더 및 하위 폴더에서 모든 이미지 파일 검색"""
        folder = Path(folder_path); files = []
        for f in sorted(folder.rglob("*")):
            if f.is_file() and f.suffix.lower() in self.SUPPORTED:
                files.append(str(f))
        logger.info(f"📁 {len(files)}개 사진 발견 (하위 폴더 포함)")
        return files

    def analyze_photos(self, paths, progress_cb=None, result_cb=None):
        """
        GPS+Vision 역할 분리:
        - GPS  → 정확한 위치/주소 (신뢰)
        - Vision → 장면 유형+묘사 (신사 내부, 음식 등)
        - 합산 → GPS 주소 + Vision 장면유형으로 최종 장소 결정
        result_cb: 사진 1장 분석 후 결과 전달 (idx, total, result_dict)
        """
        results = []; total = len(paths); gps_count = 0; vision_count = 0

        for i, p in enumerate(paths):
            if progress_cb: progress_cb(i+1, total, p)
            logger.info(f"📷 [{i+1}/{total}] {Path(p).name}")

            r = {"file_path":p,"file_name":Path(p).name,"gps":None,
                 "location_name":"","location_name_local":"","vision":{},"exif_date":"","day_date":"",
                 "poi_resolved":False,"name_confident":False}

            # ── STEP 1: EXIF GPS + 날짜 (무료) ──
            gps_location = ""
            gps_local = ""
            gps_is_poi = False
            exif = self._extract_exif(p)
            if exif:
                r["exif_date"] = exif.get("date","")
                if exif.get("lat") and exif.get("lon"):
                    r["gps"] = {"lat":exif["lat"],"lon":exif["lon"],"date":exif.get("date","")}
                    addr_data = self._gps_to_addr(exif["lat"], exif["lon"])
                    gps_location = addr_data.get("korean","")
                    gps_local = addr_data.get("local","")
                    gps_is_poi = addr_data.get("is_poi", False)
                    r["city"] = addr_data.get("city","")
                    r["region"] = addr_data.get("region","")
                    r["country"] = addr_data.get("country","")
                    gps_count += 1
                    poi_tag = "🏢 POI" if gps_is_poi else "📮 주소"
                    logger.info(f"  📍 GPS ({poi_tag}): {gps_location}")

            # ── STEP 2: Vision으로 장면만 파악 (~$0.00003/장) ──
            vision = self._vision_with_gps(p, gps_location)
            if vision:
                r["vision"] = vision
                vision_count += 1

                scene_type = vision.get("scene_type","")
                visible_name = vision.get("visible_name","")

                if gps_location:
                    if gps_is_poi:
                        # Google이 시설명 확인 → 신뢰 (간판읽기 무시)
                        r["location_name"] = gps_location
                        r["poi_resolved"] = True
                        r["name_confident"] = True
                        if addr_data.get("place_id"):
                            r["place_id"] = addr_data["place_id"]
                    else:
                        # 간판 교차검증 성공시에만 실명 신뢰, 아니면 중립 표기
                        poi = self._resolve_poi(exif["lat"], exif["lon"], scene_type, visible_name) if r.get("gps") else None
                        if poi:
                            r["location_name"] = poi["name"]
                            r["poi_id"] = poi.get("id", "")
                            r["poi_resolved"] = True
                            r["name_confident"] = True
                            if poi.get("id"):
                                r["place_id"] = poi["id"]
                        else:
                            # 불확실 → 중립 표기 "{동네} {유형}" (사용자가 실명 입력)
                            r["location_name"] = self._make_place_name(
                                gps_location, gps_local, scene_type)
                            r["poi_resolved"] = False
                            r["name_confident"] = False

                    r["location_name_local"] = gps_local
                    if scene_type:
                        r["vision"]["place_type"] = scene_type
                else:
                    r["location_name"] = visible_name or scene_type or "미확인"
                    r["location_name_local"] = ""
            else:
                r["location_name"] = gps_location
                r["location_name_local"] = gps_local
                r["vision"] = {"scene_type":"관광지","scene_description":"","mood":"즐거운"}

            r["day_date"] = self._extract_day_date(r)
            results.append(r)
            if result_cb:
                try: result_cb(i+1, total, r)
                except: pass

        # ── 배치 한글 변환 (외국어 장소명 모아서 1번 AI 호출) ──
        foreign_items = []
        for i, r in enumerate(results):
            # Places(한글 상호명)는 스킵하되, POI여도 외국어가 남으면 번역
            # (무료 모드: Nominatim이 한글 OSM명 없을 때 원문 일본어 POI명 반환 → 제목/본문 누출 방지)
            if r.get("poi_resolved") and not self._has_foreign_chars(r.get("location_name","")):
                continue
            name = r.get("location_name","")
            if name and self._has_foreign_chars(name):
                foreign_items.append((i, name, r.get("location_name_local","")))

        if foreign_items and len(foreign_items) <= 50:
            translated = self._batch_translate([f[1] for f in foreign_items])
            if translated:
                for idx, (ri, orig, _) in enumerate(foreign_items):
                    if idx < len(translated) and translated[idx]:
                        results[ri]["location_name"] = translated[idx]
                        logger.info(f"  🔤 번역: {orig} → {translated[idx]}")

        cost = vision_count * 0.00003
        logger.info(f"✅ 분석 완료: GPS {gps_count}장 + Vision {vision_count}장 (비용 ~${cost:.4f})")
        return results

    def _extract_day_date(self, photo_result):
        """
        촬영 날짜 추출 우선순위:
        1) EXIF DateTimeOriginal (가장 정확)
        2) EXIF GPS 날짜
        3) 파일명에서 날짜 패턴
        4) 파일 수정일시 (최후의 수단)
        """
        # 1) EXIF 촬영일시 (예: "2024:05:25 14:30:00")
        exif_date = photo_result.get("exif_date","")
        if exif_date:
            match = re.search(r'(\d{4})[:\-/](\d{2})[:\-/](\d{2})', exif_date)
            if match:
                return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"

        # 2) GPS 날짜
        gps = photo_result.get("gps")
        if gps and gps.get("date"):
            match = re.search(r'(\d{4})[:\-/](\d{2})[:\-/](\d{2})', gps["date"])
            if match:
                return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"

        # 3) 파일명 날짜 패턴
        fname = photo_result.get("file_name","")
        # YYYYMMDD (20240525)
        m = re.search(r'(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])', fname)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        # YYMMDD (240525)
        m = re.search(r'(2[0-9])(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])', fname)
        if m:
            return f"20{m.group(1)}-{m.group(2)}-{m.group(3)}"

        # 4) 파일 수정일시 (최후의 수단)
        try:
            fpath = photo_result.get("file_path","")
            if fpath and os.path.exists(fpath):
                mtime = os.path.getmtime(fpath)
                dt = datetime.fromtimestamp(mtime)
                return dt.strftime("%Y-%m-%d")
        except:
            pass

        return ""

    @staticmethod
    def group_by_day(photo_results):
        """
        사진 분석 결과를 일별로 그룹핑
        반환: [{"day_number":1, "day_date":"2024-05-25", "day_label":"1일차", "photos":[...]}, ...]
        """
        from collections import OrderedDict
        day_map = OrderedDict()

        for r in photo_results:
            day_date = r.get("day_date","") or "미분류"
            if day_date not in day_map:
                day_map[day_date] = []
            day_map[day_date].append(r)

        days = []
        for i, (date_key, photos) in enumerate(day_map.items(), 1):
            # DAY-N 형식이면 그대로, 날짜면 변환
            if date_key.startswith("DAY-"):
                label = f"{date_key.replace('DAY-','')}일차"
            elif date_key == "미분류":
                label = "미분류"
            else:
                label = f"{i}일차 ({date_key})"
            days.append({
                "day_number": i,
                "day_date": date_key,
                "day_label": label,
                "photos": photos
            })

        logger.info(f"📅 {len(days)}일로 그룹핑: {', '.join(d['day_label'] for d in days)}")
        return days

    def _extract_exif(self, path):
        """EXIF에서 GPS + 촬영일시 + GPS날짜 추출"""
        try:
            from PIL import Image; from PIL.ExifTags import TAGS, GPSTAGS
            img = Image.open(path); exif = img._getexif()
            if not exif: return None
            result = {"lat":None,"lon":None,"date":"","gps_date":""}
            for tid, val in exif.items():
                tag = TAGS.get(tid)
                # 촬영일시 (우선순위: DateTimeOriginal > DateTimeDigitized > DateTime)
                if tag == "DateTimeOriginal" and not result["date"]:
                    result["date"] = str(val)
                elif tag == "DateTimeDigitized" and not result["date"]:
                    result["date"] = str(val)
                elif tag == "DateTime" and not result["date"]:
                    result["date"] = str(val)
                elif tag == "GPSInfo":
                    gi = {}
                    for gtid, gval in val.items(): gi[GPSTAGS.get(gtid,gtid)] = gval
                    result["lat"] = self._dms(gi.get("GPSLatitude"),gi.get("GPSLatitudeRef"))
                    result["lon"] = self._dms(gi.get("GPSLongitude"),gi.get("GPSLongitudeRef"))
                    # GPS 날짜
                    if gi.get("GPSDateStamp"):
                        result["gps_date"] = str(gi["GPSDateStamp"])
            # GPS 날짜를 date에 보조로 사용
            if not result["date"] and result["gps_date"]:
                result["date"] = result["gps_date"]
            return result
        except: return None

    def _dms(self, dms, ref):
        if not dms or not ref: return None
        try:
            dd = float(dms[0])+float(dms[1])/60+float(dms[2])/3600
            if ref in('S','W'): dd=-dd
            return round(dd,6)
        except: return None

    @staticmethod
    def _exif_to_epoch(exif_date_str):
        """EXIF 날짜 문자열 → Unix epoch (초)
        지원 형식: "2024:05:25 14:30:00", "2024-05-25 14:30:00", "2024:05:25"
        반환: int (epoch) 또는 None
        """
        if not exif_date_str:
            return None
        import re
        # "2024:05:25 14:30:00" or "2024-05-25 14:30:00"
        m = re.match(r'(\d{4})[:\-/](\d{2})[:\-/](\d{2})\s*(\d{2})?:?(\d{2})?:?(\d{2})?', exif_date_str)
        if not m:
            return None
        try:
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            hour = int(m.group(4)) if m.group(4) else 12  # 시간 없으면 낮 12시
            minute = int(m.group(5)) if m.group(5) else 0
            second = int(m.group(6)) if m.group(6) else 0

            dt = datetime(year, month, day, hour, minute, second)
            # Google Directions API departure_time은 UTC epoch 필요
            # 하지만 EXIF는 로컬 시간 → 일단 로컬 그대로 사용
            # (대부분 같은 타임존에서 비교하므로 실용적)
            epoch = int(dt.timestamp())

            # 과거 시간이면 Google API가 거부할 수 있으므로
            # 같은 요일+시간으로 다음주 날짜로 변환
            import calendar
            from datetime import timedelta
            now_epoch = int(datetime.now().timestamp())
            if epoch < now_epoch:
                # 같은 요일, 같은 시간으로 다음 주 날짜 계산
                days_ahead = 7 - (datetime.now().weekday() - dt.weekday()) % 7
                if days_ahead == 0:
                    days_ahead = 7
                future_dt = datetime.now().replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                ) + timedelta(days=days_ahead)
                epoch = int(future_dt.timestamp())
                logger.debug(f"  📅 과거 시간 → 같은 요일 다음주로: {dt} → {future_dt}")

            return epoch
        except Exception as e:
            logger.debug(f"  EXIF 시간 변환 실패: {exif_date_str}: {e}")
            return None

    def _gps_to_addr(self, lat, lon):
        """
        GPS → 장소명 (Google 우선, Nominatim fallback)
        반환: {"korean":"장소명", "local":"현지어", "is_poi":True/False}
        is_poi=True: 정확한 시설명 (蛇の目鮨, 佐賀神社 등)
        is_poi=False: 주소/도로명 (1-chōme Tōjin 등) → Vision 보완 필요
        """
        if self.google_api_key:
            result = self._google_geocode(lat, lon)
            if result and result.get("korean"):
                return result
        return self._nominatim_geocode(lat, lon)

    def _google_geocode(self, lat, lon):
        """
        Google Nearby Search → Place Details → Reverse Geocoding
        is_poi=True: 시설명 확인됨 (蛇の目鮨, 佐賀神社 등)
        is_poi=False: 주소만 확인됨 → analyze_photos에서 Vision 보완
        """
        result = {"korean":"","local":"","is_poi":False,"city":"","region":""}
        try:
            key = self.google_api_key

            # ── STEP 1: Nearby Search (반경 100m, 시설만) ──
            nearby_url = (
                f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?"
                f"location={lat},{lon}&radius=100&language=ko&key={key}"
            )
            req = urllib.request.Request(nearby_url)
            with urllib.request.urlopen(req, timeout=10) as r:
                nearby = json.loads(r.read().decode())

            if nearby.get("results"):
                # 도로/행정구역 제외, 실제 시설만 필터링
                skip_types = {"route","street_address","sublocality","locality",
                              "administrative_area_level_1","administrative_area_level_2",
                              "country","postal_code","plus_code","geocode",
                              "political","neighborhood"}
                place = None
                for p in nearby["results"]:
                    types = set(p.get("types",[]))
                    if not types.issubset(skip_types):
                        place = p
                        break

                if place:
                    place_id = place.get("place_id","")
                    if place_id:
                        # Place Details 1번으로 ko+ja 모두 가져오기
                        det_url = (
                            f"https://maps.googleapis.com/maps/api/place/details/json?"
                            f"place_id={place_id}&fields=name,types"
                            f"&language=ko&key={key}"
                        )
                        req2 = urllib.request.Request(det_url)
                        with urllib.request.urlopen(req2, timeout=10) as r2:
                            det = json.loads(r2.read().decode())
                            if det.get("result"):
                                result["korean"] = det["result"].get("name","")

                        # 현지어 이름 (한글과 다른 경우만)
                        if result["korean"] and not self._has_foreign_chars(result["korean"]):
                            # 이미 한글이면 현지어만 따로
                            det_ja = (
                                f"https://maps.googleapis.com/maps/api/place/details/json?"
                                f"place_id={place_id}&fields=name&language=ja&key={key}"
                            )
                            req3 = urllib.request.Request(det_ja)
                            with urllib.request.urlopen(req3, timeout=10) as r3:
                                det3 = json.loads(r3.read().decode())
                                if det3.get("result"):
                                    result["local"] = det3["result"].get("name","")
                        else:
                            # 한글 아님 → 이 이름이 현지어
                            result["local"] = result["korean"]
                    else:
                        result["korean"] = place.get("name","")

                    result["is_poi"] = True
                    if place_id:
                        result["place_id"] = place_id
                    logger.info(f"    🗺️ Google POI: {result['korean']} ({result['local']})")
                    # POI에도 city/region 가져오기 (SEO 키워드용)
                    try:
                        rev_url2 = (
                            f"https://maps.googleapis.com/maps/api/geocode/json?"
                            f"latlng={lat},{lon}&language=ko&result_type=locality|administrative_area_level_1&key={key}"
                        )
                        req_cr = urllib.request.Request(rev_url2)
                        with urllib.request.urlopen(req_cr, timeout=8) as r_cr:
                            geo_cr = json.loads(r_cr.read().decode())
                        if geo_cr.get("results"):
                            for comp in geo_cr["results"][0].get("address_components",[]):
                                types = comp.get("types",[])
                                if "locality" in types:
                                    result["city"] = comp.get("short_name","")
                                elif "administrative_area_level_1" in types:
                                    result["region"] = comp.get("long_name","")
                                elif "country" in types:
                                    result["country"] = comp.get("long_name","")
                    except: pass
                    return result

            # ── STEP 2: Nearby 실패 → 주소만 반환 (is_poi=False) ──
            rev_url = (
                f"https://maps.googleapis.com/maps/api/geocode/json?"
                f"latlng={lat},{lon}&language=ko&key={key}"
            )
            req = urllib.request.Request(rev_url)
            with urllib.request.urlopen(req, timeout=10) as r:
                geo = json.loads(r.read().decode())

            if geo.get("results"):
                # 동네/구역 이름 추출 (주소 전체가 아닌)
                best = geo["results"][0]
                addr_comps = best.get("address_components",[])
                neighborhood = ""
                city = ""
                region_name = ""
                country = ""
                for comp in addr_comps:
                    types = comp.get("types",[])
                    if "sublocality_level_2" in types or "neighborhood" in types:
                        neighborhood = comp.get("long_name","")
                    elif "sublocality_level_1" in types or "sublocality" in types:
                        if not neighborhood:
                            neighborhood = comp.get("long_name","")
                    elif "locality" in types:
                        city = comp.get("short_name","")
                    elif "administrative_area_level_1" in types:
                        region_name = comp.get("long_name","")
                    elif "country" in types:
                        country = comp.get("long_name","")

                result["korean"] = neighborhood or city or best.get("formatted_address","").split(",")[0]
                result["city"] = city
                result["region"] = region_name
                result["country"] = country
                result["is_poi"] = False

                # 현지어
                time.sleep(0.05)
                rev_ja = (
                    f"https://maps.googleapis.com/maps/api/geocode/json?"
                    f"latlng={lat},{lon}&language=ja&key={key}"
                )
                req2 = urllib.request.Request(rev_ja)
                with urllib.request.urlopen(req2, timeout=10) as r2:
                    geo2 = json.loads(r2.read().decode())
                    if geo2.get("results"):
                        for comp in geo2["results"][0].get("address_components",[]):
                            types = comp.get("types",[])
                            if "sublocality_level_2" in types or "neighborhood" in types:
                                result["local"] = comp.get("long_name","")
                                break

            logger.info(f"    🗺️ Google 주소: {result['korean']} (POI 아님)")

        except Exception as e:
            logger.warning(f"⚠️  Google Geocoding: {e}")

        return result

    @staticmethod
    def _pick_admin(addr):
        """Nominatim address dict → (city, region, country).
        무료 모드에서 지역 감지/위키 박스가 동작하도록 행정구역을 추출한다."""
        city = (addr.get("city") or addr.get("town") or addr.get("municipality")
                or addr.get("county") or "")
        region = (addr.get("province") or addr.get("state") or addr.get("region") or "")
        country = addr.get("country", "")
        return city, region, country

    def _nominatim_geocode(self, lat, lon):
        """Nominatim fallback (무료)"""
        result = {"korean":"","local":"","is_poi":False,"city":"","region":"","country":""}
        try:
            url19 = (f"https://nominatim.openstreetmap.org/reverse?"
                     f"format=json&lat={lat}&lon={lon}&zoom=19&accept-language=ko"
                     f"&addressdetails=1&namedetails=1")
            req = urllib.request.Request(url19, headers={"User-Agent":"TravelBlogPro/1.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data19 = json.loads(r.read().decode())

            name19 = data19.get("name","")
            osm_class = data19.get("class","")
            osm_type = data19.get("type","")
            addr = data19.get("address",{})
            # 무료 모드: 지역 위키 박스/지역 감지가 동작하도록 행정구역 채움
            # (Google geocode 경로와 동일한 city/region/country 필드 제공)
            result["city"], result["region"], result["country"] = self._pick_admin(addr)
            is_road = osm_class in ("highway","road") or osm_type in ("road","residential","tertiary","secondary","primary","unclassified","service")

            if name19 and not is_road:
                result["korean"] = name19
                result["is_poi"] = True
            else:
                parts = []
                for key in ["suburb","neighbourhood","quarter","city","town","county"]:
                    if addr.get(key):
                        parts.append(addr[key])
                        if len(parts) >= 2: break
                result["korean"] = ", ".join(parts) if parts else name19

            time.sleep(0.1)  # Nominatim rate limit (최소)

            url_local = (f"https://nominatim.openstreetmap.org/reverse?"
                         f"format=json&lat={lat}&lon={lon}&zoom=19&accept-language=local"
                         f"&namedetails=1")
            req2 = urllib.request.Request(url_local, headers={"User-Agent":"TravelBlogPro/1.0"})
            with urllib.request.urlopen(req2, timeout=10) as r2:
                data_local = json.loads(r2.read().decode())
                result["local"] = data_local.get("name","")

        except Exception as e:
            logger.warning(f"⚠️  Nominatim: {e}")
        return result

    def _make_place_name(self, gps_addr, gps_local, scene_type):
        """
        주소(is_poi=False)를 Vision scene_type과 결합하여 의미있는 장소명 생성
        예: "마쓰바라" + "신사" → "사가 신사"
            "에키미나미" + "맛집" → "사가역 주변 맛집"
            "도진" + "거리" → "도진 거리"
        """
        # scene_type이 있으면 동네+유형, 없으면 동네만
        # 동네명 정리: 번지수 제거
        clean = re.sub(r'\d+[-−]\d+|\d+초메|Chome.*|chōme.*|\d+번지?','', gps_addr).strip()
        clean = re.sub(r'[,、]\s*$','', clean).strip()
        # 로마자 주소 패턴 제거
        clean = re.sub(r'^\d+\s+','', clean)

        if not clean and gps_local:
            # 한글이 없으면 현지어에서 추출
            clean = re.sub(r'[\d丁目番地号〒−-]+','', gps_local).strip()
            clean = re.sub(r'^佐賀県佐賀市','사가 ', clean).strip()
            clean = re.sub(r'^日本\s*','', clean).strip()

        if not clean:
            clean = "여행지"

        if scene_type and scene_type not in clean:
            return f"{clean} {scene_type}"
        return clean

    def _has_foreign_chars(self, text):
        """한글이 아닌 외국어 포함 여부 (일본어, 로마자 등)"""
        if not text: return False
        # 일본어: 히라가나/가타카나/CJK한자
        if re.search(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', text):
            return True
        # 로마자 단어 포함 (영어 2글자 이상 연속)
        # "SAGA AIRPORT", "Matsubara", "Tōjin" 등 감지
        # 한글+숫자+기호만 있으면 False
        stripped = re.sub(r'[가-힣0-9\s\-→·,、()（）/\[\]#@!~]', '', text)
        if stripped and re.search(r'[a-zA-ZāēīōūĀĒĪŌŪ]{2,}', stripped):
            return True
        return False

    def _translate_to_korean(self, foreign_name, local_name=""):
        """일본어/중국어 장소명을 한글 음독으로 변환 (AI 사용, 1회 호출)"""
        try:
            prompt = f"""아래 장소명을 한글 발음/의미로 자연스럽게 번역하세요.
일본어 → 한글 음독 또는 한글 의미역 (더 자연스러운 쪽)

예시:
- 県庁前通り → 현청앞거리
- 中央大通り → 중앙대로
- 駅南本町 → 역남혼마치
- 水ヶ江一丁目 → 미즈가에 1초메
- 唐人町通り → 도진마치거리
- 佐賀空港 → 사가 공항
- 松原三丁目 → 마쓰바라 3초메
- 呉服町通り → 고후쿠마치거리

번역할 장소명: {foreign_name}
{f"현지어 원문: {local_name}" if local_name else ""}

한글 번역만 출력 (설명 없이):"""
            r = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role":"user","content":prompt}],
                max_tokens=50, temperature=0.1
            )
            translated = r.choices[0].message.content.strip()
            # 불필요한 따옴표나 설명 제거
            translated = re.sub(r'^["\'\s]+|["\'\s]+$', '', translated)
            translated = translated.split('\n')[0].strip()
            if translated and len(translated) < 50:
                logger.info(f"  🔤 번역: {foreign_name} → {translated}")
                return translated
        except:
            pass
        return None

    def _batch_translate(self, names):
        """여러 외국어 장소명을 한번에 번역 (1회 AI 호출)"""
        if not names: return []
        try:
            numbered = "\n".join(f"{i+1}. {n}" for i,n in enumerate(names))
            prompt = f"""아래 장소명들을 한글 발음/의미로 번역하세요.
일본어 → 한글 음독, 로마자 → 한글 음독

예시:
- 県庁前通り → 현청앞거리
- Matsubara → 마쓰바라
- Tōjin → 도진
- Hachimankōji → 하치만코지
- SHIRAYAMA → 시라야마
- Ekiminamihonmachi → 에키미나미혼마치
- Gofuku Motomachi → 고후쿠모토마치
- Mizugae → 미즈가에
- Jōnai → 조나이
- SAGA AIRPORT → 사가 공항
- 蛇の目鮨 → 자노메즈시

번역할 장소명:
{numbered}

각 번호에 대해 한글 번역만 한줄씩 출력 (번호 포함, 설명 없이):"""
            r = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role":"user","content":prompt}],
                max_tokens=50 * len(names), temperature=0.1
            )
            txt = r.choices[0].message.content.strip()
            results = []
            for line in txt.split("\n"):
                line = line.strip()
                if not line: continue
                # "1. 사가 공항" → "사가 공항"
                m = re.match(r'^\d+[\.\)]\s*(.+)', line)
                if m:
                    val = m.group(1).strip()
                    val = re.sub(r'^["\'\s]+|["\'\s]+$', '', val)
                    results.append(val if val and len(val) < 50 else None)
            return results
        except Exception as e:
            logger.warning(f"⚠️ 배치 번역 실패: {e}")
            return []

    def _guess_type(self, filename, location, gps_place_type=""):
        fn = filename.lower(); loc = (location or "").lower()
        pt = "관광지"; mood = "즐거운"

        # GPS에서 파악한 유형 우선 사용
        if gps_place_type:
            type_map = {
                "restaurant":"맛집","cafe":"카페","fast_food":"맛집",
                "bar":"술집","pub":"술집",
                "shrine":"신사","temple":"사찰","place_of_worship":"사찰/신사",
                "museum":"박물관","gallery":"미술관","castle":"성",
                "park":"공원","garden":"정원","viewpoint":"전망대",
                "hotel":"호텔","hostel":"호스텔","guest_house":"게스트하우스",
                "airport":"공항","station":"역",
                "beach":"해변","hot_spring":"온천",
            }
            if gps_place_type in type_map:
                pt = type_map[gps_place_type]
                mood_map = {"맛집":"맛있는","카페":"아늑한","신사":"경건한","사찰":"고즈넉한",
                           "공원":"상쾌한","호텔":"편안한","해변":"시원한","온천":"따뜻한",
                           "박물관":"흥미로운","전망대":"탁 트인"}
                mood = mood_map.get(pt, "즐거운")

        # 파일명/장소명으로 추가 추정
        if pt == "관광지":
            if any(w in fn+loc for w in ["food","meal","eat","restaurant","식당","맛집","고기","라멘","ramen"]):
                pt="맛집"; mood="맛있는"
            elif any(w in fn+loc for w in ["cafe","coffee","카페","커피"]):
                pt="카페"; mood="아늑한"
            elif any(w in fn+loc for w in ["hotel","호텔","펜션","숙소","리조트"]):
                pt="숙소"; mood="편안한"
            elif any(w in fn+loc for w in ["sea","beach","ocean","바다","해변","공원","산","mountain"]):
                pt="자연"; mood="시원한"
            elif any(w in fn+loc for w in ["shrine","신사","jinja","torii"]):
                pt="신사"; mood="경건한"
            elif any(w in fn+loc for w in ["temple","사찰","寺"]):
                pt="사찰"; mood="고즈넉한"

        return {"place_name":location,"place_name_kr":location,"place_type":pt,
                "food_name":"","scene_description":"","mood":mood,"season_weather":"","blog_tip":""}

    def _vision_with_gps(self, path, gps_hint=""):
        """
        Vision(detail:low)으로 장면만 파악
        - 장소 이름은 GPS가 담당, Vision은 추측하지 않음
        - "무엇이 보이는지"만 정확히 묘사
        - detail:low = 85토큰 (~$0.00003/장)
        """
        try:
            with open(path,"rb") as f: b64=base64.b64encode(f.read()).decode()
            ext = Path(path).suffix.lower()
            mime = {".jpg":"jpeg",".jpeg":"jpeg",".png":"png",".webp":"webp"}.get(ext,"jpeg")

            gps_ctx = f"\nGPS 위치: {gps_hint}" if gps_hint else "\nGPS 위치 없음"

            r = self.client.chat.completions.create(model=self.model,messages=[{"role":"user","content":[
                {"type":"text","text":f"""이 여행 사진에 보이는 것을 분석하세요.{gps_ctx}

중요: 장소 이름을 추측하지 마세요. 사진에서 간판이나 표지판이 보이면 그것만 읽으세요.
대신 사진에 보이는 장면을 정확히 묘사하세요.

JSON으로만 응답:
{{"scene_type":"신사/사찰/맛집/카페/관광지/공원/거리/숙소/공항/역/시장/해변/온천/성/박물관 중 택1","visible_name":"사진에 간판/표지판이 보이면 그 이름, 안 보이면 빈문자열","food_name":"음식이 보이면 음식명, 아니면 빈문자열","scene_description":"사진에 보이는 장면을 구체적으로 2~3문장 묘사(예: 빨간 도리이가 보이고 참배객이 있다, 장어덮밥이 접시에 놓여있다)","mood":"분위기 키워드","season_weather":"계절/날씨 추정","blog_tip":"이 장소 팁 한줄"}}"""},
                {"type":"image_url","image_url":{"url":f"data:image/{mime};base64,{b64}","detail":"low"}}
            ]}],max_tokens=250)
            txt = r.choices[0].message.content.strip()
            if "```json" in txt: txt=txt.split("```json")[1].split("```")[0].strip()
            elif "```" in txt: txt=txt.split("```")[1].split("```")[0].strip()
            result = json.loads(txt)
            logger.info(f"  🔍 Vision: [{result.get('scene_type','')}] {result.get('scene_description','')[:40]}...")
            return result
        except Exception as e:
            logger.warning(f"⚠️  Vision: {e}"); return {}

    def _vision(self, path):
        """하위호환"""
        return self._vision_with_gps(path, "")


# ============================================================
# 여행 구조화기 (날짜별/장소별/코스별 분류)
# ============================================================
class TripStructurer:
    """사진 분석 결과를 날짜별/장소별/코스별로 구조화"""

    @staticmethod
    def structure(photo_results):
        """
        사진 분석 결과를 3가지 방식으로 구조화
        반환: {"by_day":[...], "by_place":[...], "by_course":[...]}
        """
        result = {
            "by_day": TripStructurer._group_by_day(photo_results),
            "by_place": TripStructurer._group_by_place(photo_results),
            "by_course": TripStructurer._group_by_course(photo_results),
        }
        logger.info(f"📊 구조화 완료: 일별 {len(result['by_day'])}그룹 / "
                     f"장소별 {len(result['by_place'])}그룹 / 코스별 {len(result['by_course'])}그룹")
        return result

    @staticmethod
    def _group_by_day(photo_results):
        """날짜별 그룹핑"""
        from collections import OrderedDict
        day_map = OrderedDict()
        for r in photo_results:
            day_date = r.get("day_date","") or "미분류"
            day_map.setdefault(day_date, []).append(r)

        groups = []
        for i, (date_key, photos) in enumerate(day_map.items(), 1):
            if date_key.startswith("DAY-"):
                label = f"{date_key.replace('DAY-','')}일차"
            elif date_key == "미분류":
                label = "미분류"
            else:
                label = f"{i}일차 ({date_key})"
            # 코스 라인 생성 (유사 장소 합치기)
            places = []
            for p in photos:
                name = p.get("location_name","")
                if not name: continue
                # 이미 유사한 이름이 있으면 건너뛰기
                is_dup = False
                for existing in places:
                    # 짧은 쪽이 긴 쪽에 포함되면 중복
                    short, long_ = sorted([name, existing], key=len)
                    if short in long_ or long_ in short:
                        is_dup = True; break
                    # 앞 3글자 같으면 중복 (같은 동네)
                    if len(short) >= 3 and short[:3] == long_[:3]:
                        is_dup = True; break
                if not is_dup:
                    places.append(name)
            groups.append({
                "group_id": i, "label": label, "date": date_key,
                "photos": photos, "course_line": " → ".join(places)
            })
        return groups

    @staticmethod
    def _group_by_place(photo_results):
        """장소 유형별 그룹핑 (신사, 맛집, 거리, 관광지 등)"""
        type_map = {}
        for r in photo_results:
            v = r.get("vision", {})
            scene = v.get("scene_type","") or v.get("place_type","기타")
            # 유사 유형 통합
            merge = {"사찰":"신사/사찰","카페":"맛집/카페","시장":"맛집/카페"}
            scene = merge.get(scene, scene)
            type_map.setdefault(scene, []).append(r)

        groups = []
        for i, (place_type, photos) in enumerate(type_map.items(), 1):
            places = []
            for p in photos:
                name = p.get("location_name","")
                if name and name not in places: places.append(name)
            groups.append({
                "group_id": i, "label": place_type,
                "photos": photos, "course_line": " / ".join(places)
            })
        return groups

    @staticmethod
    def _group_by_course(photo_results):
        """가까운 장소끼리 코스로 묶기 (GPS 거리 기반)"""
        import math

        # GPS 있는 사진만 추출
        gps_photos = [r for r in photo_results if r.get("gps")]
        no_gps = [r for r in photo_results if not r.get("gps")]

        if not gps_photos:
            return [{"group_id":1, "label":"코스 1", "photos":photo_results, "course_line":""}]

        # 시간순 정렬
        gps_photos.sort(key=lambda x: x.get("exif_date","") or "")

        # 간단한 클러스터링: 이전 사진과 500m 이상 떨어지면 새 코스
        courses = []
        current = [gps_photos[0]]

        for r in gps_photos[1:]:
            prev = current[-1]
            dist = TripStructurer._haversine(
                prev["gps"]["lat"], prev["gps"]["lon"],
                r["gps"]["lat"], r["gps"]["lon"]
            )
            if dist > 500:  # 500m 이상 떨어지면 새 코스
                courses.append(current)
                current = [r]
            else:
                current.append(r)
        courses.append(current)

        # GPS 없는 사진은 마지막 코스에 추가
        if no_gps and courses:
            courses[-1].extend(no_gps)

        groups = []
        for i, photos in enumerate(courses, 1):
            places = []
            for p in photos:
                name = p.get("location_name","")
                if name and name not in places: places.append(name)
            groups.append({
                "group_id": i, "label": f"코스 {i}",
                "photos": photos, "course_line": " → ".join(places)
            })
        return groups

    @staticmethod
    def segment_index(places_meta):
        """[(region, date)] 순서 입력 → 일정(세그먼트) id 리스트.
        지역(도시) 또는 날짜가 바뀌면 새 세그먼트. 같은 도시·같은 날이면
        거리가 멀어도 한 일정(예: 교토 은각사/금각사/후시미=1세그먼트).
        region/date가 빈 값이면 경계로 치지 않음(이어붙임)."""
        ids = []
        cur = 0
        for i, (reg, day) in enumerate(places_meta):
            if i == 0:
                ids.append(0)
                continue
            preg, pday = places_meta[i - 1]
            if (reg and preg and reg != preg) or (day and pday and day != pday):
                cur += 1
            ids.append(cur)
        return ids

    @staticmethod
    def _haversine(lat1, lon1, lat2, lon2):
        """두 GPS 좌표 간 거리 (미터)"""
        import math
        R = 6371000
        p = math.pi / 180
        a = (0.5 - math.cos((lat2-lat1)*p)/2 +
             math.cos(lat1*p)*math.cos(lat2*p) * (1-math.cos((lon2-lon1)*p))/2)
        return 2 * R * math.asin(math.sqrt(a))


class TripPlanner:
    """사진 분석 결과 → 검수용 계획 초안(TripPlan dict). 네트워크 미사용."""

    @staticmethod
    def _photo_id(file_path):
        import hashlib, os
        base = os.path.basename(file_path or "")
        return "p" + hashlib.md5(base.encode("utf-8")).hexdigest()[:8]

    @staticmethod
    def _assign_day(exif_date, cutoff_hour=4):
        """'2026:06:22 14:30:00' -> 'YYYY-MM-DD'. 시각<cutoff면 전날. 실패시 None."""
        import re
        from datetime import datetime, timedelta
        if not exif_date:
            return None
        m = re.search(r'(\d{4})[:\-/](\d{2})[:\-/](\d{2})[ T]?(\d{2})?:?(\d{2})?', exif_date)
        if not m:
            return None
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hh = int(m.group(4)) if m.group(4) else 12
        try:
            dt = datetime(y, mo, d, hh)
        except ValueError:
            return None
        if hh < cutoff_hour:
            dt = dt - timedelta(days=1)
        return dt.strftime("%Y-%m-%d")

    @staticmethod
    def build_draft(photo_results, free_mode=False):
        """photo_results → TripPlan dict (검수 전 초안). 입력 dict를 변형하지 않음."""
        region = ""
        for r in photo_results:
            if r.get("region"):
                region = r["region"]; break

        day_map = {}
        undated = []
        for r in photo_results:
            pid = TripPlanner._photo_id(r.get("file_path", ""))
            day = TripPlanner._assign_day(r.get("exif_date", ""))
            if day is None:
                undated.append(pid)
            else:
                day_map.setdefault(day, []).append((pid, r))

        days = []
        for day_no, (date_key, items) in enumerate(sorted(day_map.items()), 1):
            stops = TripPlanner._stops_for_day(items)
            days.append({"day_no": day_no, "date": date_key, "stops": stops})

        return {
            "plan_version": 1,
            "trip_title": "",
            "region": region,
            "region_source": "auto" if region else "none",
            "free_mode": bool(free_mode),
            "days": days,
            "undated_photo_ids": undated,
            "excluded_photo_ids": [],
        }

    @staticmethod
    def groups_from_plan(plan, photo_results):
        """확정 plan + 원본 photo_results → 생성기용 Day별 그룹 리스트.
        photo_results를 변형하지 않음(복사본에 확정 장소명 덮어씀). 네트워크 미사용.
        place_meta는 별점·가격 줄용으로 그룹에 실어두되 이 단계에선 소비하지 않음."""
        by_pid = {}
        for r in photo_results:
            by_pid[TripPlanner._photo_id(r.get("file_path", ""))] = r
        groups = []
        for d in plan.get("days", []):
            photos, memos, directives, meta, names = [], {}, {}, {}, []
            seen_names = {}
            for s in d.get("stops", []):
                raw = s.get("name", "") or "미확인"
                # 같은 날 같은 이름이 두 번 나오면 = 재방문(세션 클러스터링이 분리한
                # 별개 방문). 이름이 같으면 하류가 전부 name 키로 묶어(place_groups,
                # 프롬프트 장소목록, memos/meta dict) 두 방문이 한 섹션으로 재병합되고
                # 메모·별점은 뒤엣것이 앞엣것을 덮어썼다 → 표시 이름을 구분한다.
                seen_names[raw] = seen_names.get(raw, 0) + 1
                n_th = seen_names[raw]
                name = raw if n_th == 1 else (
                    f"{raw} (재방문)" if n_th == 2 else f"{raw} (재방문 {n_th - 1})")
                if name not in names:
                    names.append(name)
                bits = []
                if s.get("events"):
                    bits.append("사건: " + "; ".join(s["events"]))
                if s.get("feeling"):
                    bits.append("느낌: " + s["feeling"])
                if s.get("ai_instruction"):
                    directives[name] = s["ai_instruction"]
                if bits:
                    memos[name] = " / ".join(bits)
                rc = s.get("receipt") or {}
                meta[name] = {
                    "rating": s.get("rating"),
                    "amount": rc.get("amount"),
                    "currency": rc.get("currency", ""),
                    "show_rating": s.get("show_rating", True),
                    "show_price": s.get("show_price", True),
                }
                for pid in s.get("photo_ids", []):
                    r = by_pid.get(pid)
                    if not r:
                        continue
                    rc2 = dict(r)
                    if s.get("name"):
                        rc2["location_name"] = name   # 재방문 구분 이름과 동일해야
                    photos.append(rc2)                # 하류 장소 그룹핑이 맞는다
            if not photos:
                continue
            groups.append({
                "group_id": d.get("day_no", len(groups) + 1),
                "label": f"{d.get('day_no','')}일차",
                "photos": photos,
                "course_line": " → ".join(names),
                "place_memos": memos,
                "place_directives": directives,
                "place_meta": meta,
            })
        return groups

    # 세션 클러스터링 임계 — 사용자가 확정한 plan stop을 정답으로 두고 실측 튜닝
    # (6개 일차, 사진 쌍 F1: 이름키+격자 0.456 → 45분/300m 0.940). 300m는 뚜렷한
    # 최적(200m 0.815 / 500m 0.797), 시간은 30~60분 고원이라 45분 채택.
    STOP_GAP_MIN = 45
    STOP_DIST_M = 300

    @staticmethod
    def _exif_seconds(exif_date):
        """'2024:12:21 17:30:57' → 비교용 절대 초(순수함수). 실패 시 None.
        차이 계산에만 쓰므로 달력 정확도는 불필요(월 경계 오차는 임계 초과라 무해)."""
        m = re.search(r'(\d{4})[:\-/](\d{2})[:\-/](\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?',
                      exif_date or "")
        if not m:
            return None
        y, mo, d, hh, mi = (int(m.group(i)) for i in range(1, 6))
        ss = int(m.group(6) or 0)
        return ((((y * 12 + mo) * 31 + d) * 24 + hh) * 60 + mi) * 60 + ss

    @staticmethod
    def _stop_name(photos):
        """클러스터 대표 이름 — 확신 이름 최빈, 없으면 전체 최빈(빈 값 제외)."""
        from collections import Counter
        conf = [p.get("location_name", "") for p in photos
                if p.get("name_confident") and p.get("location_name")]
        pool = conf or [p.get("location_name", "") for p in photos
                        if p.get("location_name")]
        return Counter(pool).most_common(1)[0][0] if pool else ""

    @staticmethod
    def _stops_for_day(items, gap_min=None, dist_m=None):
        """하루치 (pid, photo) 튜플 → 장소(stop) 목록. 입력 비변형.

        시간순으로 훑으며 직전 사진과 (시간차 ≤ gap AND 거리 ≤ dist)면 같은 stop
        으로 잇는 **세션 클러스터링**. 사람이 "한 장소"라고 부르는 것 = 그 자리에
        머무는 동안의 연속 촬영이라는 관찰에 기반한다.

        ⚠ 과거 구현은 '이름 우선 + ~110m 격자'였다. 무료 모드의 역지오코딩 세부명이
          같은 장소 안에서 관광지/공원/거리/신사/주차장으로 갈리고 격자 경계까지
          겹쳐 장소가 심하게 과분할됐다(실측: 62장 하루가 자동 31개 stop → 사용자가
          손으로 6개로 정리). 시간·거리는 이름 품질과 무관해 무료 모드에서 특히 강하다.
        """
        gap = (TripPlanner.STOP_GAP_MIN if gap_min is None else gap_min) * 60
        dist = TripPlanner.STOP_DIST_M if dist_m is None else dist_m

        # 시간순 정렬(호출부가 정렬을 보장하지 않음). 시간 없는 사진은 원래 순서 유지.
        ordered = sorted(
            enumerate(items),
            key=lambda t: (TripPlanner._exif_seconds(t[1][1].get("exif_date", ""))
                           is None,
                           TripPlanner._exif_seconds(t[1][1].get("exif_date", "")) or 0,
                           t[0]))
        ordered = [it for _, it in ordered]

        groups = []       # [{"pids": [...], "photos": [...], "t":, "lat":, "lon":}]
        for pid, p in ordered:
            g = p.get("gps") or {}
            lat, lon = g.get("lat"), g.get("lon")
            t = TripPlanner._exif_seconds(p.get("exif_date", ""))
            if groups:
                cur = groups[-1]
                same = True
                if t is not None and cur["t"] is not None:
                    same = same and abs(t - cur["t"]) <= gap
                if lat is not None and cur["lat"] is not None:
                    same = same and TripStructurer._haversine(
                        cur["lat"], cur["lon"], lat, lon) <= dist
                elif (lat is None) != (cur["lat"] is None):
                    same = False          # GPS 유/무가 갈리면 판단 불가 → 분리
                if same:
                    cur["pids"].append(pid)
                    cur["photos"].append(p)
                    if t is not None: cur["t"] = t
                    if lat is not None: cur["lat"], cur["lon"] = lat, lon
                    continue
            groups.append({"pids": [pid], "photos": [p],
                           "t": t, "lat": lat, "lon": lon})

        stops = []
        for order, grp in enumerate(groups, 1):
            pids, name = grp["pids"], TripPlanner._stop_name(grp["photos"])
            stops.append({
                "stop_id": "s" + pids[0][1:],
                "order": order,
                "name": name,
                "name_source": "auto" if name else "none",
                "events": [], "feeling": "", "ai_instruction": "",
                "rating": None, "receipt": None,
                "show_rating": True, "show_price": True,
                "photo_ids": list(pids),
            })
        return stops

    @staticmethod
    def match_receipts_to_stops(plan, receipts):
        """영수증을 가게명<->장소명 일치(+같은 날짜 우대)로 stop에 배정.
        이름 일치 없으면 미배정(추측 안 함). plan을 직접 갱신하고
        미배정은 plan['unmatched_receipts']에 둔다. 반환: (plan, unmatched)."""
        # 멱등성: 기존 배정 초기화 후 다시 매칭
        for d in plan.get("days", []):
            for s in d.get("stops", []):
                s["receipt"] = None
        unmatched = []
        for r in (receipts or []):
            store = (r or {}).get("store_name", "")
            rdate = (r or {}).get("date", "")
            best_score, candidates = 0, []
            for d in plan.get("days", []):
                date_match = bool(rdate) and d.get("date") == rdate
                for s in d.get("stops", []):
                    if ReceiptReader.crosscheck_name(store, s.get("name", "")):
                        score = 2 if date_match else 1
                        if score > best_score:
                            best_score, candidates = score, [s]
                        elif score == best_score:
                            candidates.append(s)
            # 동점(2곳 이상 동일 신뢰도)이면 추측하지 않고 미배정으로 남겨 사용자가 고르게 함
            if best_score > 0 and len(candidates) == 1:
                candidates[0]["receipt"] = r
            else:
                unmatched.append(r)
        plan["unmatched_receipts"] = unmatched
        return plan, unmatched

    @staticmethod
    def merge_user_edits(new_plan, old_plan):
        """재생성된 new_plan에 old_plan의 사용자 편집을 이식.
        photo_id 겹침이 가장 많은 구 stop을 매칭. 영수증은 제외(매칭이 별도 처리). 네트워크 X."""
        from collections import Counter
        old_stops = [s for d in (old_plan or {}).get("days", []) for s in d.get("stops", [])]
        pid_to_old = {}
        for i, s in enumerate(old_stops):
            for pid in s.get("photo_ids", []):
                pid_to_old[pid] = i
        for d in new_plan.get("days", []):
            for s in d.get("stops", []):
                c = Counter(pid_to_old[pid] for pid in s.get("photo_ids", []) if pid in pid_to_old)
                if not c:
                    continue
                old = old_stops[c.most_common(1)[0][0]]
                if old.get("name_source") == "user" and old.get("name"):
                    s["name"], s["name_source"] = old["name"], "user"
                for k in ("events", "feeling", "ai_instruction", "rating", "show_rating", "show_price"):
                    v = old.get(k)
                    if v not in (None, "", []):
                        s[k] = v
        return new_plan


class ReceiptReader:
    """영수증 이미지 → {store_name, amount, currency, date}. (이 태스크는 파싱만)"""

    _CUR = [("JPY", ["¥", "円", "JPY"]), ("KRW", ["₩", "원", "KRW"]),
            ("USD", ["$", "USD"])]

    @staticmethod
    def _parse_amount(text):
        """텍스트에서 (정수금액, 통화코드). 실패 시 (None, '')."""
        import re
        if not text:
            return (None, "")
        currency = ""
        for code, syms in ReceiptReader._CUR:
            if any(s in text for s in syms):
                currency = code; break
        nums = re.findall(r'\d[\d,]*(?:\.\d+)?', text)
        if not nums:
            return (None, "")
        vals = [int(float(n.replace(",", ""))) for n in nums]
        amount = max(vals) if vals else None
        if amount is None:
            return (None, "")
        return (amount, currency)

    def __init__(self, config):
        self.model = config.get("openai", "model") or "gpt-4o-mini"
        from openai import OpenAI
        self.client = OpenAI(api_key=config.get("openai", "api_key"))

    @staticmethod
    def crosscheck_name(store_name, stop_name):
        """가게명과 장소명이 충분히 유사하면 True(장소명 반영 제안용)."""
        def norm(s):
            return "".join((s or "").lower().split())
        a, b = norm(store_name), norm(stop_name)
        if not a or not b:
            return False
        short, long_ = sorted([a, b], key=len)
        if len(short) < 2:  # 한 글자 부분일치는 우연 매칭 위험이 커 제외
            return False
        return short in long_

    def read(self, image_path):
        """영수증 이미지 -> {store_name, amount, currency, date, ocr_source}.
        실패 시 빈 값(수동 입력 폴백). currency=='' 이면 통화 미상."""
        import base64, mimetypes, json
        out = {"store_name": "", "amount": None, "currency": "", "date": "",
               "ocr_source": "auto"}
        try:
            mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
            with open(image_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            prompt = (
                "이 영수증 이미지에서 다음을 JSON으로만 추출: "
                "store_name(가게명), total_text(합계 금액이 보이는 줄 원문 그대로, 통화기호 포함), "
                "date(YYYY-MM-DD). 모르면 빈 문자열."
            )
            r = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ]}],
                response_format={"type": "json_object"},
            )
            data = json.loads(r.choices[0].message.content)
            out["store_name"] = data.get("store_name", "") or ""
            out["date"] = data.get("date", "") or ""
            amount, currency = self._parse_amount(data.get("total_text", ""))
            out["amount"] = amount
            out["currency"] = currency
        except Exception as e:
            logger.warning("receipt OCR failed: %s", str(e))
        return out


# ============================================================
# 여행 블로그 글 생성기 v2
# ============================================================
class TravelBlogGenerator:
    def __init__(self, config):
        self.config = config
        self.model = config.get("openai","model") or "gpt-4o-mini"
        self.max_tok = int(config.get("openai","max_tokens") or 16000)
        from openai import OpenAI
        self.client = OpenAI(api_key=config.get("openai","api_key"))
        self.google_key = config.get("google","maps_api_key") or ""

    _CUR_SYM = {"JPY": "¥", "KRW": "₩", "USD": "$"}

    def _format_meta_line(self, rating, amount, currency, show_rating, show_price):
        """별점·가격을 텍스트 한 줄 HTML로. URL 없음. 표시할 게 없으면 ''."""
        parts = []
        if show_rating and rating is not None:
            parts.append(f"⭐ {rating:g}")
        if show_price and amount is not None:
            sym = self._CUR_SYM.get(currency, "")
            parts.append(f"{sym}{amount:,}")
        if not parts:
            return ""
        return '<p>' + ' / '.join(parts) + '</p>'

    # ─────────────────────────────────────────
    # 초안 3종 생성
    # ─────────────────────────────────────────
    def generate_drafts(self, group, group_label, trip_title="",
                        naver_analysis=None, style_analysis=None,
                        selected_structure=None, route_modes=None,
                        progress_cb=None):
        """
        하나의 그룹(일별/장소별/코스별)에 대해 3가지 초안 생성
        route_modes: {"장소A→장소B": "transit", "장소B→장소C": "walking", ...}
        progress_cb: 진행 상황 콜백 함수 (문자열 메시지)
        """
        def _progress(msg):
            if progress_cb:
                try: progress_cb(msg)
                except: pass
            logger.info(msg)

        photos = group["photos"]
        course_line = group.get("course_line","")

        _progress(f"⏳ 1/6 사진 요약 ({len(photos)}장)...")
        photo_summary = self._photo_summary(photos)

        _progress("⏳ 2/6 지역 감지...")
        region = self._detect_region(photos)
        region = self._koreanize_region(region)  # 네이버 SEO: 지역명 한글 정규화
        region_desc = self._generate_region_desc(region, naver_analysis)
        # 태그 확장(I5)용 방문 카테고리 수집 — 각 사진의 Vision scene_type/place_type
        place_types = [
            (p.get("vision", {}).get("scene_type") or p.get("vision", {}).get("place_type") or "")
            for p in photos
        ]
        place_types = [t for t in place_types if t]

        _progress("⏳ 3/6 장소 특징 검색...")
        place_intros = self._search_place_intros(photos)

        _progress("⏳ 4/6 경로 정보 조회...")
        route_data = self._fetch_route_data(photos, route_modes or {})

        styles = [
            {"name":"감성 후기형","desc":"감성적이고 서정적인 톤. 개인적 감상과 분위기 중심.","temp":0.9},
            {"name":"정보 가이드형","desc":"실용 정보 중심. 가격, 운영시간, 교통편 등 구체적 정보 포함.","temp":0.6},
            {"name":"코스 추천형","desc":"동선과 코스 중심. 시간 배분, 이동 방법 등 여행 계획에 도움.","temp":0.7},
        ]

        naver_ctx = self._naver_context(naver_analysis)
        style_ctx = self._style_context(style_analysis)
        # 어미 지시는 거대 프롬프트 속에서 희석돼 무시된다(실측: 규칙+설정충돌 제거
        # 후에도 해요체 회귀). 어미 패턴 "목록"을 주면 레지스터가 뒤섞인 혼합체가
        # 나온다(실측: 였다+답니다+더라고요 혼재) → 참고 문체의 지배 레지스터
        # (평서체 vs 해요체)를 판별해 이진 지시로 system 메시지에 주입한다.
        _endings = [e for e in ((style_analysis or {}).get("ending_patterns") or []) if e]
        _plain = sum(1 for e in _endings
                     if re.search(r'(다|였다|이다|한다|았다|었다|했다)\s*[.…]?\s*$', e))
        if _endings and _plain * 2 >= len(_endings):
            self._current_register = "plain"    # 반말 평서체(-다)
        elif _endings:
            self._current_register = "polite"   # 해요체
        else:
            self._current_register = None

        # 사용자 선택 구조 → 프롬프트에 반영
        struct_ctx = ""
        if selected_structure:
            if isinstance(selected_structure, str):
                # 웹에서 스타일명만 전달된 경우 ("감성 후기형" 등)
                # → 해당 스타일만 생성하도록 styles 필터링
                matched = [s for s in styles if s["name"] == selected_structure]
                if matched:
                    styles = matched  # 선택된 스타일 1개만 생성
            elif isinstance(selected_structure, list):
                # Tkinter에서 구조 체크박스 리스트 전달된 경우
                struct_lines = [f"  {i+1}. {s['type']}: {s['desc']}"
                               for i, s in enumerate(selected_structure)
                               if isinstance(s, dict)]
                if struct_lines:
                    struct_ctx = "\n[사용자 지정 글 구조 (반드시 이 순서대로 작성)]\n" + "\n".join(struct_lines) + "\n"

        self._current_route_modes = route_modes or {}
        self._current_route_data = route_data
        self._current_place_meta = group.get("place_meta", {})

        # 장소별 메모
        place_memos = group.get("place_memos", {})
        place_directives = group.get("place_directives", {})

        drafts = []
        for si, s in enumerate(styles):
            _progress(f"⏳ {si+5}/6 초안 생성: {s['name']}...")
            logger.info(f"📝 초안 생성: {s['name']}...")
            prompt = self._build_prompt(
                photos, photo_summary, course_line, region, region_desc,
                group_label, trip_title, s, naver_ctx, style_ctx,
                struct_ctx=struct_ctx, place_intros=place_intros,
                place_memos=place_memos, place_directives=place_directives,
            )
            post = self._call_ai(prompt, s["temp"], photos)
            if post:
                post["style"] = s["name"]
                if post.get("content"):
                    post["content"] = self._number_places(post["content"])
                # 지역 위키 박스를 글 최상단에 삽입 (있을 때만)
                if region_desc and post.get("content"):
                    post["content"] = region_desc + "\n" + post["content"]
                post["region_desc"] = region_desc
                post["course_line"] = course_line
                post["group_label"] = group_label
                post["region"] = region
                post["photo_results"] = photos
                # SEO 강제·검증 (E): 핵심 태그 병합 + 경고 부착
                # 태그 확장(I5): 핵심 태그 + 지역×방문카테고리 조합 태그(결정적) → AI 태그로 채움
                core_and_expand = self.extract_core_tags(naver_analysis, region) + self._expand_tags(region, place_types)
                post["tags"] = self.merge_tags(post.get("tags"), core_and_expand, cap=25)
                # 제목 최적화 (G6) — 실측 상위 제목 패턴 기반, 노출 관련은 코드가 강제
                best_title = self.optimize_title(post, naver_analysis, region)
                if best_title:
                    post["original_title"] = post.get("title", "")
                    post["title"] = best_title
                post["seo_warnings"] = self.seo_check(post, naver_analysis, region)
                drafts.append(post)
            time.sleep(1)

        logger.info(f"✅ {len(drafts)}개 초안 생성 완료")
        _progress(f"✅ {len(drafts)}개 초안 완료!")
        return drafts

    def _search_place_intros(self, photos):
        """장소별 특징을 AI에게 물어서 3줄 소개 생성"""
        from collections import OrderedDict
        places = OrderedDict()
        for r in photos:
            loc = r.get("location_name", "")
            if loc and loc not in places:
                places[loc] = {
                    "gps": r.get("gps"),
                    "scene_type": r.get("vision", {}).get("scene_type", ""),
                    "food": r.get("vision", {}).get("food_name", ""),
                }

        if not places:
            return ""

        # 한 번의 AI 호출로 모든 장소 특징을 검색
        place_list = []
        for i, (name, info) in enumerate(places.items(), 1):
            extras = []
            if info["scene_type"]: extras.append(f"장면: {info['scene_type']}")
            if info["food"]: extras.append(f"음식: {info['food']}")
            extra_str = f" ({', '.join(extras)})" if extras else ""
            place_list.append(f"{i}. {name}{extra_str}")

        prompt = (
            f"아래 여행지/맛집에 대해 각각 3줄로 짧게 특징을 소개해주세요.\n"
            f"실제 존재하는 정보만 작성하고, 모르면 '정보 부족'이라고 쓰세요.\n"
            f"형식: 장소명: (3줄 소개)\n\n"
            + "\n".join(place_list)
        )

        try:
            r = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=1500, temperature=0.5
            )
            result = r.choices[0].message.content.strip()
            logger.info(f"📍 {len(places)}개 장소 특징 검색 완료")
            return result
        except Exception as e:
            logger.warning(f"⚠️ 장소 특징 검색 실패: {e}")
            return ""

    def _detect_region(self, photos):
        """사진들에서 여행 지역 자동 감지 — 도시/지역명 우선"""
        from collections import Counter
        # 1순위: city 또는 region 필드
        cities = []
        regions = []
        for r in photos:
            city = r.get("city", "")
            region = r.get("region", "")
            if city: cities.append(city)
            if region: regions.append(region)

        # 가장 빈도 높은 도시명
        if cities:
            most_common = Counter(cities).most_common(1)[0][0]
            return most_common

        # 도시 없으면 지역명
        if regions:
            most_common = Counter(regions).most_common(1)[0][0]
            return most_common

        # 2순위: 장소명에서 중복 제거한 목록
        locations = []
        for r in photos:
            name = r.get("location_name", "")
            if name and name not in locations:
                locations.append(name)
        if locations:
            return " ".join(locations[:3])  # 최대 3곳

        return "여행지"

    def _koreanize_region(self, name):
        """네이버 SEO: 지역명을 한글 표기로 정규화 (로마자/외국어 → 한글).

        구글 지오코딩이 locality short_name을 로마자(예: Kitakyushu)로 반환하는 탓에
        지역명이 영문으로 들어가는 문제 보정. 한글이 이미 있으면 그대로,
        알파벳이 없으면 그대로, 그 외에는 GPT로 한글 지명 변환(세션 캐시).
        """
        if not name:
            return name
        if re.search(r'[가-힣]', name):      # 이미 한글 포함 → 그대로
            return name
        if not re.search(r'[A-Za-z]', name):  # 변환할 로마자 없음 → 그대로
            return name
        cache = getattr(self, '_region_ko_cache', None)
        if cache is None:
            cache = self._region_ko_cache = {}
        if name in cache:
            return cache[name]
        try:
            r = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content":
                        "지명을 한국어 표기로만 변환하는 도구. 설명·접미사 없이 한글 지명만 출력."},
                    {"role": "user", "content":
                        f"'{name}'의 한국어 지명 표기를 한 단어로만 답하세요. "
                        f"예: Fukuoka→후쿠오카, Kitakyushu→기타큐슈, Osaka→오사카, Tokyo→도쿄."}
                ],
                max_tokens=20, temperature=0
            )
            ko = (r.choices[0].message.content or "").strip().split()[0].strip(' .\"\'·')
            if ko and re.search(r'[가-힣]', ko):
                cache[name] = ko
                logger.info(f"🈯 지역명 한글화: {name} → {ko}")
                return ko
        except Exception as e:
            logger.warning(f"⚠️ 지역명 한글화 실패: {e}")
        return name

    def _generate_region_desc(self, region_hint, naver_analysis=None):
        """지역 위키 박스 생성 (AI) — 소개·특산품·먹거리·관광지 구조화 HTML 반환

        포스팅 최상단에 들어갈 '정보성 박스'. 디자인 시스템(올리브 #8B9467)에 맞춘
        스타일드 HTML을 코드에서 직접 조립하므로 AI가 형식을 망가뜨릴 여지가 없다.
        실패 시 "" 반환 → 호출부에서 박스 미삽입(글 생성은 정상 진행).
        """
        if not region_hint:
            return ""
        exclude = ("지역 미정", "위치 정보 오류", "장소 미정", "위치 정보 미정", "여행지")
        if region_hint.strip() in exclude:
            return ""
        # 실측 근거(E의 네이버 상위 블로그 분석) — 있으면 재료로 제공, 환각 방지 지시 유지
        evidence = ""
        na = naver_analysis or {}
        kws = [k for k in (na.get("common_keywords") or []) if k][:10]
        top_titles = [t for t in (na.get("top_titles") or []) if t][:5]
        if kws or top_titles:
            evidence = (
                "\n[실측 참고 — 이 지역 검색 상위 블로그의 빈출 키워드/제목입니다. "
                "이 중 당신이 확실히 아는 것만 반영하고, 모르는 것은 무시하세요.]\n"
                + (f"키워드: {', '.join(kws)}\n" if kws else "")
                + (f"상위 글 제목: {' / '.join(top_titles)}\n" if top_titles else "")
            )
        try:
            r = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content":
                        "정확한 지역 백과사전. 도시·현 레벨에서 전국적으로 유명하고 확실히 아는 것만 답한다. "
                        "조금이라도 불확실하면 그 항목을 비운다 — 개수를 채우려고 지어내지 않는다. "
                        "인접 현·다른 지방의 명소·특산품·음식을 절대 섞지 않는다. "
                        "동·구·번지 단위의 작은 가게나 소규모 명소는 넣지 않는다. JSON으로만 응답."},
                    {"role": "user", "content":
                        f"'{region_hint}' 여행 전 꼭 알아야 할 핵심 정보를 아래 JSON 형식으로만 응답하세요.\n"
                        f"모든 값은 한국어. specialties/foods/spots는 각 0~6개, tips(여행 실용 팁)는 0~3개, "
                        f"access(대표 접근 교통)는 0~2개 배열 — "
                        f"'{region_hint}' 안에 실제로 있고 전국적으로 유명한 것만 넣으세요. "
                        f"확실하지 않으면 빈 배열로 두세요(개수 채우기 절대 금지).\n"
                        f"{evidence}"
                        '{"intro":"4~6줄 지역 소개(확실한 사실만)","specialties":[],'
                        '"foods":[],"spots":[],"tips":[],"access":[]}'}
                ],
                max_tokens=900, temperature=0
            )
            txt = r.choices[0].message.content.strip()
            if "```json" in txt:
                txt = txt.split("```json")[1].split("```")[0].strip()
            elif "```" in txt:
                txt = txt.split("```")[1].split("```")[0].strip()
            data = json.loads(txt)

            intro = (data.get("intro") or "").strip()
            specialties = [s for s in (data.get("specialties") or []) if s][:6]
            foods = [s for s in (data.get("foods") or []) if s][:6]
            spots = [s for s in (data.get("spots") or []) if s][:6]
            tips = [s for s in (data.get("tips") or []) if s][:3]
            access = [s for s in (data.get("access") or []) if s][:2]
            if not intro and not (specialties or foods or spots or tips or access):
                return ""

            rows = []
            if specialties:
                rows.append(("🎁 특산품", " · ".join(specialties)))
            if foods:
                rows.append(("🍽 먹거리", " · ".join(foods)))
            if spots:
                rows.append(("🗺 관광지", " · ".join(spots)))
            if access:
                rows.append(("🚌 가는 법", " · ".join(access)))
            if tips:
                rows.append(("💡 여행 팁", " · ".join(tips)))
            row_html = "".join(
                f'<p style="font-size:0.9em;color:#3d3d3d;line-height:1.9;margin:6px 0">'
                f'<b style="color:#8B9467">{label}</b>  {val}</p>'
                for label, val in rows
            )
            intro_html = (
                f'<p style="font-size:0.92em;color:#555;line-height:1.9;margin:0 0 14px">{intro}</p>'
                if intro else ""
            )
            box = (
                '<div style="background:#f7f8f3;border:1px solid #e3e7d8;border-radius:12px;'
                'padding:24px;margin:10px 0 24px">'
                f'<h3 style="text-align:center;font-size:1.15em;color:#3d3d3d;margin:0 0 16px;font-weight:600">'
                f'📍 {region_hint} 여행 전 꼭 알아야 할 핵심 정보</h3>'
                f'{intro_html}{row_html}'
                '</div>'
            )
            logger.info(f"📍 지역 위키 박스 생성: {region_hint} (특산품{len(specialties)}/먹거리{len(foods)}/관광지{len(spots)}/팁{len(tips)}/교통{len(access)})")
            return box
        except Exception as e:
            logger.warning(f"⚠️ 지역 위키 박스 생성 실패: {e}")
            return ""

    def _build_prompt(self, photos, photo_summary, course_line, region,
                      region_desc, group_label, trip_title, style, naver_ctx, style_ctx,
                      struct_ctx="", place_intros="", place_memos=None, place_directives=None):
        """AI 프롬프트 생성 — 세련된 여행 블로그 디자인"""
        title_hint = trip_title or "사진 데이터를 보고 매력적인 제목 생성"

        # 구글맵/경로는 코드에서 자동 삽입 — AI에게 지시 불필요
        gmap_note = ""

        # 장소 목록 생성
        from collections import OrderedDict
        place_photos = OrderedDict()
        for r in photos:
            loc = r.get("location_name", "") or "미확인"
            if loc not in place_photos:
                place_photos[loc] = []
            place_photos[loc].append(r.get("file_name", ""))
        places_str = "\n".join(
            f"  - {p} ({len(fns)}장: {', '.join(fns)})" for p, fns in place_photos.items()
        )
        place_list = list(place_photos.keys())
        num_places = len(place_list)

        # 사진이 많은 그룹은 AI가 전 사진을 배치·설명하게 하면 응답이 max_tokens에
        # 잘려 생성 자체가 실패한다(finish_reason=length — 34/62장 그룹 사고).
        # → 20장 초과 시 장소당 대표 태그 1개만 지시하고 나머지는 코드가 자동 배치
        #   (_insert_photos_with_map 2단계 h2 매칭). "형식은 코드가 조립" 원칙.
        # 문체 프로파일이 있으면(문체 따라하기) 하드코딩 구어체 규칙이 그걸 덮지 않게 양보
        tone_rule = ('2. ★★★ 말투: [참고 문체]가 최우선 ★★★\n'
                     '   - 문장 어미는 [참고 문체]에 명시된 어미 패턴만 사용하세요 '
                     '(예시에 없는 "~했어요","~답니다" 금지)\n'
                     '   - 톤·습관도 [참고 문체]를 따르세요 — 다른 규칙의 예시 어미보다 [참고 문체]가 우선'
                     if (style_ctx or "").strip() else
                     '2. 말투: 친근한 구어체 "~했어요","~더라고요", 센스있는 표현')

        per_place_photo = len(photos) > 40
        if per_place_photo:
            rep_tags = "\n".join(
                f"   - {p} → [PHOTO:{fns[0]}]"
                for p, fns in place_photos.items() if fns and fns[0])
            photo_rules = f"""4. ★★★ 사진 태그는 장소당 대표 1개만! (사진이 많은 날) ★★★
   - 아래 대표 태그를 각 장소 섹션의 (C) 위치에 정확히 1개씩만 넣으세요:
{rep_tags}
   - 그 외 [PHOTO:] 태그는 절대 넣지 마세요 — 나머지 사진은 시스템이 자동 배치합니다
   - 각 대표 태그 아래에 그 장소에서 찍은 사진들에 대한 감상을 2~3줄 <p>로 작성

5. ★★★ 분량 절제 ★★★
   - 장소가 많은 날이므로 장소당 소개·설명을 간결하게 — 응답 전체가 잘리면 안 됩니다"""
        else:
            photo_rules = f"""4. ★★★ 사진마다 2~3줄 설명 필수! ★★★
   - 모든 [PHOTO:파일명] 바로 아래에 <p> 태그로 2~3줄 감상
   - scene_description, food_name 참고하여 구체적 묘사
   - 오감을 자극하는 표현 사용 (시각, 미각, 촉각, 후각)

5. ★★★ 사진 배치 ★★★
   - 총 {len(photos)}장이므로 [PHOTO:] 태그도 정확히 {len(photos)}개
   - 사진 → 텍스트 → 사진 → 텍스트 리듬감 있게 반복"""

        # 장소별 사용자 메모
        memo_ctx = ""
        if place_memos:
            memo_lines = []
            for loc, memo in place_memos.items():
                if memo.strip():
                    memo_lines.append(f"  - {loc}: {memo}")
            if memo_lines:
                memo_ctx = (
                    "\n[사용자 메모 — 글에 반드시 자연스럽게 반영하세요]\n"
                    + "\n".join(memo_lines) + "\n"
                )

        # 장소별 필수 지시 (plan 검수에서 입력) — 일반 메모보다 격상, 최우선 준수
        directive_ctx = ""
        if place_directives:
            d_lines = [f"  - {loc}: {d}" for loc, d in place_directives.items() if str(d).strip()]
            if d_lines:
                directive_ctx = (
                    "\n[장소별 필수 지시 — 아래 지시는 반드시 그대로 따르세요. "
                    "다른 규칙과 충돌하면 이 지시가 우선합니다]\n"
                    + "\n".join(d_lines) + "\n"
                )

        # 사용자 커스텀 스타일 설정 (settings.json에서)
        custom_style_ctx = ""
        if hasattr(self, '_custom_style_prompt') and self._custom_style_prompt:
            csp = self._custom_style_prompt
            if (style_ctx or "").strip():
                # 참고 문체(문체 따라하기)가 있으면 설정의 말투/톤 기본값
                # ('친근 구어체' 등)이 그것을 되덮지 않게 해당 줄만 제거.
                # 상충 지시 2개가 공존하면 모델이 구어체로 회귀한다(실측).
                csp = "\n".join(l for l in csp.split("\n")
                                if not re.match(r'\s*-\s*(말투|톤)\s*:', l))
            custom_style_ctx = "\n" + csp + "\n"

        # 일정 일수 판별 (그룹 라벨에서)
        import re as _re
        day_match = _re.search(r'(\d+)일', group_label or "")
        num_days = int(day_match.group(1)) if day_match else 1

        return f"""당신은 월 방문자 10만의 인기 여행 블로거입니다.
감성적이면서도 정보가 풍부한, 읽고 싶어지는 여행 포스팅을 작성하세요.

[글 스타일]: {style['name']} - {style['desc']}
[그룹]: {group_label}
[제목 힌트]: {title_hint}
[제목 규칙]: 제목은 한글로, 지역+테마 중심. 확실하지 않은 추정 상호명(특히 영문)을 제목에 넣지 마세요.
[코스]: {course_line}
{naver_ctx}{style_ctx}{struct_ctx}{memo_ctx}{directive_ctx}{custom_style_ctx}
[방문 장소 목록 (시간순, 장소별 사진 수)]:
{places_str}

★★★ 위 장소 목록의 순서대로, 각 장소별로 섹션을 만들어 글을 작성하세요 ★★★
같은 장소의 사진은 해당 장소 섹션에 모두 포함해야 합니다.

★★★ 장소명 규칙(필수) ★★★
- 위 [방문 장소 목록]에 있는 이름만 사용하세요.
- 목록에 없는 새 가게/상호명을 절대 지어내지 마세요. (예: 목록에 없는 "둥부르","두번" 같은 이름 생성 금지)
- <h2 data-place="..."> 의 장소명은 목록의 이름과 정확히 일치해야 합니다.

[장소별 특징 소개 (검색 결과 — 글에 자연스럽게 반영하세요)]:
{place_intros if place_intros else "(검색 결과 없음 — 사진 데이터만으로 작성)"}

[묘사 원칙 — 반드시 지킬 것]
- 사진에 실제로 보이는 것과 위 장소 정보만 묘사하세요. (제목 포함)
- 확인할 수 없는 인테리어 분위기·재료 출처·메뉴 구성·영업 방식을 단정하지 마세요. 보이는 사실만.
- 같은 형용사·문장을 여러 장소/사진에 반복하지 마세요. 각 장소·사진마다 새로운 표현으로.
- 사진 설명은 그 사진의 구체적 장면을 오감으로 묘사(색·질감·맛·소리·온도). 다른 사진과 같은 문장 금지.

[사진 참고 데이터]:
{photo_summary}

═══════════════════════════════════════
★★★ 디자인 규칙 (가장 중요! 반드시 정확히 따르세요) ★★★
═══════════════════════════════════════

[전체 HTML 구조 — 이 순서를 정확히 따르세요]

1️⃣ 인트로 영역:
<div style="text-align:center;padding:20px 0">
<p style="font-size:1.1em;color:#8B9467;letter-spacing:2px">✈ {region} 여행기 ✈</p>
<br/>
<p style="font-size:0.95em;color:#888;line-height:1.8">
📍 {course_line}
</p>
<br/>
<p style="font-size:0.95em;color:#666;line-height:2.0">
(2~3줄 일정 소개글)
</p>
</div>

<p style="text-align:center;color:#d4d4d4;letter-spacing:8px">─ ─ ─ ─ ─ ─ ─</p>

2️⃣ 장소별 섹션 — ★★★ 아래 순서를 반드시 지키세요! ★★★

각 장소마다 아래 순서로 작성:

(A) 장소 헤더:
<div style="text-align:center;padding:30px 0 15px">
<p style="font-size:0.8em;color:#8B9467;letter-spacing:3px">PLACE N</p>
<h2 data-place="장소명" style="font-size:1.3em;color:#3d3d3d;margin:8px 0;font-weight:600">장소명 한글 (현지어)</h2>
</div>

(B) ★★★ 장소 소개글 3~4줄 (필수!) ★★★:
<p style="text-align:center;font-size:0.92em;color:#555;line-height:2.0">
이 장소가 어떤 곳인지, 무엇이 유명한지, 어떤 분위기인지 3~4문장으로 소개.
[장소별 특징 소개] 데이터를 참고하여 자연스럽게 작성.
예) "야키니쿠 라이크는 1인 야키니쿠 전문점으로, 혼밥족들에게 특히 인기가 많은 곳이에요.
합리적인 가격에 다양한 부위를 즐길 수 있고, 각 테이블에 개별 그릴이 있어 편하게 고기를 구워 먹을 수 있답니다."
</p>
<br/>

(C) 사진 + 사진설명 (반복):
[PHOTO:파일명]
<p style="text-align:center;font-size:0.92em;color:#555;line-height:2.0">
(이 사진에 대한 감상/설명 2~3줄)
</p>
<br/>

[PHOTO:파일명]
<p style="text-align:center;font-size:0.92em;color:#555;line-height:2.0">
(다음 사진 설명 2~3줄)
</p>

(D) 구글맵은 넣지 마세요! (코드에서 자동 삽입됩니다)

(E) 장소 구분선:
<p style="text-align:center;color:#d4d4d4;letter-spacing:8px">─ ─ ─ ─ ─ ─ ─</p>

(F) 이동 경로는 넣지 마세요! (코드에서 자동 삽입됩니다)

(다음 장소의 (A)부터 반복...)

3️⃣ 꿀팁 영역: (일반론 금지 — 장소 유형/사진 근거 기반 구체 팁만. 마땅치 않으면 2개로 줄이세요)
<p style="text-align:center;color:#d4d4d4;letter-spacing:8px">─ ─ ─ ─ ─ ─ ─</p>
<div style="text-align:center;padding:20px 0">
<p style="font-size:0.8em;color:#8B9467;letter-spacing:3px">TRAVEL TIPS</p>
<h3 style="font-size:1.1em;color:#3d3d3d;margin:8px 0">🧳 여행 꿀팁!</h3>
</div>
<div style="text-align:center;font-size:0.9em;color:#666;line-height:2.2">
<p>✔ 팁 내용 1</p>
<p>✔ 팁 내용 2</p>
<p>✔ 팁 내용 3</p>
<p>✔ 팁 내용 4</p>
</div>

4️⃣ 아웃트로:
<p style="text-align:center;color:#d4d4d4;letter-spacing:8px">─ ─ ─ ─ ─ ─ ─</p>
<div style="text-align:center;padding:20px 0;font-size:0.92em;color:#666;line-height:2.0">
<p>(마무리 인사 2~3줄)</p>
<br/>
<p style="color:#8B9467;font-size:0.85em">✈ 다음 여행기에서 또 만나요 ✈</p>
</div>

═══════════════════════════════════════

[필수 규칙]
1. ★★★ 장소명·순서 규칙 ★★★
   - 반드시 "한글이름 (현지어)" 형식: 예) 시노자키 신사 (篠崎神社)
   - 로마자 절대 금지! Matsubara(X) → 마쓰바라(O)
   - [방문 장소 목록]에 없는 상호명을 새로 지어내지 마세요. 목록의 이름만 사용.
   - 장소 섹션은 반드시 [코스]에 나온 방문 순서 그대로 작성 (순서 변경 절대 금지)

{tone_rule}

3. ★★★ 장소 소개글 3~4줄 필수! (가장 중요!) ★★★
   - 장소 헤더 바로 아래, 사진 위에 반드시 3~4문장 소개글
   - [장소별 특징 소개] 데이터가 있으면 반드시 활용
   - 소개글이 없는 장소 섹션은 절대 안 됨!

{photo_rules}

6. ★★★ 구글맵/이동경로 HTML을 절대 넣지 마세요 ★★★
   - 구글맵 링크, iframe, maps URL은 코드에서 자동 삽입됩니다
   - AI가 직접 구글맵 관련 HTML을 쓰면 중복됩니다!
   - 이동 경로 안내도 코드에서 자동 삽입됩니다
   - "📍 지도에서 보기", "📍 경로 보기" 같은 텍스트도 넣지 마세요

7. ★★★ 구분선으로 장소 구분 ★★★
   - 장소가 바뀔 때마다: <p style="text-align:center;color:#d4d4d4;letter-spacing:8px">─ ─ ─ ─ ─ ─ ─</p>

8. ★★★ 색상 & 크기 일관성 ★★★
   - 포인트 색상: #8B9467 — 섹션 라벨, 강조
   - 본문 색상: #555 — 가독성 좋은 부드러운 톤
   - 제목: #3d3d3d, font-size:1.3em
   - 본문: font-size:0.92em, line-height:2.0

9. 정확성: 데이터에 없는 구체적 사실(가격 등) 지어내지 않기

10. ★★★ 추천 대상 문장 ★★★
   - 각 장소 소개에 "어떤 사람에게 추천하는지" 문장을 1개 자연스럽게 포함하라
     (예: "혼자 조용히 여행하는 사람에게 특히 추천한다")

11. ★★★ 실용 정보는 근거 있는 것만 ★★★
   - 가격·영업시간 등 실용 정보는 장소별 지시·영수증·실측 참고 자료에 명시된 것만 서술하라.
     자료에 없는 숫자·시간을 지어내지 말 것

12. ★★★ 짧은 단락 리듬 ★★★
   - 한 단락은 2~4문장으로 짧게 끊어라. 각 장소는 경험담 → 실용정보 → 추천 순으로 전개하라

[JSON 응답]
{{"title":"제목 30~50자","content":"HTML본문","meta_description":"150자","tags":["태그x7"],"hashtags":["#해시x5"]}}"""

    # ── 결정적 후처리 스크럽 ──
    FABRICATION_PHRASES = [
        "신선한 재료로 만든", "신선한 재료로", "엄선된 재료로", "엄선된 재료의",
        "정성껏 만든", "정성을 다해 만든", "고급스러운 인테리어의", "고급스러운 인테리어",
        "모던한 인테리어의", "모던한 인테리어", "세련된 인테리어의", "세련된 인테리어",
        "일본식 커피 전문점", "현지인들이 즐겨 찾는", "현지인이 즐겨 찾는",
    ]
    CLICHE_WORDS = ["아늑한", "여유로운", "편안한", "완벽한", "포근한"]
    CLICHE_CAP = 2

    def _scrub_content(self, content):
        """결정적 후처리: 날조 수식구 제거 + 상투어 2회 초과분 형용사 제거.
        Korean 어구만 타깃이라 HTML 태그/base64는 건드리지 않는다."""
        if not content:
            return content
        import re as _re
        for ph in self.FABRICATION_PHRASES:
            content = content.replace(ph + " ", "").replace(ph, "")
        for w in self.CLICHE_WORDS:
            cnt = {"n": 0}
            def _rep(m):
                cnt["n"] += 1
                return m.group(0) if cnt["n"] <= self.CLICHE_CAP else ""
            content = _re.sub(_re.escape(w) + r"\s?", _rep, content)
        content = _re.sub(r"  +", " ", content)
        content = _re.sub(r"\s+([.,!?])", r"\1", content)
        return content

    def _scrub_title(self, title, bad_names=None):
        """제목에서 비신뢰 상호명/영문 토큰 제거 + 구두점 정리. 다 지워지면 원본 유지."""
        import re as _re
        t = title or ""
        for nm in (bad_names or []):
            if nm:
                t = t.replace(nm, "")
        # 한글 제목 기준 — 남은 라틴 문자 런(영문 상호) 제거
        t = _re.sub(r"[A-Za-z][A-Za-z0-9'&.\- ]*[A-Za-z0-9]", "", t)
        t = _re.sub(r"\s*[,·:\-]\s*$", "", t)
        t = _re.sub(r"^\s*[,·:\-]\s*", "", t)
        t = _re.sub(r"\s*,\s*,", ",", t)
        t = _re.sub(r"\s+([,.])", r"\1", t)
        t = _re.sub(r"  +", " ", t).strip()
        return t or (title or "")

    def _call_ai(self, prompt, temperature, photos):
        """AI 호출 + 사진 삽입 + 구글맵 링크 삽입 + 결정적 스크럽.
        장소가 많은 그룹은 응답이 max_tokens에 잘려 JSON이 미완성으로 온다
        (finish_reason=length, 'Unterminated string') → 분량 축소 지시를 붙여
        최대 3회 재시도. 전부 실패하면 None(호출부가 실패로 보고해야 함)."""
        for attempt in range(3):
            extra = ""
            if attempt:
                pct = "70%" if attempt == 1 else "50%"
                extra = (f"\n\n[중요] 직전 응답이 길이 제한으로 잘렸습니다. "
                         f"본문 전체 분량을 {pct} 수준으로 줄이세요 — 장소별 설명을 "
                         f"더 간결하게, 사진 설명은 1줄로. JSON을 반드시 완결하세요.")
            sys_msg = "인기 여행 블로거. 한글(현지어) 표기. JSON만 응답. 절대 구글맵 URL이나 이동경로 HTML을 넣지 마세요 - 자동 삽입됩니다. 사진에 보이는 사실과 제공된 장소 정보만 쓰고 확인 불가한 인테리어·재료·메뉴를 지어내지 마세요. 같은 형용사(아늑한/여유로운/편안한 등)를 반복하지 말고 장소마다 다르게 묘사하세요."
            register = getattr(self, "_current_register", None)
            if register == "plain":
                sys_msg += (" 글 전체를 반말 평서체(문어체)로만 작성하세요 — 모든 문장이"
                            " '-다'로 끝나야 합니다(예: ~였다, ~다고 한다, ~인상적이었다)."
                            " 존댓말 어미(~요, ~니다, ~했어요, ~답니다, ~네요)는 단 한 문장도 금지.")
            elif register == "polite":
                sys_msg += " 글 전체를 해요체로 일관되게 작성하세요(어미 혼용 금지)."
            try:
                r = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role":"system","content":sys_msg},
                        {"role":"user","content":prompt + extra}
                    ],
                    temperature=temperature, max_tokens=self.max_tok
                )
                choice = r.choices[0]
                txt = choice.message.content.strip()
                if "```json" in txt: txt=txt.split("```json")[1].split("```")[0].strip()
                elif "```" in txt: txt=txt.split("```")[1].split("```")[0].strip()
                if getattr(choice, "finish_reason", "") == "length":
                    logger.warning(f"⚠️ AI 응답이 길이 제한으로 잘림 (시도 {attempt+1}/3) → 분량 축소 재시도")
                    logger.warning(f"   [디버그] 응답 {len(txt)}자 | 머리: {txt[:200]!r}")
                    logger.warning(f"   [디버그] 꼬리: {txt[-300:]!r}")
                    continue
                post = json.loads(txt)
            except json.JSONDecodeError as e:
                logger.warning(f"⚠️ AI 응답 JSON 파싱 실패 (시도 {attempt+1}/3): {e}")
                continue
            except Exception as e:
                logger.error(f"❌ AI 생성 오류: {e}"); return None
            try:
                post["content"] = self._insert_photos_with_map(post["content"], photos)
                post["content"] = self._scrub_content(post["content"])
                bad = [r.get("location_name", "") for r in photos
                       if r.get("location_name") and not r.get("name_confident")]
                if post.get("title"):
                    post["title"] = self._scrub_title(post["title"], bad)
                return post
            except Exception as e:
                logger.error(f"❌ AI 생성 후처리 오류: {e}"); return None
        logger.error("❌ AI 생성 실패: 3회 모두 응답이 잘리거나 JSON 파싱 실패")
        return None

    # ─────────────────────────────────────────
    # 하위호환: 일별 글 생성
    # ─────────────────────────────────────────
    def generate_by_days(self, day_groups, trip_title="",
                         naver_analysis=None, style_analysis=None):
        posts = []
        for day in day_groups:
            drafts = self.generate_drafts(day, day["label"], trip_title, naver_analysis, style_analysis)
            if drafts:
                posts.append(drafts[0])  # 첫 번째 초안 사용
        return posts

    def generate(self, photo_results, trip_title="",
                 naver_analysis=None, style_analysis=None):
        group = {"photos":photo_results, "label":"전체", "course_line":""}
        drafts = self.generate_drafts(group, "전체", trip_title, naver_analysis, style_analysis)
        return drafts[0] if drafts else None

    # ─────────────────────────────────────────
    # 사진 + 구글맵 링크 삽입
    # ─────────────────────────────────────────
    @staticmethod
    def _dedupe_separators(content):
        """연속된 구분선(─) 문단을 1개로 정규화.
        AI가 인접 구분선을 중복 출력하는 경우를 대비. 본문이 사이에 끼면(비인접) 보존."""
        sep = r'<p[^>]*>\s*─[\s─]*</p>'
        return re.sub(
            rf'(?:{sep})(?:\s*(?:<br\s*/?>)?\s*(?:{sep}))+',
            '<p style="text-align:center;color:#d4d4d4;letter-spacing:8px">─ ─ ─ ─ ─ ─ ─</p>',
            content)

    @staticmethod
    def _number_places(content):
        """AI가 채번하지 않고 남긴 'PLACE N' 리터럴을 등장 순서대로 1,2,3…으로 치환.
        (형식은 코드가 조립 — AI 채번 의존 제거) 이미 숫자면 무변경. 순수함수."""
        if not content or "PLACE N" not in content:
            return content or ""
        counter = {"n": 0}
        def _sub(m):
            counter["n"] += 1
            return f"PLACE {counter['n']}"
        return re.sub(r"PLACE N\b", _sub, content)

    @staticmethod
    def _find_asset_spans(content):
        """코드 조립물(사진 figure·위키박스·경로카드) 구간 [(start,end)]을 찾는다.
        div 블록은 중첩이 있어 깊이 카운트로 닫는 지점을 찾는다. 순수함수."""
        spans = []
        for m in re.finditer(r'<figure[^>]*>.*?</figure>', content, re.DOTALL | re.IGNORECASE):
            spans.append((m.start(), m.end()))
        opener = re.compile(
            r'<div[^>]*style="[^"]*(?:background:#f7f8f3|linear-gradient)[^"]*"[^>]*>',
            re.IGNORECASE)
        for m in opener.finditer(content):
            depth = 0
            for t in re.finditer(r'<div\b|</div>', content[m.start():], re.IGNORECASE):
                depth += 1 if t.group().lower().startswith('<div') else -1
                if depth == 0:
                    spans.append((m.start(), m.start() + t.end()))
                    break
        spans.sort()
        merged = []
        for s, e in spans:
            if merged and s < merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))
        return merged

    @staticmethod
    def _protect_assets(content):
        """코드 조립물을 [KEEP_n] 토큰으로 치환 → (경량 텍스트, 자산 리스트).
        AI에게는 텍스트만 주므로 사진/박스/카드를 물리적으로 만질 수 없다."""
        content = content or ""
        spans = TravelBlogGenerator._find_asset_spans(content)
        assets, out, prev = [], [], 0
        for s, e in spans:
            out.append(content[prev:s])
            out.append(f"[KEEP_{len(assets) + 1}]")
            assets.append(content[s:e])
            prev = e
        out.append(content[prev:])
        return "".join(out), assets

    @staticmethod
    def _restore_assets(text, assets):
        """[KEEP_n] 토큰을 원 자산으로 복원. 각 토큰이 정확히 1회씩 없거나
        미지 토큰이 남으면 None(= revise 거부, 원본 유지)."""
        if text is None:
            return None
        for i in range(len(assets), 0, -1):
            tok = f"[KEEP_{i}]"
            if text.count(tok) != 1:
                return None
            text = text.replace(tok, assets[i - 1])
        if re.search(r'\[KEEP_\d+\]', text):
            return None
        return text

    def revise_draft(self, post, feedback, naver_analysis=None):
        """가안 + 자연어 피드백 → 최종본 post 재작성. 실패 시 None(원본 무손상).
        코드 조립물은 [KEEP_n]으로 잠가 AI가 만질 수 없다(형식은 코드 불변식)."""
        feedback = (feedback or "").strip()
        content = (post or {}).get("content") or ""
        if not feedback or not content:
            return None
        text, assets = self._protect_assets(content)
        prompt = (
            "아래는 여행 블로그 글(HTML 조각)이다. 사용자 피드백을 반영해 수정하라.\n"
            "[규칙]\n"
            "1. 피드백에 해당하는 부분만 고치고, 나머지 문장·HTML 태그·구조는 그대로 유지한다.\n"
            "2. [KEEP_숫자] 토큰은 절대 추가/삭제/수정하지 않는다 — 원래 자리에 그대로 둔다.\n"
            "3. 구글맵/이동경로/URL/이미지 태그를 새로 넣지 않는다 (코드가 자동 삽입).\n"
            "4. 수정된 글 전체를 그대로 출력한다. 설명·코드펜스 금지.\n\n"
            f"[사용자 피드백]\n{feedback}\n\n[글]\n{text}"
        )
        try:
            r = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4, max_tokens=self.max_tok,
            )
            out = (r.choices[0].message.content or "").strip()
        except Exception as e:
            logger.warning(f"⚠️ 피드백 재작성 LLM 실패: {e}")
            return None
        if out.startswith("```"):
            out = re.sub(r'^```[a-zA-Z]*\n?', '', out)
            out = re.sub(r'\n?```$', '', out).strip()
        restored = self._restore_assets(out, assets)
        if not restored:
            logger.warning("⚠️ 피드백 재작성 거부: KEEP 토큰 결손/중복 — 원본 유지")
            return None
        if out.count("http") > text.count("http"):
            logger.warning("⚠️ 피드백 재작성 거부: 신규 URL 유입 — 원본 유지")
            return None
        new_post = dict(post)
        new_post["content"] = self._number_places(restored)
        new_post["seo_warnings"] = self.seo_check(
            new_post, naver_analysis, (post or {}).get("region", ""))
        return new_post

    @staticmethod
    def _compose_collage(paths, out_dir=None):
        """같은 장소 사진 2장을 EXIF 방향 보정 후 가로로 이어붙여 콜라주 이미지 생성
        - 높이 1080px로 정규화(비율 유지) 후 사이 8px 흰 여백을 두고 결합
        - JPEG q85로 임시파일 저장, 경로 반환
        - 입력이 2장 미만이거나 파일 오류 시 None (호출부가 단독 삽입으로 폴백)
        """
        if not paths or len(paths) < 2:
            return None
        try:
            from PIL import Image, ImageOps
            import tempfile

            resized = []
            target_h = 1080
            for p in paths[:2]:
                if not p or not os.path.exists(p):
                    return None
                with Image.open(p) as src:
                    img = src
                    try:
                        img = ImageOps.exif_transpose(img)
                    except Exception:
                        pass
                    if img.mode != 'RGB':
                        img = img.convert('RGB')
                    w, h = img.size
                    if h != target_h and h > 0:
                        new_w = max(1, round(w * target_h / h))
                        img = img.resize((new_w, target_h), Image.LANCZOS)
                    else:
                        img = img.copy()
                    resized.append(img)

            gap = 8
            total_w = sum(im.width for im in resized) + gap
            canvas = Image.new('RGB', (total_w, target_h), (255, 255, 255))
            x = 0
            for im in resized:
                canvas.paste(im, (x, 0))
                x += im.width + gap

            fd, tmp_path = tempfile.mkstemp(suffix='.jpg', dir=out_dir)
            os.close(fd)
            canvas.save(tmp_path, format='JPEG', quality=85)
            return tmp_path
        except Exception as e:
            logger.warning(f"⚠️ 콜라주 합성 실패: {e}")
            return None

    def _insert_photos_with_map(self, content, results):
        """장소 매칭 기반 사진 삽입
        - 같은 장소 사진 2장은 콜라주로 합성해 한 장으로 삽입(홀수 마지막 1장은 단독)
        - 같은 장소 중 마지막 청크에만 지도 1개
        - 장소→장소 이동 경로 안내
        """
        inserted = set()

        # 장소별 그룹핑 (순서 유지)
        from collections import OrderedDict
        place_groups = OrderedDict()
        for r in results:
            loc = r.get("location_name", "") or "미확인"
            if loc not in place_groups:
                place_groups[loc] = []
            place_groups[loc].append(r)

        # 장소별 렌더 유닛 구성: 2장씩 콜라주 청크(홀수 마지막은 단독), 마지막 청크만 지도 표시
        units = []
        for loc, photos in place_groups.items():
            chunks = [photos[i:i + 2] for i in range(0, len(photos), 2)]
            for ci, chunk in enumerate(chunks):
                is_last_chunk = (ci == len(chunks) - 1)
                collage_path = None
                if len(chunk) == 2:
                    collage_path = self._compose_collage(
                        [p.get("file_path", "") for p in chunk])

                if collage_path:
                    rep = chunk[-1]  # 지도/GPS 대표는 청크의 마지막 사진
                    units.append({
                        "photos": chunk,
                        "fp": collage_path,
                        "display": self._display_name(rep),
                        "gps": rep.get("gps"),
                        "show_map": is_last_chunk,
                        "file_names": [p.get("file_name", "") for p in chunk],
                        "place_id": rep.get("place_id", ""),
                    })
                else:
                    for pi, r in enumerate(chunk):
                        is_last_photo = is_last_chunk and (pi == len(chunk) - 1)
                        units.append({
                            "photos": [r],
                            "fp": r.get("file_path", ""),
                            "display": self._display_name(r),
                            "gps": r.get("gps"),
                            "show_map": is_last_photo,
                            "file_names": [r.get("file_name", "")],
                            "place_id": r.get("place_id", ""),
                        })

        # 1단계: AI가 넣은 [PHOTO:] 태그 처리.
        #  사진 순서의 진실원은 계획검수/EXIF지 AI가 아니다 — AI는 태그를
        #  듬성듬성 달거나(per-place 모드 규칙 무시) 순서를 뒤집기도 한다(실측).
        #  ① 태그 위치가 유닛(EXIF) 순서와 역전되면 그 태그는 무시(강등),
        #  ② 태그 없는/강등된 유닛은 같은 장소의 "다음 앵커" 앞에 병합 삽입해
        #     시간순을 보존하고, 앵커 뒤 꼬리 유닛만 2단계(섹션 끝)로 넘긴다.
        def _unit_html(u):
            map_card_url = (f"https://www.google.com/maps/place/?q=place_id:{u['place_id']}"
                             if u.get("place_id") else None)
            return self._photo_html(
                u["fp"], u["display"], u["gps"], show_map=u["show_map"],
                map_card_url=map_card_url, src_files=u["file_names"])

        units_by_place = OrderedDict()
        for u in units:
            u["_placed"] = False
            loc0 = u["photos"][0].get("location_name", "")
            units_by_place.setdefault(loc0, []).append(u)

        for loc0, uls in units_by_place.items():
            # 앵커 확정: 태그가 존재하는 유닛 중, EXIF 순서와 태그 위치가 함께
            # 증가하는 최장 부분열(LIS)만 채택 — 역전 태그는 강등해 재배치.
            # (그리디로 하면 역전 태그가 먼저 승격돼 정상 태그들이 밀려난다)
            tag_pos = []
            for u in uls:
                tag = f"[PHOTO:{u['file_names'][0]}]"
                pos = content.find(tag)
                u["_anchor_tag"] = tag if pos >= 0 else None
                tag_pos.append(pos)
            cand = [(i, tag_pos[i]) for i in range(len(uls)) if tag_pos[i] >= 0]
            keep = set()
            if cand:
                n = len(cand)
                length = [1] * n
                prev = [-1] * n
                for i in range(n):
                    for j in range(i):
                        if cand[j][1] < cand[i][1] and length[j] + 1 > length[i]:
                            length[i] = length[j] + 1
                            prev[i] = j
                # 최장 체인, 동률이면 끝 태그 위치가 앞선 체인
                best = max(range(n), key=lambda k: (length[k], -cand[k][1]))
                while best != -1:
                    keep.add(cand[best][0])
                    best = prev[best]
            for i, u in enumerate(uls):
                if i not in keep:
                    u["_anchor_tag"] = None

            # 앵커 사이 누락 유닛을 다음 앵커 앞에 병합 (꼬리는 2단계로)
            pending = []
            for u in uls:
                if not u["_anchor_tag"]:
                    pending.append(u)
                    continue
                htmls = [_unit_html(p) for p in pending] + [_unit_html(u)]
                content = content.replace(
                    u["_anchor_tag"], "\n<br/>\n".join(htmls), 1)
                for p in pending + [u]:
                    p["_placed"] = True
                    for fn in p["file_names"]:
                        inserted.add(fn)
                pending = []

        # 2단계: 누락 유닛 → 장소별로 묶어 해당 <h2> 섹션 "끝"에 시간순 일괄 삽입.
        #  ⚠ 과거 구현은 유닛마다 h2 직후에 개별 삽입했고, 기존 figure 체인 추적이
        #    1000자 창 가정(base64 이전 시대)이라 수백 KB짜리 base64 figure 앞에서
        #    즉시 멈춤 → 전 유닛이 h2 바로 뒤 같은 위치에 꽂혀 시간 역순 +
        #    소개글보다 앞 배치 사고("사진 순서 뒤죽박죽"). 섹션 끝 삽입이면
        #    AI 앵커 첫 청크(소개글 뒤) → 나머지 청크(섹션 끝) 순으로 시간순 보존.
        missing_units = [u for u in units if not u["_placed"]]
        if missing_units:
            missing_photo_cnt = sum(len(u["file_names"]) for u in missing_units)
            logger.info(f"📸 사진 자동 배치: {missing_photo_cnt}/{len(results)}장 추가 삽입")

            h2_pattern = re.compile(
                r'<h2[^>]*>(.*?)</h2>', re.IGNORECASE | re.DOTALL)

            by_place = OrderedDict()
            for u in missing_units:
                loc = u["photos"][0].get("location_name", "")
                by_place.setdefault(loc, []).append(u)

            for loc, uls in by_place.items():
                htmls = []
                fns_all = []
                for u in uls:
                    htmls.append(_unit_html(u))
                    fns_all.extend(u["file_names"])
                block = "\n<br/>\n".join(htmls)

                placed = False
                loc_chars = set(loc.replace(" ", "")) if loc else set()
                if loc_chars:
                    best_match = None
                    best_score = 0
                    for m in h2_pattern.finditer(content):
                        h2_text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
                        h2_chars = set(h2_text.replace(" ", ""))
                        overlap = len(loc_chars & h2_chars) / len(loc_chars)
                        if overlap > best_score and overlap >= 0.4:
                            best_score = overlap
                            best_match = m

                    if best_match:
                        insert_pos = self._section_end_pos(content, best_match.end())
                        content = (content[:insert_pos] + '\n<br/>\n' + block + '\n'
                                   + content[insert_pos:])
                        placed = True
                        for fn in fns_all:
                            inserted.add(fn)

                if not placed:
                    for fn in fns_all:
                        inserted.add(fn)
                    fb = "\n".join(f'<h3>📸 {u["display"]}</h3>\n{h}'
                                   for u, h in zip(uls, htmls))
                    for marker in ['<div class="travel-tips">', '<div class="outro">',
                                   '🚆', '여행 꿀팁']:
                        if marker in content:
                            content = content.replace(marker, f'{fb}\n{marker}', 1)
                            placed = True
                            break
                    if not placed:
                        content += f'\n{fb}'

        # 3단계: 장소→장소 이동 경로 안내 삽입
        content = self._insert_route_guides(content, place_groups)
        content = self._insert_meta_lines(content)

        # 남은 [PHOTO:] 태그 정리
        content = re.sub(r'\[PHOTO:[^\]]*\]', '', content)

        # 연속된 구분선(─) 문단 중복 제거 → 1개로 정규화
        content = self._dedupe_separators(content)

        # 인트로 코스 요약 한 줄(코드 조립 — AI 미개입, 순서 왜곡/환각 방지)
        content = self._insert_course_summary(content, results)

        total = len(results)
        placed_cnt = len(inserted)
        if placed_cnt < total:
            logger.warning(f"⚠️ 사진 {placed_cnt}/{total}장만 삽입됨")
        else:
            logger.info(f"✅ 사진 {total}장 전체 삽입")
        return content

    # 장소 섹션 h2를 감싸는 헤더 div (생성 프롬프트가 조립하는 정형 마크업 —
    # _insert_route_guides의 카드 삽입 앵커와 동일 문자열)
    _SECTION_HEADER_DIV = '<div style="text-align:center;padding:30px 0 15px">'

    @staticmethod
    def _section_end_pos(content, h2_end):
        """h2가 여는 장소 섹션의 끝(다음 섹션 헤더 직전) 위치를 반환. 순수함수.
        다음 <h2가 있으면 그 h2를 감싸는 헤더 div(400자 창 rfind) 앞,
        없으면 TRAVEL TIPS/아웃트로 마커 앞, 그것도 없으면 본문 끝."""
        next_h2 = content.find('<h2', h2_end)
        if next_h2 >= 0:
            win_start = max(h2_end, next_h2 - 400)
            div_idx = content[win_start:next_h2].rfind(
                TravelBlogGenerator._SECTION_HEADER_DIV)
            return win_start + div_idx if div_idx >= 0 else next_h2
        for marker in ('<div class="travel-tips">', '<div class="outro">',
                       '🚆', '여행 꿀팁'):
            mi = content.find(marker, h2_end)
            if mi >= 0:
                if not marker.startswith('<'):
                    # 텍스트 마커는 TIPS 헤딩(<h3>🧳 여행 꿀팁) 등 태그 내부일 수
                    # 있다 — 그대로 삽입하면 태그가 깨지므로 래퍼 div 앞으로 되짚는다
                    win_start = max(h2_end, mi - 400)
                    div_idx = content[win_start:mi].rfind('<div')
                    if div_idx >= 0:
                        return win_start + div_idx
                return mi
        return len(content)

    @staticmethod
    def _insert_course_summary(content, results):
        """방문 순서 그대로 'A → B → C' 코스 요약 한 줄을 첫 <h2> 직전(없으면 본문 맨 앞)에 삽입.
        AI에게 맡기지 않고 코드가 조립(순서 왜곡·환각 방지). URL 없음. 순수함수.
        장소가 8개 초과면 사진 수 상위 8개만 남기되 원래 방문 순서는 유지한다."""
        if not content or not results:
            return content or ""
        from collections import OrderedDict
        counts = OrderedDict()
        for r in results:
            loc = (r.get("location_name") or "").strip()
            if not loc or loc == "미확인":
                continue
            counts[loc] = counts.get(loc, 0) + 1

        names = list(counts.keys())
        if len(names) > 8:
            top8 = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:8]
            top_names = {n for n, _ in top8}
            names = [n for n in names if n in top_names]

        if len(names) < 2:
            return content

        # 프롬프트 템플릿이 인트로에 이미 "📍 {course_line}"을 넣도록 지시하므로
        # (AI가 그 지시를 따랐다면) 중복 삽입하지 않는다 — 이 함수는 AI가 코스 라인을
        # 빠뜨렸을 때만 동작하는 백스톱이다. 앞 두 장소가 화살표로 이어져 있으면 존재로 판정.
        probe = re.compile(
            re.escape(names[0]) + r'[^<]{0,30}(→|->)\s*' + re.escape(names[1]))
        if probe.search(content):
            return content

        summary = " → ".join(names)
        html = f'<p style="text-align:center;margin:16px 0;color:#666">🚶 {summary}</p>'

        m = re.search(r'<h2', content, re.IGNORECASE)
        if m:
            return content[:m.start()] + html + '\n' + content[m.start():]
        return html + '\n' + content

    def _fetch_route_data(self, photos, route_modes):
        """장소→장소 구간별 Google Directions API로 경로 정보 조회
        route_modes: {"장소A→장소B": "transit", ...} (구간별 이동수단)
        반환: {("출발","도착"): {distance, duration, steps, mode, url, dir_map_url, departure_time}}
        """
        if not self.google_key:
            logger.info("🔑 Google Maps API 키 없음 → 직선 거리로 대체")
            return {}

        from collections import OrderedDict
        places = OrderedDict()
        place_photos = {}  # loc → [photos] (세그먼트 판정용)
        # 장소별 마지막 사진의 EXIF 시간 수집 (출발 시간 추정용)
        place_last_time = {}
        for r in photos:
            loc = r.get("location_name", "")
            if loc and loc not in places:
                gps = r.get("gps")
                if gps:
                    places[loc] = gps
            # 해당 장소의 가장 마지막 사진 시간 기록
            if loc:
                place_photos.setdefault(loc, []).append(r)
                exif_dt = r.get("exif_date", "") or (r.get("gps", {}) or {}).get("date", "")
                if exif_dt:
                    place_last_time[loc] = exif_dt

        place_names = list(places.keys())
        if len(place_names) < 2:
            return {}

        route_data = {}
        import urllib.request, urllib.parse
        for i in range(len(place_names) - 1):
            fr_name, to_name = place_names[i], place_names[i + 1]
            fr_gps, to_gps = places[fr_name], places[to_name]
            # 같은 일정(지역+날짜) 내부 → Directions 호출 스킵(경로 생략됨)
            if self._same_segment(place_photos.get(fr_name), place_photos.get(to_name)):
                continue
            route_key = f"{fr_name}→{to_name}"
            travel_mode = route_modes.get(route_key, "transit")

            # ★ 출발 시간: 출발 장소의 마지막 사진 EXIF 시간 → Unix timestamp
            departure_epoch = PhotoAnalyzer._exif_to_epoch(place_last_time.get(fr_name, ""))

            params = {
                "origin": f"{fr_gps['lat']},{fr_gps['lon']}",
                "destination": f"{to_gps['lat']},{to_gps['lon']}",
                "mode": travel_mode,
                "language": "ko",
                "key": self.google_key,
            }
            # departure_time: transit/driving만 지원 (walking/bicycling은 무시됨)
            if departure_epoch and travel_mode in ("transit", "driving"):
                params["departure_time"] = str(departure_epoch)
                logger.info(f"  ⏰ 출발시간: {place_last_time.get(fr_name, '')} → epoch {departure_epoch}")

            url = f"https://maps.googleapis.com/maps/api/directions/json?{urllib.parse.urlencode(params)}"

            try:
                req = urllib.request.Request(url, headers={"User-Agent": "TravelBlog/1.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode())

                if data.get("status") == "OK" and data.get("routes"):
                    leg = data["routes"][0]["legs"][0]
                    distance = leg["distance"]["text"]
                    duration = leg["duration"]["text"]

                    # 경로 단계 요약
                    steps_summary = []
                    for step in leg.get("steps", []):
                        mode_icon = {
                            "WALKING": "🚶", "TRANSIT": "🚌",
                            "DRIVING": "🚗", "BICYCLING": "🚲"
                        }.get(step.get("travel_mode", ""), "➡️")

                        transit_detail = step.get("transit_details")
                        if transit_detail:
                            line = transit_detail.get("line", {})
                            vehicle = line.get("vehicle", {}).get("type", "")
                            line_name = line.get("short_name") or line.get("name", "")
                            depart = transit_detail.get("departure_stop", {}).get("name", "")
                            arrive = transit_detail.get("arrival_stop", {}).get("name", "")
                            num_stops = transit_detail.get("num_stops", 0)

                            vehicle_icon = {"BUS": "🚌", "SUBWAY": "🚇",
                                           "TRAIN": "🚆", "TRAM": "🚊",
                                           "HEAVY_RAIL": "🚆"}.get(vehicle, "🚌")

                            detail_str = f"{vehicle_icon} {line_name}"
                            if depart and arrive:
                                detail_str += f" ({depart} → {arrive}"
                                if num_stops:
                                    detail_str += f", {num_stops}정거장"
                                detail_str += ")"
                            step_dur = step.get("duration", {}).get("text", "")
                            if step_dur:
                                detail_str += f" {step_dur}"
                            steps_summary.append(detail_str)
                        else:
                            step_dist = step.get("distance", {}).get("text", "")
                            step_dur = step.get("duration", {}).get("text", "")
                            s = f"{mode_icon} {step_dist}"
                            if step_dur:
                                s += f" ({step_dur})"
                            steps_summary.append(s)

                    # 구글맵 경로 URL (이동수단별)
                    mode_idx = {"driving": "0", "bicycling": "1",
                                "transit": "3", "walking": "2"}.get(travel_mode, "3")
                    dir_url = (
                        f"https://www.google.com/maps/dir/"
                        f"{fr_gps['lat']},{fr_gps['lon']}/"
                        f"{to_gps['lat']},{to_gps['lon']}/"
                        f"data=!4m2!4m1!3e{mode_idx}"
                    )

                    # 경로 지도 Embed URL (Directions mode)
                    dir_map_url = (
                        f"https://www.google.com/maps/embed/v1/directions"
                        f"?key={self.google_key}"
                        f"&origin={fr_gps['lat']},{fr_gps['lon']}"
                        f"&destination={to_gps['lat']},{to_gps['lon']}"
                        f"&mode={travel_mode}&language=ko"
                    )

                    route_data[(fr_name, to_name)] = {
                        "distance": distance,
                        "duration": duration,
                        "steps": steps_summary[:5],
                        "mode": travel_mode,
                        "url": dir_url,
                        "dir_map_url": dir_map_url,
                        "departure_time": place_last_time.get(fr_name, ""),
                    }
                    dt_str = place_last_time.get(fr_name, "")
                    logger.info(f"🗺️ {fr_name}→{to_name} [{travel_mode}]: {distance}, {duration}"
                                + (f" (출발 {dt_str})" if dt_str else ""))
                else:
                    logger.warning(f"⚠️ 경로 조회 실패: {fr_name}→{to_name}: {data.get('status')}")
            except Exception as e:
                logger.warning(f"⚠️ Directions API 오류: {fr_name}→{to_name}: {e}")

            time.sleep(0.3)

        return route_data

    def _place_seg(self, photos):
        """장소(사진 묶음)의 일정 키 (한글 지역, 날짜). 없으면 ('','')."""
        for p in photos or []:
            reg = p.get("city") or p.get("region") or ""
            day = p.get("day_date") or (p.get("exif_date", "") or "")[:10]
            if reg or day:
                return (self._koreanize_region(reg) if reg else "", day)
        return ("", "")

    def _same_segment(self, from_photos, to_photos):
        """두 장소가 같은 일정(지역+날짜)인지. 정보 부족 시 False(=경로 표시)."""
        fr = self._place_seg(from_photos)
        to = self._place_seg(to_photos)
        if fr == ("", "") or to == ("", ""):
            return False
        return fr == to

    def _insert_meta_lines(self, content):
        """장소별 별점·가격 줄을 매칭되는 <h2> 헤딩 바로 뒤에 삽입.
        매칭 헤딩 없으면 조용히 생략. self._current_place_meta 사용."""
        meta = getattr(self, "_current_place_meta", {}) or {}
        if not meta:
            return content
        import re as _re
        h2s = list(_re.finditer(r'(<h2[^>]*>)(.*?)(</h2>)', content,
                                _re.IGNORECASE | _re.DOTALL))
        if not h2s:
            return content
        inserts = []
        for loc, m in meta.items():
            line = self._format_meta_line(
                m.get("rating"), m.get("amount"), m.get("currency", ""),
                m.get("show_rating", True), m.get("show_price", True))
            if not line:
                continue
            loc_chars = set((loc or "").replace(" ", ""))
            if not loc_chars:
                continue
            best, best_score = None, 0
            for h in h2s:
                txt = _re.sub(r'<[^>]+>', '', h.group(2)).strip()
                hc = set(txt.replace(" ", ""))
                ov = len(loc_chars & hc) / len(loc_chars)
                if ov > best_score and ov >= 0.4:
                    best_score, best = ov, h
            if best is not None:
                inserts.append((best.end(), "\n" + line))
        for pos, html in sorted(inserts, reverse=True):
            content = content[:pos] + html + content[pos:]
        return content

    def _insert_route_guides(self, content, place_groups):
        """장소→장소 사이에 이동 경로 카드 삽입.
        같은 일정(세그먼트) 내부 이동은 생략, 세그먼트 경계(지역/날짜 이동)만 표시."""
        import re as _re
        places = list(place_groups.keys())
        if len(places) < 2:
            return content

        route_data = getattr(self, '_current_route_data', {})
        route_modes = getattr(self, '_current_route_modes', {})

        MODE_LABELS = {
            "walking": ("🚶", "도보"),
            "transit": ("🚌", "대중교통"),
            "driving": ("🚗", "자가용"),
            "bicycling": ("🚲", "자전거"),
        }

        # 역순 삽입
        for i in range(len(places) - 1, 0, -1):
            from_place = places[i - 1]
            to_place = places[i]
            from_photos = place_groups[from_place]
            to_photos = place_groups[to_place]

            # 같은 일정(지역+날짜) 내부 이동 → 경로 카드 생략
            if self._same_segment(from_photos, to_photos):
                continue

            rd = route_data.get((from_place, to_place))
            route_key = f"{from_place}→{to_place}"
            cur_mode = route_modes.get(route_key, "transit")
            mode_icon, mode_label = MODE_LABELS.get(cur_mode, ("🚌", "대중교통"))

            if rd:
                # ── API 결과 있음 → 상세 경로 + 지도 ──
                route_html = (
                    f'\n<div style="background:linear-gradient(135deg,#eef6ff,#f0f4ff);'
                    f'border:1px solid #bfdbfe;border-radius:12px;padding:16px 20px;'
                    f'margin:28px 0">'
                    f'<div style="font-size:1em;font-weight:bold;color:#1e40af;'
                    f'margin-bottom:8px">'
                    f'{mode_icon} 이동&nbsp; {from_place} → {to_place}</div>'
                    f'\n<div style="display:flex;gap:12px;margin-bottom:8px;'
                    f'font-size:.92em;color:#374151">'
                    f'<span>📏 {rd["distance"]}</span>'
                    f'<span>⏱️ {rd["duration"]}</span>'
                    f'<span style="color:#6b7280">({mode_label})</span></div>\n'
                )

                # 경로 단계
                if rd.get("steps"):
                    route_html += (
                        '<div style="background:#f8fafc;border-radius:8px;'
                        'padding:10px 14px;margin-bottom:10px;font-size:.85em;'
                        'color:#4b5563;line-height:1.8">\n'
                    )
                    for step in rd["steps"]:
                        route_html += f'{step}<br/>\n'
                    route_html += '</div>\n'

                # 출발 시간 표시
                if rd.get("departure_time"):
                    route_html += (
                        f'<div style="color:#6b7280;font-size:.85em;margin-bottom:8px">'
                        f'🕐 출발: {rd["departure_time"]}</div>\n'
                    )

                # 경로 지도 (Directions Embed) - 제거 (iframe 네이버 미지원)

                # 링크 없이 텍스트만 (네이버 에디터 OG 카드 방지)
                route_html += (
                    f'<p style="color:#8B9467;font-size:.85em;font-weight:bold;text-align:center">'
                    f'📍 {from_place} → {to_place} 경로</p>'
                    f'\n</div>\n'
                )
            else:
                # ── API 없음 → 직선거리 fallback ──
                from_gps = next((p["gps"] for p in from_photos if p.get("gps")), None)
                to_gps = next((p["gps"] for p in to_photos if p.get("gps")), None)

                dist_str = ""
                if from_gps and to_gps:
                    dist = TripStructurer._haversine(
                        from_gps["lat"], from_gps["lon"],
                        to_gps["lat"], to_gps["lon"])
                    if dist < 1000:
                        dist_str = f"직선 약 {int(dist)}m"
                    else:
                        dist_str = f"직선 약 {dist/1000:.1f}km"

                # departure_time 표시
                dt_str = ""
                last_photo = from_photos[-1] if from_photos else None
                if last_photo and last_photo.get("datetime"):
                    dt_str = last_photo["datetime"]

                route_html = (
                    f'\n<div style="background:linear-gradient(135deg,#eef6ff,#f0f4ff);'
                    f'border:1px solid #bfdbfe;border-radius:12px;padding:16px 20px;'
                    f'margin:28px 0">'
                    f'<div style="font-weight:bold;color:#1e40af;margin-bottom:8px">'
                    f'{mode_icon} 이동&nbsp; {from_place} → {to_place}</div>'
                )
                if dist_str:
                    route_html += f'<div style="color:#6b7280;font-size:.9em;margin-bottom:8px">{dist_str}</div>'
                if dt_str:
                    route_html += f'<div style="color:#6b7280;font-size:.85em;margin-bottom:8px">🕐 출발: {dt_str}</div>'
                route_html += (
                    f'<p style="color:#8B9467;font-size:.85em;font-weight:bold;text-align:center">'
                    f'📍 {from_place} → {to_place} 경로</p>'
                )
                route_html += '\n</div>\n'

            # to_place(목적지) 섹션 직전에 경로 삽입.
            # ⚠ 과거 구현은 h2 앞에 `(<div|p ...>[\s\S]*?)?` 선행 그룹을 붙여
            #   m.start()가 이전 섹션의 아무 <p>에나 앵커됨 → 카드가 출발지 사진
            #   한복판/글 맨 앞에 꽂히는 오배치 사고("일정 순서 엉망"). 또 첫 매치
            #   채택이라 '고베 X' 같은 유사 이름끼리 오매칭.
            # → h2만 스캔해 "최고 일치"를 고르고, h2를 감싸는 장소 헤더 div가
            #   바로 앞에 있으면 그 div 앞에 넣는다. 못 찾으면 조용히 생략
            #   (엉뚱한 위치에 넣는 것보다 낫다).
            h2_pat = _re.compile(r'<h2[^>]*>(.*?)</h2>', _re.IGNORECASE | _re.DOTALL)
            to_chars = set(to_place.replace(" ", ""))
            best, best_score = None, 0.0
            if to_chars:
                for m in h2_pat.finditer(content):
                    h2_text = _re.sub(r'<[^>]+>', '', m.group(1)).strip()
                    overlap = len(to_chars & set(h2_text.replace(" ", ""))) / len(to_chars)
                    if overlap > best_score and overlap >= 0.4:
                        best_score, best = overlap, m
            if best is not None:
                insert_pos = best.start()
                # h2 직전 400자 안의 장소 헤더 div(PLACE 라벨 포함) 시작을 찾으면 그 앞에
                win_start = max(0, insert_pos - 400)
                window = content[win_start:insert_pos]
                div_idx = window.rfind('<div style="text-align:center;padding:30px 0 15px">')
                if div_idx >= 0:
                    insert_pos = win_start + div_idx
                content = content[:insert_pos] + route_html + '\n' + content[insert_pos:]

        return content

    # 도로/노선명 패턴 — 캡션 부기로 가치가 없고 글을 조잡하게 만든다
    # (예: 生田北１３９号線, 神戸方面第７号線, 天の橋立線, 千日前通, パールストリート)
    _ROAD_NAME_PAT = re.compile(
        r'(号線|国道|県道|府道|市道|旧道|バイパス|方面|街道$|線$|通り?$|ストリート$|[Ss]treet$)')

    def _display_name(self, r):
        """사진의 표시 이름 생성. 세부 위치가 도로/노선명이면 부기하지 않는다."""
        loc_kr = r.get("location_name", "")
        loc_local = r.get("location_name_local", "")
        if loc_local and self._ROAD_NAME_PAT.search(loc_local):
            loc_local = ""
        if loc_local and loc_local != loc_kr and not self._is_same_text(loc_kr, loc_local):
            return f"{loc_kr} ({loc_local})"
        return loc_kr or loc_local or "여행지"

    def _photo_html(self, fp, display, gps, show_map=True, map_card_url=None,
                    src_files=None):
        """단일 사진(또는 콜라주) HTML 생성 — EXIF 방향 보정 + base64 인코딩.
        src_files: 이 figure를 구성하는 원본 파일명 목록(순서 유지). 발행기
        (html_to_blocks)가 이 목록으로 figure를 제자리에서 개별 사진으로 전개해
        네이버 발행 순서를 계획/EXIF 그대로 보존한다(콜라주 alt 재매칭 폐기)."""
        import base64, mimetypes, io

        img_src = f"file:///{fp}"  # fallback
        try:
            if fp and os.path.exists(fp):
                from PIL import Image, ImageOps
                img = Image.open(fp)
                try:
                    img = ImageOps.exif_transpose(img)
                except Exception:
                    pass
                if img.mode not in ('RGB', 'RGBA'):
                    img = img.convert('RGB')
                buf = io.BytesIO()
                fmt = 'PNG' if img.mode == 'RGBA' else 'JPEG'
                img.save(buf, format=fmt, quality=85)
                b64 = base64.b64encode(buf.getvalue()).decode()
                mime = f"image/{'png' if fmt == 'PNG' else 'jpeg'}"
                img_src = f"data:{mime};base64,{b64}"
        except Exception as e:
            logger.warning(f"⚠️ 이미지 인코딩 실패: {fp}: {e}")

        data_attr = ""
        if src_files:
            # 파일명에 '|'는 없다고 가정(secure_filename 통과분). 발행 시 이 목록
            # 순서대로 개별 image 블록으로 전개된다.
            data_attr = ' data-files="' + "|".join(src_files) + '"'
        img_html = (
            f'\n<figure style="text-align:center;margin:24px 0"{data_attr}>'
            f'<img src="{img_src}" alt="{display}" '
            f'style="max-width:100%;border-radius:12px;'
            f'box-shadow:0 4px 15px rgba(0,0,0,.15)"/>'
            f'</figure>\n'
        )

        # 캡션 라인은 항상 출력(가운데 정렬·회색·작은 글씨). 📍 접두는 지도 표시
        # 대상(show_map)이고 GPS가 있을 때만 붙는다(구글맵 URL은 절대 넣지 않는다 —
        # 네이버 에디터에서 URL 붙여넣기 시 OG 카드로 변환되는 문제 방지).
        if display:
            caption_text = f"📍 {display}" if (gps and show_map) else display
            img_html += (
                f'<p style="text-align:center;margin:4px 0 20px;'
                f'color:#999;font-size:.85em">'
                f'{caption_text}</p>\n'
            )
            # 발행용 지도 카드 마커(주석) — 미리보기에는 안 보이고, 발행기가
            # html_to_blocks에서 map_card 블록으로 변환해 OG 카드 변환을 유도한다.
            # 본문 텍스트에는 여전히 URL을 노출하지 않는다(불변식 유지).
            if show_map and gps and map_card_url:
                safe_display = display.replace("|", "").replace("-->", "")
                img_html += f'<!--MAPCARD:{map_card_url}|{safe_display}-->\n'

        return img_html

    def _photo_summary(self, results):
        lines = []
        place_details_cache = {}
        total = len(results)
        # 사진 15장 초과시 간소화 (토큰 절약)
        compact = total > 15

        for i, r in enumerate(results, 1):
            v = r.get("vision",{})
            loc_kr = r.get("location_name","")
            loc_local = r.get("location_name_local","")
            display = f"{loc_kr} ({loc_local})" if loc_local and loc_local != loc_kr else loc_kr
            gps = r.get("gps")
            gps_str = f"{gps['lat']},{gps['lon']}" if gps else "없음"
            scene_type = v.get("scene_type","") or v.get("place_type","관광지")
            visible_name = v.get("visible_name","")

            if compact:
                # 간소화 모드: 핵심만
                entry = (
                    f"사진{i}: {r.get('file_name','')}\n"
                    f"  위치: {display} | GPS: {gps_str}\n"
                    f"  장면: {scene_type}"
                )
                if visible_name: entry += f" | 간판: {visible_name}"
                food = v.get('food_name','')
                if food: entry += f" | 음식: {food}"
                desc = v.get('scene_description','')
                if desc: entry += f"\n  묘사: {desc[:60]}"
            else:
                # 상세 모드
                date = r.get("exif_date","") or (r.get("gps",{}) or {}).get("date","")
                place_info = ""
                if gps and self.google_key and loc_kr not in place_details_cache:
                    detail = self._fetch_place_detail(gps["lat"], gps["lon"], loc_kr)
                    place_details_cache[loc_kr] = detail
                elif loc_kr in place_details_cache:
                    detail = place_details_cache[loc_kr]
                else:
                    detail = ""
                place_info = detail

                entry = (
                    f"사진{i}: {r.get('file_name','')}\n"
                    f"  GPS 위치: {display}\n"
                    f"  GPS 좌표: {gps_str}\n"
                    f"  사진 장면: {scene_type}\n"
                    f"  간판/이름: {visible_name or '없음'}\n"
                    f"  음식: {v.get('food_name','') or '없음'}\n"
                    f"  장면 묘사: {v.get('scene_description','')}\n"
                    f"  분위기: {v.get('mood','')}\n"
                    f"  촬영일: {date or '불명'}\n"
                    f"  팁: {v.get('blog_tip','')}"
                )
                if place_info:
                    entry += f"\n  ★ 장소 상세: {place_info}"

            lines.append(entry)

        # 전체 사진 파일명 목록 (누락 방지용)
        all_files = [r.get('file_name','') for r in results]
        header = (
            f"★★★ 총 {total}장 — 아래 사진을 하나도 빠짐없이 모두 [PHOTO:파일명]으로 포함 ★★★\n"
            f"파일 목록: {', '.join(all_files)}\n"
            f"{'━' * 50}"
        )
        return header + "\n\n" + "\n\n".join(lines)

    def _fetch_place_detail(self, lat, lon, name_hint=""):
        """Google Place Details + 네이버 블로그 검색으로 장소 정보 보강"""
        parts = []
        try:
            key = self.google_key
            # 무료 모드: Google Maps 키 없으면 유료 Places 호출 생략(네이버 검색만 사용)
            nearby = {}
            if key:
                # ── Google Place Details ──
                nearby_url = (
                    f"https://maps.googleapis.com/maps/api/place/nearbysearch/json?"
                    f"location={lat},{lon}&radius=80&language=ko&key={key}"
                )
                req = urllib.request.Request(nearby_url)
                with urllib.request.urlopen(req, timeout=8) as r:
                    nearby = json.loads(r.read().decode())

            if nearby.get("results"):
                skip_types = {"route","street_address","sublocality","locality",
                              "administrative_area_level_1","country","postal_code",
                              "plus_code","geocode","political","neighborhood"}
                place = None
                for p in nearby["results"]:
                    types = set(p.get("types",[]))
                    if not types.issubset(skip_types):
                        place = p; break

                if place and place.get("place_id"):
                    place_id = place["place_id"]
                    det_url = (
                        f"https://maps.googleapis.com/maps/api/place/details/json?"
                        f"place_id={place_id}"
                        f"&fields=name,rating,user_ratings_total,editorial_summary,"
                        f"reviews,opening_hours,types,formatted_address,website"
                        f"&language=ko&key={key}"
                    )
                    req2 = urllib.request.Request(det_url)
                    with urllib.request.urlopen(req2, timeout=8) as r2:
                        det = json.loads(r2.read().decode())

                    result = det.get("result",{})

                    # 이름 + 평점
                    name = result.get("name","")
                    rating = result.get("rating")
                    total_reviews = result.get("user_ratings_total")
                    if name:
                        info = name
                        if rating: info += f" (★{rating}"
                        if total_reviews: info += f", 리뷰 {total_reviews}개)"
                        elif rating: info += ")"
                        parts.append(info)

                    # 공식 설명
                    summary = result.get("editorial_summary",{}).get("overview","")
                    if summary:
                        parts.append(f"소개: {summary[:200]}")

                    # 리뷰 2개 (블로그 내용 풍성하게)
                    reviews = result.get("reviews",[])
                    rev_count = 0
                    for rev in reviews[:5]:
                        txt = rev.get("text","")
                        if len(txt) >= 40 and rev_count < 2:
                            parts.append(f"후기: {txt[:150]}")
                            rev_count += 1

                    # 영업시간
                    hours = result.get("opening_hours",{}).get("weekday_text",[])
                    if hours:
                        parts.append(f"영업시간: {', '.join(hours[:2])}")

                    # 주소
                    addr = result.get("formatted_address","")
                    if addr:
                        parts.append(f"주소: {addr}")

        except Exception as e:
            logger.debug(f"Google 장소 상세 조회 실패: {e}")

        # ── 네이버 블로그 검색으로 추가 정보 ──
        if name_hint:
            naver_info = self._search_naver_blog(name_hint)
            if naver_info:
                parts.append(f"블로그 정보: {naver_info}")

        return " | ".join(parts) if parts else ""

    def _search_naver_blog(self, query):
        """네이버 블로그에서 장소 관련 정보 검색"""
        try:
            client_id = self.config.get("naver","client_id") or ""
            client_secret = self.config.get("naver","client_secret") or ""

            if not client_id or not client_secret:
                return ""

            encoded = urllib.parse.quote(f"{query} 여행 후기")
            url = f"https://openapi.naver.com/v1/search/blog.json?query={encoded}&display=3&sort=sim"
            req = urllib.request.Request(url)
            req.add_header("X-Naver-Client-Id", client_id)
            req.add_header("X-Naver-Client-Secret", client_secret)

            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read().decode())

            items = data.get("items",[])
            if not items:
                return ""

            # 가장 관련도 높은 블로그 글에서 핵심 정보 추출
            snippets = []
            for item in items[:2]:
                desc = item.get("description","")
                # HTML 태그 제거
                desc = re.sub(r'<[^>]+>', '', desc)
                if len(desc) >= 30:
                    snippets.append(desc[:120])

            return " / ".join(snippets) if snippets else ""

        except Exception as e:
            logger.debug(f"네이버 블로그 검색 실패: {e}")
            return ""

    @staticmethod
    def extract_core_tags(analysis, region):
        """실측 데이터(상위 블로그 빈도 키워드)+확정 지역명으로 핵심 태그 3~5개.
        LLM 없음(결정적). analysis/region 없으면 축소·빈 리스트(조용히 생략)."""
        region = (region or "").strip()
        tags = []
        if region:
            tags.append(region)
            tags.append(f"{region}여행")
        kws = (analysis or {}).get("common_keywords") or []
        if region and any("맛집" in k for k in kws):
            tags.append(f"{region}맛집")
        for k in kws:
            if len(tags) >= 5:
                break
            if k and k not in tags:
                tags.append(k)
        return tags[:5]

    @staticmethod
    def _expand_tags(region, place_types):
        """지역×방문 카테고리 조합 태그를 결정적으로 생성 (LLM 없음).
        region이 비어 있으면 빈 리스트. 카테고리 태그는 실제 방문한(place_types에
        존재하는) 카테고리에 대해서만 생성한다(방문 안 한 카테고리 환각 금지 — lessons #3).
        place_types: 방문 stop들의 scene/POI 타입 문자열 목록(예: vision scene_type)."""
        region = (region or "").strip()
        if not region:
            return []

        tags = [f"{region}여행", f"{region}여행코스", f"{region}가볼만한곳"]

        combined = " ".join(str(t).strip().lower() for t in (place_types or []) if t)

        def has(*keywords):
            return any(k in combined for k in keywords)

        # 카테고리 키워드: 스펙에 명시된 영/한 표기 + 실제 Vision scene_type 한글 값(신사/사찰/공원/맛집 등)을
        # 함께 매칭해야 실사용 데이터(코드베이스 scene_type 한글 enum)에서 정상 작동한다.
        if has("restaurant", "food", "음식점", "식당", "맛집"):
            tags.append(f"{region}맛집")
        if has("cafe", "카페"):
            tags.append(f"{region}카페")
        if has("hotel", "lodging", "숙소", "료칸"):
            tags.append(f"{region}숙소")
        if has("temple", "shrine", "park", "attraction", "명소", "관광", "신사", "사찰", "공원"):
            tags.append(f"{region}관광지")
        if has("market", "시장"):
            tags.append(f"{region}시장")
        if has("bar", "izakaya", "이자카야", "술집"):
            tags.append(f"{region}이자카야")

        return tags

    @staticmethod
    def merge_tags(ai_tags, core_tags, cap=25):
        """핵심 태그(코드 추출)를 앞에 보장하고 AI 태그로 채움.
        공백/# 무시 정규화로 중복 제거, 상한 cap."""
        def norm(t):
            return re.sub(r'[\s#]', '', str(t)).lower()
        merged, seen = [], set()
        for t in list(core_tags or []) + list(ai_tags or []):
            t = str(t).strip()
            if not t:
                continue
            k = norm(t)
            if not k or k in seen:
                continue
            seen.add(k)
            merged.append(t)
            if len(merged) >= cap:
                break
        return merged

    @staticmethod
    def seo_check(post, analysis, region=""):
        """생성 결과 SEO 검증 → 경고 문자열 목록(발행은 막지 않음).
        analysis 없으면 빈 리스트(검증 스킵). 순수함수."""
        if not analysis or not isinstance(analysis, dict):
            return []
        warns = []
        region = (region or "").strip()
        title = (post or {}).get("title", "") or ""
        kws = analysis.get("common_keywords") or []
        # 1) 제목에 핵심 키워드(지역명 또는 빈도 1위) 포함 여부
        head_kw = region or (kws[0] if kws else "")
        if head_kw and head_kw not in title:
            warns.append(f"제목에 핵심 키워드 '{head_kw}' 미포함")
        # 2) 본문 분량: 상위 평균의 60% 미만이면 경고
        avg_chars = (analysis.get("avg_analysis") or {}).get("avg_chars") or 0
        if avg_chars > 0:
            body = re.sub(r'<[^>]+>', '', (post or {}).get("content", "") or "")
            n = len(body.replace("\n", "").replace(" ", ""))
            if n < avg_chars * 0.6:
                warns.append(f"분량 {n:,}자 — 상위 평균({avg_chars:,}자)의 {n*100//avg_chars}%")
        # 3) 태그에 지역명 포함 여부
        if region:
            tags = (post or {}).get("tags") or []
            if not any(region in str(t) for t in tags):
                warns.append(f"태그에 지역명 '{region}' 부재")
        return warns

    def optimize_title(self, post, naver_analysis, region):
        """네이버 상위 실측 제목 패턴 기반 제목 최적화. 노출 관련은 코드가 강제:
        후보 3개 생성 → (지역명 포함 AND 15~45자) 첫 통과 후보 채택.
        분석 없음/전부 탈락/LLM 실패 → None (기존 제목 유지, seo_check가 경고)."""
        na = naver_analysis or {}
        top_titles = [t for t in (na.get("top_titles") or []) if t][:10]
        region = (region or "").strip()
        if not top_titles or not region:
            return None
        kws = [k for k in (na.get("common_keywords") or []) if k][:8]
        body = re.sub(r'<[^>]+>', ' ', (post or {}).get("content", "") or "")[:800]
        prompt = (
            f"'{region}' 여행 블로그 글의 검색 노출용 제목을 만들어라.\n"
            "[실측 — 이 키워드로 네이버 상위에 노출된 실제 제목들]\n"
            + "\n".join(f"- {t}" for t in top_titles)
            + (f"\n[연관 키워드] {', '.join(kws)}" if kws else "")
            + f"\n[글 내용 요약]\n{body}\n\n"
            "[규칙] 상위 제목들의 구조·키워드 배치·길이 패턴을 모방하되 그대로 베끼지 말 것. "
            f"'{region}'을(를) 반드시 포함. 낚시·과장·이모지 금지. 글 내용에 실제로 있는 것만. "
            '서로 다른 제목 후보 3개를 JSON으로만: {"titles":["...","...","..."]}'
        )
        try:
            r = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0.5, max_tokens=300,
            )
            cands = (json.loads(r.choices[0].message.content).get("titles") or [])
        except Exception as e:
            logger.warning(f"⚠️ 제목 최적화 실패(기존 제목 유지): {e}")
            return None
        for c in cands:
            c = str(c).strip()
            if region in c and 15 <= len(c) <= 45:
                return c
        return None

    def _naver_context(self, na):
        if not na or not na.get("top_titles"): return ""

        parts = ["\n[네이버 SEO 분석 — 상위 블로그 구조 기반 작성 필수]"]
        parts.append(f"검색 키워드: {na.get('keyword','')}")
        parts.append(f"연관 키워드: {', '.join(na.get('common_keywords',[])[:10])}")

        # 상세 구조 분석 데이터
        avg = na.get("avg_analysis", {})
        if avg and avg.get("avg_chars"):
            parts.append(f"\n[상위 블로그 평균 스펙]")
            parts.append(f"  글자 수: {avg['avg_chars']:,}자 (이 정도 분량으로 작성)")
            parts.append(f"  이미지: {avg['avg_images']}장 (사진 삽입 위치 표시)")
            if avg.get("avg_videos", 0) > 0:
                parts.append(f"  동영상: {avg['avg_videos']}개")
            mr = avg.get("map_ratio", 0)
            if mr >= 0.3:
                parts.append(f"  지도: 상위 글 {mr*100:.0f}%가 포함 — 지도·경로는 코드가 자동 삽입하니 본문에 절대 넣지 마세요")

        # 공통 섹션 순서
        if avg and avg.get("common_sections"):
            parts.append(f"\n[상위 블로그 공통 섹션 순서 — 이 순서 참고]")
            for i, sec in enumerate(avg["common_sections"], 1):
                parts.append(f"  {i}. {sec}")

        # 개별 블로그 소제목 참고
        blogs = na.get("blog_structures", [])
        if blogs:
            parts.append(f"\n[상위 블로그 소제목 예시]")
            for b in blogs[:2]:
                heads = b.get("headings", [])[:5]
                if heads:
                    parts.append(f"  {b.get('title','')[:30]}: {' / '.join(heads)}")

        # 추천 구조
        struct = na.get("recommended_structure", [])
        if struct:
            parts.append(f"\n[추천 글 구성]")
            for s in struct:
                parts.append(f"  - {s['type']}: {s['desc']}")

        return "\n".join(parts) + "\n"

    def _style_context(self, profile):
        """문체 프로파일(dict) → 프롬프트 조각. 순수함수, 네트워크 없음.
        규칙 + 짧은 예시만 넣고 원문 문단은 넣지 않는다(표절 방지)."""
        if not profile or not isinstance(profile, dict):
            return ""
        tone = (profile.get("tone") or "").strip()
        if not tone:
            return ""
        lines = ["\n[참고 문체 — 아래 규칙을 모방하되 문장을 그대로 베끼지 말 것]"]
        person = (profile.get("person") or "").strip()
        lines.append(f"· 톤: {tone}" + (f" / {person}" if person else ""))
        if profile.get("sentence_length"):
            lines.append(f"· 리듬: {profile['sentence_length']}")
        endings = [e for e in (profile.get("ending_patterns") or []) if e][:5]
        if endings:
            lines.append("· 어미: " + " / ".join(endings))
        if profile.get("emoji_usage"):
            lines.append(f"· 이모지: {profile['emoji_usage']}")
        habits = [h for h in (profile.get("rhetorical_habits") or []) if h][:5]
        if habits:
            lines.append("· 습관: " + ", ".join(habits))
        donts = [d for d in (profile.get("donts") or []) if d][:3]
        if donts:
            lines.append("· 피할 것: " + ", ".join(donts))
        examples = [e for e in (profile.get("examples") or []) if e][:2]
        if examples:
            lines.append("· 참고 어감(복붙 금지): " + " / ".join(f'"{e}"' for e in examples))
        return "\n".join(lines) + "\n"

    @staticmethod
    def _is_same_text(a, b):
        clean = lambda s: re.sub(r'[\s,、・-]','', s or '')
        return clean(a) == clean(b)


class LocalSaver:
    def __init__(self): self.dir=Path("posts"); self.dir.mkdir(exist_ok=True)
    def save(self, data, keyword="travel"):
        ts=datetime.now().strftime("%Y%m%d_%H%M%S"); safe=re.sub(r'[^\w가-힣]','_',keyword)[:30]
        p=self.dir/f"{ts}_{safe}.html"
        html=f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<meta name="description" content="{data.get('meta_description','')}">
<title>{data.get('title','')}</title>
<style>body{{font-family:'Noto Sans KR',sans-serif;max-width:800px;margin:0 auto;padding:20px;line-height:1.9;color:#333;background:#fafafa}}
h1{{color:#2d3436;font-size:1.8em;border-left:5px solid #0984e3;padding-left:15px}}
h2{{color:#0984e3;font-size:1.3em;margin-top:35px;border-bottom:2px solid #dfe6e9;padding-bottom:8px}}
figure{{text-align:center;margin:25px 0}}img{{max-width:100%;border-radius:12px;box-shadow:0 4px 15px rgba(0,0,0,.12)}}
.tags{{margin-top:30px;padding:15px;background:#fff;border-radius:12px;border:1px solid #dfe6e9}}
.tag{{display:inline-block;background:#e8f4f8;color:#0984e3;padding:5px 14px;margin:3px;border-radius:20px;font-size:.9em}}</style>
</head><body><h1>{data.get('title','')}</h1>{data.get('content','')}
<div class="tags"><p><b>🏷️</b></p>{''.join(f'<span class="tag">{t}</span>' for t in data.get('tags',[]))}</div>
<p style="color:#999;margin-top:15px">{' '.join(data.get('hashtags',[]))}</p></body></html>"""
        with open(p,'w',encoding='utf-8') as f: f.write(html)
        logger.info(f"💾 저장: {p}"); return str(p)
