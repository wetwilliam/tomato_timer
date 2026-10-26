"""小番茄 — 待在螢幕角落的番茄鐘，附「目前專注任務」與簡單待辦清單。

操作：
  單擊番茄    暫停 / 繼續
  雙擊番茄    打開「任務與待辦」面板
  拖曳番茄    移動位置（會記住）
  右鍵番茄    選單：時間設定、位置、提示音、結束…
資料存在 %APPDATA%\\TomatoTimer\\data.json
"""
import ctypes
import datetime
import json
import math
import os
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import simpledialog

try:
    import winsound
except ImportError:  # 非 Windows 時靜音
    winsound = None

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    pass

DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "TomatoTimer")
DATA_FILE = os.path.join(DATA_DIR, "data.json")
DEFAULTS = {
    "focus_min": 25, "break_min": 5, "sound": True, "corner": "br", "pos": None,
    "current_task": "", "todos": [], "stats": {"date": "", "count": 0},
}
PRESETS = ((25, 5), (45, 10), (50, 10))
CORNERS = (("br", "右下角"), ("tr", "右上角"), ("bl", "左下角"), ("tl", "左上角"))

FONT = "Microsoft JhengHei UI"
KEY = "#010203"            # 視窗透明色
TOMATO = "#E5533D"
LEAF = "#4CAF50"
BREAK = "#3DB89A"
PAUSED = "#BFB2AE"
RING_BG = "#E8E0DC"
FACE = "#4A2A24"
CHEEK = "#F48B7B"
PILL_BG = "#2F2B2A"
PILL_FG = "#FFFFFF"
PILL_SUB = "#C9C2BF"
IDLE_ALPHA = 0.6

# 面板配色
BG = "#FFF8F5"
INK = "#3A302D"
SUB = "#9A8F8B"
LINE = "#EADFDB"
DONE = "#B8AEAA"


def load():
    d = json.loads(json.dumps(DEFAULTS))
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            d.update(json.load(f))
    except Exception:
        pass
    return d


def save(d):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = DATA_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        os.replace(tmp, DATA_FILE)
    except Exception:
        pass


def work_area(root):
    """扣掉工作列後的可用區域 (left, top, right, bottom)。"""
    try:
        class RECT(ctypes.Structure):
            _fields_ = [(n, ctypes.c_long) for n in ("l", "t", "r", "b")]
        r = RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)
        return r.l, r.t, r.r, r.b
    except Exception:
        return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


def rrect(c, x0, y0, x1, y1, r, **kw):
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1,
           x1 - r, y1, x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return c.create_polygon(pts, smooth=True, **kw)


def fit(font, text, maxw):
    if font.measure(text) <= maxw:
        return text
    while text and font.measure(text + "…") > maxw:
        text = text[:-1]
    return text + "…"


def fmt(sec):
    sec = int(math.ceil(sec))
    return f"{sec // 60:02d}:{sec % 60:02d}"


class Tomato:
    def __init__(self):
        self.d = load()
        self.root = root = tk.Tk()
        self.k = root.winfo_fpixels("1i") / 96
        self.T = self.Si(64)
        self.GAP = self.Si(6)
        self.PILL_W = self.Si(220)
        self.W, self.H = self.T + self.GAP + self.PILL_W, self.T

        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-transparentcolor", KEY)
        root.attributes("-alpha", IDLE_ALPHA)
        root.configure(bg=KEY)
        self.cv = tk.Canvas(root, width=self.W, height=self.H, bg=KEY, highlightthickness=0)
        self.cv.pack()
        self.f_time = tkfont.Font(family=FONT, size=12, weight="bold")
        self.f_small = tkfont.Font(family=FONT, size=9)

        self.mode, self.paused, self.remaining, self.end = "focus", False, 0, None
        self.hover = False
        self.msg, self.msg_until = None, 0
        self.anim_t0 = None
        self.panel = None
        self.press = None
        self.click_job = None
        self.skip_release = False
        self.ticks = 0
        self.mvars = []

        c = self.cv
        c.bind("<Enter>", lambda e: self.set_hover(True))
        c.bind("<Leave>", lambda e: self.set_hover(False))
        c.bind("<ButtonPress-1>", self.on_press)
        c.bind("<B1-Motion>", self.on_drag)
        c.bind("<ButtonRelease-1>", self.on_release)
        c.bind("<Double-Button-1>", self.on_double)
        c.bind("<Button-3>", self.show_menu)

        self.place_initial()
        self.start_phase("focus")
        self.tick()

    # ---------- 尺寸 ----------
    def S(self, v):
        return v * self.k

    def Si(self, v):
        return int(round(v * self.k))

    # ---------- 位置 ----------
    def place_initial(self):
        l, t, r, b = work_area(self.root)
        pos = self.d.get("pos")
        if pos and l - self.T < pos[0] < r and t - self.T < pos[1] < b:
            self.tx, self.ty = pos
        else:
            m = self.Si(16)
            cor = self.d.get("corner", "br")
            self.tx = r - self.T - m if "r" in cor else l + m
            self.ty = b - self.T - m if "b" in cor else t + m
        self.update_side()
        self.place()

    def update_side(self):
        l, t, r, b = work_area(self.root)
        self.side = "right" if self.tx + self.T / 2 > (l + r) / 2 else "left"

    def place(self):
        wx = self.tx - self.GAP - self.PILL_W if self.side == "right" else self.tx
        self.root.geometry(f"{self.W}x{self.H}+{int(wx)}+{int(self.ty)}")

    def set_corner(self, cor):
        self.d["corner"], self.d["pos"] = cor, None
        save(self.d)
        self.place_initial()
        self.refresh()

    # ---------- 滑鼠 ----------
    def set_hover(self, v):
        self.hover = v
        self.refresh()

    def on_press(self, e):
        self.press = (e.x_root, e.y_root, self.tx, self.ty)
        self.dragging = False

    def on_drag(self, e):
        if not self.press:
            return
        x0, y0, tx, ty = self.press
        if not self.dragging and abs(e.x_root - x0) + abs(e.y_root - y0) > self.Si(4):
            self.dragging = True
        if self.dragging:
            self.tx, self.ty = tx + e.x_root - x0, ty + e.y_root - y0
            self.place()

    def on_release(self, e):
        if self.skip_release:
            self.skip_release = False
            return
        if getattr(self, "dragging", False):
            self.dragging = False
            self.update_side()
            self.place()
            self.d["pos"] = [self.tx, self.ty]
            save(self.d)
            self.refresh()
            return
        if self.click_job:
            self.root.after_cancel(self.click_job)
        self.click_job = self.root.after(260, self.single_click)

    def single_click(self):
        self.click_job = None
        self.toggle_pause()

    def on_double(self, e):
        if self.click_job:
            self.root.after_cancel(self.click_job)
            self.click_job = None
        self.skip_release = True
        self.toggle_panel()

    # ---------- 計時 ----------
    def total(self):
        return 60 * (self.d["focus_min"] if self.mode == "focus" else self.d["break_min"])

    def remaining_now(self):
        if self.paused or self.end is None:
            return self.remaining
        return max(0.0, self.end - time.monotonic())

    def start_phase(self, mode):
        self.mode, self.paused = mode, False
        self.remaining = self.total()
        self.end = time.monotonic() + self.remaining

    def toggle_pause(self):
        if self.paused:
            self.end = time.monotonic() + self.remaining
            self.paused = False
        else:
            self.remaining = self.remaining_now()
            self.paused = True
        self.refresh()

    def restart(self):
        self.start_phase(self.mode)
        self.refresh()

    def skip(self):
        self.phase_done(counted=False)

    def set_durations(self, f, b):
        elapsed = self.total() - self.remaining_now()
        self.d["focus_min"], self.d["break_min"] = f, b
        save(self.d)
        self.remaining = max(1, self.total() - elapsed)
        self.end = time.monotonic() + self.remaining
        self.refresh()

    def custom_durations(self):
        f = simpledialog.askinteger("自訂時間", "專注幾分鐘？", parent=self.root,
                                    initialvalue=self.d["focus_min"], minvalue=1, maxvalue=180)
        if not f:
            return
        b = simpledialog.askinteger("自訂時間", "休息幾分鐘？", parent=self.root,
                                    initialvalue=self.d["break_min"], minvalue=1, maxvalue=60)
        if b:
            self.set_durations(f, b)

    def today_count(self):
        st = self.d["stats"]
        today = datetime.date.today().isoformat()
        if st.get("date") != today:
            st["date"], st["count"] = today, 0
        return st["count"]

    def phase_done(self, counted=True):
        if self.mode == "focus":
            if counted:
                self.today_count()
                self.d["stats"]["count"] += 1
                save(self.d)
            self.start_phase("break")
            self.notify("起來走走吧～喝口水、伸個懶腰", 12)
        else:
            self.start_phase("focus")
            task = self.d["current_task"].strip()
            self.notify(f"回來專注囉：{task}" if task else "回來專注囉！", 8)
        if counted and self.d.get("sound") and winsound:
            try:
                winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
            except Exception:
                pass
        self.anim_t0 = time.monotonic()
        self.animate()
        self.refresh()

    def notify(self, text, secs):
        self.msg, self.msg_until = text, time.monotonic() + secs

    def tick(self):
        if not self.paused and self.remaining_now() <= 0:
            self.phase_done()
        if self.msg and time.monotonic() > self.msg_until:
            self.msg = None
        self.ticks += 1
        if self.ticks % 20 == 0:  # 偶爾重新置頂，避免被其他置頂視窗蓋住
            self.root.attributes("-topmost", True)
        self.refresh()
        self.root.after(500, self.tick)

    def animate(self):
        if self.anim_t0 is None:
            return
        if time.monotonic() - self.anim_t0 > 1.4:
            self.anim_t0 = None
        self.draw()
        if self.anim_t0 is not None:
            self.root.after(30, self.animate)

    def bounce(self):
        if self.anim_t0 is None:
            return 0
        p = min(1.0, (time.monotonic() - self.anim_t0) / 1.4)
        return self.S(7) * abs(math.sin(math.pi * 3 * p)) * (1 - p)

    # ---------- 繪圖 ----------
    def refresh(self):
        show = self.hover or self.msg is not None
        self.root.attributes("-alpha", 1.0 if show else IDLE_ALPHA)
        self.draw()
        if self.panel:
            self.panel.refresh_controls()

    def draw(self):
        c, S = self.cv, self.S
        c.delete("all")
        ox = self.W - self.T if self.side == "right" else 0
        cx = ox + self.T / 2
        cy = self.T / 2 + S(3) - self.bounce()
        R, r = S(26), S(19)

        frac = 1 - self.remaining_now() / self.total()
        c.create_oval(cx - R, cy - R, cx + R, cy + R, outline=RING_BG, width=S(4))
        if frac > 0.003:
            c.create_arc(cx - R, cy - R, cx + R, cy + R, start=90, extent=-359.9 * frac,
                         style="arc", outline=BREAK if self.mode == "break" else TOMATO, width=S(4))

        if self.mode == "break" and not self.paused:
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=BREAK, outline="")
            self.draw_walker(cx, cy)
        else:
            body = PAUSED if self.paused else (TOMATO if self.mode == "focus" else BREAK)
            c.create_oval(cx - r, cy - r, cx + r, cy + r, fill=body, outline="")
            c.create_oval(cx - r * .62, cy - r * .62, cx - r * .25, cy - r * .32, fill="#FFFFFF",
                          outline="", stipple="gray50")
            top = cy - r
            c.create_polygon(cx - S(10), top + S(2), cx - S(4), top - S(3), cx, top + S(1),
                             cx + S(4), top - S(3), cx + S(10), top + S(2), cx, top + S(5),
                             smooth=True, fill=LEAF, outline="")
            c.create_line(cx, top + S(1), cx + S(2), top - S(6), fill=LEAF, width=S(2.2),
                          capstyle="round")
            self.draw_face(cx, cy, sleepy=self.paused)

        if self.hover or self.msg:
            self.draw_pill(cy)

    def draw_face(self, cx, cy, sleepy):
        c, S = self.cv, self.S
        ey, dx = cy + S(2), S(6)
        for sx in (-dx, dx):
            if sleepy:
                c.create_line(cx + sx - S(2.5), ey, cx + sx + S(2.5), ey, fill=FACE,
                              width=S(1.6), capstyle="round")
            else:
                c.create_oval(cx + sx - S(1.8), ey - S(2.2), cx + sx + S(1.8), ey + S(2.2),
                              fill=FACE, outline="")
            c.create_oval(cx + sx * 1.7 - S(2.6), ey + S(2.5), cx + sx * 1.7 + S(2.6),
                          ey + S(5.5), fill=CHEEK, outline="")
        c.create_arc(cx - S(3.5), ey - S(1), cx + S(3.5), ey + S(6), start=200, extent=140,
                     style="arc", outline=FACE, width=S(1.6))

    def draw_walker(self, cx, cy):
        c, S = self.cv, self.S
        w = dict(fill="#FFFFFF", width=S(2.4), capstyle="round", joinstyle="round")
        step = int(time.monotonic()) % 2
        c.create_oval(cx + S(1) - S(3.2), cy - S(12) - S(3.2), cx + S(1) + S(3.2),
                      cy - S(12) + S(3.2), fill="#FFFFFF", outline="")
        c.create_line(cx + S(0.5), cy - S(7), cx - S(1), cy + S(3), **w)
        hip = (cx - S(1), cy + S(3))
        if step:
            c.create_line(cx - S(6), cy - S(1), cx, cy - S(5), cx + S(6), cy - S(1), **w)
            c.create_line(*hip, cx - S(6), cy + S(12), **w)
            c.create_line(*hip, cx + S(3), cy + S(7), cx + S(5), cy + S(12), **w)
        else:
            c.create_line(cx - S(5), cy + S(1), cx, cy - S(5), cx + S(5), cy - S(3), **w)
            c.create_line(*hip, cx - S(3), cy + S(12), **w)
            c.create_line(*hip, cx + S(5), cy + S(11), **w)

    def draw_pill(self, cy):
        c, S = self.cv, self.S
        x0 = 0 if self.side == "right" else self.T + self.GAP
        x1 = x0 + self.PILL_W
        y0, y1 = self.H / 2 - S(23), self.H / 2 + S(23)
        rrect(c, x0, y0, x1, y1, S(14), fill=PILL_BG, outline="")
        pad = S(14)

        status = "已暫停" if self.paused else ("專注中" if self.mode == "focus" else "休息中")
        c.create_text(x0 + pad, y0 + S(14), anchor="w", text=fmt(self.remaining_now()),
                      font=self.f_time, fill=PILL_FG)
        c.create_text(x0 + pad + self.f_time.measure("00:00") + S(8), y0 + S(15), anchor="w",
                      text=status, font=self.f_small, fill=PILL_SUB)
        cnt = f"× {self.today_count()}"
        tw = self.f_small.measure(cnt)
        c.create_text(x1 - pad, y0 + S(15), anchor="e", text=cnt, font=self.f_small, fill=PILL_SUB)
        dx = x1 - pad - tw - S(6)
        c.create_oval(dx - S(4.5), y0 + S(15) - S(4.5), dx + S(4.5), y0 + S(15) + S(4.5),
                      fill=TOMATO, outline="")

        if self.msg:
            line2, col = self.msg, "#FFD9A8"
        elif self.mode == "break":
            line2, col = "起來走走吧～", "#BFF0E1"
        else:
            task = self.d["current_task"].strip()
            line2, col = (f"▶ {task}", PILL_FG) if task else ("雙擊番茄設定專注任務", PILL_SUB)
        c.create_text(x0 + pad, y1 - S(13), anchor="w", font=self.f_small, fill=col,
                      text=fit(self.f_small, line2, self.PILL_W - 2 * pad))

    # ---------- 選單 ----------
    def show_menu(self, e):
        m = tk.Menu(self.root, tearoff=0, font=(FONT, 10))
        m.add_command(label="繼續" if self.paused else "暫停", command=self.toggle_pause)
        m.add_command(label="重新開始這一輪", command=self.restart)
        m.add_command(label="跳到休息" if self.mode == "focus" else "跳到專注", command=self.skip)
        m.add_separator()
        m.add_command(label="任務與待辦…", command=self.toggle_panel)

        dur = tk.StringVar(value=f"{self.d['focus_min']}/{self.d['break_min']}")
        tm = tk.Menu(m, tearoff=0, font=(FONT, 10))
        for f, b in PRESETS:
            tm.add_radiobutton(label=f"專注 {f} / 休息 {b} 分鐘", variable=dur, value=f"{f}/{b}",
                               command=lambda f=f, b=b: self.set_durations(f, b))
        tm.add_separator()
        tm.add_command(label=f"自訂…（目前 {self.d['focus_min']} / {self.d['break_min']}）",
                       command=self.custom_durations)
        m.add_cascade(label="時間設定", menu=tm)

        pm = tk.Menu(m, tearoff=0, font=(FONT, 10))
        for key, name in CORNERS:
            pm.add_command(label=name, command=lambda k=key: self.set_corner(k))
        m.add_cascade(label="移到角落", menu=pm)

        snd = tk.BooleanVar(value=bool(self.d.get("sound")))
        m.add_checkbutton(label="提示音", variable=snd, command=lambda: self.set_sound(snd.get()))
        m.add_separator()
        m.add_command(label="結束小番茄", command=self.quit)
        self.mvars = [dur, snd]
        m.tk_popup(e.x_root, e.y_root)

    def set_sound(self, v):
        self.d["sound"] = v
        save(self.d)

    def quit(self):
        save(self.d)
        self.root.destroy()

    # ---------- 任務 ----------
    def toggle_panel(self):
        if self.panel:
            self.panel.close()
        else:
            self.panel = Panel(self)

    def set_task(self, text):
        self.d["current_task"] = text
        save(self.d)
        self.draw()

    def run(self):
        self.root.mainloop()


class Panel:
    def __init__(self, app):
        self.app = app
        d = app.d
        w = self.win = tk.Toplevel(app.root)
        w.title("小番茄 · 任務與待辦")
        w.attributes("-topmost", True)
        w.attributes("-toolwindow", True)
        w.resizable(False, False)
        w.configure(bg=BG, padx=app.Si(16), pady=app.Si(14))
        w.protocol("WM_DELETE_WINDOW", self.close)
        w.bind("<Escape>", lambda e: self.close())

        tk.Label(w, text="目前專注", font=(FONT, 9), fg=SUB, bg=BG).pack(anchor="w")
        self.task_var = tk.StringVar(value=d["current_task"])
        te = tk.Entry(w, textvariable=self.task_var, font=(FONT, 12, "bold"), relief="flat",
                      bg="white", fg=INK, width=26, highlightthickness=1,
                      highlightcolor=TOMATO, highlightbackground=LINE, insertbackground=INK)
        te.pack(fill="x", ipady=app.Si(5), pady=(app.Si(2), app.Si(12)))
        te.bind("<Return>", lambda e: w.focus_set())
        self.task_var.trace_add("write", lambda *a: self.on_task_typed())

        tk.Label(w, text="待辦清單　（點一下＝設為目前專注，雙擊＝改名）", font=(FONT, 9), fg=SUB,
                 bg=BG).pack(anchor="w")
        self.list_fr = tk.Frame(w, bg=BG)
        self.list_fr.pack(fill="x", pady=(app.Si(4), app.Si(4)))

        add = tk.Frame(w, bg="white", highlightthickness=1, highlightbackground=LINE,
                       highlightcolor=TOMATO)
        add.pack(fill="x", pady=(app.Si(2), app.Si(12)))
        tk.Label(add, text="＋", font=(FONT, 11), fg=TOMATO, bg="white").pack(side="left",
                                                                          padx=(app.Si(6), 0))
        self.add_var = tk.StringVar()
        ae = tk.Entry(add, textvariable=self.add_var, font=(FONT, 10), relief="flat", bg="white",
                      fg=INK, insertbackground=INK)
        ae.pack(side="left", fill="x", expand=True, ipady=app.Si(5), padx=app.Si(4))
        ae.bind("<Return>", self.add_todo)
        self.add_entry = ae

        ctl = tk.Frame(w, bg=BG)
        ctl.pack(fill="x")
        self.btn_pause = self.button(ctl, "", app.toggle_pause, primary=True)
        self.btn_pause.pack(side="left")
        self.button(ctl, "重來", app.restart).pack(side="left", padx=(app.Si(6), 0))
        self.btn_skip = self.button(ctl, "", app.skip)
        self.btn_skip.pack(side="left", padx=(app.Si(6), 0))
        self.button(ctl, "清除已完成", self.clear_done).pack(side="right")

        self.stat = tk.Label(w, font=(FONT, 9), fg=SUB, bg=BG)
        self.stat.pack(anchor="w", pady=(app.Si(10), 0))

        self.render()
        self.refresh_controls()
        self.position()
        (ae if d["current_task"].strip() else te).focus_set()

    def button(self, parent, text, cmd, primary=False):
        bg, fg = (TOMATO, "white") if primary else ("#F3E9E5", INK)
        b = tk.Label(parent, text=text, font=(FONT, 9, "bold" if primary else "normal"), bg=bg,
                     fg=fg, padx=self.app.Si(10), pady=self.app.Si(3), cursor="hand2")
        b.bind("<Button-1>", lambda e: cmd())
        return b

    def position(self):
        a, w = self.app, self.win
        w.update_idletasks()
        pw, ph = w.winfo_reqwidth(), w.winfo_reqheight()
        l, t, r, b = work_area(a.root)
        gap = a.Si(10)
        x = a.tx + a.T - pw if a.side == "right" else a.tx
        y = a.ty - ph - gap - a.Si(30) if a.ty + a.T / 2 > (t + b) / 2 else a.ty + a.T + gap
        x = min(max(l, x), r - pw)
        y = min(max(t, y), b - ph)
        w.geometry(f"+{int(x)}+{int(y)}")

    def on_task_typed(self):
        self.app.set_task(self.task_var.get())
        self.render()

    def set_current(self, text):
        self.task_var.set(text)

    def click_item(self, text):
        # 延遲一下，讓雙擊（改名）不會先觸發「設為目前專注」
        if getattr(self, "click_job", None):
            self.win.after_cancel(self.click_job)
        self.click_job = self.win.after(260, lambda: self.set_current(text))

    def edit_item(self, i, lbl):
        if getattr(self, "click_job", None):
            self.win.after_cancel(self.click_job)
            self.click_job = None
        old = self.todos()[i]["text"]
        var = tk.StringVar(value=old)
        ent = tk.Entry(lbl.master, textvariable=var, font=(FONT, 10), relief="flat", bg="white",
                       fg=INK, highlightthickness=1, highlightcolor=TOMATO,
                       highlightbackground=LINE, insertbackground=INK)
        lbl.pack_forget()
        ent.pack(side="left", fill="x", expand=True, ipady=self.app.Si(2))
        ent.select_range(0, "end")
        ent.focus_set()
        done = [False]

        def commit(e=None, keep=True):
            if done[0]:
                return
            done[0] = True
            new = var.get().strip()
            if keep and new and new != old:
                self.todos()[i]["text"] = new
                save(self.app.d)
                if self.app.d["current_task"].strip() == old:
                    self.task_var.set(new)  # 目前專注跟著改名
            self.render()

        ent.bind("<Return>", commit)
        ent.bind("<FocusOut>", commit)
        ent.bind("<Escape>", lambda e: (commit(keep=False), "break")[1])

    def todos(self):
        return self.app.d["todos"]

    def add_todo(self, e=None):
        text = self.add_var.get().strip()
        if not text:
            return
        self.todos().append({"text": text, "done": False})
        if not self.app.d["current_task"].strip():
            self.task_var.set(text)
        self.add_var.set("")
        save(self.app.d)
        self.render()

    def toggle(self, i, done):
        self.todos()[i]["done"] = done
        save(self.app.d)
        self.render()

    def delete(self, i):
        del self.todos()[i]
        save(self.app.d)
        self.render()

    def clear_done(self):
        self.app.d["todos"] = [t for t in self.todos() if not t["done"]]
        save(self.app.d)
        self.render()

    def render(self):
        a = self.app
        for ch in self.list_fr.winfo_children():
            ch.destroy()
        self.vars = []
        if not self.todos():
            tk.Label(self.list_fr, text="還沒有待辦，從下面新增一個吧～", font=(FONT, 9),
                     fg=DONE, bg=BG).pack(anchor="w", pady=a.Si(4))
        cur = a.d["current_task"].strip()
        for i, t in enumerate(self.todos()):
            row = tk.Frame(self.list_fr, bg=BG)
            row.pack(fill="x")
            var = tk.BooleanVar(value=t["done"])
            self.vars.append(var)
            tk.Checkbutton(row, variable=var, bg=BG, activebackground=BG, bd=0,
                           command=lambda i=i, v=var: self.toggle(i, v.get())).pack(side="left")
            is_cur = t["text"] == cur and not t["done"]
            font = (FONT, 10, "overstrike") if t["done"] else (FONT, 10, "bold" if is_cur else "normal")
            fg = DONE if t["done"] else (TOMATO if is_cur else INK)
            lbl = tk.Label(row, text=("▶ " if is_cur else "") + t["text"], font=font, fg=fg, bg=BG,
                           anchor="w", justify="left", wraplength=a.Si(230), cursor="hand2")
            lbl.pack(side="left", fill="x", expand=True)
            lbl.bind("<Button-1>", lambda e, s=t["text"]: self.click_item(s))
            lbl.bind("<Double-Button-1>", lambda e, i=i, l=lbl: self.edit_item(i, l))
            x = tk.Label(row, text="✕", font=(FONT, 9), fg=LINE, bg=BG, cursor="hand2")
            x.pack(side="right", padx=(a.Si(6), 0))
            x.bind("<Button-1>", lambda e, i=i: self.delete(i))
            x.bind("<Enter>", lambda e, x=x: x.config(fg=TOMATO))
            x.bind("<Leave>", lambda e, x=x: x.config(fg=LINE))
        if self.win.winfo_ismapped():
            self.position()

    def refresh_controls(self):
        a = self.app
        self.btn_pause.config(text="▶ 繼續" if a.paused else "❚❚ 暫停")
        self.btn_skip.config(text="跳到休息" if a.mode == "focus" else "跳到專注")
        n = a.today_count()
        left = sum(1 for t in self.todos() if not t["done"])
        self.stat.config(text=f"今天完成 {n} 顆番茄　·　待辦剩 {left} 項　·　"
                              f"{a.d['focus_min']}/{a.d['break_min']} 分鐘")

    def close(self):
        self.app.panel = None
        self.win.destroy()


if __name__ == "__main__":
    Tomato().run()
