"""Lingo Lens Desktop - Windows clipboard selection translator.

Select Chinese, English, or Japanese text in any Windows app, press Ctrl+C,
and the translation appears at the top-right of the screen.
"""

from __future__ import annotations

import html
import json
import re
import sys
import threading
import tkinter as tk
import ctypes
from ctypes import wintypes
from pathlib import Path
from queue import Empty, Queue
from urllib.parse import urlencode
from urllib.request import Request, urlopen


FALLBACK = {
    "ambitious": "雄心勃勃的；有抱负的",
    "friction": "阻力；让事情变难的额外步骤",
    "threshold": "门槛；开始做某事所需的最低程度",
    "confidence": "信心；自信",
    "estimate": "估计；估算",
    "significant": "显著的；重要的",
    "revenue": "收入；收益",
    "decline": "下降；减少",
}

REVERSE_FALLBACK = {translation: word for word, translation in FALLBACK.items()}
ZH_JA_FALLBACK = {
    "你好": "こんにちは",
    "谢谢": "ありがとう",
    "早上好": "おはようございます",
    "再见": "さようなら",
}
JA_ZH_FALLBACK = {translation: text for text, translation in ZH_JA_FALLBACK.items()}


class LingoLensDesktop:
    POLL_MS = 350
    BROWSER_PROCESSES = {
        "chrome.exe",
        "msedge.exe",
        "firefox.exe",
        "brave.exe",
        "opera.exe",
        "vivaldi.exe",
    }

    def __init__(self, self_test: bool = False) -> None:
        self.self_test = self_test
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        self.instance_mutex = kernel32.CreateMutexW(
            None, False, "Local\\LingoLensDesktopSingleInstance"
        )
        if not self_test and kernel32.GetLastError() == 183:
            raise SystemExit(0)
        self.root = tk.Tk()
        self.root.title("Lingo Lens Desktop")
        self.root.configure(bg="#f6f5f1")
        self.root.resizable(False, False)
        self.root.geometry("385x318+80+100")

        self.enabled = tk.BooleanVar(value=not self_test)
        self.ignore_browsers = tk.BooleanVar(value=True)
        self.chinese_target = tk.StringVar(value="en")
        self.status = tk.StringVar(value="正在监听剪贴板" if not self_test else "正在进行启动自检")
        self.last_clipboard = "" if self_test else self.read_clipboard()
        self.current_text = ""
        self.current_direction = ("en", "zh-CN")
        self.request_number = 0
        self.results: Queue[tuple[int, str, str | None]] = Queue()
        self.hide_timer: str | None = None

        self.build_control_panel()
        self.build_overlay()
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        if self_test:
            self.root.after(500, self.quit)
        else:
            self.root.after(self.POLL_MS, self.poll_clipboard)
            self.root.after(120, self.read_results)

    def build_control_panel(self) -> None:
        shell = tk.Frame(self.root, bg="#f6f5f1", padx=24, pady=22)
        shell.pack(fill="both", expand=True)

        tk.Label(shell, text="Lingo Lens", bg="#f6f5f1", fg="#1f2926", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        tk.Label(shell, text="跨应用划词翻译", bg="#f6f5f1", fg="#df664b", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 14))
        tk.Label(
            shell,
            text="在任何软件中选中中文、英文或日文后按 Ctrl+C，译文会自动显示在屏幕右上角。",
            justify="left",
            wraplength=335,
            bg="#f6f5f1",
            fg="#53605a",
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w")

        controls = tk.Frame(shell, bg="#f6f5f1")
        controls.pack(fill="x", pady=(17, 8))
        tk.Checkbutton(
            controls,
            text="启用自动翻译",
            variable=self.enabled,
            command=self.toggle_enabled,
            bg="#f6f5f1",
            activebackground="#f6f5f1",
            fg="#1f2926",
            selectcolor="#fffefa",
            font=("Microsoft YaHei UI", 10),
        ).pack(side="left")
        tk.Button(
            controls,
            text="翻译当前剪贴板",
            command=self.translate_clipboard_now,
            relief="flat",
            cursor="hand2",
            bg="#1f2926",
            fg="#fffefa",
            activebackground="#30403a",
            activeforeground="#fffefa",
            padx=10,
            pady=5,
            font=("Microsoft YaHei UI", 9),
        ).pack(side="right")
        tk.Checkbutton(
            shell,
            text="浏览器内容交给网页扩展处理",
            variable=self.ignore_browsers,
            bg="#f6f5f1",
            activebackground="#f6f5f1",
            fg="#1f2926",
            selectcolor="#fffefa",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(2, 5))
        target_row = tk.Frame(shell, bg="#f6f5f1")
        target_row.pack(fill="x", pady=(0, 5))
        tk.Label(
            target_row,
            text="中文翻译为：",
            bg="#f6f5f1",
            fg="#53605a",
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left")
        tk.Radiobutton(
            target_row,
            text="英文",
            variable=self.chinese_target,
            value="en",
            bg="#f6f5f1",
            activebackground="#f6f5f1",
            fg="#1f2926",
            selectcolor="#fffefa",
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left", padx=(4, 8))
        tk.Radiobutton(
            target_row,
            text="日文",
            variable=self.chinese_target,
            value="ja",
            bg="#f6f5f1",
            activebackground="#f6f5f1",
            fg="#1f2926",
            selectcolor="#fffefa",
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left")
        tk.Label(shell, textvariable=self.status, bg="#f6f5f1", fg="#76817c", font=("Microsoft YaHei UI", 9)).pack(anchor="w")

    def build_overlay(self) -> None:
        self.overlay = tk.Toplevel(self.root)
        self.overlay.withdraw()
        self.overlay.overrideredirect(True)
        self.overlay.attributes("-topmost", True)
        self.overlay.configure(bg="#dfe2dc")

        card = tk.Frame(self.overlay, bg="#fffefa", padx=16, pady=14)
        card.pack(fill="both", expand=True, padx=1, pady=1)
        header = tk.Frame(card, bg="#fffefa")
        header.pack(fill="x")
        tk.Label(header, text="CURRENT SELECTION", bg="#fffefa", fg="#76817c", font=("Segoe UI", 8, "bold")).pack(side="left")
        tk.Button(
            header,
            text="×",
            command=self.hide_overlay,
            relief="flat",
            cursor="hand2",
            bg="#fffefa",
            fg="#76817c",
            activebackground="#fffefa",
            activeforeground="#1f2926",
            font=("Segoe UI", 15),
            padx=2,
            pady=0,
        ).pack(side="right")
        self.original_label = tk.Label(card, text="", justify="left", wraplength=320, bg="#fffefa", fg="#37423e", font=("Segoe UI", 10))
        self.original_label.pack(anchor="w", fill="x", pady=(8, 10))
        tk.Frame(card, height=1, bg="#ecece7").pack(fill="x")
        self.translation_label = tk.Label(card, text="", justify="left", wraplength=320, bg="#fffefa", fg="#1f2926", font=("Microsoft YaHei UI", 13, "bold"))
        self.translation_label.pack(anchor="w", fill="x", pady=(12, 7))
        footer = tk.Frame(card, bg="#fffefa")
        footer.pack(fill="x")
        self.source_label = tk.Label(footer, text="", bg="#fffefa", fg="#76817c", font=("Microsoft YaHei UI", 8))
        self.source_label.pack(side="left")
        tk.Button(
            footer,
            text="复制译文",
            command=self.copy_translation,
            relief="flat",
            cursor="hand2",
            bg="#df664b",
            fg="#fffefa",
            activebackground="#c7543c",
            activeforeground="#fffefa",
            padx=9,
            pady=4,
            font=("Microsoft YaHei UI", 8),
        ).pack(side="right")

    def read_clipboard(self) -> str:
        try:
            return self.root.clipboard_get().strip()
        except tk.TclError:
            return ""

    @staticmethod
    def detect_language(text: str) -> str | None:
        """Detect Chinese, English, or Japanese from the dominant script."""
        stripped = text.strip()
        if not 1 < len(stripped) <= 500 or LingoLensDesktop.looks_like_path_or_url(stripped):
            return None
        english_letters = len(re.findall(r"[A-Za-z]", stripped))
        han_characters = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", stripped))
        kana_characters = len(re.findall(r"[\u3040-\u30ff\u31f0-\u31ff]", stripped))
        if kana_characters and kana_characters + han_characters >= english_letters:
            return "ja"
        if han_characters and han_characters >= english_letters:
            return "zh-CN"
        if english_letters:
            return "en"
        return None

    def direction_for_text(self, text: str) -> tuple[str, str] | None:
        source = self.detect_language(text)
        if source == "zh-CN":
            return (source, self.chinese_target.get())
        if source in {"en", "ja"}:
            return (source, "zh-CN")
        return None

    @staticmethod
    def direction_label(direction: tuple[str, str]) -> str:
        labels = {"zh-CN": "中", "en": "英", "ja": "日"}
        return f"{labels[direction[0]]} → {labels[direction[1]]}"

    @staticmethod
    def looks_like_path_or_url(text: str) -> bool:
        if re.match(r"^[A-Za-z]:[\\/]", text):
            return True
        if re.match(r"^(?:https?|file|ftp)://", text, re.IGNORECASE):
            return True
        if text.startswith("\\\\"):
            return True
        if not re.search(r"\s", text) and (text.count("/") >= 2 or text.count("\\") >= 2):
            return True
        return False

    @classmethod
    def foreground_is_browser(cls) -> bool:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.GetForegroundWindow.restype = wintypes.HWND
        kernel32.OpenProcess.restype = wintypes.HANDLE
        window = user32.GetForegroundWindow()
        if not window:
            return False
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(process_id))
        process = kernel32.OpenProcess(0x1000, False, process_id.value)
        if not process:
            return False
        try:
            buffer = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(len(buffer))
            if not kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                return False
            return Path(buffer.value).name.lower() in cls.BROWSER_PROCESSES
        finally:
            kernel32.CloseHandle(process)

    def toggle_enabled(self) -> None:
        self.status.set("正在监听剪贴板" if self.enabled.get() else "自动翻译已暂停")
        if not self.enabled.get():
            self.hide_overlay()

    def poll_clipboard(self) -> None:
        text = self.read_clipboard()
        if text != self.last_clipboard:
            self.last_clipboard = text
            direction = self.direction_for_text(text)
            if self.enabled.get() and direction:
                if self.ignore_browsers.get() and self.foreground_is_browser():
                    self.status.set("浏览器内容已交给网页扩展处理")
                else:
                    self.start_translation(text, direction)
        self.root.after(self.POLL_MS, self.poll_clipboard)

    def translate_clipboard_now(self) -> None:
        text = self.read_clipboard()
        direction = self.direction_for_text(text)
        if not direction:
            self.status.set("剪贴板中没有可翻译的中文、英文或日文")
            return
        self.start_translation(text, direction)

    def start_translation(self, text: str, direction: tuple[str, str]) -> None:
        self.request_number += 1
        request_id = self.request_number
        self.current_text = text
        self.current_direction = direction
        target_label = {"zh-CN": "中文", "en": "英文", "ja": "日文"}[direction[1]]
        self.status.set(f"正在翻译最新复制的内容为{target_label}")
        self.show_overlay(text, f"正在生成{target_label}…", "")
        threading.Thread(target=self.translate_worker, args=(request_id, text, direction), daemon=True).start()

    def translate_worker(self, request_id: int, text: str, direction: tuple[str, str]) -> None:
        normalized = text.strip().lower()
        route = self.direction_label(direction)
        if direction == ("en", "zh-CN") and normalized in FALLBACK:
            self.results.put((request_id, FALLBACK[normalized], f"内置词典 · {route}"))
            return
        if direction == ("zh-CN", "en") and text.strip() in REVERSE_FALLBACK:
            self.results.put((request_id, REVERSE_FALLBACK[text.strip()], f"内置词典 · {route}"))
            return
        if direction == ("zh-CN", "ja") and text.strip() in ZH_JA_FALLBACK:
            self.results.put((request_id, ZH_JA_FALLBACK[text.strip()], f"内置词典 · {route}"))
            return
        if direction == ("ja", "zh-CN") and text.strip() in JA_ZH_FALLBACK:
            self.results.put((request_id, JA_ZH_FALLBACK[text.strip()], f"内置词典 · {route}"))
            return
        try:
            if "ja" in direction:
                params = urlencode({
                    "client": "gtx",
                    "sl": direction[0],
                    "tl": direction[1],
                    "dt": "t",
                    "q": text,
                })
                request = Request(
                    f"https://translate.googleapis.com/translate_a/single?{params}",
                    headers={"User-Agent": "LingoLensDesktop/0.2"},
                )
                with urlopen(request, timeout=12) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                translation = "".join(
                    str(segment[0]) for segment in payload[0] if segment and segment[0]
                ).strip()
            else:
                params = urlencode({"q": text, "langpair": f"{direction[0]}|{direction[1]}"})
                request = Request(
                    f"https://api.mymemory.translated.net/get?{params}",
                    headers={"User-Agent": "LingoLensDesktop/0.2"},
                )
                with urlopen(request, timeout=12) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                translation = html.unescape(str(payload.get("responseData", {}).get("translatedText", ""))).strip()
            if not translation:
                raise RuntimeError("没有得到翻译结果")
            self.results.put((request_id, translation, f"在线翻译 · {route}"))
        except Exception:
            self.results.put((request_id, "暂时无法连接翻译服务，请稍后重新复制一次。", ""))

    def read_results(self) -> None:
        try:
            while True:
                request_id, translation, source = self.results.get_nowait()
                if request_id == self.request_number:
                    self.show_overlay(self.current_text, translation, source)
                    self.status.set("已翻译最新复制的内容")
        except Empty:
            pass
        self.root.after(120, self.read_results)

    def show_overlay(self, original: str, translation: str, source: str) -> None:
        self.original_label.configure(text=original)
        self.translation_label.configure(text=translation)
        self.source_label.configure(text=source)
        self.overlay.update_idletasks()
        width = max(335, self.overlay.winfo_reqwidth())
        height = self.overlay.winfo_reqheight()
        x = self.overlay.winfo_screenwidth() - width - 22
        y = 24
        self.overlay.geometry(f"{width}x{height}+{x}+{y}")
        self.overlay.deiconify()
        self.overlay.lift()
        if self.hide_timer:
            self.root.after_cancel(self.hide_timer)
        self.hide_timer = self.root.after(18000, self.hide_overlay)

    def hide_overlay(self) -> None:
        if self.hide_timer:
            self.root.after_cancel(self.hide_timer)
            self.hide_timer = None
        self.overlay.withdraw()

    def copy_translation(self) -> None:
        translation = self.translation_label.cget("text")
        if not translation or translation.startswith("正在生成"):
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(translation)
        self.root.update()
        self.last_clipboard = translation
        self.status.set("译文已复制到剪贴板")

    def quit(self) -> None:
        self.overlay.destroy()
        self.root.destroy()
        if self.instance_mutex:
            ctypes.windll.kernel32.CloseHandle(self.instance_mutex)
            self.instance_mutex = None

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    LingoLensDesktop(self_test="--self-test" in sys.argv).run()
