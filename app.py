"""
TravelBlog Pro v10.0 — Web Edition (Final)
Flask 백엔드 API 서버
- 설정 시스템 (settings.json 저장/로드)
- 전체 그룹 일괄 생성
- Selenium/Clipboard 발행 선택
- blocks → content 변환
"""
import os, sys, json, re, threading, logging, time, base64
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

from core import (Config, PhotoAnalyzer, TripStructurer, TravelBlogGenerator,
                  LocalSaver, NaverBlogAnalyzer, StyleAnalyzer, logger)
from posters import NaverPoster, TistoryPoster, html_to_blocks

app = Flask(__name__, static_folder='static')
CORS(app)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

UPLOAD_DIR = Path("uploads"); UPLOAD_DIR.mkdir(exist_ok=True)
SETTINGS_FILE = Path("settings.json")

# ═══ 기본 설정 ═══
DEFAULT_SETTINGS = {
    "blog_style": {
        "tone": "친근 구어체",
        "mood": "감성적",
        "emoji_level": "적당히",
        "photo_desc_length": "2~3줄",
        "place_intro_length": "3~4줄",
        "include_tips": True,
        "include_outro": True
    },
    "design": {
        "accent_color": "#8B9467",
        "separator_style": "─ ─ ─",
        "place_label": "PLACE N",
        "intro_style": "✈ 여행기 ✈"
    },
    "ref_urls": [],
    "api": {
        "openai_key": "",
        "openai_model": "gpt-4o-mini",
        "google_key": "",
        "naver_id": "",
        "naver_pw": "",
        "publish_method": "selenium",
        "default_visibility": "비공개"
    },
    "custom_prompt": {
        "extra_instructions": "",
        "banned_expressions": "",
        "required_keywords": ""
    }
}

# ═══ 전역 상태 ═══
state = {
    "cfg": None, "analyzer": None, "generator": None,
    "photo_paths": [], "photo_results": [], "trip_structure": None,
    "selected_mode": "by_place", "selected_groups": [],
    "group_states": {},
    "naver_analysis": None, "style_analysis": None,
    "current_step": 1, "completed": set(),
    "progress": {"status": "idle", "message": "", "percent": 0},
    "settings": dict(DEFAULT_SETTINGS),
    "plan": None,
}


def load_settings():
    """settings.json에서 설정 로드"""
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
            # 기본값과 병합 (새 키 누락 방지)
            merged = dict(DEFAULT_SETTINGS)
            for k, v in saved.items():
                if isinstance(v, dict) and k in merged and isinstance(merged[k], dict):
                    merged[k] = {**merged[k], **v}
                else:
                    merged[k] = v
            state["settings"] = merged
            logger.info(f"⚙️ 설정 로드: {SETTINGS_FILE}")
        except Exception as e:
            logger.warning(f"설정 로드 실패: {e}")
            state["settings"] = dict(DEFAULT_SETTINGS)
    else:
        state["settings"] = dict(DEFAULT_SETTINGS)

    # .env 환경변수가 있으면 우선
    api = state["settings"]["api"]
    if os.environ.get("OPENAI_API_KEY"):
        api["openai_key"] = os.environ["OPENAI_API_KEY"]
    if os.environ.get("GOOGLE_MAPS_API_KEY"):
        api["google_key"] = os.environ["GOOGLE_MAPS_API_KEY"]
    if os.environ.get("NAVER_USERNAME"):
        api["naver_id"] = os.environ["NAVER_USERNAME"]
    if os.environ.get("NAVER_PASSWORD"):
        api["naver_pw"] = os.environ["NAVER_PASSWORD"]


def save_settings():
    """설정을 settings.json에 저장"""
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(state["settings"], f, ensure_ascii=False, indent=2)
        logger.info(f"⚙️ 설정 저장: {SETTINGS_FILE}")
    except Exception as e:
        logger.warning(f"설정 저장 실패: {e}")


def init_engine():
    load_settings()
    state["cfg"] = Config()
    state["analyzer"] = PhotoAnalyzer(state["cfg"])
    state["generator"] = TravelBlogGenerator(state["cfg"])


def blocks_to_html(blocks):
    """blocks 리스트 → HTML 문자열 변환 (발행/저장용)"""
    parts = []
    for b in blocks:
        t = b.get("type", "text")
        c = b.get("content", "")
        if t == "text":
            for line in c.split('\n'):
                if line.strip():
                    parts.append(f'<p style="text-align:center;font-size:0.92em;color:#555;line-height:2.0">{line}</p>')
                else:
                    parts.append('<br/>')
        elif t == "image":
            path = b.get("path", "")
            if path and os.path.exists(path):
                try:
                    from PIL import Image, ImageOps
                    import io
                    img = Image.open(path)
                    try: img = ImageOps.exif_transpose(img)
                    except: pass
                    if img.mode not in ('RGB','RGBA'): img = img.convert('RGB')
                    buf = io.BytesIO()
                    img.save(buf, format='JPEG', quality=85)
                    b64 = base64.b64encode(buf.getvalue()).decode()
                    parts.append(f'<figure style="text-align:center;margin:20px 0">'
                                 f'<img src="data:image/jpeg;base64,{b64}" '
                                 f'style="max-width:100%;border-radius:12px"/></figure>')
                except: pass
        elif t == "separator":
            sep = state["settings"]["design"].get("separator_style", "─ ─ ─")
            parts.append(f'<p style="text-align:center;color:#d4d4d4;letter-spacing:8px">{sep} {sep} ─</p>')
        elif t == "styled_label":
            color = b.get("color", state["settings"]["design"].get("accent_color", "#8B9467"))
            parts.append(f'<p style="text-align:center;font-size:0.8em;color:{color};letter-spacing:3px">{c}</p>')
        elif t == "heading":
            parts.append(f'<h2 style="text-align:center;font-size:1.3em;color:#3d3d3d;font-weight:600">{c}</h2>')
        elif t == "route":
            parts.append(f'<div style="background:linear-gradient(135deg,#eef6ff,#f0f4ff);border:1px solid #bfdbfe;'
                         f'border-radius:12px;padding:16px 20px;margin:20px 0;text-align:center">'
                         f'<p style="font-weight:bold;color:#1e40af">{c}</p></div>')
        elif t == "map_link":
            parts.append(f'<p style="text-align:center;color:#8B9467;font-size:0.85em">{c}</p>')
    return "\n".join(parts)


# ═══════════════════════════════════════
# API 엔드포인트
# ═══════════════════════════════════════

@app.route('/')
def index():
    r = send_from_directory('static', 'index.html')
    r.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    r.headers['Pragma'] = 'no-cache'
    return r


# ── 설정 ──
@app.route('/api/settings', methods=['GET'])
def api_settings_get():
    # API키는 마스킹
    s = json.loads(json.dumps(state["settings"]))
    api = s.get("api", {})
    for k in ["openai_key", "google_key", "naver_pw"]:
        if api.get(k):
            api[k] = api[k][:8] + "..." if len(api[k]) > 8 else "***"
    return jsonify(s)


@app.route('/api/settings', methods=['POST'])
def api_settings_post():
    data = request.json or {}
    s = state["settings"]
    for section in ["blog_style", "design", "custom_prompt"]:
        if section in data and isinstance(data[section], dict):
            s[section] = {**s.get(section, {}), **data[section]}
    if "ref_urls" in data:
        s["ref_urls"] = data["ref_urls"]
    if "api" in data:
        api_data = data["api"]
        for k, v in api_data.items():
            if v and "..." not in str(v) and v != "***":
                s["api"][k] = v
    save_settings()
    return jsonify({"saved": True})


@app.route('/api/settings/raw', methods=['GET'])
def api_settings_raw():
    return jsonify(state["settings"])


# ── 프로필 시스템 ──
PROFILE_DIR = Path("profiles"); PROFILE_DIR.mkdir(exist_ok=True)
LAST_PROFILE = Path("last_profile.txt")

@app.route('/api/profiles')
def api_profiles():
    """저장된 프로필 목록"""
    profiles = []
    for f in sorted(PROFILE_DIR.glob("*.json")):
        try:
            with open(f, 'r', encoding='utf-8') as fp:
                data = json.load(fp)
            bs = data.get("blog_style", {})
            profiles.append({
                "name": f.stem,
                "tone": bs.get("tone", ""),
                "mood": bs.get("mood", ""),
                "accent_color": data.get("design", {}).get("accent_color", "#8B9467"),
                "ref_count": len(data.get("ref_urls", [])),
                "modified": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
            })
        except: pass
    last = LAST_PROFILE.read_text(encoding='utf-8').strip() if LAST_PROFILE.exists() else ""
    return jsonify({"profiles": profiles, "last_used": last})


@app.route('/api/profiles/<name>', methods=['GET'])
def api_profile_load(n):
    """프로필 로드"""
    f = PROFILE_DIR / f"{n}.json"
    if not f.exists():
        return jsonify({"error": "프로필 없음"}), 404
    with open(f, 'r', encoding='utf-8') as fp:
        data = json.load(fp)
    # .env 우선 적용
    api = data.get("api", {})
    if os.environ.get("OPENAI_API_KEY"): api["openai_key"] = os.environ["OPENAI_API_KEY"]
    if os.environ.get("GOOGLE_MAPS_API_KEY"): api["google_key"] = os.environ["GOOGLE_MAPS_API_KEY"]
    if os.environ.get("NAVER_USERNAME"): api["naver_id"] = os.environ["NAVER_USERNAME"]
    if os.environ.get("NAVER_PASSWORD"): api["naver_pw"] = os.environ["NAVER_PASSWORD"]
    data["api"] = api
    state["settings"] = data
    LAST_PROFILE.write_text(n, encoding='utf-8')
    logger.info(f"⚙️ 프로필 로드: {n}")
    return jsonify(data)


@app.route('/api/profiles/save', methods=['POST'])
def api_profile_save():
    """프로필 저장"""
    data = request.json or {}
    name = data.get("profile_name", "").strip()
    if not name:
        return jsonify({"error": "프로필 이름 필요"}), 400
    # 안전한 파일명
    safe_name = re.sub(r'[^\w가-힣\s-]', '', name).strip()
    if not safe_name:
        return jsonify({"error": "잘못된 이름"}), 400

    profile_data = data.get("settings", {})
    f = PROFILE_DIR / f"{safe_name}.json"
    with open(f, 'w', encoding='utf-8') as fp:
        json.dump(profile_data, fp, ensure_ascii=False, indent=2)

    state["settings"] = profile_data
    LAST_PROFILE.write_text(safe_name, encoding='utf-8')
    save_settings()  # settings.json도 동기화
    logger.info(f"⚙️ 프로필 저장: {safe_name}")
    return jsonify({"saved": True, "name": safe_name})


@app.route('/api/profiles/<name>', methods=['DELETE'])
def api_profile_delete(n):
    """프로필 삭제"""
    f = PROFILE_DIR / f"{n}.json"
    if f.exists():
        f.unlink()
        logger.info(f"⚙️ 프로필 삭제: {n}")
    return jsonify({"deleted": True})


# ── 상태 ──
@app.route('/api/status')
def api_status():
    return jsonify({
        "step": state["current_step"],
        "completed": list(state["completed"]),
        "photo_count": len(state["photo_results"]),
        "group_count": len(state["selected_groups"]),
        "progress": state["progress"],
    })


# ── 업로드 ──
@app.route('/api/upload', methods=['POST'])
def api_upload():
    files = request.files.getlist('photos')
    if not files:
        return jsonify({"error": "파일이 없습니다"}), 400
    paths, errors = [], []
    for f in files:
        if not f.filename: continue
        try:
            fn = f.filename.replace('/', '_').replace('\\', '_')
            dest = UPLOAD_DIR / fn
            if dest.exists():
                dest = UPLOAD_DIR / f"{dest.stem}_{int(time.time())}{dest.suffix}"
            f.save(str(dest))
            paths.append(str(dest))
        except Exception as e:
            errors.append(f"{f.filename}: {e}")
    state["photo_paths"] = paths
    return jsonify({"uploaded": len(paths), "files": [os.path.basename(p) for p in paths],
                    "errors": errors if errors else None})


# ── 분석 ──
@app.route('/api/analyze', methods=['POST'])
def api_analyze():
    if not state["photo_paths"]:
        return jsonify({"error": "사진 없음"}), 400
    def task():
        state["progress"] = {"status": "analyzing", "message": "사진 분석 중...", "percent": 0}
        try:
            total = len(state["photo_paths"])
            def cb(cur, tot, name):
                state["progress"] = {"status": "analyzing",
                    "message": f"📷 분석 중... ({cur}/{tot}) {Path(name).name}",
                    "percent": int((cur/tot)*100)}
            results = state["analyzer"].analyze_photos(state["photo_paths"], progress_cb=cb)
            state["photo_results"] = results
            state["trip_structure"] = TripStructurer.structure(results)
            state["selected_mode"] = "by_place"
            state["selected_groups"] = state["trip_structure"].get("by_place", [])
            state["group_states"] = {}
            state["completed"].add(1)
            state["progress"] = {"status": "done", "message": f"✅ {len(results)}장 분석 완료", "percent": 100}
        except Exception as e:
            state["progress"] = {"status": "error", "message": f"❌ {e}", "percent": 0}
    threading.Thread(target=task, daemon=True).start()
    return jsonify({"started": True})


# ── 사진 ──
@app.route('/api/photos')
def api_photos():
    results = []
    for r in state["photo_results"]:
        thumb = ""
        fp = r.get("file_path", "")
        if fp and os.path.exists(fp):
            try:
                from PIL import Image, ImageOps
                import io
                img = Image.open(fp)
                try: img = ImageOps.exif_transpose(img)
                except: pass
                img.thumbnail((200, 200))
                buf = io.BytesIO()
                img.save(buf, format='JPEG', quality=60)
                thumb = f"data:image/jpeg;base64,{base64.b64encode(buf.getvalue()).decode()}"
            except: pass
        results.append({
            "file_name": r.get("file_name",""), "location_name": r.get("location_name",""),
            "location_name_local": r.get("location_name_local",""),
            "scene_description": r.get("scene_description",""),
            "food_name": r.get("food_name",""),
            "city": r.get("city",""), "region": r.get("region",""),
            "gps": r.get("gps"), "thumbnail": thumb, "included": True,
        })
    return jsonify(results)


@app.route('/api/photos/rename', methods=['POST'])
def api_photos_rename():
    data = request.json or {}
    old, new = data.get("old_name",""), data.get("new_name","")
    if not old or not new: return jsonify({"error":"이름 필요"}), 400
    cnt = sum(1 for r in state["photo_results"] if r.get("location_name")==old)
    for r in state["photo_results"]:
        if r.get("location_name") == old: r["location_name"] = new
    if cnt and state["photo_results"]:
        state["trip_structure"] = TripStructurer.structure(state["photo_results"])
        state["selected_groups"] = state["trip_structure"].get(state["selected_mode"], [])
    return jsonify({"renamed": cnt})


@app.route('/api/photos/update', methods=['POST'])
def api_photos_update():
    data = request.json or {}
    idx, new = data.get("index",-1), data.get("location_name","")
    if idx<0 or idx>=len(state["photo_results"]) or not new:
        return jsonify({"error":"잘못된 요청"}), 400
    state["photo_results"][idx]["location_name"] = new
    if state["photo_results"]:
        state["trip_structure"] = TripStructurer.structure(state["photo_results"])
        state["selected_groups"] = state["trip_structure"].get(state["selected_mode"], [])
    return jsonify({"updated": True})


# ── 그룹 ──
@app.route('/api/groups')
def api_groups():
    if state.get("plan") and state["plan"].get("days"):
        groups = _active_groups()
        return jsonify([{"label": g.get("label",""),
                         "photo_count": len(g.get("photos",[])),
                         "course_line": g.get("course_line","")} for g in groups])
    mode = request.args.get('mode', state["selected_mode"])
    if state["trip_structure"]:
        groups = state["trip_structure"].get(mode, [])
        state["selected_mode"] = mode
        state["selected_groups"] = groups
        return jsonify([{"label":g.get("label",""),"photo_count":len(g.get("photos",[])),"course_line":g.get("course_line","")} for g in groups])
    return jsonify([])


def _is_free_mode():
    return not bool(state["settings"]["api"].get("google_key", ""))


def _plan_path():
    title = (state.get("plan") or {}).get("trip_title", "") or "untitled"
    safe = "".join(c for c in title if c.isalnum() or c in " _-").strip() or "untitled"
    d = os.path.join("plans", safe)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "plan.json")

def _save_plan():
    if not state.get("plan"):
        return
    try:
        with open(_plan_path(), "w", encoding="utf-8") as f:
            json.dump(state["plan"], f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"plan 저장 실패: {e}")

@app.route('/api/plan/draft', methods=['POST'])
def api_plan_draft():
    data = request.json or {}
    if state.get("plan") and not data.get("overwrite"):
        return jsonify({"need_confirm": True,
                        "message": "기존 계획이 있습니다. 덮어쓸까요?"}), 409
    if not state["photo_results"]:
        return jsonify({"error": "사진 분석을 먼저 실행하세요"}), 400
    from core import TripPlanner
    free_mode = _is_free_mode()
    state["plan"] = TripPlanner.build_draft(state["photo_results"], free_mode=free_mode)
    _save_plan()
    return jsonify(state["plan"])

@app.route('/api/plan', methods=['GET'])
def api_plan_get():
    return jsonify(state.get("plan") or {})

@app.route('/api/plan', methods=['POST'])
def api_plan_post():
    state["plan"] = request.json or {}
    _save_plan()
    return jsonify({"ok": True})


def _find_stop(plan, stop_id):
    for d in plan.get("days", []):
        for s in d.get("stops", []):
            if s["stop_id"] == stop_id:
                return d, s
    return None, None

def _remove_pid_everywhere(plan, pid):
    for d in plan.get("days", []):
        for s in d.get("stops", []):
            if pid in s.get("photo_ids", []):
                s["photo_ids"].remove(pid)
    for k in ("undated_photo_ids", "excluded_photo_ids"):
        if pid in plan.get(k, []):
            plan[k].remove(pid)

@app.route('/api/plan/stop/move', methods=['POST'])
def api_plan_move():
    data = request.json or {}
    plan = state.get("plan") or {}
    pid, to_stop = data.get("photo_id"), data.get("to_stop_id")
    if not pid or not to_stop:
        return jsonify({"error": "photo_id/to_stop_id 필요"}), 400
    _, s = _find_stop(plan, to_stop)
    if not s:
        return jsonify({"error": "대상 장소 없음"}), 400
    _remove_pid_everywhere(plan, pid)
    s.setdefault("photo_ids", []).append(pid)
    _save_plan()
    return jsonify({"ok": True})

@app.route('/api/plan/exclude', methods=['POST'])
def api_plan_exclude():
    data = request.json or {}
    plan = state.get("plan") or {}
    pid = data.get("photo_id")
    if not pid:
        return jsonify({"error": "photo_id 필요"}), 400
    _remove_pid_everywhere(plan, pid)
    if data.get("restore"):
        plan.setdefault("undated_photo_ids", []).append(pid)
    else:
        plan.setdefault("excluded_photo_ids", []).append(pid)
    _save_plan()
    return jsonify({"ok": True})

@app.route('/api/plan/receipt', methods=['POST'])
def api_plan_receipt():
    from core import ReceiptReader
    from werkzeug.utils import secure_filename
    stop_id = request.form.get("stop_id")
    f = request.files.get("receipt")
    if not f or not stop_id:
        return jsonify({"error": "stop_id/파일 필요"}), 400
    plan = state.get("plan") or {}
    _, s = _find_stop(plan, stop_id)
    if not s:
        return jsonify({"error": "대상 장소 없음 (계획을 먼저 생성하세요)"}), 400
    rdir = os.path.join("uploads", "receipts"); os.makedirs(rdir, exist_ok=True)
    fname = secure_filename(f"{stop_id}_{f.filename}") or "receipt.jpg"
    path = os.path.join(rdir, fname)
    f.save(path)
    info = ReceiptReader(state["cfg"]).read(path)
    info["image_path"] = path
    s["receipt"] = info
    suggest = ReceiptReader.crosscheck_name(info.get("store_name", ""), s.get("name", ""))
    _save_plan()
    return jsonify({"receipt": info, "suggest_name": suggest})


# ── SEO ──
@app.route('/api/seo', methods=['POST'])
def api_seo():
    data = request.json or {}
    keyword = data.get("keyword","")
    if not keyword:
        plan = state.get("plan") or {}
        region = plan.get("region","")        # E 연결점: 확정 지역명을 네이버 검색 키워드로 우선
        if region:
            keyword = region + " 여행"
        else:
            locs = set()
            for r in state["photo_results"]:
                if r.get("city"): locs.add(r["city"])
                if r.get("region"): locs.add(r["region"])
            keyword = " ".join(list(locs)[:2]) + " 여행" if locs else "여행"
    try:
        nba = NaverBlogAnalyzer(state["cfg"])
        analysis = nba.analyze(keyword)
        state["naver_analysis"] = analysis
        return jsonify({"keyword":keyword, "analysis":analysis})
    except Exception as e:
        return jsonify({"error":str(e)}), 500


# ── 스타일 분석 ──
@app.route('/api/style', methods=['POST'])
def api_style():
    data = request.json or {}
    urls = data.get("urls", [])
    if not urls: return jsonify({"error":"URL 필요"}), 400
    try:
        sa = StyleAnalyzer()
        results = [sa.analyze(u) for u in urls]
        if results:
            merged = dict(results[0])
            all_p, all_e = [], []
            for r in results:
                all_p.extend(r.get("sample_paragraphs",[])); all_e.extend(r.get("common_endings",[]))
            merged["sample_paragraphs"] = list(dict.fromkeys(all_p))[:10]
            merged["common_endings"] = list(dict.fromkeys(all_e))[:10]
            state["style_analysis"] = merged
        return jsonify({"count":len(results),"results":results})
    except Exception as e:
        return jsonify({"error":str(e)}), 500


def _apply_settings_to_generator():
    """settings의 blog_style/custom_prompt를 generator에 반영"""
    s = state["settings"]
    bs = s.get("blog_style", {})
    ds = s.get("design", {})
    cp = s.get("custom_prompt", {})

    # 커스텀 프롬프트 조각 생성
    parts = []
    parts.append(f"[사용자 스타일 설정]")
    parts.append(f"- 말투: {bs.get('tone','친근 구어체')}")
    parts.append(f"- 톤: {bs.get('mood','감성적')}")
    parts.append(f"- 이모지: {bs.get('emoji_level','적당히')}")
    parts.append(f"- 사진 설명: {bs.get('photo_desc_length','2~3줄')}")
    parts.append(f"- 장소 소개: {bs.get('place_intro_length','3~4줄')}")
    if not bs.get("include_tips", True):
        parts.append("- 꿀팁 섹션: 미포함 (TRAVEL TIPS 섹션 생략)")
    if not bs.get("include_outro", True):
        parts.append("- 마무리 인사: 미포함 (아웃트로 생략)")
    parts.append(f"- 포인트 색상: {ds.get('accent_color','#8B9467')}")
    parts.append(f"- 구분선: {ds.get('separator_style','─ ─ ─')}")
    parts.append(f"- 장소 라벨: {ds.get('place_label','PLACE N')}")

    if cp.get("extra_instructions"):
        parts.append(f"\n[추가 지시사항]\n{cp['extra_instructions']}")
    if cp.get("banned_expressions"):
        parts.append(f"\n[금지 표현] 다음 표현 사용 금지: {cp['banned_expressions']}")
    if cp.get("required_keywords"):
        parts.append(f"\n[필수 키워드] 반드시 포함: {cp['required_keywords']}")

    # generator에 custom_style_prompt 속성으로 저장
    state["generator"]._custom_style_prompt = "\n".join(parts)


def _active_groups():
    """plan이 있으면 확정 plan 기반 Day 그룹, 없으면 기존 selected_groups."""
    plan = state.get("plan")
    if plan and plan.get("days"):
        from core import TripPlanner
        g = TripPlanner.groups_from_plan(plan, state["photo_results"])
        if g:
            return g
    return state["selected_groups"]


# ── AI 생성 (단일 그룹) ──
@app.route('/api/generate', methods=['POST'])
def api_generate():
    data = request.json or {}
    gi = data.get("group_index", 0)
    title = data.get("title","")
    structure = data.get("structure","감성 후기형")
    place_memos = data.get("place_memos",{})
    route_modes = data.get("route_modes",{})
    groups = _active_groups()
    if gi >= len(groups):
        return jsonify({"error":"잘못된 그룹"}), 400
    def task():
        state["progress"] = {"status":"generating","message":"AI 초안 생성 중...","percent":0}
        try:
            _apply_settings_to_generator()
            g = groups[gi]
            tmp = dict(g); tmp["place_memos"] = {**g.get("place_memos", {}), **(data.get("place_memos") or {})}
            dr = state["generator"].generate_drafts(
                tmp, g["label"], title,
                state["naver_analysis"], state["style_analysis"],
                selected_structure=structure, route_modes=route_modes,
                progress_cb=lambda m: state["progress"].update({"message":m}))
            state["group_states"].setdefault(gi,{})["drafts"] = dr
            state["completed"].add(3)
            state["progress"] = {"status":"done","message":f"✅ {len(dr)}개 초안 완료","percent":100}
        except Exception as e:
            state["progress"] = {"status":"error","message":f"❌ {e}","percent":0}
    threading.Thread(target=task, daemon=True).start()
    return jsonify({"started":True})


# ── AI 생성 (전체 그룹) ──
@app.route('/api/generate_all', methods=['POST'])
def api_generate_all():
    data = request.json or {}
    title = data.get("title","")
    structure = data.get("structure","감성 후기형")
    place_memos = data.get("place_memos",{})
    route_modes = data.get("route_modes",{})
    groups = _active_groups()
    total = len(groups)
    if total == 0:
        return jsonify({"error":"그룹 없음"}), 400
    def task():
        state["progress"] = {"status":"generating","message":f"전체 {total}개 그룹 생성 중...","percent":0}
        try:
            _apply_settings_to_generator()
            for gi in range(total):
                g = groups[gi]
                state["progress"] = {"status":"generating",
                    "message":f"[{gi+1}/{total}] {g.get('label','')} 생성 중...",
                    "percent":int((gi/total)*100)}
                tmp = dict(g); tmp["place_memos"] = {**g.get("place_memos", {}), **(data.get("place_memos") or {})}
                dr = state["generator"].generate_drafts(
                    tmp, g["label"], title,
                    state["naver_analysis"], state["style_analysis"],
                    selected_structure=structure, route_modes=route_modes,
                    progress_cb=lambda m,_gi=gi: state["progress"].update(
                        {"message":f"[{_gi+1}/{total}] {m}"}))
                state["group_states"].setdefault(gi,{})["drafts"] = dr
            state["completed"].add(3)
            state["progress"] = {"status":"done","message":f"✅ 전체 {total}개 그룹 완료","percent":100}
        except Exception as e:
            state["progress"] = {"status":"error","message":f"❌ {e}","percent":0}
    threading.Thread(target=task, daemon=True).start()
    return jsonify({"started":True,"total":total})


# ── 초안/블록 ──
@app.route('/api/drafts/<int:gi>')
def api_drafts(gi):
    gs = state["group_states"].get(gi,{})
    return jsonify([{"title":d.get("title",""),"content":d.get("content",""),
        "tags":d.get("tags",[]),"meta_description":d.get("meta_description",""),
        "hashtags":d.get("hashtags",[])} for d in gs.get("drafts",[])])


@app.route('/api/blocks/<int:gi>/<int:di>')
def api_blocks(gi, di):
    gs = state["group_states"].get(gi,{})
    drafts = gs.get("drafts",[])
    if di >= len(drafts): return jsonify({"error":"잘못된 인덱스"}), 400
    d = drafts[di]
    groups = _active_groups()
    photos = groups[gi].get("photos", []) if gi < len(groups) else []
    blocks = html_to_blocks(d.get("content",""), photos)
    return jsonify({"title":d.get("title",""),"tags":d.get("tags",[]),"blocks":blocks})


# ── 미리보기 ──
@app.route('/api/preview', methods=['POST'])
def api_preview():
    data = request.json or {}
    blocks = data.get("blocks",[])
    return jsonify({"html": blocks_to_html(blocks)})


# ── 발행 ──
@app.route('/api/publish', methods=['POST'])
def api_publish():
    data = request.json or {}
    title = data.get("title","")
    blocks = data.get("blocks",[])
    tags = data.get("tags",[])
    visibility = data.get("visibility", state["settings"]["api"].get("default_visibility","비공개"))
    method = data.get("method", state["settings"]["api"].get("publish_method","selenium"))

    def task():
        state["progress"] = {"status":"publishing","message":"발행 준비 중...","percent":0}
        try:
            content_html = blocks_to_html(blocks)
            post_data = {"title":title,"content":content_html,"tags":tags,
                         "blocks":blocks,"visibility":visibility}
            poster = NaverPoster(state["cfg"])
            result = poster.post(post_data, method=method, visibility=visibility)
            if result.get("success"):
                url = result.get("url","")
                state["progress"] = {"status":"done",
                    "message":f"✅ 발행 완료!{' URL: '+url if url else ''}","percent":100}
            else:
                state["progress"] = {"status":"error",
                    "message":f"❌ {result.get('reason','알 수 없는 오류')}","percent":0}
        except Exception as e:
            state["progress"] = {"status":"error","message":f"❌ {e}","percent":0}
    threading.Thread(target=task, daemon=True).start()
    return jsonify({"started":True})


# ── 전체 발행 ──
@app.route('/api/publish_all', methods=['POST'])
def api_publish_all():
    data = request.json or {}
    group_data = data.get("groups",[])  # [{title, blocks, tags}, ...]
    visibility = data.get("visibility", state["settings"]["api"].get("default_visibility","비공개"))
    method = data.get("method", state["settings"]["api"].get("publish_method","selenium"))
    total = len(group_data)
    if not total: return jsonify({"error":"데이터 없음"}), 400
    def task():
        state["progress"] = {"status":"publishing","message":f"전체 {total}개 발행 중...","percent":0}
        try:
            poster = NaverPoster(state["cfg"])
            for i, gd in enumerate(group_data):
                state["progress"]["message"] = f"[{i+1}/{total}] 발행 중..."
                state["progress"]["percent"] = int((i/total)*100)
                content_html = blocks_to_html(gd.get("blocks",[]))
                post_data = {"title":gd.get("title",""),"content":content_html,
                             "tags":gd.get("tags",[]),"blocks":gd.get("blocks",[]),
                             "visibility":visibility}
                poster.post(post_data, method=method, visibility=visibility)
                time.sleep(5)  # 스팸 방지
            state["progress"] = {"status":"done","message":f"✅ {total}개 발행 완료!","percent":100}
        except Exception as e:
            state["progress"] = {"status":"error","message":f"❌ {e}","percent":0}
    threading.Thread(target=task, daemon=True).start()
    return jsonify({"started":True})


# ── 저장 ──
@app.route('/api/save', methods=['POST'])
def api_save():
    data = request.json or {}
    saver = LocalSaver()
    result = saver.save({"title":data.get("title",""),"content":data.get("content",""),
                         "tags":data.get("tags",[]),"meta_description":""})
    return jsonify({"saved_to": result})


@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    return send_from_directory(str(UPLOAD_DIR), filename)


if __name__ == '__main__':
    init_engine()
    print("\n" + "="*50)
    print("  TravelBlog Pro v10.0 — Web Edition (Final)")
    print("  http://localhost:5000")
    print("="*50 + "\n")
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)
