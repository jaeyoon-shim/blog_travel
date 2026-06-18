"""
TravelBlog Pro v3.0 — SaaS 수준 블로그 자동화
STEP 1~5 단계별 워크플로우
"""
import os, sys, re, json, threading, webbrowser, logging
from pathlib import Path
from core import (Config, PhotoAnalyzer, TripStructurer, TravelBlogGenerator,
                  LocalSaver, NaverBlogAnalyzer, StyleAnalyzer, logger)
from posters import NaverPoster, TistoryPoster
try:
    import tkinter as tk; from tkinter import ttk, filedialog, messagebox as msg
except ImportError:
    print("tkinter 필요"); sys.exit(1)
try:
    from PIL import Image, ImageTk; HAS_PIL = True
except ImportError:
    HAS_PIL = False

# ═══ 디자인 시스템 ═══
C = {"bg":"#0f172a","sf":"#1e293b","sf2":"#334155","bd":"#475569",
     "fg":"#f1f5f9","fg2":"#94a3b8","fg3":"#64748b",
     "pri":"#3b82f6","pri2":"#2563eb","ok":"#10b981",
     "warn":"#f59e0b","err":"#ef4444","acc":"#8b5cf6"}


class TravelBlogGUI:
    def __init__(self):
        self.cfg = Config()
        self.analyzer = PhotoAnalyzer(self.cfg)
        self.generator = TravelBlogGenerator(self.cfg)
        self.saver = LocalSaver()
        self.naver_poster = NaverPoster(self.cfg)
        self.tistory_poster = TistoryPoster(self.cfg)
        # 상태
        self.photo_paths = []
        self.photo_results = []
        self.trip_structure = None
        self.selected_mode = "by_day"
        self.selected_groups = []
        self.current_group_idx = 0
        self.group_states = {}
        self.naver_analysis = None
        self.style_analysis = None
        self.struct_checks = []
        self.thumb_cache = {}
        self.photo_check_vars = []
        self.current_step = 1
        self.completed = set()
        self._loading_overlay = None
        self._loading_label = None
        self._loading_sub = None
        self._build()

    # ═══ UI 프레임워크 ═══
    def _build(self):
        self.root = tk.Tk()
        self.root.title("TravelBlog Pro v3.0")
        self.root.geometry("1100x950")
        self.root.configure(bg=C["bg"])
        self.root.minsize(900, 700)

        # 헤더
        hdr = tk.Frame(self.root, bg=C["sf"], height=80)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        brd = tk.Frame(hdr, bg=C["sf"])
        brd.pack(side="left", padx=20, pady=10)
        tk.Label(brd, text="✈️ TravelBlog Pro", fg=C["pri"], bg=C["sf"],
                 font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(brd, text="AI 여행 블로그 자동화 · v3.0", fg=C["fg3"], bg=C["sf"],
                 font=("Segoe UI", 8)).pack(anchor="w")

        # 스텝 인디케이터
        self.step_f = tk.Frame(hdr, bg=C["sf"])
        self.step_f.pack(side="right", padx=20, pady=12)
        self.step_w = []
        names = ["사진 업로드", "SEO & 구조", "사진 선택", "AI 초안", "검토 & 발행"]
        for i, n in enumerate(names):
            sf = tk.Frame(self.step_f, bg=C["sf"]); sf.pack(side="left", padx=3)
            cir = tk.Label(sf, text=str(i + 1), width=3, font=("Segoe UI", 9, "bold"),
                           fg="white", bg=C["fg3"])
            cir.pack()
            lbl = tk.Label(sf, text=n, fg=C["fg3"], bg=C["sf"], font=("맑은 고딕", 7))
            lbl.pack()
            self.step_w.append((cir, lbl))
            if i < 4:
                tk.Label(self.step_f, text="─", fg=C["bd"], bg=C["sf"],
                         font=("Consolas", 9)).pack(side="left")

        tk.Frame(self.root, bg=C["bd"], height=1).pack(fill="x")

        # 스타일
        s = ttk.Style(); s.theme_use("clam")
        s.configure("TNotebook", background=C["bg"], borderwidth=0)
        s.configure("TNotebook.Tab", background=C["sf"], foreground=C["fg2"],
                    padding=[14, 7], font=("맑은 고딕", 9))
        s.map("TNotebook.Tab", background=[("selected", C["pri"])],
              foreground=[("selected", "white")])
        for nm, bg_ in [("P.TButton", C["pri"]), ("S.TButton", C["sf2"]),
                         ("Ok.TButton", C["ok"]), ("Gh.TButton", C["bg"])]:
            s.configure(nm, font=("맑은 고딕", 10, "bold"), padding=8,
                        background=bg_, foreground="white")

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True)

        self._step1(); self._step2(); self._step3(); self._step4(); self._step5()
        self._upd_step()

    def _upd_step(self):
        for i, (cir, lbl) in enumerate(self.step_w):
            n = i + 1
            if n < self.current_step:
                cir.config(bg=C["ok"], text="✓"); lbl.config(fg=C["ok"])
            elif n == self.current_step:
                cir.config(bg=C["pri"], text=str(n)); lbl.config(fg=C["fg"])
            else:
                cir.config(bg=C["fg3"], text=str(n)); lbl.config(fg=C["fg3"])

    def _go(self, n):
        self.current_step = n; self.nb.select(n - 1); self._upd_step()

    # ── 공통 UI 헬퍼 ──
    def _card(self, parent, title="", icon=""):
        cd = tk.Frame(parent, bg=C["sf"], padx=14, pady=10,
                      highlightbackground=C["bd"], highlightthickness=1)
        if title:
            h = tk.Frame(cd, bg=C["sf"]); h.pack(fill="x", pady=(0, 6))
            tk.Label(h, text=f"{icon}  {title}" if icon else title,
                     fg=C["fg"], bg=C["sf"], font=("맑은 고딕", 11, "bold")).pack(anchor="w")
            tk.Frame(cd, bg=C["bd"], height=1).pack(fill="x", pady=(0, 6))
        return cd

    def _inp(self, parent, label, ph=""):
        tk.Label(parent, text=label, fg=C["fg2"], bg=C["sf"],
                 font=("맑은 고딕", 9)).pack(anchor="w", pady=(5, 1))
        e = tk.Entry(parent, font=("맑은 고딕", 10), bg=C["sf2"], fg=C["fg"],
                     insertbackground=C["fg"], relief="flat", highlightthickness=1,
                     highlightbackground=C["bd"], highlightcolor=C["pri"])
        e.pack(fill="x", ipady=5)
        if ph:
            e.insert(0, ph); e.config(fg=C["fg3"])
            e.bind("<FocusIn>", lambda ev: (e.delete(0, "end"), e.config(fg=C["fg"])) if e.get() == ph else None)
            e.bind("<FocusOut>", lambda ev: (e.insert(0, ph), e.config(fg=C["fg3"])) if not e.get().strip() else None)
        return e

    def _gv(self, entry, ph=""):
        v = entry.get().strip()
        return "" if v == ph else v

    def _get_ref_urls(self):
        """참고 블로그 URL 다중 추출"""
        raw = self.ref_urls_text.get("1.0", "end").strip()
        urls = []
        for line in raw.split("\n"):
            u = line.strip()
            if u and u.startswith("http") and u != "https://blog.naver.com/...":
                urls.append(u)
        return urls

    def _ref_clear_hint(self, event=None):
        """힌트 텍스트 자동 삭제"""
        txt = self.ref_urls_text.get("1.0", "end").strip()
        if txt == "https://blog.naver.com/...":
            self.ref_urls_text.delete("1.0", "end")

    # ═══════════════════════════════════════
    # STEP 1: 사진 업로드 & 설정
    # ═══════════════════════════════════════
    def _step1(self):
        t = tk.Frame(self.nb, bg=C["bg"])
        self.nb.add(t, text="  STEP 1  📸  ")
        ct = tk.Frame(t, bg=C["bg"])
        ct.pack(fill="both", expand=True, padx=24, pady=16)

        c1 = self._card(ct, "사진 업로드", "📸")
        c1.pack(fill="x", pady=(0, 12))
        tk.Label(c1, text="여행 사진을 업로드하면 GPS · 장소 · 장면을 자동 분석합니다",
                 fg=C["fg2"], bg=C["sf"], font=("맑은 고딕", 9)).pack(anchor="w", pady=(0, 8))
        br = tk.Frame(c1, bg=C["sf"]); br.pack(fill="x")
        ttk.Button(br, text="📁 폴더 선택", style="P.TButton",
                   command=self._sel_folder).pack(side="left", padx=(0, 8))
        ttk.Button(br, text="🖼️ 파일 선택", style="S.TButton",
                   command=self._sel_files).pack(side="left")
        self.photo_lbl = tk.Label(c1, text="선택된 사진 없음", fg=C["warn"], bg=C["sf"],
                                  font=("맑은 고딕", 10, "bold"))
        self.photo_lbl.pack(anchor="w", pady=(8, 0))

        c2 = self._card(ct, "블로그 설정", "⚙️")
        c2.pack(fill="x", pady=(0, 12))
        self.title_input = self._inp(c2, "여행 제목", "예: 후쿠오카 2박3일")
        self.seo_kw = self._inp(c2, "SEO 키워드", "미입력 시 자동 추출")

        # 참고 블로그 URL (다중 입력)
        ref_f = tk.Frame(c2, bg=C["sf"])
        ref_f.pack(fill="x", pady=(4, 0))
        tk.Label(ref_f, text="📝 참고 블로그 (문체 참고용, 여러 개 가능)", fg=C["fg2"],
                 bg=C["sf"], font=("맑은 고딕", 9)).pack(anchor="w")
        self.ref_urls_text = tk.Text(ref_f, bg=C["sf2"], fg=C["fg"],
                                      font=("맑은 고딕", 9), wrap="word",
                                      relief="flat", height=3,
                                      insertbackground=C["fg"],
                                      highlightthickness=1, highlightbackground=C["bd"],
                                      highlightcolor=C["pri"])
        self.ref_urls_text.pack(fill="x", pady=(2, 0))
        self.ref_urls_text.insert("1.0", "https://blog.naver.com/...\n")
        self.ref_urls_text.bind("<FocusIn>", self._ref_clear_hint)
        tk.Label(ref_f, text="한 줄에 하나씩 URL 입력 — 여러 블로그 문체를 조합하여 반영",
                 fg=C["fg3"], bg=C["sf"], font=("맑은 고딕", 7)).pack(anchor="w")

        ttk.Button(ct, text="▶  사진 분석 시작  →  STEP 2", style="P.TButton",
                   command=self._do_analyze).pack(fill="x", ipady=4, pady=(8, 0))
        self.progress_lbl = tk.Label(ct, text="", fg=C["fg2"], bg=C["bg"],
                                     font=("맑은 고딕", 10))
        self.progress_lbl.pack(pady=(8, 0))

    # ═══════════════════════════════════════
    # STEP 2: 사진 확인 & 장소명 편집
    # ═══════════════════════════════════════
    def _step2(self):
        t = tk.Frame(self.nb, bg=C["bg"])
        self.nb.add(t, text="  STEP 2  🖼️  ")
        ct = tk.Frame(t, bg=C["bg"])
        ct.pack(fill="both", expand=True, padx=24, pady=16)

        nv = tk.Frame(ct, bg=C["sf"], padx=12, pady=8,
                      highlightbackground=C["bd"], highlightthickness=1)
        nv.pack(fill="x", pady=(0, 8))
        ttk.Button(nv, text="◀", style="Gh.TButton",
                   command=self._ph_prev).pack(side="left")
        self.photo_nav = tk.Label(nv, text="", fg=C["warn"], bg=C["sf"],
                                  font=("맑은 고딕", 11, "bold"))
        self.photo_nav.pack(side="left", padx=14)
        ttk.Button(nv, text="▶", style="Gh.TButton",
                   command=self._ph_next).pack(side="left")
        tk.Frame(nv, bg=C["sf"], width=20).pack(side="left", expand=True)
        ttk.Button(nv, text="🔄 장소별 정렬", style="S.TButton",
                   command=self._sort_by_place).pack(side="right", padx=(4, 0))
        ttk.Button(nv, text="전체선택", style="Gh.TButton",
                   command=self._ck_all).pack(side="right", padx=(4, 0))
        ttk.Button(nv, text="전체해제", style="Gh.TButton",
                   command=self._uck_all).pack(side="right")

        # 장소 요약 패널
        self.place_summary_f = tk.Frame(ct, bg=C["sf2"], padx=10, pady=6,
                                         highlightbackground=C["bd"], highlightthickness=1)
        self.place_summary_f.pack(fill="x", pady=(0, 6))
        self.place_summary_lbl = tk.Label(self.place_summary_f,
            text="📍 장소별 사진 수: (사진 분석 후 표시)", fg=C["fg2"], bg=C["sf2"],
            font=("맑은 고딕", 9), anchor="w", wraplength=900, justify="left")
        self.place_summary_lbl.pack(anchor="w")

        # ── 장소명 적용 버튼 ──
        apply_f = tk.Frame(ct, bg=C["bg"]); apply_f.pack(fill="x", pady=(0, 6))
        ttk.Button(apply_f, text="✅ 장소명 변경 적용", style="Ok.TButton",
                   command=self._apply_places).pack(side="left", padx=(0, 8))
        tk.Label(apply_f, text="장소명 수정 후 클릭하면 목록이 갱신됩니다",
                 fg=C["fg3"], bg=C["bg"], font=("맑은 고딕", 8)).pack(side="left")

        lf = tk.Frame(ct, bg=C["sf"], highlightbackground=C["bd"], highlightthickness=1)
        lf.pack(fill="both", expand=True, pady=(0, 8))
        self.ph_canvas = tk.Canvas(lf, bg=C["bg"], highlightthickness=0)
        vsb = tk.Scrollbar(lf, orient="vertical", command=self.ph_canvas.yview)
        self.ph_canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.ph_canvas.pack(side="left", fill="both", expand=True)
        self.ph_list = tk.Frame(self.ph_canvas, bg=C["bg"])
        self.ph_canvas.create_window((0, 0), window=self.ph_list, anchor="nw")
        self.ph_list.bind("<Configure>",
            lambda e: self.ph_canvas.configure(scrollregion=self.ph_canvas.bbox("all")))
        self.ph_canvas.bind_all("<MouseWheel>",
            lambda e: self.ph_canvas.yview_scroll(-1 * (e.delta // 120), "units"))

        ttk.Button(ct, text="→  STEP 3: SEO & 포스팅 구조", style="P.TButton",
                   command=lambda: self._go(3)).pack(fill="x", ipady=4)

    # ═══════════════════════════════════════
    # STEP 3: SEO & 포스팅 구조 + 초안 생성
    # ═══════════════════════════════════════
    def _step3(self):
        t = tk.Frame(self.nb, bg=C["bg"])
        self.nb.add(t, text="  STEP 3  📊  ")
        ct = tk.Frame(t, bg=C["bg"])
        ct.pack(fill="both", expand=True, padx=24, pady=16)

        # ── 포스팅 방식 ──
        cm = self._card(ct, "포스팅 방식", "📋")
        cm.pack(fill="x", pady=(0, 6))
        mr = tk.Frame(cm, bg=C["sf"]); mr.pack(fill="x")
        self.mode_var = tk.StringVar(value="by_day")
        for tx, vl in [("📅 일별", "by_day"), ("🏷️ 장소별", "by_place"),
                        ("🗺️ 코스별", "by_course")]:
            tk.Radiobutton(mr, text=tx, variable=self.mode_var, value=vl,
                           fg=C["fg"], bg=C["sf"], selectcolor=C["sf2"],
                           activebackground=C["sf"], font=("맑은 고딕", 10),
                           command=self._on_mode).pack(side="left", padx=(0, 14))
        # 포스팅 방식별 구조 미리보기
        self.mode_preview_lbl = tk.Text(cm, bg=C["sf2"], fg=C["fg2"],
                                         font=("맑은 고딕", 9), wrap="word",
                                         relief="flat", height=5, state="disabled",
                                         highlightthickness=1,
                                         highlightbackground=C["bd"])
        self.mode_preview_lbl.pack(fill="x", pady=(4, 0))
        self.mode_preview_lbl.tag_configure("header", foreground=C["warn"],
                                             font=("맑은 고딕", 10, "bold"))
        self.mode_preview_lbl.tag_configure("course", foreground="#22d3ee")

        # ── SEO 분석 ──
        cs = self._card(ct, "네이버 상위 블로그 구조 분석", "🔍")
        cs.pack(fill="x", pady=(0, 6))
        self.seo_text = tk.Text(cs, bg=C["bg"], fg=C["fg"], font=("맑은 고딕", 9),
                                wrap="word", relief="flat", height=6, state="disabled",
                                highlightthickness=1, highlightbackground=C["bd"])
        self.seo_text.pack(fill="x")

        # ── 글 구조 선택 ──
        cc = self._card(ct, "글 구조 선택 (체크한 섹션이 순서대로 작성됩니다)", "✏️")
        cc.pack(fill="x", pady=(0, 6))
        self.struct_frame = tk.Frame(cc, bg=C["sf"])
        self.struct_frame.pack(fill="x")

        # ── 초안 생성 ──
        br = tk.Frame(ct, bg=C["bg"]); br.pack(fill="x", pady=(4, 0))
        ttk.Button(br, text="✍️ 이 그룹 초안 생성", style="P.TButton",
                   command=self._do_gen).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(br, text="🚀 전체 일괄 생성", style="Ok.TButton",
                   command=self._do_gen_all).pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.gen_lbl = tk.Label(ct, text="", fg=C["fg2"], bg=C["bg"],
                                font=("맑은 고딕", 10))
        self.gen_lbl.pack(pady=(6, 0))

    # ═══════════════════════════════════════
    # STEP 4: AI 초안 편집 & 확정
    # ═══════════════════════════════════════
    def _step4(self):
        t = tk.Frame(self.nb, bg=C["bg"])
        self.nb.add(t, text="  STEP 4  ✍️  ")
        ct = tk.Frame(t, bg=C["bg"])
        ct.pack(fill="both", expand=True, padx=24, pady=16)

        # ── 상단: 그룹 네비 + 초안 선택 ──
        nv = tk.Frame(ct, bg=C["bg"]); nv.pack(fill="x", pady=(0, 6))
        ttk.Button(nv, text="◀", style="Gh.TButton",
                   command=self._dr_prev).pack(side="left")
        self.draft_nav = tk.Label(nv, text="", fg=C["warn"], bg=C["bg"],
                                  font=("맑은 고딕", 11, "bold"))
        self.draft_nav.pack(side="left", padx=12)
        ttk.Button(nv, text="▶", style="Gh.TButton",
                   command=self._dr_next).pack(side="left")

        # 초안 선택 라디오
        cs = self._card(ct, "AI 초안 선택", "🔹")
        cs.pack(fill="x", pady=(0, 4))
        self.draft_var = tk.IntVar(value=0)
        self.draft_w = []
        dr_row = tk.Frame(cs, bg=C["sf"]); dr_row.pack(fill="x")
        for i in range(3):
            rb = tk.Radiobutton(dr_row, variable=self.draft_var, value=i,
                                fg=C["pri"], bg=C["sf"], selectcolor=C["sf2"],
                                font=("맑은 고딕", 9, "bold"), text=f"초안 {i+1}")
            rb.pack(side="left", padx=(0, 12))
            self.draft_w.append({"rb": rb})
        ttk.Button(dr_row, text="🌐 브라우저", style="Gh.TButton",
                   command=self._dr_browser).pack(side="right")

        # ── 편집 가능 미리보기 (블록 리스트) ──
        edit_lbl = tk.Frame(ct, bg=C["bg"]); edit_lbl.pack(fill="x", pady=(4, 2))
        tk.Label(edit_lbl, text="📝 본문 편집 — 텍스트 직접 수정, ▲▼로 블록 순서 변경",
                 fg=C["fg2"], bg=C["bg"], font=("맑은 고딕", 9)).pack(side="left")

        edit_area = tk.Frame(ct, bg=C["sf"], highlightbackground=C["bd"],
                              highlightthickness=1)
        edit_area.pack(fill="both", expand=True, pady=(0, 4))

        # 블록 리스트 (스크롤)
        self.block_canvas = tk.Canvas(edit_area, bg=C["bg"], highlightthickness=0)
        vsb = tk.Scrollbar(edit_area, orient="vertical", command=self.block_canvas.yview)
        self.block_canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.block_canvas.pack(side="left", fill="both", expand=True)
        self.block_list = tk.Frame(self.block_canvas, bg=C["bg"])
        self.block_canvas.create_window((0, 0), window=self.block_list, anchor="nw")
        self.block_list.bind("<Configure>",
            lambda e: self.block_canvas.configure(scrollregion=self.block_canvas.bbox("all")))
        # 마우스 휠 스크롤 (canvas 영역에서만)
        def _on_mousewheel(e):
            self.block_canvas.yview_scroll(-1 * (e.delta // 120), "units")
        self.block_canvas.bind("<MouseWheel>", _on_mousewheel)
        self.block_canvas.bind("<Enter>",
            lambda e: self.block_canvas.bind_all("<MouseWheel>", _on_mousewheel))
        self.block_canvas.bind("<Leave>",
            lambda e: self.block_canvas.unbind_all("<MouseWheel>"))

        # 블록 조작 버튼
        blk_btns = tk.Frame(ct, bg=C["bg"]); blk_btns.pack(fill="x", pady=(0, 4))
        ttk.Button(blk_btns, text="▲ 위로", style="Gh.TButton",
                   command=self._block_up).pack(side="left", padx=(0, 4))
        ttk.Button(blk_btns, text="▼ 아래로", style="Gh.TButton",
                   command=self._block_down).pack(side="left", padx=(0, 4))
        ttk.Button(blk_btns, text="➕ 텍스트 추가", style="Gh.TButton",
                   command=self._block_add_text).pack(side="left", padx=(0, 4))
        ttk.Button(blk_btns, text="🗑️ 삭제", style="Gh.TButton",
                   command=self._block_delete).pack(side="left", padx=(0, 12))

        # AI 수정
        ai_f = tk.Frame(blk_btns, bg=C["bg"]); ai_f.pack(side="right")
        self.ai_inst = tk.Entry(ai_f, font=("맑은 고딕", 9), bg=C["sf2"], fg=C["fg"],
                                 insertbackground=C["fg"], width=30,
                                 highlightthickness=1, highlightbackground=C["bd"])
        self.ai_inst.pack(side="left", padx=(0, 4), ipady=2)
        self.ai_inst.insert(0, "AI 수정 지시 (예: 더 친근하게)")
        self.ai_inst.bind("<FocusIn>", lambda e: (
            self.ai_inst.delete(0, "end") if "AI 수정" in self.ai_inst.get() else None))
        ttk.Button(ai_f, text="🤖 AI 수정", style="S.TButton",
                   command=self._do_ai_edit).pack(side="left")

        # ── 하단: 확정 버튼 ──
        ba = tk.Frame(ct, bg=C["bg"]); ba.pack(fill="x")
        ttk.Button(ba, text="✅ 최종안 확정 → STEP 5 발행", style="Ok.TButton",
                   command=self._confirm_blocks).pack(fill="x", ipady=4)

        # 블록 편집 상태
        self.edit_blocks = []  # [{"type","content"/"path", widget}, ...]
        self.selected_block_idx = None

    # ═══════════════════════════════════════
    # STEP 5: 검토 & 발행
    # ═══════════════════════════════════════
    def _step5(self):
        t = tk.Frame(self.nb, bg=C["bg"])
        self.nb.add(t, text="  STEP 5  🚀  ")
        ct = tk.Frame(t, bg=C["bg"])
        ct.pack(fill="both", expand=True, padx=24, pady=16)

        nv = tk.Frame(ct, bg=C["bg"]); nv.pack(fill="x", pady=(0, 8))
        ttk.Button(nv, text="◀", style="Gh.TButton",
                   command=self._fn_prev).pack(side="left")
        self.final_nav = tk.Label(nv, text="", fg=C["warn"], bg=C["bg"],
                                  font=("맑은 고딕", 11, "bold"))
        self.final_nav.pack(side="left", padx=12)
        ttk.Button(nv, text="▶", style="Gh.TButton",
                   command=self._fn_next).pack(side="left")
        self.final_st = tk.Label(nv, text="", fg=C["ok"], bg=C["bg"],
                                 font=("맑은 고딕", 10))
        self.final_st.pack(side="right")

        self.final_txt = tk.Text(ct, bg=C["bg"], fg=C["fg"],
                                 font=("맑은 고딕", 10), wrap="word", relief="flat",
                                 highlightthickness=1, highlightbackground=C["bd"])
        self.final_txt.pack(fill="both", expand=True, pady=(0, 8))

        cp = self._card(ct, "발행 설정", "⚡")
        cp.pack(fill="x", pady=(0, 6))
        r1 = tk.Frame(cp, bg=C["sf"]); r1.pack(fill="x", pady=(0, 4))
        self.naver_var = tk.BooleanVar(value=True)
        self.tistory_var = tk.BooleanVar(value=bool(self.cfg.get("tistory", "blog_name")))
        tk.Checkbutton(r1, text="네이버", variable=self.naver_var,
                       fg=C["fg"], bg=C["sf"], selectcolor=C["sf2"],
                       font=("맑은 고딕", 10)).pack(side="left", padx=(0, 12))
        tk.Checkbutton(r1, text="티스토리", variable=self.tistory_var,
                       fg=C["fg"], bg=C["sf"], selectcolor=C["sf2"],
                       font=("맑은 고딕", 10)).pack(side="left")
        tk.Label(r1, text="🤖 Selenium v6 자동발행",
                 fg=C["ok"], bg=C["sf"], font=("맑은 고딕", 9)).pack(side="right")

        # ── 공개 설정 ──
        r3 = tk.Frame(cp, bg=C["sf"]); r3.pack(fill="x", pady=(6, 0))
        tk.Label(r3, text="공개:", fg=C["fg2"], bg=C["sf"],
                 font=("맑은 고딕", 10)).pack(side="left", padx=(0, 6))
        self.pub_visibility = tk.StringVar(value="public")
        for val, txt in [("public", "전체공개"), ("private", "비공개"),
                         ("neighbor", "이웃공개")]:
            tk.Radiobutton(r3, text=txt, variable=self.pub_visibility,
                           value=val, fg=C["fg"], bg=C["sf"],
                           selectcolor=C["sf2"], font=("맑은 고딕", 9)
                           ).pack(side="left", padx=(0, 8))

        pb = tk.Frame(ct, bg=C["bg"]); pb.pack(fill="x", pady=(0, 4))
        ttk.Button(pb, text="🌐 미리보기", style="S.TButton",
                   command=self._fn_preview).pack(side="left", padx=(0, 6))
        ttk.Button(pb, text="💾 저장", style="S.TButton",
                   command=self._fn_save).pack(side="left", padx=(0, 6))
        ttk.Button(pb, text="🚀 발행", style="Ok.TButton",
                   command=self._do_pub).pack(side="left")
        self.pub_log = tk.Text(ct, bg=C["bg"], fg=C["fg2"], font=("Consolas", 9),
                               wrap="word", relief="flat", height=5, state="disabled",
                               highlightthickness=1, highlightbackground=C["bd"])
        self.pub_log.pack(fill="x")

    # ═══════════════════════════════════════
    # STEP 1 로직
    # ═══════════════════════════════════════
    def _sel_folder(self):
        d = filedialog.askdirectory()
        if d:
            self.photo_paths = self.analyzer.scan_folder(d)
            self.photo_lbl.config(text=f"✅ {len(self.photo_paths)}장", fg=C["ok"])

    def _sel_files(self):
        fs = filedialog.askopenfilenames(
            filetypes=[("이미지", "*.jpg *.jpeg *.png *.webp *.heic *.bmp *.tiff")])
        if fs:
            self.photo_paths = list(fs)
            self.photo_lbl.config(text=f"✅ {len(self.photo_paths)}장", fg=C["ok"])

    def _do_analyze(self):
        if not self.photo_paths:
            msg.showwarning("", "사진을 선택하세요"); return
        self._show_loading(f"⏳ {len(self.photo_paths)}장 사진 분석 중...", detail_mode=True)
        self.progress_lbl.config(text="⏳ 분석 중...", fg=C["warn"])

        def task():
            def cb(cur, tot, name):
                self.root.after(0, lambda c=cur, t=tot, n=name: (
                    self.progress_lbl.config(text=f"🔍 {c}/{t} — {Path(n).name}"),
                    self._update_loading(f"⏳ 사진 분석 {c}/{t}"),
                    self._append_loading_log(
                        f"\n📷 [{c}/{t}] {Path(n).name}\n", "title")))

            def result_cb(cur, tot, r):
                """사진 1장 분석 후 결과 상세 표시 (큰 썸네일 + 상세정보)"""
                def show():
                    self._append_loading_log("─" * 50 + "\n", "dim")
                    # 큰 썸네일 삽입
                    fp = r.get("file_path", "")
                    if HAS_PIL and fp and os.path.exists(fp):
                        try:
                            from PIL import ImageOps
                            img = Image.open(fp)
                            try: img = ImageOps.exif_transpose(img)
                            except: pass
                            img.thumbnail((120, 120))
                            ph = ImageTk.PhotoImage(img)
                            if not hasattr(self, '_loading_thumbs'):
                                self._loading_thumbs = []
                            self._loading_thumbs.append(ph)
                            if self._loading_log:
                                self._loading_log.config(state="normal")
                                self._loading_log.image_create("end", image=ph)
                                self._loading_log.insert("end", "\n")
                                self._loading_log.config(state="disabled")
                        except: pass

                    # Google 주소
                    loc = r.get("location_name", "")
                    loc_local = r.get("location_name_local", "")
                    city = r.get("city", "")
                    region = r.get("region", "")
                    addr_parts = [x for x in [region, city] if x]
                    addr_str = ", ".join(addr_parts) if addr_parts else ""
                    if loc:
                        self._append_loading_log(
                            f"  🗺️ Google 주소: {loc}", "gps")
                        if loc_local and loc_local != loc:
                            self._append_loading_log(f" ({loc_local})", "dim")
                        if addr_str:
                            self._append_loading_log(f"  [{addr_str}]", "dim")
                        self._append_loading_log("\n")
                    else:
                        self._append_loading_log("  🗺️ Google 주소: 없음\n", "dim")

                    # GPS 좌표
                    gps = r.get("gps")
                    if gps:
                        self._append_loading_log(
                            f"  📍 GPS: {gps['lat']:.5f}, {gps['lon']:.5f}\n", "gps")
                    else:
                        self._append_loading_log("  📍 GPS: 없음\n", "dim")

                    # Vision 분석
                    v = r.get("vision", {})
                    scene = v.get("scene_type", "")
                    desc = v.get("scene_description", "")
                    food = v.get("food_name", "")
                    mood = v.get("mood", "")
                    if scene or desc:
                        vis_text = f"  🔍 Vision: [{scene}]" if scene else "  🔍 Vision:"
                        if desc:
                            vis_text += f" {desc[:80]}"
                        self._append_loading_log(vis_text + "\n", "vision")
                    if food:
                        self._append_loading_log(f"  🍽️ 음식: {food}\n", "vision")
                    if mood:
                        self._append_loading_log(f"  💭 분위기: {mood}\n", "dim")

                self.root.after(0, show)

            self.photo_results = self.analyzer.analyze_photos(
                self.photo_paths, cb, result_cb=result_cb)

            refs = self._get_ref_urls()
            if refs:
                all_styles = []
                sa = StyleAnalyzer()
                for url in refs:
                    try:
                        s = sa.analyze(url)
                        if s: all_styles.append(s)
                    except Exception:
                        pass
                if all_styles:
                    # 여러 블로그 문체 통합 (마지막이 우선, 특징은 합산)
                    merged = dict(all_styles[0])
                    if len(all_styles) > 1:
                        merged["note"] = f"{len(all_styles)}개 블로그 문체 조합"
                        for extra in all_styles[1:]:
                            for k in ["tone", "sentence_style", "expressions"]:
                                if extra.get(k):
                                    old = merged.get(k, "")
                                    merged[k] = f"{old} / {extra[k]}" if old else extra[k]
                    self.style_analysis = merged
                else:
                    self.style_analysis = None
            else:
                self.style_analysis = None

            kw = self._gv(self.seo_kw, "미입력 시 자동 추출")
            if not kw:
                from collections import Counter
                cities, regions = [], []
                for r in self.photo_results:
                    c = r.get("city", ""); rg = r.get("region", "")
                    if c and len(c) >= 2: cities.append(c)
                    if rg and len(rg) >= 2: regions.append(rg)
                rn = ""
                if cities: rn = Counter(cities).most_common(1)[0][0]
                elif regions: rn = Counter(regions).most_common(1)[0][0]
                else:
                    locs = []
                    for r in self.photo_results:
                        for p in re.split(r'[,、 ]', r.get("location_name", "")):
                            p = p.strip()
                            if len(p) >= 2 and p not in locs: locs.append(p)
                    if locs: rn = Counter(locs).most_common(1)[0][0]
                if rn and self.analyzer._has_foreign_chars(rn):
                    tr = self.analyzer._batch_translate([rn])
                    if tr and tr[0]: rn = tr[0]
                if rn:
                    kw = f"{rn} 여행"
                    self.root.after(0, lambda k=kw: (
                        self.seo_kw.delete(0, "end"),
                        self.seo_kw.config(fg=C["fg"]),
                        self.seo_kw.insert(0, k)))
            if kw:
                if self.analyzer._has_foreign_chars(kw.replace("여행", "").strip()):
                    b = kw.replace("여행", "").strip()
                    tr = self.analyzer._batch_translate([b])
                    if tr and tr[0]:
                        kw = f"{tr[0]} 여행"
                        self.root.after(0, lambda k=kw: (
                            self.seo_kw.delete(0, "end"),
                            self.seo_kw.config(fg=C["fg"]),
                            self.seo_kw.insert(0, k)))
                self.root.after(0, lambda k=kw: self.progress_lbl.config(
                    text=f"📊 SEO: '{k}'"))
                self.naver_analysis = NaverBlogAnalyzer(self.cfg).analyze(kw)

            self.trip_structure = TripStructurer.structure(self.photo_results)
            self.group_states = {}
            self.root.after(0, self._analysis_done)
        threading.Thread(target=task, daemon=True).start()

    def _analysis_done(self):
        self._hide_loading()
        self.progress_lbl.config(text=f"✅ {len(self.photo_results)}장 완료!", fg=C["ok"])
        self.completed.add(1); self._go(2); self._on_mode(); self._render_seo()

    # ═══════════════════════════════════════
    # STEP 2 로직
    # ═══════════════════════════════════════
    def _on_mode(self):
        if not self.trip_structure: return
        self.selected_mode = self.mode_var.get()
        self.selected_groups = self.trip_structure.get(self.selected_mode, [])
        self.current_group_idx = 0; self._init_gs(); self._render_photos()
        # 포스팅 구조 상세 미리보기
        self._update_mode_preview()

    def _update_mode_preview(self):
        """포스팅 방식별 상세 구조 표시"""
        if not hasattr(self, 'mode_preview_lbl'): return
        mode = self.selected_mode
        groups = self.selected_groups
        n = len(groups)
        mode_names = {"by_day": "📅 일별", "by_place": "🏷️ 장소별", "by_course": "🗺️ 코스별"}

        w = self.mode_preview_lbl
        w.config(state="normal")
        w.delete("1.0", "end")

        w.insert("end", f"{mode_names.get(mode, mode)} — 총 {n}개 포스팅\n", "header")
        for i, g in enumerate(groups):
            lbl = g.get("label", f"그룹{i+1}")
            photos = g.get("photos", [])
            photo_cnt = len(photos)
            places = []
            seen = set()
            for p in photos:
                loc = p.get("location_name", "")
                if loc and loc not in seen:
                    places.append(loc); seen.add(loc)
            course = " → ".join(places) if places else ""
            w.insert("end", f"\n📌 {i+1}. {lbl} ({photo_cnt}장)\n")
            if course:
                w.insert("end", f"   🗺️ {course}\n", "course")
            if i >= 9 and n > 10:
                w.insert("end", f"\n... +{n-10}개 더\n")
                break
        w.config(state="disabled")

    def _init_gs(self):
        for i, g in enumerate(self.selected_groups):
            if i not in self.group_states:
                self.group_states[i] = {
                    "checked": [True] * len(g["photos"]),
                    "drafts": [], "selected_draft": 0, "final_post": None}

    def _render_seo(self):
        na = self.naver_analysis
        self.seo_text.config(state="normal")
        self.seo_text.delete("1.0", "end")

        if na and na.get("top_titles"):
            kw = na.get("keyword", "")
            avg = na.get("avg_analysis", {})
            blogs = na.get("blog_structures", [])

            self.seo_text.insert("end", f"🔍 '{kw}' 상위 블로그 구조 분석\n{'━' * 50}\n\n")

            if avg and avg.get("avg_chars"):
                self.seo_text.insert("end",
                    f"📊 종합: {avg['avg_chars']:,}자 | 이미지 {avg['avg_images']}장 | "
                    f"지도 {avg.get('map_ratio', 0) * 100:.0f}% | "
                    f"동영상 {avg.get('video_ratio', 0) * 100:.0f}%\n\n")

            if avg and avg.get("common_sections"):
                self.seo_text.insert("end",
                    f"📋 공통순서: {' → '.join(avg['common_sections'])}\n\n")

            if blogs:
                self.seo_text.insert("end", "📝 개별 블로그\n")
                for i, b in enumerate(blogs, 1):
                    t = b.get("title", "")[:35]
                    ch = b.get("char_count", 0)
                    im = b.get("image_count", 0)
                    mp = "✅" if b.get("has_map") else "—"
                    vd = "✅" if b.get("has_video") else "—"
                    self.seo_text.insert("end",
                        f"  [{i}] {t}…  {ch:,}자 📷{im} 🗺{mp} 🎬{vd}\n")
                    secs = b.get("sections", [])
                    if secs:
                        self.seo_text.insert("end",
                            f"      {' → '.join(secs)}\n")
                self.seo_text.insert("end", "\n")

            kws = ', '.join(na.get('common_keywords', [])[:8])
            self.seo_text.insert("end", f"🔑 {kws}\n")
            tips = na.get('seo_tips', '')
            if tips: self.seo_text.insert("end", f"💡 {tips}\n")

        elif na and na.get("keyword"):
            self.seo_text.insert("end", f"⚠️ '{na['keyword']}' 결과 없음")
        else:
            self.seo_text.insert("end", "사진 분석 후 자동 표시됩니다")
        self.seo_text.config(state="disabled")

        # 구조 체크박스
        for w in self.struct_frame.winfo_children(): w.destroy()
        self.struct_checks = []
        SECS = [
            ("인트로/인사", "인사말+배경", True),
            ("지역 소개", "기본정보", True),
            ("여행 코스/경로", "동선표시", True),
            ("방문 장소 후기", "장소별 후기", True),
            ("구글 지도", "지도삽입", True),
            ("맛집/카페", "음식점", False),
            ("숙소 후기", "숙소정보", False),
            ("교통/이동 팁", "교통수단", False),
            ("비용 정보", "경비", False),
            ("여행 꿀팁", "실용팁", True),
            ("마무리 인사", "감상+댓글", True),
        ]
        rec = set()
        if na and na.get("recommended_structure"):
            for s in na["recommended_structure"]: rec.add(s["type"])
        for typ, desc, dflt in SECS:
            f = tk.Frame(self.struct_frame, bg=C["sf"])
            f.pack(fill="x", padx=2, pady=1)
            on = dflt or typ in rec
            var = tk.BooleanVar(value=on)
            star = " ⭐" if typ in rec else ""
            tk.Checkbutton(f, text=f"{typ}: {desc}{star}", variable=var,
                           fg=C["fg"], bg=C["sf"], selectcolor=C["sf2"],
                           activebackground=C["sf"], font=("맑은 고딕", 9)).pack(side="left")
            self.struct_checks.append((var, {"type": typ, "desc": desc}))

    def _get_struct(self):
        return [s for v, s in self.struct_checks if v.get()]

    # ═══════════════════════════════════════
    # STEP 3 로직
    # ═══════════════════════════════════════
    def _render_photos(self):
        for w in self.ph_list.winfo_children(): w.destroy()
        self.photo_check_vars = []
        self.place_entries = []
        self.route_mode_combos = []  # (from_place, to_place, Combobox)
        if not self.selected_groups: return
        gi = self.current_group_idx
        g = self.selected_groups[gi]
        self.photo_nav.config(
            text=f"📌 {g['label']} ({gi + 1}/{len(self.selected_groups)})")

        if g.get("course_line"):
            tk.Label(self.ph_list, text=f"📍 {g['course_line']}",
                     fg=C["warn"], bg=C["bg"], font=("맑은 고딕", 10),
                     wraplength=900).pack(anchor="w", padx=8, pady=(4, 6))

        st = self.group_states.get(gi, {})
        ck = st.get("checked", [True] * len(g["photos"]))
        user_places = st.get("user_places", {})
        route_modes = st.get("route_modes", {})  # {"장소A→장소B": "transit"}

        TRAVEL_OPTIONS = ["🚌 대중교통", "🚶 도보", "🚗 자가용", "🚲 자전거"]
        MODE_MAP = {"🚌 대중교통": "transit", "🚶 도보": "walking",
                    "🚗 자가용": "driving", "🚲 자전거": "bicycling"}
        MODE_RMAP = {v: k for k, v in MODE_MAP.items()}

        # 장소 순서 파악 (구분선 + 이동수단 표시용)
        prev_loc = None
        place_idx = 0
        for i, r in enumerate(g["photos"]):
            cur_loc = user_places.get(i, r.get("location_name", "")) or "미확인"

            if cur_loc != prev_loc:
                if prev_loc is not None:
                    # ── 이동 경로 카드 (이전→현재) ──
                    route_key = f"{prev_loc}→{cur_loc}"
                    route_f = tk.Frame(self.ph_list, bg="#1a3a5c", padx=10, pady=6,
                                        highlightbackground=C["pri"], highlightthickness=1)
                    route_f.pack(fill="x", padx=6, pady=(8, 2))

                    tk.Label(route_f, text=f"🚶 {prev_loc}  →  {cur_loc}",
                             fg="#93c5fd", bg="#1a3a5c",
                             font=("맑은 고딕", 9, "bold")).pack(side="left")

                    tk.Label(route_f, text="이동:", fg=C["fg3"], bg="#1a3a5c",
                             font=("맑은 고딕", 8)).pack(side="left", padx=(12, 4))
                    cb = ttk.Combobox(route_f, values=TRAVEL_OPTIONS,
                                      width=12, state="readonly",
                                      font=("맑은 고딕", 8))
                    saved_mode = route_modes.get(route_key, "transit")
                    cb.set(MODE_RMAP.get(saved_mode, "🚌 대중교통"))
                    cb.pack(side="left")
                    cb.bind("<<ComboboxSelected>>",
                            lambda ev, rk=route_key, c=cb: self._on_route_mode(rk, c))
                    self.route_mode_combos.append((prev_loc, cur_loc, cb))

                # ── 장소 헤더 ──
                place_hdr = tk.Frame(self.ph_list, bg=C["bg"])
                place_hdr.pack(anchor="w", padx=10, pady=(4, 0))
                tk.Label(place_hdr, text=f"📍 {cur_loc}",
                         fg=C["pri"], bg=C["bg"],
                         font=("맑은 고딕", 10, "bold")).pack(side="left")

                # ── 장소별 메모란 ──
                memo_f = tk.Frame(self.ph_list, bg=C["sf2"], padx=10, pady=4,
                                   highlightbackground=C["bd"], highlightthickness=1)
                memo_f.pack(fill="x", padx=10, pady=(2, 4))
                tk.Label(memo_f, text="📝 메모:", fg=C["fg3"], bg=C["sf2"],
                         font=("맑은 고딕", 8)).pack(side="left")
                memo_entry = tk.Entry(memo_f, font=("맑은 고딕", 9), bg=C["bg"],
                                       fg=C["fg"], insertbackground=C["fg"],
                                       relief="flat", highlightthickness=1,
                                       highlightbackground=C["bd"],
                                       highlightcolor=C["pri"])
                memo_entry.pack(side="left", fill="x", expand=True, padx=(4, 0), ipady=2)
                # 기존 메모 로드
                place_memos = st.get("place_memos", {})
                if cur_loc in place_memos:
                    memo_entry.insert(0, place_memos[cur_loc])
                memo_entry.insert(tk.END, "")  # 커서 끝으로
                memo_entry.bind("<FocusOut>",
                    lambda ev, loc=cur_loc, e=memo_entry: self._on_memo_edit(loc, e))
                memo_entry.bind("<Return>",
                    lambda ev, loc=cur_loc, e=memo_entry: self._on_memo_edit(loc, e))

                prev_loc = cur_loc
                place_idx += 1

            var = tk.BooleanVar(value=ck[i] if i < len(ck) else True)
            self.photo_check_vars.append(var)
            var.trace_add("write", lambda *a, ii=i: self._ph_toggle(ii))

            row = tk.Frame(self.ph_list, bg=C["sf"], padx=6, pady=4,
                           highlightbackground=C["bd"], highlightthickness=1)
            row.pack(fill="x", padx=4, pady=1)

            # 체크박스
            tk.Checkbutton(row, variable=var, bg=C["sf"], selectcolor=C["sf2"],
                           activebackground=C["sf"], fg=C["fg"]).pack(side="left")

            # 썸네일
            if HAS_PIL:
                fp = r.get("file_path", "")
                if fp and os.path.exists(fp):
                    th = self._thumb(fp, 50)
                    if th:
                        lbl = tk.Label(row, image=th, bg=C["sf"])
                        lbl.image = th
                        lbl.pack(side="left", padx=(4, 6))

            # 정보 + 장소명 편집
            inf = tk.Frame(row, bg=C["sf"])
            inf.pack(side="left", fill="x", expand=True)

            v = r.get("vision", {})
            fn = r.get("file_name", "")
            auto_loc = r.get("location_name", "") or "미확인"
            sc = v.get("scene_type", "")
            food = v.get("food_name", "")

            # 첫째 줄: 파일명 + 자동분석 결과
            info_parts = [f"📷 {fn}"]
            if sc: info_parts.append(f"[{sc}]")
            if food: info_parts.append(f"🍽️{food}")
            tk.Label(inf, text="  ".join(info_parts), fg=C["fg2"], bg=C["sf"],
                     font=("맑은 고딕", 8), anchor="w").pack(anchor="w")

            # 둘째 줄: 장소명 편집 (핵심!)
            place_row = tk.Frame(inf, bg=C["sf"])
            place_row.pack(fill="x", pady=(2, 0))
            tk.Label(place_row, text="📍", fg=C["fg3"], bg=C["sf"],
                     font=("맑은 고딕", 9)).pack(side="left")
            pe = tk.Entry(place_row, font=("맑은 고딕", 9), bg=C["sf2"], fg=C["fg"],
                          insertbackground=C["fg"], relief="flat",
                          highlightthickness=1, highlightbackground=C["bd"],
                          highlightcolor=C["pri"], width=30)
            pe.pack(side="left", padx=(4, 0), ipady=2)
            # 사용자 지정값이 있으면 그걸, 없으면 자동분석값
            pe.insert(0, user_places.get(i, auto_loc))
            pe.bind("<FocusOut>", lambda ev, idx=i, entry=pe: self._on_place_edit(idx, entry))
            pe.bind("<Return>", lambda ev, idx=i, entry=pe: self._on_place_edit(idx, entry))
            self.place_entries.append((i, pe))

            # 자동분석 원본 표시 (다르면)
            if user_places.get(i) and user_places[i] != auto_loc:
                tk.Label(place_row, text=f"(원본: {auto_loc})", fg=C["fg3"],
                         bg=C["sf"], font=("맑은 고딕", 7)).pack(side="left", padx=(6, 0))

            # 설명
            desc = v.get("scene_description", "")
            if desc:
                tk.Label(inf, text=f"💬 {desc[:60]}", fg=C["fg3"], bg=C["sf"],
                         font=("맑은 고딕", 7), anchor="w").pack(anchor="w")

        # 장소 요약 업데이트
        self._update_place_summary()

    def _update_place_summary(self):
        """장소별 사진 수 요약 표시"""
        gi = self.current_group_idx
        if gi >= len(self.selected_groups): return
        g = self.selected_groups[gi]
        st = self.group_states.get(gi, {})
        user_places = st.get("user_places", {})
        ck = st.get("checked", [True] * len(g["photos"]))

        from collections import OrderedDict
        place_count = OrderedDict()
        for i, r in enumerate(g["photos"]):
            if not (i < len(ck) and ck[i]): continue
            loc = user_places.get(i, r.get("location_name", "")) or "미확인"
            place_count[loc] = place_count.get(loc, 0) + 1

        if place_count:
            parts = [f"{loc}({cnt}장)" for loc, cnt in place_count.items()]
            total = sum(place_count.values())
            txt = f"📍 {len(place_count)}개 장소, {total}장 선택 — " + " → ".join(parts)
        else:
            txt = "📍 선택된 사진이 없습니다"
        self.place_summary_lbl.config(text=txt)

    def _sort_by_place(self):
        """같은 장소끼리 모아서 정렬 (시간순 유지하면서 장소 그룹핑)"""
        gi = self.current_group_idx
        if gi >= len(self.selected_groups): return
        g = self.selected_groups[gi]
        st = self.group_states.get(gi, {})
        user_places = st.get("user_places", {})

        photos = g["photos"]
        # 각 사진의 실제 장소명 결정
        def get_place(i):
            return user_places.get(i, photos[i].get("location_name", "")) or "미확인"

        # 장소 첫 등장 순서 유지
        place_order = []
        seen = set()
        for i in range(len(photos)):
            p = get_place(i)
            if p not in seen:
                place_order.append(p)
                seen.add(p)

        # 장소별로 사진 모으기 (원래 시간순 유지)
        from collections import OrderedDict
        groups = OrderedDict()
        for pl in place_order:
            groups[pl] = []
        for i, r in enumerate(photos):
            pl = get_place(i)
            groups[pl].append((i, r))

        # 재정렬
        new_photos = []
        new_checked = []
        new_user_places = {}
        old_ck = st.get("checked", [True] * len(photos))
        old_up = dict(user_places)

        for pl in place_order:
            for old_i, r in groups[pl]:
                new_i = len(new_photos)
                new_photos.append(r)
                new_checked.append(old_ck[old_i] if old_i < len(old_ck) else True)
                if old_i in old_up:
                    new_user_places[new_i] = old_up[old_i]

        g["photos"] = new_photos
        st["checked"] = new_checked
        st["user_places"] = new_user_places
        self._render_photos()

    def _on_memo_edit(self, loc, entry):
        """장소별 메모 저장"""
        gi = self.current_group_idx
        st = self.group_states.get(gi, {})
        if "place_memos" not in st:
            st["place_memos"] = {}
        val = entry.get().strip()
        if val:
            st["place_memos"][loc] = val
        elif loc in st["place_memos"]:
            del st["place_memos"][loc]

    def _on_place_edit(self, idx, entry):
        """사용자가 장소명을 수정했을 때 — 저장 + 요약 갱신"""
        gi = self.current_group_idx
        st = self.group_states.get(gi, {})
        if "user_places" not in st:
            st["user_places"] = {}
        new_val = entry.get().strip()
        g = self.selected_groups[gi]
        auto_val = g["photos"][idx].get("location_name", "") if idx < len(g["photos"]) else ""
        if new_val and new_val != auto_val:
            st["user_places"][idx] = new_val
        elif idx in st["user_places"]:
            del st["user_places"][idx]
        self._update_place_summary()

    def _apply_places(self):
        """장소명 편집 내용을 모두 저장하고 목록 새로고침"""
        gi = self.current_group_idx
        st = self.group_states.get(gi, {})
        if "user_places" not in st:
            st["user_places"] = {}
        # 모든 entry에서 현재 값 수집
        for idx, entry in self.place_entries:
            new_val = entry.get().strip()
            g = self.selected_groups[gi]
            auto_val = g["photos"][idx].get("location_name", "") if idx < len(g["photos"]) else ""
            if new_val and new_val != auto_val:
                st["user_places"][idx] = new_val
            elif idx in st.get("user_places", {}) and (not new_val or new_val == auto_val):
                del st["user_places"][idx]
        # 목록 새로고침
        self._render_photos()

    # ── 로딩 오버레이 ──
    def _show_loading(self, msg_text="⏳ 처리 중...", detail_mode=False):
        """로딩 오버레이 표시. detail_mode=True면 상세 스크롤 영역 포함"""
        if hasattr(self, '_loading_overlay') and self._loading_overlay:
            self._update_loading(msg_text)
            return
        self._loading_overlay = tk.Frame(self.root, bg="#0f172a")
        self._loading_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        inner = tk.Frame(self._loading_overlay, bg=C["sf"], padx=30, pady=20,
                         highlightbackground=C["pri"], highlightthickness=2)
        if detail_mode:
            inner.place(relx=0.5, rely=0.5, anchor="center",
                        relwidth=0.85, relheight=0.8)
        else:
            inner.place(relx=0.5, rely=0.5, anchor="center")
        self._loading_label = tk.Label(inner, text=msg_text,
                                        fg=C["warn"], bg=C["sf"],
                                        font=("맑은 고딕", 13, "bold"))
        self._loading_label.pack(pady=(0, 8))
        self._loading_sub = tk.Label(inner, text="잠시 기다려주세요...",
                                      fg=C["fg3"], bg=C["sf"],
                                      font=("맑은 고딕", 9))
        self._loading_sub.pack()
        if detail_mode:
            # 상세 로그 스크롤 영역
            self._loading_log = tk.Text(inner, bg="#0f172a", fg=C["fg2"],
                                         font=("Consolas", 9), wrap="word",
                                         relief="flat", state="disabled",
                                         highlightthickness=1,
                                         highlightbackground=C["bd"])
            self._loading_log.pack(fill="both", expand=True, pady=(8, 0))
            # 색상 태그
            self._loading_log.tag_configure("title", foreground=C["warn"],
                                             font=("맑은 고딕", 10, "bold"))
            self._loading_log.tag_configure("gps", foreground="#22d3ee")
            self._loading_log.tag_configure("vision", foreground="#a78bfa")
            self._loading_log.tag_configure("place", foreground=C["ok"])
            self._loading_log.tag_configure("dim", foreground=C["fg3"])
        else:
            self._loading_log = None
        self.root.update_idletasks()

    def _append_loading_log(self, text, tag=None):
        """로딩 로그에 텍스트 추가"""
        if not hasattr(self, '_loading_log') or not self._loading_log:
            return
        self._loading_log.config(state="normal")
        if tag:
            self._loading_log.insert("end", text, tag)
        else:
            self._loading_log.insert("end", text)
        self._loading_log.see("end")
        self._loading_log.config(state="disabled")
        self.root.update_idletasks()

    def _update_loading(self, msg_text):
        """로딩 메시지 업데이트"""
        if hasattr(self, '_loading_label') and self._loading_label:
            self._loading_label.config(text=msg_text)
            self.root.update_idletasks()

    def _hide_loading(self):
        """로딩 오버레이 제거"""
        if hasattr(self, '_loading_overlay') and self._loading_overlay:
            self._loading_overlay.destroy()
            self._loading_overlay = None
            self._loading_label = None
            self._loading_sub = None
            self._loading_log = None
        if hasattr(self, '_loading_thumbs'):
            self._loading_thumbs = []

    def _on_route_mode(self, route_key, combo):
        """이동수단 콤보박스 변경 시 저장"""
        MODE_MAP = {"🚌 대중교통": "transit", "🚶 도보": "walking",
                    "🚗 자가용": "driving", "🚲 자전거": "bicycling"}
        gi = self.current_group_idx
        st = self.group_states.get(gi, {})
        if "route_modes" not in st:
            st["route_modes"] = {}
        st["route_modes"][route_key] = MODE_MAP.get(combo.get(), "transit")

    def _get_route_modes(self, gi):
        """현재 그룹의 구간별 이동수단 반환: {"장소A→장소B": "transit", ...}"""
        st = self.group_states.get(gi, {})
        return st.get("route_modes", {})

    def _thumb(self, p, sz=50):
        if p in self.thumb_cache: return self.thumb_cache[p]
        try:
            from PIL import ImageOps
            img = Image.open(p)
            try: img = ImageOps.exif_transpose(img)
            except: pass
            img.thumbnail((sz, sz))
            ph = ImageTk.PhotoImage(img)
            self.thumb_cache[p] = ph; return ph
        except: return None

    def _ph_toggle(self, idx):
        gi = self.current_group_idx
        if gi in self.group_states:
            ck = self.group_states[gi]["checked"]
            if idx < len(self.photo_check_vars):
                while len(ck) <= idx: ck.append(True)
                ck[idx] = self.photo_check_vars[idx].get()

    def _ck_all(self):
        for v in self.photo_check_vars: v.set(True)
    def _uck_all(self):
        for v in self.photo_check_vars: v.set(False)
    def _ph_prev(self):
        if self.current_group_idx > 0:
            self.current_group_idx -= 1; self._render_photos()
    def _ph_next(self):
        if self.current_group_idx < len(self.selected_groups) - 1:
            self.current_group_idx += 1; self._render_photos()

    def _get_ck(self, gi):
        """선택된 사진 목록 반환 (사용자 지정 장소명 반영)"""
        g = self.selected_groups[gi]
        st = self.group_states.get(gi, {})
        ck = st.get("checked", [True] * len(g["photos"]))
        user_places = st.get("user_places", {})
        result = []
        for i, p in enumerate(g["photos"]):
            if i < len(ck) and ck[i]:
                photo = dict(p)  # 복사
                if i in user_places:
                    photo["location_name"] = user_places[i]
                result.append(photo)
        return result

    # ═══════════════════════════════════════
    # 초안 생성
    # ═══════════════════════════════════════
    def _do_gen(self):
        if not self.selected_groups:
            msg.showwarning("", "분석을 먼저 완료하세요"); return
        gi = self.current_group_idx
        photos = self._get_ck(gi)
        if not photos:
            msg.showwarning("", "사진을 선택하세요"); return
        self._show_loading(f"⏳ AI 초안 생성 ({len(photos)}장)...", detail_mode=True)
        self.gen_lbl.config(text=f"⏳ AI 초안 생성 ({len(photos)}장)...", fg=C["warn"])
        ss = self._get_struct()
        rm = self._get_route_modes(gi)

        # 선택된 포스팅 방식 표시
        mode_names = {"by_day":"일별","by_place":"장소별","by_course":"코스별"}
        mode_name = mode_names.get(self.mode_var.get(), "일별")
        self.root.after(0, lambda: self._append_loading_log(
            f"📋 포스팅 방식: {mode_name}\n", "place"))

        # 선택된 장소 목록 표시
        places = [p.get("location_name","?") for p in photos if p.get("location_name")]
        course = " → ".join(dict.fromkeys(places))
        self.root.after(0, lambda c=course: self._append_loading_log(
            f"🗺️ 코스: {c}\n\n", "gps"))

        def progress(msg_text):
            self.root.after(0, lambda t=msg_text: (
                self.gen_lbl.config(text=t, fg=C["warn"]),
                self._update_loading(t),
                self._append_loading_log(f"{t}\n", "vision")))

        def task():
            try:
                g = self.selected_groups[gi]
                tmp = dict(g); tmp["photos"] = photos
                pl = [p.get("location_name", "") for p in photos if p.get("location_name")]
                tmp["course_line"] = " → ".join(dict.fromkeys(pl))
                # 장소별 메모 전달
                st = self.group_states.get(gi, {})
                tmp["place_memos"] = st.get("place_memos", {})
                title = self._gv(self.title_input, "예: 후쿠오카 2박3일")
                dr = self.generator.generate_drafts(
                    tmp, g["label"], title,
                    self.naver_analysis, self.style_analysis,
                    selected_structure=ss,
                    route_modes=rm,
                    progress_cb=progress)
                self.group_states[gi]["drafts"] = dr
                self.root.after(0, lambda: (
                    self._append_loading_log(f"\n✅ {len(dr)}개 초안 완료!\n", "place")))
                import time; time.sleep(1)  # 완료 메시지 보여주기
                self.root.after(0, lambda: (self._hide_loading(), self._show_dr(gi)))
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda: (
                    self._hide_loading(),
                    self.gen_lbl.config(text=f"❌ 오류: {err_msg}", fg=C["err"])))
        threading.Thread(target=task, daemon=True).start()

    def _do_gen_all(self):
        if not self.selected_groups:
            msg.showwarning("", "분석을 먼저 완료하세요"); return
        tot = len(self.selected_groups)
        ss = self._get_struct()
        self._show_loading(f"⏳ 전체 {tot}개 그룹 초안 생성...", detail_mode=True)

        mode_names = {"by_day":"일별","by_place":"장소별","by_course":"코스별"}
        mode_name = mode_names.get(self.mode_var.get(), "일별")
        self.root.after(0, lambda: self._append_loading_log(
            f"📋 포스팅 방식: {mode_name} | {tot}개 그룹\n\n", "place"))

        def task():
            try:
                for gi in range(tot):
                    def progress(msg_text, g=gi):
                        self.root.after(0, lambda t=f"[{g+1}/{tot}] {msg_text}": (
                            self.gen_lbl.config(text=t, fg=C["warn"]),
                            self._update_loading(t),
                            self._append_loading_log(f"  {msg_text}\n", "vision")))

                    gph = self._get_ck(gi)
                    g = self.selected_groups[gi]
                    lbl = g.get("label", f"그룹{gi+1}")
                    self.root.after(0, lambda g_=gi, l=lbl, n=len(gph) if gph else 0: (
                        self.gen_lbl.config(text=f"⏳ {g_+1}/{tot}...", fg=C["warn"]),
                        self._update_loading(f"⏳ {g_+1}/{tot} 그룹 생성 중..."),
                        self._append_loading_log(
                            f"\n📌 [{g_+1}/{tot}] {l} ({n}장)\n", "title")))
                    if not gph: continue
                    tmp = dict(g); tmp["photos"] = gph
                    pl = [p.get("location_name", "") for p in gph if p.get("location_name")]
                    course = " → ".join(dict.fromkeys(pl))
                    self.root.after(0, lambda c=course: self._append_loading_log(
                        f"  🗺️ {c}\n", "gps"))
                    tmp["course_line"] = course
                    # 장소별 메모 전달
                    st = self.group_states.get(gi, {})
                    tmp["place_memos"] = st.get("place_memos", {})
                    title = self._gv(self.title_input, "예: 후쿠오카 2박3일")
                    rm = self._get_route_modes(gi)
                    dr = self.generator.generate_drafts(
                        tmp, g["label"], title,
                        self.naver_analysis, self.style_analysis,
                        selected_structure=ss,
                        route_modes=rm,
                        progress_cb=progress)
                    self.group_states[gi]["drafts"] = dr
                self.root.after(0, lambda: (
                    self._append_loading_log(f"\n✅ {tot}개 그룹 초안 완료!\n", "place")))
                import time; time.sleep(1)
                self.root.after(0, lambda: (
                    self._hide_loading(),
                    self.gen_lbl.config(text=f"✅ {tot}개 완료!", fg=C["ok"]),
                    self._show_dr(0)))
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda: (
                    self._hide_loading(),
                    self.gen_lbl.config(text=f"❌ 오류: {err_msg}", fg=C["err"])))
        threading.Thread(target=task, daemon=True).start()

    # ═══════════════════════════════════════
    # STEP 4 로직: 블록 기반 편집
    # ═══════════════════════════════════════
    def _show_dr(self, gi):
        self.gen_lbl.config(text="✅ 초안 완료!", fg=C["ok"])
        self.completed.add(3); self._go(4)
        self.current_group_idx = gi
        g = self.selected_groups[gi]
        self.draft_nav.config(
            text=f"📌 {g['label']} ({gi + 1}/{len(self.selected_groups)})")
        dr = self.group_states[gi].get("drafts", [])
        for i in range(3):
            w = self.draft_w[i]
            if i < len(dr):
                d = dr[i]
                w["rb"].config(text=f"{d.get('style', f'초안{i+1}')} — {d.get('title', '')[:30]}")
            else:
                w["rb"].config(text=f"초안 {i+1} (없음)")
        self.draft_var.set(0)
        self._load_draft_to_blocks()
        if not hasattr(self, '_dr_trace_set'):
            self.draft_var.trace_add("write", lambda *a: self._load_draft_to_blocks())
            self._dr_trace_set = True

    def _load_draft_to_blocks(self):
        """선택된 초안을 블록 리스트로 변환하여 에디터에 표시"""
        gi = self.current_group_idx
        dr = self.group_states.get(gi, {}).get("drafts", [])
        idx = self.draft_var.get()
        if idx >= len(dr):
            return
        d = dr[idx]
        html = d.get("content", "")
        photos = self._get_ck(gi)

        # HTML → blocks (import 안전하게)
        try:
            from posters import html_to_blocks
            blocks = html_to_blocks(html, photos)
        except Exception as e:
            logger.error(f"html_to_blocks 실패: {e}")
            # 폴백: 전체 content를 하나의 텍스트 블록으로
            raw = re.sub(r'<[^>]+>', '', html)
            raw = re.sub(r'\n{3,}', '\n\n', raw)
            blocks = [{"type": "text", "content": raw}]
            # 사진 블록 추가
            for p in photos:
                fp = p.get("file_path", "")
                if fp:
                    blocks.append({"type": "image", "path": fp})

        # 제목 블록 맨 앞에 추가
        title = d.get("title", "")
        if title:
            blocks.insert(0, {"type": "text", "content": f"# {title}"})

        # 태그 블록 맨 뒤에 추가
        tags = d.get("tags", [])
        if tags:
            blocks.append({"type": "text",
                           "content": "🏷️ " + " ".join(f"#{t}" for t in tags)})

        self.edit_blocks = blocks
        self.selected_block_idx = None
        self._render_blocks()

    def _render_blocks(self):
        """블록 리스트를 에디터 UI에 렌더링"""
        # 기존 위젯 모두 제거
        for w in self.block_list.winfo_children():
            w.destroy()

        # 썸네일 이미지 참조 유지 (GC 방지)
        if not hasattr(self, '_block_thumbs'):
            self._block_thumbs = []
        self._block_thumbs.clear()

        for i, b in enumerate(self.edit_blocks):
            btype = b.get("type", "text")
            is_selected = (i == self.selected_block_idx)
            border_color = C["pri"] if is_selected else C["bd"]

            f = tk.Frame(self.block_list, bg=C["sf"], padx=6, pady=4,
                         highlightbackground=border_color,
                         highlightthickness=2 if is_selected else 1)
            f.pack(fill="x", pady=2, padx=4)
            f.bind("<Button-1>", lambda e, idx=i: self._select_block(idx))

            # 좌측 블록번호+타입 표시
            num_lbl = tk.Label(f, text=f"{i+1:02d}", fg=C["fg3"], bg=C["sf"],
                               font=("Consolas", 7))
            num_lbl.pack(side="left", padx=(0, 2))
            num_lbl.bind("<Button-1>", lambda e, idx=i: self._select_block(idx))

            if btype == "text":
                content = b.get("content", "")
                # 높이 자동 계산 (줄 수 + 길이 기반)
                lines = content.count('\n') + 1
                est_wrap = max(1, len(content) // 80)
                h = max(2, min(10, max(lines, est_wrap)))
                txt = tk.Text(f, bg=C["bg"], fg=C["fg"], font=("맑은 고딕", 9),
                              wrap="word", relief="flat", height=h,
                              highlightthickness=1, highlightbackground=C["bd"],
                              insertbackground=C["fg"])
                txt.insert("1.0", content)
                txt.pack(fill="x", expand=True)
                # 선택은 프레임 클릭으로만 (텍스트 내부 클릭은 편집)
                txt.bind("<FocusIn>", lambda e, idx=i: self._select_block_quiet(idx))
                txt.bind("<KeyRelease>",
                         lambda e, idx=i, w=txt: self._on_block_edit(idx, w))
                b["_widget"] = txt

            elif btype == "image":
                path = b.get("path", "")
                fn = Path(path).name if path else "?"
                row = tk.Frame(f, bg=C["sf"]); row.pack(fill="x")
                row.bind("<Button-1>", lambda e, idx=i: self._select_block(idx))
                tk.Label(row, text="🖼️", fg=C["ok"], bg=C["sf"],
                         font=("맑은 고딕", 10)).pack(side="left", padx=(0, 4))
                th = self._thumb(path, 50)
                if th:
                    self._block_thumbs.append(th)  # GC 방지
                    img_lbl = tk.Label(row, image=th, bg=C["sf"])
                    img_lbl.pack(side="left", padx=(0, 6))
                    img_lbl.bind("<Button-1>", lambda e, idx=i: self._select_block(idx))
                tk.Label(row, text=fn, fg=C["fg2"], bg=C["sf"],
                         font=("맑은 고딕", 8)).pack(side="left")
                row2 = tk.Frame(f, bg=C["sf"]); row2.pack(fill="x")

            elif btype == "map_link":
                url = b.get("url", "")
                content = b.get("content", "📍 구글 지도에서 보기")
                rr = tk.Frame(f, bg=C["sf"]); rr.pack(fill="x")
                rr.bind("<Button-1>", lambda e, idx=i: self._select_block(idx))
                tk.Label(rr, text="📍", fg="#3b82f6", bg=C["sf"],
                         font=("맑은 고딕", 10)).pack(side="left", padx=(0, 4))
                tk.Label(rr, text=f"{content}", fg="#3b82f6", bg=C["sf"],
                         font=("맑은 고딕", 9, "underline")).pack(side="left")
                tk.Label(rr, text=f"  ({url[:50]}…)" if len(url) > 50 else f"  ({url})",
                         fg=C["fg3"], bg=C["sf"],
                         font=("Consolas", 7)).pack(side="left", padx=(4, 0))

            elif btype == "separator":
                rr = tk.Frame(f, bg=C["sf"]); rr.pack(fill="x", pady=4)
                rr.bind("<Button-1>", lambda e, idx=i: self._select_block(idx))
                tk.Label(rr, text="─ ─ ─ ─ ─ ─ ─ ─ ─ ─", fg="#d4d4d4", bg=C["sf"],
                         font=("맑은 고딕", 9)).pack()

            elif btype == "styled_label":
                content = b.get("content", "")
                color = b.get("color", "#8B9467")
                rr = tk.Frame(f, bg=C["sf"]); rr.pack(fill="x", pady=2)
                rr.bind("<Button-1>", lambda e, idx=i: self._select_block(idx))
                tk.Label(rr, text=content, fg=color, bg=C["sf"],
                         font=("맑은 고딕", 8)).pack()

            elif btype == "heading":
                content = b.get("content", "")
                rr = tk.Frame(f, bg=C["sf"]); rr.pack(fill="x", pady=4)
                rr.bind("<Button-1>", lambda e, idx=i: self._select_block(idx))
                tk.Label(rr, text=content, fg="#3d3d3d", bg=C["sf"],
                         font=("맑은 고딕", 13, "bold")).pack()

            elif btype == "route":
                content = b.get("content", "")
                rr = tk.Frame(f, bg=C["sf"]); rr.pack(fill="x")
                rr.bind("<Button-1>", lambda e, idx=i: self._select_block(idx))
                tk.Label(rr, text="🗺️", fg=C["warn"], bg=C["sf"],
                         font=("맑은 고딕", 10)).pack(side="left", padx=(0, 4))
                tk.Label(rr, text=content[:80], fg=C["fg2"], bg=C["sf"],
                         font=("맑은 고딕", 8), wraplength=800).pack(side="left")

        # 스크롤 영역 갱신
        self.block_list.update_idletasks()
        self.block_canvas.configure(scrollregion=self.block_canvas.bbox("all"))

    def _select_block(self, idx):
        """블록 선택 (하이라이트 갱신)"""
        # 현재 편집 중인 텍스트 저장
        self._save_all_text_blocks()
        self.selected_block_idx = idx
        self._render_blocks()

    def _select_block_quiet(self, idx):
        """블록 선택 (재렌더 없이 인덱스만 업데이트 — 텍스트 편집 중 사용)"""
        self.selected_block_idx = idx

    def _save_all_text_blocks(self):
        """모든 텍스트 블록의 위젯 내용을 데이터에 저장"""
        for b in self.edit_blocks:
            w = b.get("_widget")
            if w and b.get("type") == "text":
                try:
                    b["content"] = w.get("1.0", "end").strip()
                except:
                    pass

    def _on_block_edit(self, idx, widget):
        """텍스트 블록 실시간 내용 저장"""
        if idx < len(self.edit_blocks):
            self.edit_blocks[idx]["content"] = widget.get("1.0", "end").strip()

    def _block_up(self):
        self._save_all_text_blocks()
        idx = self.selected_block_idx
        if idx is None or idx <= 0: return
        self.edit_blocks[idx], self.edit_blocks[idx-1] = \
            self.edit_blocks[idx-1], self.edit_blocks[idx]
        self.selected_block_idx = idx - 1
        self._render_blocks()

    def _block_down(self):
        self._save_all_text_blocks()
        idx = self.selected_block_idx
        if idx is None or idx >= len(self.edit_blocks) - 1: return
        self.edit_blocks[idx], self.edit_blocks[idx+1] = \
            self.edit_blocks[idx+1], self.edit_blocks[idx]
        self.selected_block_idx = idx + 1
        self._render_blocks()

    def _block_add_text(self):
        """선택 위치 아래에 빈 텍스트 블록 추가"""
        self._save_all_text_blocks()
        idx = self.selected_block_idx
        pos = (idx + 1) if idx is not None else len(self.edit_blocks)
        self.edit_blocks.insert(pos, {"type": "text", "content": ""})
        self.selected_block_idx = pos
        self._render_blocks()

    def _block_delete(self):
        self._save_all_text_blocks()
        idx = self.selected_block_idx
        if idx is None or idx >= len(self.edit_blocks): return
        self.edit_blocks.pop(idx)
        if self.edit_blocks:
            self.selected_block_idx = min(idx, len(self.edit_blocks) - 1)
        else:
            self.selected_block_idx = None
        self._render_blocks()

    def _do_ai_edit(self):
        """AI로 선택된 텍스트 블록 수정"""
        self._save_all_text_blocks()
        inst = self.ai_inst.get().strip()
        if not inst or "AI 수정" in inst:
            msg.showwarning("", "수정 지시를 입력하세요"); return
        idx = self.selected_block_idx
        if idx is None:
            msg.showwarning("", "수정할 블록을 선택하세요"); return
        b = self.edit_blocks[idx]
        if b["type"] != "text":
            msg.showwarning("", "텍스트 블록만 AI 수정 가능합니다"); return

        original = b["content"]
        self._show_loading("⏳ AI 수정 중...", detail_mode=False)

        def task():
            try:
                prompt = (
                    f"아래 텍스트를 다음 지시에 따라 수정해줘. 수정된 텍스트만 출력.\n\n"
                    f"[원문]:\n{original}\n\n"
                    f"[수정 지시]: {inst}\n\n"
                    f"수정된 텍스트만 출력 (설명 없이):"
                )
                r = self.generator.client.chat.completions.create(
                    model=self.generator.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7, max_tokens=2000)
                result = r.choices[0].message.content.strip()
                self.edit_blocks[idx]["content"] = result
                self.root.after(0, lambda: (
                    self._hide_loading(), self._render_blocks()))
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda: (
                    self._hide_loading(),
                    msg.showerror("AI 수정 실패", err_msg)))
        threading.Thread(target=task, daemon=True).start()

    def _confirm_blocks(self):
        """블록 에디터 내용을 최종안으로 확정 → STEP 5"""
        self._save_all_text_blocks()
        gi = self.current_group_idx
        if not self.edit_blocks:
            msg.showwarning("", "블록이 비어있습니다"); return

        # 블록에서 title, tags, content 추출
        title = ""
        tags = []
        content_blocks = []

        for b in self.edit_blocks:
            if b["type"] == "text":
                c = b.get("content", "").strip()
                if not c: continue
                if c.startswith("# ") and not title:
                    title = c[2:].strip()
                    continue
                if c.startswith("🏷️"):
                    import re as _re
                    tags = _re.findall(r'#(\S+)', c)
                    continue
                content_blocks.append(b)
            else:
                content_blocks.append(b)

        # content를 HTML로 재조립
        html_parts = []
        for b in content_blocks:
            if b["type"] == "text":
                c = b["content"]
                if c.startswith("## "):
                    html_parts.append(f'<h3>{c[3:]}</h3>')
                elif c.startswith("# "):
                    html_parts.append(f'<h2>{c[2:]}</h2>')
                else:
                    paragraphs = c.split('\n\n')
                    for p in paragraphs:
                        p = p.strip()
                        if p:
                            html_parts.append(f'<p>{p}</p>')
            elif b["type"] == "image":
                fp = b.get("path", "")
                html_parts.append(
                    f'<figure style="text-align:center;margin:24px 0">'
                    f'<img src="file:///{fp}" alt="" '
                    f'style="max-width:100%;border-radius:12px"/></figure>')
            elif b["type"] == "map_link":
                url = b.get("url", "")
                txt = b.get("content", "📍 구글 지도에서 보기")
                html_parts.append(
                    f'<p style="text-align:center"><a href="{url}" target="_blank" '
                    f'style="color:#8B9467;text-decoration:none;font-size:0.85em">{txt}</a></p>')
            elif b["type"] == "separator":
                html_parts.append(
                    '<p style="text-align:center;color:#d4d4d4;letter-spacing:8px">'
                    '─ ─ ─ ─ ─ ─ ─</p>')
            elif b["type"] == "styled_label":
                color = b.get("color", "#8B9467")
                html_parts.append(
                    f'<p style="text-align:center;font-size:0.8em;color:{color};'
                    f'letter-spacing:3px">{b.get("content", "")}</p>')
            elif b["type"] == "heading":
                place = b.get("place", "")
                html_parts.append(
                    f'<h2 data-place="{place}" style="text-align:center;font-size:1.3em;'
                    f'color:#3d3d3d;font-weight:600">{b.get("content", "")}</h2>')
            elif b["type"] == "route":
                html_parts.append(f'<p>{b.get("content", "")}</p>')

        content = "\n".join(html_parts)

        photos = self._get_ck(gi)
        g = self.selected_groups[gi]

        if not title:
            dr = self.group_states.get(gi, {}).get("drafts", [])
            idx = self.draft_var.get()
            if idx < len(dr):
                title = dr[idx].get("title", "제목 없음")
        if not tags:
            dr = self.group_states.get(gi, {}).get("drafts", [])
            idx = self.draft_var.get()
            if idx < len(dr):
                tags = dr[idx].get("tags", [])

        self.group_states[gi]["final_post"] = {
            "title": title,
            "content": content,
            "tags": tags,
            "meta_description": "",
            "group_label": g["label"],
            "photos": photos,
            "blocks": content_blocks,  # 발행 시 직접 사용
        }
        self.completed.add(4)
        self._show_final(); self._go(5)

    def _dr_browser(self):
        gi = self.current_group_idx
        dr = self.group_states.get(gi, {}).get("drafts", [])
        idx = self.draft_var.get()
        if idx < len(dr):
            path = self.saver.save(dr[idx], f"preview_{dr[idx].get('style', '')}")
            threading.Thread(target=lambda: webbrowser.open(
                f"file:///{os.path.abspath(path)}"), daemon=True).start()

    def _dr_prev(self):
        if self.current_group_idx > 0:
            self.current_group_idx -= 1
            gi = self.current_group_idx
            if self.group_states.get(gi, {}).get("drafts"):
                self._show_dr(gi)

    def _dr_next(self):
        if self.current_group_idx < len(self.selected_groups) - 1:
            self.current_group_idx += 1
            gi = self.current_group_idx
            if self.group_states.get(gi, {}).get("drafts"):
                self._show_dr(gi)

    # ═══════════════════════════════════════
    # STEP 5 로직
    # ═══════════════════════════════════════
    def _show_final(self):
        finals = [(i, s["final_post"]) for i, s in self.group_states.items()
                  if s.get("final_post")]
        if not finals: return
        gi = self.current_group_idx
        post = self.group_states.get(gi, {}).get("final_post")
        if not post:
            gi, post = finals[0]

        self.final_nav.config(
            text=f"📌 {post.get('group_label', '')}  "
                 f"({len(finals)}/{len(self.selected_groups)} 완료)")
        self.final_st.config(text=f"✅ {len(finals)}개 확정")

        self.final_txt.config(state="normal")
        self.final_txt.delete("1.0", "end")
        self.final_txt.insert("end",
            f"📄 {post.get('title', '')}\n{'━' * 50}\n\n")
        raw = re.sub(r'<[^>]+>', '', post.get("content", ""))
        raw = re.sub(r'\n{3,}', '\n\n', raw)
        self.final_txt.insert("end", raw[:3000])
        if len(raw) > 3000:
            self.final_txt.insert("end", "\n\n… (미리보기로 전체 확인)")
        self.final_txt.insert("end",
            f"\n\n{'─' * 50}\n🏷️ {', '.join(post.get('tags', []))}\n")
        self.final_txt.config(state="disabled")

    def _fn_prev(self):
        finals = [i for i, s in self.group_states.items() if s.get("final_post")]
        if not finals: return
        cur = finals.index(self.current_group_idx) if self.current_group_idx in finals else 0
        if cur > 0:
            self.current_group_idx = finals[cur - 1]; self._show_final()

    def _fn_next(self):
        finals = [i for i, s in self.group_states.items() if s.get("final_post")]
        if not finals: return
        cur = finals.index(self.current_group_idx) if self.current_group_idx in finals else 0
        if cur < len(finals) - 1:
            self.current_group_idx = finals[cur + 1]; self._show_final()

    def _fn_preview(self):
        post = self.group_states.get(self.current_group_idx, {}).get("final_post")
        if post:
            path = self.saver.save(post, f"final_{post.get('group_label', '')}")
            threading.Thread(target=lambda: webbrowser.open(
                f"file:///{os.path.abspath(path)}"), daemon=True).start()

    def _fn_save(self):
        finals = [(i, s["final_post"]) for i, s in self.group_states.items()
                  if s.get("final_post")]
        for _, post in finals:
            d = dict(post)
            d["hashtags"] = [f"#{t}" for t in d.get("tags", [])]
            self.saver.save(d, d.get("group_label", ""))
        msg.showinfo("저장", f"✅ {len(finals)}개 저장 완료!")

    def _do_pub(self):
        finals = [(i, s["final_post"]) for i, s in self.group_states.items()
                  if s.get("final_post")]
        if not finals:
            msg.showwarning("", "확정된 글이 없습니다"); return
        method = "selenium"  # v6 Selenium 고정
        visibility = self.pub_visibility.get()
        vis_label = {"public": "전체공개", "private": "비공개",
                     "neighbor": "이웃공개"}.get(visibility, visibility)
        ok = msg.askyesno("🚀 발행 확인",
            f"{len(finals)}개 글을 {vis_label}으로 발행합니다.\n계속 진행할까요?")
        if not ok: return
        self._plog(f"🚀 {len(finals)}개 발행 시작 ({vis_label})\n")
        self._show_loading(f"⏳ {len(finals)}개 발행 중...", detail_mode=True)

        def task():
            import time as _t
            published_urls = []  # 발행된 포스팅 URL 수집

            for idx, (gi, post) in enumerate(finals):
                d = dict(post)
                d["hashtags"] = [f"#{t}" for t in d.get("tags", [])]
                lbl = d.get("group_label", "")
                self.root.after(0, lambda l=lbl, i=idx: (
                    self._plog(f"\n📌 {l}\n"),
                    self._update_loading(f"⏳ {i+1}/{len(finals)} 발행 중..."),
                    self._append_loading_log(f"\n📌 [{i+1}/{len(finals)}] {l}\n", "title")))

                if self.naver_var.get():
                    self.root.after(0, lambda: self._append_loading_log(
                        "  🤖 네이버 Selenium 발행 중...\n", "gps"))
                    r = self.naver_poster.post(d, method=method,
                                               visibility=visibility)
                    m = f"  네이버: {'✅' if r['success'] else '❌ ' + r.get('reason', '')}\n"
                    self.root.after(0, lambda m=m: (
                        self._plog(m), self._append_loading_log(m)))
                    # 발행 URL 수집
                    if r.get("success") and r.get("url"):
                        published_urls.append({"label": lbl, "url": r["url"],
                                               "title": d.get("title", lbl)})
                    _t.sleep(2)

                if self.tistory_var.get():
                    r = self.tistory_poster.post(d, method=method)
                    m = f"  티스토리: {'✅' if r['success'] else '❌ ' + r.get('reason', '')}\n"
                    self.root.after(0, lambda m=m: (
                        self._plog(m), self._append_loading_log(m)))
                    _t.sleep(2)

                self.saver.save(d, f"발행_{lbl}")
                if idx < len(finals) - 1:
                    wait = 30
                    self.root.after(0, lambda w=wait: (
                        self._plog(f"  ⏳ {w}초 대기\n"),
                        self._append_loading_log(f"  ⏳ {w}초 대기...\n", "dim")))
                    _t.sleep(wait)

            # ── 통합본 요약 포스팅 (2개 이상 발행 시) ──
            if len(finals) >= 2 and self.naver_var.get():
                self.root.after(0, lambda: (
                    self._update_loading("⏳ 통합 요약 포스팅 생성 중..."),
                    self._append_loading_log(
                        "\n\n📝 통합 요약 포스팅 생성 중...\n", "title"),
                    self._plog("\n📝 통합 요약 포스팅 생성 중...\n")))
                _t.sleep(2)

                summary_post = self._build_summary_post(finals, published_urls)
                if summary_post:
                    self.root.after(0, lambda: self._append_loading_log(
                        "  🤖 통합본 발행 중...\n", "gps"))
                    r = self.naver_poster.post(summary_post, method=method,
                                               visibility=visibility)
                    m = f"  통합본: {'✅' if r['success'] else '❌ ' + r.get('reason', '')}\n"
                    self.root.after(0, lambda m=m: (
                        self._plog(m), self._append_loading_log(m)))
                    self.saver.save(summary_post, "통합_요약")

            self.root.after(0, lambda: (
                self._hide_loading(),
                self._plog(f"\n✅ 발행 완료!\n")))
        threading.Thread(target=task, daemon=True).start()

    def _build_summary_post(self, finals, published_urls):
        """전체 일정 통합 요약 포스팅 생성"""
        title = self._gv(self.title_input, "예: 후쿠오카 2박3일")
        if not title: title = "여행 일정 총정리"

        # 전체 장소 수집
        all_places = []
        for gi, post in finals:
            lbl = post.get("group_label", "")
            tags = post.get("tags", [])
            all_places.append({"label": lbl, "tags": tags})

        # 요약 HTML 생성
        summary_html = f"<h2>📋 {title} — 전체 일정 총정리</h2>\n"
        summary_html += "<p>이 글은 전체 여행 일정을 한눈에 볼 수 있는 요약 포스팅입니다.</p>\n\n"

        for idx, (gi, post) in enumerate(finals):
            lbl = post.get("group_label", "")
            post_title = post.get("title", lbl)

            summary_html += f"<h3>📌 {idx+1}. {lbl}</h3>\n"

            # 각 포스팅에서 장소명 추출
            photos = self._get_ck(gi) if gi < len(self.selected_groups) else []
            places = [p.get("location_name", "") for p in photos if p.get("location_name")]
            if places:
                course = " → ".join(dict.fromkeys(places))
                summary_html += f"<p>🗺️ 코스: {course}</p>\n"

            # 발행된 포스팅 링크 연결
            url_info = next((u for u in published_urls if u["label"] == lbl), None)
            if url_info and url_info.get("url"):
                summary_html += (
                    f'<p style="margin:8px 0">'
                    f'<a href="{url_info["url"]}" target="_blank" '
                    f'style="color:#3b82f6;font-weight:bold;font-size:1.1em">'
                    f'👉 {post_title} — 상세 후기 보러가기</a></p>\n')
            else:
                summary_html += f"<p>📄 {post_title}</p>\n"

            summary_html += "\n"

        summary_html += "<hr/>\n"
        summary_html += f"<p>총 {len(finals)}개의 포스팅으로 구성된 여행기입니다. "
        summary_html += "각 링크를 클릭하면 상세 후기를 볼 수 있습니다!</p>\n"

        # 태그 통합
        all_tags = set()
        for gi, post in finals:
            all_tags.update(post.get("tags", []))
        all_tags.add("여행총정리")

        return {
            "title": f"📋 {title} 전체 일정 총정리",
            "content": summary_html,
            "tags": list(all_tags)[:10],
            "hashtags": [f"#{t}" for t in list(all_tags)[:10]],
            "group_label": "통합_요약",
        }

    def _plog(self, txt):
        self.pub_log.config(state="normal")
        self.pub_log.insert("end", txt)
        self.pub_log.see("end")
        self.pub_log.config(state="disabled")

    def run(self):
        self.root.mainloop()
        self.naver_poster.close()
        self.tistory_poster.close()


if __name__ == "__main__":
    TravelBlogGUI().run()
