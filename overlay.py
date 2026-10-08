"""Always-on-top, see-through on-screen keymap for learning a layout.

    python overlay.py                                  # the default layout
    python overlay.py --layout layouts/python-programmer-dvorak --opacity 0.6 --scale 1.2
    python overlay.py --interactive                    # start draggable instead of click-through

A control bar sits above the keymap: drag its title to move both, the slider (or the mouse wheel anywhere on the bar)
sets the keymap's opacity, and its buttons toggle click-through, minimize the keymap into the bar, and quit;
right-click it for size. The keymap starts click-through (the mouse ignores it). When it isn't, left-drag moves it,
the mouse wheel changes opacity and right-click opens the same menu. Global hotkeys: Ctrl+Alt+K toggles click-through, Ctrl+Alt+M minimizes/restores,
Ctrl+Alt+Q quits.

Each key lights up as it's typed, with the char it typed brightest. The generated AHK scripts report every key they
type (their hook hides those keys from other programs) plus Caps Lock's QWERTY toggle, and their Ctrl+Alt+O opens
and closes this overlay. Without AHK, the overlay watches the physical keys itself (e.g. with the .klc installed).
Symbols are drawn in color, letters and digits dim, and each key is tinted by its finger. Shifted char on top,
unshifted below.
"""
import argparse
import ctypes
import queue
import threading
import tkinter as tk
from ctypes import wintypes

from export import OVERLAY_CLASS, OVERLAY_KEY, OVERLAY_MODE, OVERLAY_QUIT, load_layout
from model import FINGERS, LAYOUTS, LAYOUTS_DIR, ROW_OFFSET, ROWS

BG = "#010101"  # color keyed out, so the gaps between keys are fully transparent (and click-through)
FINGER_FILL = ["#3b4a6b", "#2f5d62", "#4a5d3a", "#6b5a2f", "#6b5a2f", "#4a5d3a", "#2f5d62", "#3b4a6b"]
SYMBOL_FG, OTHER_FG = "#ffd866", "#9aa0a6"
HIT_FILL, HIT_FG = "#f2f2f2", "#000000"  # a key just typed, and the char it typed
BAR_BG, BAR_FG, BAR_ACTIVE = "#202124", "#e8eaed", "#3c4043"
UNIT = 52
FLASH_MS = 120
SCANCODE = {lab: int(sc[2:], 16) for row in ROWS for lab, sc in row}
LABEL_AT = {sc: lab for lab, sc in SCANCODE.items()}
VK_SHIFT, VK_CTRL, VK_ALT, VK_LWIN, VK_RWIN = 0x10, 0x11, 0x12, 0x5B, 0x5C

user32, kernel32 = ctypes.WinDLL("user32"), ctypes.WinDLL("kernel32")
WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                                   wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


def listen(events: queue.Queue) -> None:
    """Thread: receive the AHK script's posted messages on a hidden window and queue them for the UI."""
    wc = WNDCLASSW(lpfnWndProc=ctypes.cast(user32.DefWindowProcW, WNDPROC), lpszClassName=OVERLAY_CLASS,
                   hInstance=kernel32.GetModuleHandleW(None))
    user32.RegisterClassW(ctypes.byref(wc))
    user32.CreateWindowExW(0, OVERLAY_CLASS, "Keymap overlay", 0, 0, 0, 0, 0, None, None, wc.hInstance, None)
    msg = wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
        if msg.message in (OVERLAY_KEY, OVERLAY_MODE, OVERLAY_QUIT):
            events.put((msg.message, msg.wParam, msg.lParam))
        else:
            user32.DispatchMessageW(ctypes.byref(msg))


def set_click_through(root: tk.Misc, on: bool) -> None:
    """Toggle WS_EX_TRANSPARENT on the (layered) window so the mouse ignores it."""
    GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT = -20, 0x80000, 0x20
    hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE) | WS_EX_LAYERED
    style = style | WS_EX_TRANSPARENT if on else style & ~WS_EX_TRANSPARENT
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)


class Overlay:
    def __init__(self, layout: dict, name: str, scale: float, opacity: float, click_through: bool):
        self.layouts = {False: layout, True: LAYOUTS["qwerty"]}  # by AHK's Caps Lock QWERTY mode
        self.name, self.scale, self.qwerty = name, scale, False
        self.click_through, self.minimized = click_through, False
        self.pos = (80, 80)  # the bar's top-left; the keymap hangs below it
        self.items, self.flashes = {}, {}  # label -> (rect, fill, [(text, fg) unshifted, shifted]); label -> after id

        self.root = tk.Tk()  # the keymap
        self.root.title("Keymap overlay")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True, "-alpha", opacity, "-transparentcolor", BG)
        self.root.configure(bg=BG)
        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0)
        self.canvas.pack()

        self.menu = tk.Menu(self.root, tearoff=False)
        self.menu.add_command(label="Bigger", command=lambda: self.resize(1.15))
        self.menu.add_command(label="Smaller", command=lambda: self.resize(1 / 1.15))
        self.menu.add_command(label="Click-through  (Ctrl+Alt+K)", command=self.toggle_click_through)
        self.menu.add_command(label="Minimize  (Ctrl+Alt+M)", command=self.toggle_minimized)
        self.menu.add_separator()
        self.menu.add_command(label="Quit  (Ctrl+Alt+Q)", command=self.root.destroy)
        for seq, fn in (("<ButtonPress-1>", self.grab), ("<B1-Motion>", self.drag), ("<MouseWheel>", self.wheel),
                        ("<Button-3>", self.popup), ("<Escape>", lambda e: self.root.destroy())):
            self.root.bind(seq, fn)

        self.make_bar(opacity)
        self.draw()
        self.place()
        self.root.update_idletasks()
        set_click_through(self.root, click_through)

        self.events = queue.Queue()
        threading.Thread(target=listen, args=(self.events,), daemon=True).start()
        self.vks = {lab: user32.MapVirtualKeyW(sc, 1) for lab, sc in SCANCODE.items()}  # MAPVK_VSC_TO_VK
        self.held, self.hotkey_held = set(), None
        self.hotkeys = {0x4B: self.toggle_click_through, 0x4D: self.toggle_minimized}  # Ctrl+Alt+K / M
        self.poll()

    # --- control bar ---------------------------------------------------------------
    def make_bar(self, opacity: float) -> None:
        self.bar = tk.Toplevel(self.root, bg=BAR_BG)
        self.bar.overrideredirect(True)
        self.bar.attributes("-topmost", True, "-alpha", 0.9)
        font = ("Segoe UI", 9)
        self.title = tk.Label(self.bar, text="≡  " + self.name, bg=BAR_BG, fg=BAR_FG, font=font, cursor="fleur",
                              padx=6)
        self.alpha = tk.IntVar(value=round(opacity * 100))
        slider = tk.Scale(self.bar, from_=10, to=100, orient="horizontal", variable=self.alpha, showvalue=False,
                          command=lambda v: self.root.attributes("-alpha", int(v) / 100), length=90, width=10,
                          sliderlength=14, bg=BAR_BG, troughcolor="#5f6368", highlightthickness=0, bd=0)
        button = dict(bg=BAR_BG, fg=BAR_FG, activebackground=BAR_ACTIVE, activeforeground=BAR_FG, relief="flat",
                      bd=0, font=font, padx=6)
        self.through_button = tk.Button(self.bar, command=self.toggle_click_through, **button)
        self.min_button = tk.Button(self.bar, text="–", width=2, command=self.toggle_minimized, **button)
        close = tk.Button(self.bar, text="×", width=2, command=self.root.destroy, **button)
        for w in (self.title, tk.Label(self.bar, text="opacity", bg=BAR_BG, fg=OTHER_FG, font=font), slider,
                  self.through_button, self.min_button, close):
            w.pack(side="left", padx=(0, 2))
        # A toplevel's bindings fire for every widget in it, so only the title drags; the wheel works anywhere on
        # the bar, which is never click-through.
        self.title.bind("<ButtonPress-1>", self.grab)
        self.title.bind("<B1-Motion>", self.drag)
        self.bar.bind("<Button-3>", self.popup)
        self.bar.bind("<MouseWheel>", self.wheel)
        self.update_bar()
        self.bar.update_idletasks()  # so its height is known before placing the keymap under it

    def update_bar(self) -> None:
        self.title.configure(text="≡  " + ("QWERTY" if self.qwerty else self.name))
        self.through_button.configure(text="click-through " + ("on" if self.click_through else "off"))
        self.min_button.configure(text="□" if self.minimized else "–")

    def place(self) -> None:
        x, y = self.pos
        self.bar.geometry(f"+{x}+{y}")
        self.root.geometry(f"+{x}+{y + self.bar.winfo_reqheight() + 2}")

    def toggle_click_through(self) -> None:
        self.click_through = not self.click_through
        set_click_through(self.root, self.click_through)
        self.root.attributes("-topmost", True)
        self.update_bar()

    def toggle_minimized(self) -> None:
        self.minimized = not self.minimized
        if self.minimized:
            self.root.withdraw()
        else:
            self.root.deiconify()
            self.place()
            set_click_through(self.root, self.click_through)
            self.root.attributes("-topmost", True)
        self.update_bar()

    # --- keymap --------------------------------------------------------------------
    def draw(self) -> None:
        u, c = UNIT * self.scale, self.canvas
        c.delete("all")
        for job in self.flashes.values():
            self.root.after_cancel(job)
        self.items.clear()
        self.flashes.clear()
        pad = 2 * self.scale
        width = (max(len(r) + off for r, off in zip(ROWS, ROW_OFFSET))) * u
        c.configure(width=width, height=len(ROWS) * u)
        layout = self.layouts[self.qwerty]
        for r, row in enumerate(ROWS):
            for col, (label, _) in enumerate(row):
                x, y = (col + ROW_OFFSET[r]) * u, r * u
                fill = FINGER_FILL[FINGERS[r][col]]
                rect = c.create_rectangle(x + pad, y + pad, x + u - pad, y + u - pad, fill=fill, outline="#1a1a1a")
                texts = []
                for ch, dx, dy, size in zip(layout[label], (0.5, 0.3), (0.68, 0.3), (17, 13)):
                    sym = not ch.isalnum()
                    fg = SYMBOL_FG if sym else OTHER_FG
                    texts.append((c.create_text(x + dx * u, y + dy * u, text=ch, fill=fg,
                                                font=("Consolas", int(size * self.scale), "bold" if sym else "normal")),
                                  fg))
                self.items[label] = (rect, fill, texts)

    def flash(self, label: str, shifted: bool) -> None:
        """Light up a key just typed, with the char it typed in black."""
        rect, _, texts = self.items[label]
        self.canvas.itemconfigure(rect, fill=HIT_FILL)
        for i, (text, _) in enumerate(texts):
            self.canvas.itemconfigure(text, fill=HIT_FG if i == shifted else OTHER_FG)
        if label in self.flashes:
            self.root.after_cancel(self.flashes[label])
        self.flashes[label] = self.root.after(FLASH_MS, self.unflash, label)

    def unflash(self, label: str) -> None:
        rect, fill, texts = self.items[label]
        self.canvas.itemconfigure(rect, fill=fill)
        for text, fg in texts:
            self.canvas.itemconfigure(text, fill=fg)
        self.flashes.pop(label, None)

    def set_qwerty(self, on: bool) -> None:
        if on != self.qwerty:
            self.qwerty = on
            self.draw()
            self.update_bar()

    def resize(self, factor: float) -> None:
        self.scale = min(3.0, max(0.5, self.scale * factor))
        self.draw()

    # --- input ---------------------------------------------------------------------
    def poll(self) -> None:
        """Every 20 ms: global hotkeys, the AHK script's messages, and physical keys AHK isn't hiding."""
        down = lambda vk: bool(user32.GetAsyncKeyState(vk) & 0x8000)
        ctrl_alt = down(VK_CTRL) and down(VK_ALT)
        if ctrl_alt and down(0x51):  # Ctrl+Alt+Q
            self.root.destroy()
            return
        hotkey = next((vk for vk in self.hotkeys if ctrl_alt and down(vk)), None)
        if hotkey and hotkey != self.hotkey_held:
            self.hotkeys[hotkey]()
        self.hotkey_held = hotkey

        while not self.events.empty():
            msg, wparam, lparam = self.events.get_nowait()
            if msg == OVERLAY_KEY and wparam in LABEL_AT:
                self.flash(LABEL_AT[wparam], bool(lparam))
            elif msg == OVERLAY_MODE:
                self.set_qwerty(bool(wparam))
            elif msg == OVERLAY_QUIT:
                self.root.destroy()
                return

        held = {lab for lab, vk in self.vks.items() if down(vk)}
        if not any(map(down, (VK_CTRL, VK_ALT, VK_LWIN, VK_RWIN))):  # shortcuts aren't typing
            for label in held - self.held:
                self.flash(label, down(VK_SHIFT))
        self.held = held
        self.root.after(20, self.poll)

    def grab(self, e: tk.Event) -> None:
        self.offset = (e.x_root - self.pos[0], e.y_root - self.pos[1])

    def drag(self, e: tk.Event) -> None:
        self.pos = (e.x_root - self.offset[0], e.y_root - self.offset[1])
        self.place()

    def wheel(self, e: tk.Event) -> None:
        self.alpha.set(min(100, max(10, self.alpha.get() + (5 if e.delta > 0 else -5))))
        self.root.attributes("-alpha", self.alpha.get() / 100)

    def popup(self, e: tk.Event) -> None:
        self.menu.tk_popup(e.x_root, e.y_root)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--layout", default=str(LAYOUTS_DIR / "python-programmer-dvorak"),
                    help="a layout folder (or its layout.json) or a built-in layout name")
    ap.add_argument("--opacity", type=float, default=0.7)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--interactive", action="store_true",
                    help="start draggable instead of click-through (Ctrl+Alt+K switches)")
    args = ap.parse_args()
    layout, name, _ = load_layout(args.layout)
    if old := user32.FindWindowW(OVERLAY_CLASS, None):  # replace a running overlay
        user32.PostMessageW(old, OVERLAY_QUIT, 0, 0)
    try:
        Overlay(layout, name, args.scale, args.opacity, not args.interactive).root.mainloop()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
