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
from posters import NaverPoster, TistoryPoster, html_to_blocks, summarize_publish_results

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
    "receipts": [],
    "published_gis": set(),
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


def _load_last_plan():
    """서버 시작 시 가장 최근 프로젝트 자동 복원(plan+분석결과+발행기록)."""
    try:
        cands = list(Path("plans").glob("*/plan.json")) + list(Path("plans").glob("*/project.json"))
        if not cands:
            return
        latest = max(cands, key=lambda p: p.stat().st_mtime)
        if _load_project_data(str(latest.parent)):
            logger.info(f"📂 이전 프로젝트 자동 복원: {latest.parent}")
    except Exception as e:
        logger.warning(f"프로젝트 자동 복원 실패(무시): {e}")


def init_engine():
    load_settings()
    state["cfg"] = Config()
    state["analyzer"] = PhotoAnalyzer(state["cfg"])
    state["generator"] = TravelBlogGenerator(state["cfg"])
    _load_last_plan()


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
def api_profile_load(name):
    """프로필 로드"""
    f = PROFILE_DIR / f"{name}.json"
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
    LAST_PROFILE.write_text(name, encoding='utf-8')
    logger.info(f"프로필 로드: {name}")
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
def api_profile_delete(name):
    """프로필 삭제"""
    f = PROFILE_DIR / f"{name}.json"
    if f.exists():
        f.unlink()
        logger.info(f"프로필 삭제: {name}")
    return jsonify({"deleted": True})


# ── 상태 ──
@app.route('/api/status')
def api_status():
    return jsonify({
        "step": state["current_step"],
        "completed": list(state["completed"]),
        "upload_count": len(state.get("photo_paths", [])),
        "photo_count": len(state["photo_results"]),
        "group_count": len(_active_groups()),
        "has_plan": bool((state.get("plan") or {}).get("days")),
        "has_drafts": any(gs.get("drafts") for gs in state.get("group_states", {}).values()),
        "has_saved_drafts": os.path.isdir(os.path.join(_plan_dir(), "drafts")) if state.get("plan") else False,
        "progress": state["progress"],
        "published_gis": sorted(state.get("published_gis") or []),
        "project": os.path.basename(state.get("_plan_dir") or ""),
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
            _save_project()
            state["progress"] = {"status": "done", "message": f"✅ {len(results)}장 분석 완료", "percent": 100}
        except Exception as e:
            state["progress"] = {"status": "error", "message": f"❌ {e}", "percent": 0}
    threading.Thread(target=task, daemon=True).start()
    return jsonify({"started": True})


# ── 사진 ──
@app.route('/api/photos')
def api_photos():
    from core import TripPlanner
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
            "pid": TripPlanner._photo_id(fp),
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


def _plan_dir():
    """현재 프로젝트 폴더. 제목이 없으면 '여행_YYYYMMDD_HHMM' 자동 부여(untitled 충돌 방지).
    한 세션 안에서는 state['_plan_dir'] 캐시로 일관성 유지(제목 생기면 _save_plan이 리네임)."""
    title = (state.get("plan") or {}).get("trip_title", "") or ""
    safe = "".join(c for c in title if c.isalnum() or c in " _-").strip()
    if safe:
        return os.path.join("plans", safe)
    if state.get("_plan_dir"):
        return state["_plan_dir"]
    name = "여행_" + datetime.now().strftime("%Y%m%d_%H%M")
    state["_plan_dir"] = os.path.join("plans", name)
    return state["_plan_dir"]

def _save_plan():
    if not state.get("plan"):
        return
    try:
        new_dir = _plan_dir()
        old_dir = state.get("_plan_dir")
        # 제목 변경으로 폴더명이 달라지면 새로 만들지 않고 기존 폴더를 리네임(고아 폴더 방지)
        if old_dir and old_dir != new_dir and os.path.isdir(old_dir) and not os.path.exists(new_dir):
            os.rename(old_dir, new_dir)
        os.makedirs(new_dir, exist_ok=True)
        state["_plan_dir"] = new_dir
        with open(os.path.join(new_dir, "plan.json"), "w", encoding="utf-8") as f:
            json.dump(state["plan"], f, ensure_ascii=False, indent=2)
        _save_project()
    except Exception as e:
        logger.warning(f"plan 저장 실패: {e}")


def _save_drafts(gi):
    """생성/재작성된 초안을 plan 폴더에 영구 저장 (서버 재시작 대비). 실패는 로그만."""
    try:
        drafts = state["group_states"].get(gi, {}).get("drafts")
        if not drafts:
            return
        d = os.path.join(_plan_dir(), "drafts")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"group_{gi}.json"), "w", encoding="utf-8") as f:
            json.dump(drafts, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"초안 저장 실패(무시): {e}")


def _load_saved_drafts(gi):
    """저장된 초안 파일 로드. 없으면 None."""
    try:
        p = os.path.join(_plan_dir(), "drafts", f"group_{gi}.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"초안 로드 실패(무시): {e}")
    return None


_SESSION_KEYS = ["photo_paths", "photo_results", "naver_analysis",
                 "style_analysis", "receipts"]


def _save_project():
    """현재 세션(분석 결과·SEO·문체·영수증·발행기록)을 project.json으로 저장 — 여행=프로젝트.
    완전 빈 세션만 제외 — 새 여행 직후 문체 분석만 한 상태도 저장돼야
    서버 재시작에서 살아남는다(사진/plan 없다고 문체를 버리면 안 됨)."""
    if not (state.get("plan") or any(state.get(k) for k in _SESSION_KEYS)):
        return
    try:
        d = _plan_dir()
        os.makedirs(d, exist_ok=True)
        snap = {k: state.get(k) for k in _SESSION_KEYS}
        snap["published_gis"] = sorted(state.get("published_gis") or [])
        snap["completed"] = sorted(state.get("completed") or [])
        snap["saved_at"] = datetime.now().isoformat(timespec="seconds")
        with open(os.path.join(d, "project.json"), "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"프로젝트 저장 실패(무시): {e}")


def _load_project_data(folder):
    """plans/<folder>의 plan.json+project.json을 state로 스왑. 성공 시 True."""
    try:
        pj = os.path.join(folder, "plan.json")
        if os.path.exists(pj):
            with open(pj, encoding="utf-8") as f:
                state["plan"] = json.load(f)
        prj = os.path.join(folder, "project.json")
        if os.path.exists(prj):
            with open(prj, encoding="utf-8") as f:
                snap = json.load(f)
            for k in _SESSION_KEYS:
                if k in snap:
                    state[k] = snap[k]
            state["published_gis"] = set(snap.get("published_gis") or [])
            state["completed"] = set(snap.get("completed") or [])
        state["group_states"] = {}   # 초안은 drafts/ 파일 복원 훅이 처리
        state["_plan_dir"] = folder
        return os.path.exists(pj) or os.path.exists(prj)
    except Exception as e:
        logger.warning(f"프로젝트 로드 실패(무시): {e}")
        return False


# ── 프로젝트 (여행 = 독립 프로젝트) ──
@app.route('/api/projects')
def api_projects():
    items = []
    try:
        for d in Path("plans").iterdir():
            if not d.is_dir():
                continue
            pj = d / "plan.json"
            info = {"folder": d.name, "trip_title": "", "region": "", "days": 0,
                    "saved_at": "", "has_drafts": (d / "drafts").is_dir()}
            if pj.exists():
                try:
                    p = json.loads(pj.read_text(encoding="utf-8"))
                    info.update({"trip_title": p.get("trip_title", ""),
                                 "region": p.get("region", ""),
                                 "days": len(p.get("days", []))})
                except Exception:
                    pass
            prj = d / "project.json"
            if prj.exists():
                try:
                    info["saved_at"] = json.loads(prj.read_text(encoding="utf-8")).get("saved_at", "")
                except Exception:
                    pass
            items.append(info)
    except FileNotFoundError:
        pass
    items.sort(key=lambda x: x["saved_at"], reverse=True)
    cur = state.get("_plan_dir") or ""
    return jsonify({"projects": items, "current": os.path.basename(cur) if cur else ""})


@app.route('/api/projects/open', methods=['POST'])
def api_projects_open():
    folder = (request.json or {}).get("folder", "")
    target = os.path.join("plans", os.path.basename(folder))
    if not os.path.isdir(target):
        return jsonify({"error": "프로젝트 없음"}), 404
    _save_project()   # 현재 작업 먼저 저장 — 유실 없음
    if not _load_project_data(target):
        return jsonify({"error": "로드 실패 — 현재 세션 유지"}), 500
    return jsonify({"ok": True, "folder": os.path.basename(target)})


@app.route('/api/projects/new', methods=['POST'])
def api_projects_new():
    _save_project()   # 현재 작업 먼저 저장
    state.update({"photo_paths": [], "photo_results": [], "trip_structure": None,
                  "selected_groups": [], "group_states": {}, "naver_analysis": None,
                  "style_analysis": None, "plan": None, "receipts": [],
                  "published_gis": set(), "completed": set(), "_plan_dir": None})
    # 새 프로젝트 폴더를 즉시 생성 — 셀렉터 목록에 바로 보이고 current로 등록
    # (안 만들면 "새 여행 추가가 안 된다"로 보임 + 셀렉터가 이전 여행을 표시해 혼란)
    name = "여행_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    d = os.path.join("plans", name)
    try:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "project.json"), "w", encoding="utf-8") as f:
            json.dump({"saved_at": datetime.now().isoformat(timespec="seconds")}, f, ensure_ascii=False)
        state["_plan_dir"] = d
    except Exception as e:
        logger.warning(f"새 프로젝트 폴더 생성 실패(무시): {e}")
    return jsonify({"ok": True, "folder": name})


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
    _old_plan = state.get("plan")
    state["plan"] = TripPlanner.build_draft(state["photo_results"], free_mode=free_mode)
    if data.get("title"):
        state["plan"]["trip_title"] = data["title"]
    if state["receipts"]:
        TripPlanner.match_receipts_to_stops(state["plan"], state["receipts"])
    if _old_plan and _old_plan.get("days"):
        TripPlanner.merge_user_edits(state["plan"], _old_plan)
    _save_plan()
    # 새 계획 확정 = 새 원고 세션: 이전 여행의 초안·SEO 근거가 새 여행에 새어들지 않게 초기화
    # (오사카 테스트 후 도쿄 업로드 시 오사카 초안이 계속 나오던 혼입 버그)
    state["group_states"] = {}
    state["naver_analysis"] = None
    try:
        import shutil
        _dd = os.path.join(_plan_dir(), "drafts")
        if os.path.isdir(_dd):
            shutil.rmtree(_dd)
    except Exception as e:
        logger.warning(f"이전 초안 폴더 정리 실패(무시): {e}")
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

@app.route('/api/receipts/upload', methods=['POST'])
def api_receipts_upload():
    from core import ReceiptReader, Config
    from werkzeug.utils import secure_filename
    files = request.files.getlist("receipts")
    if not files:
        return jsonify({"error": "영수증 파일 필요"}), 400
    cfg = state.get("cfg") or Config()   # 분석 전(cfg=None)에도 OCR 동작
    reader = ReceiptReader(cfg)
    rdir = os.path.join("uploads", "receipts"); os.makedirs(rdir, exist_ok=True)
    out = []
    for f in files:
        if not f or not f.filename:
            continue
        fname = secure_filename(f.filename) or "receipt.jpg"
        path = os.path.join(rdir, fname)
        f.save(path)
        info = reader.read(path)
        info["image_path"] = path
        state["receipts"].append(info)
        out.append(info)
    # plan이 이미 있으면 즉시 재매칭
    if state.get("plan") and state["plan"].get("days"):
        from core import TripPlanner
        TripPlanner.match_receipts_to_stops(state["plan"], state["receipts"])
        _save_plan()
    return jsonify({"count": len(out), "receipts": out,
                    "total": len(state["receipts"])})

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
    if not urls:
        return jsonify({"error": "URL 필요"}), 400
    try:
        sa = StyleAnalyzer(state.get("cfg"))
        results = [sa.analyze(u) for u in urls]
        if results:
            merged = dict(results[0])
            all_end, all_ex, all_src = [], [], []
            for r in results:
                all_end.extend(r.get("ending_patterns", []))
                all_ex.extend(r.get("examples", []))
                all_src.extend(r.get("source_urls", []))
            merged["ending_patterns"] = list(dict.fromkeys(all_end))[:6]
            merged["examples"] = list(dict.fromkeys(all_ex))[:2]
            merged["source_urls"] = list(dict.fromkeys(all_src))
            state["style_analysis"] = merged
            # 문체 분석은 여기서만 갱신되는데 자동저장 훅(분석완료·plan저장·발행성공)
            # 밖이라, 저장하지 않으면 서버 재시작 시 소실된다 → 즉시 프로젝트에 저장
            _save_project()
        warning = next((r.get("warning") for r in results if r.get("warning")), None)
        return jsonify({"count": len(results), "results": results, "warning": warning})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
            # 위키박스 실측 근거: SEO 분석이 없으면 자동 1회 확보(실패해도 생성 계속)
            if not state.get("naver_analysis"):
                try:
                    _plan = state.get("plan") or {}
                    _kw = (_plan.get("region") or "").strip()
                    if _kw:
                        state["progress"]["message"] = "지역 상위 블로그 분석 중..."
                        state["naver_analysis"] = NaverBlogAnalyzer(state["cfg"]).analyze(_kw + " 여행")
                except Exception as _e:
                    logger.warning(f"자동 SEO 분석 실패(무시): {_e}")
            _apply_settings_to_generator()
            g = groups[gi]
            tmp = dict(g); tmp["place_memos"] = {**g.get("place_memos", {}), **(data.get("place_memos") or {})}
            dr = state["generator"].generate_drafts(
                tmp, g["label"], title,
                state["naver_analysis"], state["style_analysis"],
                selected_structure=structure, route_modes=route_modes,
                progress_cb=lambda m: state["progress"].update({"message":m}))
            state["group_states"].setdefault(gi,{})["drafts"] = dr
            _save_drafts(gi)
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
            # 위키박스 실측 근거: SEO 분석이 없으면 자동 1회 확보(실패해도 생성 계속)
            if not state.get("naver_analysis"):
                try:
                    _plan = state.get("plan") or {}
                    _kw = (_plan.get("region") or "").strip()
                    if _kw:
                        state["progress"]["message"] = "지역 상위 블로그 분석 중..."
                        state["naver_analysis"] = NaverBlogAnalyzer(state["cfg"]).analyze(_kw + " 여행")
                except Exception as _e:
                    logger.warning(f"자동 SEO 분석 실패(무시): {_e}")
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
                _save_drafts(gi)
            state["completed"].add(3)
            state["progress"] = {"status":"done","message":f"✅ 전체 {total}개 그룹 완료","percent":100}
        except Exception as e:
            state["progress"] = {"status":"error","message":f"❌ {e}","percent":0}
    threading.Thread(target=task, daemon=True).start()
    return jsonify({"started":True,"total":total})


# ── 피드백 재작성 (가안 → 최종본) ──
@app.route('/api/revise', methods=['POST'])
def api_revise():
    data = request.json or {}
    gi = int(data.get("gi", 0))
    di = int(data.get("di", 0))
    feedback = (data.get("feedback") or "").strip()
    if not feedback:
        return jsonify({"error": "피드백이 비어있습니다"}), 400
    gs = state["group_states"].get(gi, {})
    drafts = gs.get("drafts", [])
    if di >= len(drafts):
        return jsonify({"error": "초안 없음"}), 400
    def task():
        state["progress"] = {"status": "revising", "message": "피드백 반영해 재작성 중...", "percent": 0}
        try:
            new_post = state["generator"].revise_draft(
                drafts[di], feedback, state.get("naver_analysis"))
            if new_post:
                drafts[di] = new_post
                _save_drafts(gi)
                state["progress"] = {"status": "done", "message": "✅ 최종본 재작성 완료", "percent": 100}
            else:
                state["progress"] = {"status": "error",
                                     "message": "❌ 재작성 실패 — 원본은 유지됩니다", "percent": 0}
        except Exception as e:
            state["progress"] = {"status": "error", "message": f"❌ {e} (원본 유지)", "percent": 0}
    threading.Thread(target=task, daemon=True).start()
    return jsonify({"started": True})


# ── 초안/블록 ──
@app.route('/api/drafts/save', methods=['POST'])
def api_drafts_save():
    saved = []
    for gi, gs in state["group_states"].items():
        if gs.get("drafts"):
            _save_drafts(gi)
            saved.append(gi)
    return jsonify({"saved_groups": saved})


@app.route('/api/drafts/<int:gi>')
def api_drafts(gi):
    gs = state["group_states"].get(gi,{})
    if not gs.get("drafts"):
        saved = _load_saved_drafts(gi)
        if saved:
            state["group_states"].setdefault(gi, {})["drafts"] = saved
            gs = state["group_states"][gi]
    return jsonify([{"title":d.get("title",""),"content":d.get("content",""),
        "tags":d.get("tags",[]),"meta_description":d.get("meta_description",""),
        "hashtags":d.get("hashtags",[]),
        "seo_warnings":d.get("seo_warnings",[])} for d in gs.get("drafts",[])])


@app.route('/api/blocks/<int:gi>/<int:di>')
def api_blocks(gi, di):
    gs = state["group_states"].get(gi,{})
    if not gs.get("drafts"):
        saved = _load_saved_drafts(gi)
        if saved:
            state["group_states"].setdefault(gi, {})["drafts"] = saved
            gs = state["group_states"][gi]
    drafts = gs.get("drafts",[])
    if di >= len(drafts): return jsonify({"error":"잘못된 인덱스"}), 400
    d = drafts[di]
    groups = _active_groups()
    photos = groups[gi].get("photos", []) if gi < len(groups) else []
    if not photos:
        photos = d.get("photo_results", [])   # 서버 재시작 후 복원 경로(base64 이미지 매칭용)
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
        poster = None
        try:
            content_html = blocks_to_html(blocks)
            post_data = {"title":title,"content":content_html,"tags":tags,
                         "blocks":blocks,"visibility":visibility}
            poster = NaverPoster(state["cfg"])
            result = poster.post(post_data, method=method, visibility=visibility)
            if result.get("success"):
                url = result.get("url","")
                _gi = data.get("gi")
                if _gi is not None:
                    state["published_gis"].add(int(_gi))
                _save_project()
                state["progress"] = {"status":"done",
                    "message":f"✅ 발행 완료!{' URL: '+url if url else ''}","percent":100}
            else:
                state["progress"] = {"status":"error",
                    "message":f"❌ {result.get('reason','알 수 없는 오류')}","percent":0}
        except Exception as e:
            state["progress"] = {"status":"error","message":f"❌ {e}","percent":0}
        finally:
            # 브라우저를 닫아 selenium_profile 잠금 해제 — 안 닫으면 다음 발행이
            # "session not created: Chrome instance exited"로 전부 실패한다.
            # 로그인 세션은 프로필에 저장되므로 재로그인 불필요.
            if poster:
                try: poster.close()
                except: pass
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
        poster = None
        try:
            poster = NaverPoster(state["cfg"])
            results, titles = [], []
            for i, gd in enumerate(group_data):
                state["progress"]["message"] = f"[{i+1}/{total}] 발행 중..."
                state["progress"]["percent"] = int((i/total)*100)
                content_html = blocks_to_html(gd.get("blocks",[]))
                post_data = {"title":gd.get("title",""),"content":content_html,
                             "tags":gd.get("tags",[]),"blocks":gd.get("blocks",[]),
                             "visibility":visibility}
                r = poster.post(post_data, method=method, visibility=visibility)
                results.append(r); titles.append(gd.get("title","") or f"#{i+1}")
                time.sleep(5)  # 스팸 방지
            # 실패를 무시하고 "완료"로 보고하던 버그 수정 — 결과 기반 요약
            status, msg = summarize_publish_results(results, titles)
            for _i, _r in enumerate(results):
                if (_r or {}).get("success"):
                    state["published_gis"].add(_i)
            _save_project()
            state["progress"] = {"status":status,"message":msg,
                                 "percent":100 if status=="done" else 0}
        except Exception as e:
            state["progress"] = {"status":"error","message":f"❌ {e}","percent":0}
        finally:
            # 브라우저 닫아 selenium_profile 잠금 해제 (단건 발행과 동일 이유)
            if poster:
                try: poster.close()
                except: pass
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
