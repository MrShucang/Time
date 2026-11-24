# -*- coding: utf-8 -*-
"""
定时关机 —— 到点自动关机 / 重启 / 注销 / 睡眠

运行方式：双击「启动定时关机.bat」，或执行 pythonw 定时关机.py
"""

import ctypes
import ctypes.wintypes as wintypes
import json
import math
import os
import subprocess
import sys
import threading
import tkinter as tk
import winreg
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from tkinter import messagebox, ttk

# ---------------------------------------------------------------- 常量

FONT = ("Microsoft YaHei UI", 10)
FONT_BOLD = ("Microsoft YaHei UI", 10, "bold")
FONT_BIG = ("Microsoft YaHei UI", 20, "bold")
FONT_TITLE = ("Microsoft YaHei UI", 15, "bold")

ACTION_SHUTDOWN = "关机"
ACTION_RESTART = "重启"
ACTION_LOGOFF = "注销"
ACTION_SLEEP = "睡眠"
ACTIONS = (ACTION_SHUTDOWN, ACTION_RESTART, ACTION_LOGOFF, ACTION_SLEEP)

NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW，避免执行命令时闪黑框
SHUTDOWN_WARNING_SECONDS = 5 * 60
WARNING_INNER_RADIUS = 10
WARNING_INNER_PADDING = 18
WARNING_CORNER_RADIUS = WARNING_INNER_RADIUS + WARNING_INNER_PADDING
WARNING_BUTTON_RADIUS = WARNING_INNER_RADIUS

STARTUP_REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_VALUE_NAME = "ScheduledShutdownTool"

APPDATA_DIR = Path(os.environ.get("APPDATA") or Path.home())
SETTINGS_FILE = APPDATA_DIR / "ScheduledShutdown" / "settings.json"


# ---------------------------------------------------------------- 执行动作

def run_action(action, force):
    """真正执行系统命令。返回 (是否成功, 说明)。"""
    if action == ACTION_SHUTDOWN:
        cmd = ["shutdown", "/s", "/t", "15"] + (["/f"] if force else [])
    elif action == ACTION_RESTART:
        cmd = ["shutdown", "/r", "/t", "15"] + (["/f"] if force else [])
    elif action == ACTION_LOGOFF:
        cmd = ["shutdown", "/l"]
    elif action == ACTION_SLEEP:
        cmd = ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"]
    else:
        return False, "未知动作"

    try:
        subprocess.run(cmd, creationflags=NO_WINDOW, check=False)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


# ---------------------------------------------------------------- 开机自启

def startup_command():
    """返回写入当前用户启动项的命令。"""
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'

    python_exe = Path(sys.executable).resolve()
    pythonw_exe = python_exe.with_name("pythonw.exe")
    if python_exe.name.lower() == "python.exe" and pythonw_exe.exists():
        python_exe = pythonw_exe
    script_path = Path(__file__).resolve()
    return f'"{python_exe}" "{script_path}"'


def is_startup_enabled():
    """仅当本程序的启动项存在且指向当前程序时返回 True。"""
    try:
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, STARTUP_REGISTRY_KEY, 0,
                winreg.KEY_QUERY_VALUE) as key:
            command, _ = winreg.QueryValueEx(key, STARTUP_VALUE_NAME)
    except OSError:
        return False
    if not isinstance(command, str):
        return False
    return os.path.normcase(command.strip()) == os.path.normcase(
        startup_command().strip())


def set_startup_enabled(enabled):
    """添加或移除当前用户的开机启动项。"""
    if enabled:
        with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, STARTUP_REGISTRY_KEY, 0,
                winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(
                key, STARTUP_VALUE_NAME, 0, winreg.REG_SZ, startup_command())
        return

    try:
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, STARTUP_REGISTRY_KEY, 0,
                winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, STARTUP_VALUE_NAME)
            except FileNotFoundError:
                pass
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------- 界面设置

def _saved_number(value, minimum, maximum):
    """把配置中的数字规范成两位字符串；非法时返回 None。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if not minimum <= number <= maximum:
        return None
    return f"{number:02d}"


def load_last_schedule():
    """读取上次使用的定时方式和时间；配置不存在或损坏时返回 None。"""
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        schedule = data["last_schedule"]
        mode = schedule["mode"]
        hour = _saved_number(schedule["hour"], 0, 23)
        minute = _saved_number(schedule["minute"], 0, 59)
        countdown_hour = _saved_number(schedule["countdown_hour"], 0, 99)
        countdown_minute = _saved_number(schedule["countdown_minute"], 0, 59)
        action = schedule.get("action", ACTION_SHUTDOWN)
        force = schedule.get("force", True)
        cycle_enabled = schedule.get("cycle_enabled") is True
        cycle_pending = schedule.get("cycle_pending") is True
    except (OSError, KeyError, TypeError, ValueError):
        return None
    if (mode not in ("time", "countdown") or hour is None or minute is None
            or countdown_hour is None or countdown_minute is None):
        return None
    if action not in ACTIONS:
        action = ACTION_SHUTDOWN
    if not isinstance(force, bool):
        force = True
    cycle_enabled = cycle_enabled and mode == "time"
    cycle_pending = cycle_pending and cycle_enabled
    return {
        "mode": mode,
        "hour": hour,
        "minute": minute,
        "countdown_hour": countdown_hour,
        "countdown_minute": countdown_minute,
        "action": action,
        "force": force,
        "cycle_enabled": cycle_enabled,
        "cycle_pending": cycle_pending,
    }


def save_last_schedule(schedule):
    """原子写入上次定时设置，成功返回 True。"""
    temp_file = SETTINGS_FILE.with_suffix(".tmp")
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp_file.write_text(
            json.dumps(
                {"last_schedule": schedule}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        temp_file.replace(SETTINGS_FILE)
        return True
    except OSError:
        return False


def resource_path(filename):
    """返回源码运行或 PyInstaller 打包后的资源路径。"""
    base_dir = Path(getattr(
        sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_dir / filename


# ---------------------------------------------------------------- 系统托盘

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32
gdi32 = ctypes.windll.gdi32

WM_APP = 0x8000
WM_NULL = 0x0000
WM_CONTEXTMENU = 0x007B
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205

NIM_ADD = 0
NIM_MODIFY = 1
NIM_DELETE = 2

NIF_MESSAGE = 0x1
NIF_ICON = 0x2
NIF_TIP = 0x4
NIF_INFO = 0x10
NIIF_INFO = 0x1

MF_STRING = 0x0
MF_SEPARATOR = 0x800
TPM_RIGHTBUTTON = 0x2
TPM_RETURNCMD = 0x100
PM_REMOVE = 0x1

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("uFlags", wintypes.UINT),
        ("uCallbackMessage", wintypes.UINT),
        ("hIcon", wintypes.HICON),
        ("szTip", wintypes.WCHAR * 128),
        ("dwState", wintypes.DWORD),
        ("dwStateMask", wintypes.DWORD),
        ("szInfo", wintypes.WCHAR * 256),
        ("uVersion", wintypes.UINT),
        ("szInfoTitle", wintypes.WCHAR * 64),
        ("dwInfoFlags", wintypes.DWORD),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", wintypes.HICON),
    ]


# 显式声明返回值为指针类型，否则 64 位句柄会被截断成 int
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.LoadIconW.restype = wintypes.HICON
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.PeekMessageW.restype = wintypes.BOOL
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.PeekMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), wintypes.HWND,
    wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.DefWindowProcW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.AppendMenuW.argtypes = [
    wintypes.HMENU, wintypes.UINT, wintypes.UINT, wintypes.LPCWSTR]
user32.TrackPopupMenu.argtypes = [
    wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, wintypes.HWND, ctypes.c_void_p]
user32.TrackPopupMenu.restype = wintypes.UINT
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.SystemParametersInfoW.argtypes = [
    wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
user32.SystemParametersInfoW.restype = wintypes.BOOL
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.SetWindowRgn.argtypes = [
    wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
user32.SetWindowRgn.restype = ctypes.c_int
gdi32.CreatePolygonRgn.argtypes = [
    ctypes.POINTER(wintypes.POINT), ctypes.c_int, ctypes.c_int]
gdi32.CreatePolygonRgn.restype = ctypes.c_void_p
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteObject.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.DestroyMenu.argtypes = [wintypes.HMENU]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                wintypes.WPARAM, wintypes.LPARAM]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
shell32.Shell_NotifyIconW.argtypes = [
    wintypes.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
shell32.Shell_NotifyIconW.restype = wintypes.BOOL
shell32.ExtractIconW.restype = wintypes.HICON
shell32.ExtractIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT]


class TrayIcon:
    """系统托盘图标（纯 ctypes 调用 Shell_NotifyIcon，无第三方依赖）。"""

    _WM_TRAY = WM_APP + 1
    _CLASS_NAME = "ScheduledShutdownTrayWnd"

    def __init__(self, root, on_show, on_cancel, on_quit):
        self.root = root
        self._on_show = on_show
        self._on_cancel = on_cancel
        self._on_quit = on_quit
        self.hwnd = None
        self.visible = False
        self.available = False
        self._pump_id = None
        self._pending = []          # WndProc 收集到的托盘事件
        self._hinstance = kernel32.GetModuleHandleW(None)
        self._proc = WNDPROC(self._handle_message)   # 必须持引用，否则被回收
        try:
            self._create_window()
            self.available = True
        except Exception as exc:  # noqa: BLE001
            print("系统托盘初始化失败：", exc, file=sys.stderr)

    # ---- 窗口与图标 ----

    def _load_icon(self):
        try:
            ico = shell32.ExtractIconW(self._hinstance, sys.executable, 0)
            if ico:
                return ico
        except Exception:  # noqa: BLE001
            pass
        return user32.LoadIconW(None, ctypes.cast(32512, wintypes.LPCWSTR))

    def _create_window(self):
        wc = WNDCLASSW()
        wc.lpfnWndProc = self._proc
        wc.hInstance = self._hinstance
        wc.lpszClassName = self._CLASS_NAME
        wc.hIcon = self._load_icon()
        if not user32.RegisterClassW(ctypes.byref(wc)):
            if ctypes.get_last_error() != 1410:      # 1410 = 类已注册
                raise OSError("RegisterClassW 失败")
        self._wc = wc                                # 持有结构体引用
        self._hicon = wc.hIcon
        self.hwnd = user32.CreateWindowExW(
            0, self._CLASS_NAME, "ScheduledShutdownTray", 0,
            0, 0, 0, 0, None, None, self._hinstance, None)
        if not self.hwnd:
            raise OSError("CreateWindowExW 失败")

    # ---- 消息处理 ----

    def _handle_message(self, hwnd, msg, wparam, lparam):
        # 注意：这里绝不调用任何 Tk 接口——在 WndProc 里碰 Tcl 会触发
        # 「PyEval_RestoreThread / GIL」致命错误。只记录事件，
        # 由 _pump 在正常的 Tk 上下文中处理。
        if msg == self._WM_TRAY:
            self._pending.append(lparam & 0xFFFF)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _show_menu(self):
        menu = user32.CreatePopupMenu()
        user32.AppendMenuW(menu, MF_STRING, 1, "显示主窗口")
        user32.AppendMenuW(menu, MF_STRING, 2, "取消定时任务")
        user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(menu, MF_STRING, 3, "退出程序")
        user32.SetForegroundWindow(self.hwnd)        # 让菜单能被点掉
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        cmd = user32.TrackPopupMenu(
            menu, TPM_RIGHTBUTTON | TPM_RETURNCMD, pt.x, pt.y, 0, self.hwnd, None)
        user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        user32.DestroyMenu(menu)
        if cmd == 1:
            self._on_show()
        elif cmd == 2:
            self._on_cancel()
        elif cmd == 3:
            self._on_quit()

    def _pump(self):
        """用 Tk 的 after 轮询托盘事件。

        事件有两个来源：一是 WndProc 里的记录（Tk 事件循环负责派发消息），
        二是自己 PeekMessage 兜底（Tk 没抢到时）。统一在 Tk 上下文中处理，
        避开在 ctypes 回调里调用 Tk 的崩溃问题。
        """
        self._pump_id = None
        if not self.hwnd:
            return
        msg = wintypes.MSG()
        while user32.PeekMessageW(ctypes.byref(msg), self.hwnd, 0, 0, PM_REMOVE):
            if msg.message == self._WM_TRAY:
                self._pending.append(msg.lParam & 0xFFFF)
        events, self._pending = self._pending, []
        for event in events:
            if event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                self._show_menu()
            elif event == WM_LBUTTONDBLCLK:
                self._on_show()
        if self.hwnd is None:      # 处理过程中程序已退出，别再挂定时器
            return
        try:
            self._pump_id = self.root.after(60, self._pump)
        except tk.TclError:
            self._pump_id = None

    def _start_pump(self):
        if self._pump_id is None:
            self._pump_id = self.root.after(60, self._pump)

    # ---- 对外接口 ----

    def _nid(self):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        return nid

    def show(self, tip=""):
        if not self.available:
            return False
        nid = self._nid()
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = self._WM_TRAY
        nid.hIcon = self._hicon
        nid.szTip = tip[:127]
        ok = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
        if not ok:   # 上一次异常退出可能留下残留项，改用 MODIFY 覆盖
            ok = bool(shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid)))
        self.visible = ok
        if ok:
            self._start_pump()
        return ok

    def hide(self):
        if not self.available or not self.visible:
            return
        shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._nid()))
        self.visible = False

    def set_tip(self, tip):
        if not self.available or not self.visible:
            return
        nid = self._nid()
        nid.uFlags = NIF_TIP
        nid.szTip = tip[:127]
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def notify(self, title, text):
        """弹出托盘气泡通知。"""
        if not self.available or not self.visible:
            return
        nid = self._nid()
        nid.uFlags = NIF_INFO
        nid.szInfo = text[:255]
        nid.szInfoTitle = title[:63]
        nid.dwInfoFlags = NIIF_INFO
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))

    def destroy(self):
        self.hide()
        if self._pump_id is not None:
            try:
                self.root.after_cancel(self._pump_id)
            except Exception:  # noqa: BLE001
                pass
            self._pump_id = None
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None
        if self.available:
            try:
                user32.UnregisterClassW(self._CLASS_NAME, self._hinstance)
            except Exception:  # noqa: BLE001
                pass
            self.available = False


# ---------------------------------------------------------------- 圆角按钮

@lru_cache(maxsize=1)
def _continuous_corner_template():
    """按曲率先升后降的曲线积分生成标准转角。"""
    steps = 512
    x = y = 0.0
    points = [(x, y)]
    for index in range(steps):
        t1 = index / steps
        t2 = (index + 1) / steps
        theta1 = math.pi * t1 / 2 - math.sin(2 * math.pi * t1) / 4
        theta2 = math.pi * t2 / 2 - math.sin(2 * math.pi * t2) / 4
        x += (math.cos(theta1) + math.cos(theta2)) / (2 * steps)
        y += (math.sin(theta1) + math.sin(theta2)) / (2 * steps)
        points.append((x, y))
    end_x, end_y = points[-1]
    return tuple(
        (point_x / end_x, point_y / end_y)
        for point_x, point_y in points)


def _sampled_corner(samples):
    template = _continuous_corner_template()
    if samples >= len(template):
        return template
    indexes = {
        round(index * (len(template) - 1) / samples)
        for index in range(samples + 1)
    }
    return tuple(template[index] for index in sorted(indexes))


def continuous_round_points(
        x1, y1, x2, y2, radius, samples=16):
    """生成曲率先升后降、曲率半径先降后升的圆角轮廓。"""
    radius = max(1.0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    corner = _sampled_corner(samples)
    points = [(x1 + radius, y1), (x2 - radius, y1)]

    for corner_x, corner_y in corner[1:]:
        points.append((
            x2 - radius + radius * corner_x,
            y1 + radius * corner_y))

    points.append((x2, y2 - radius))
    for corner_x, corner_y in corner[1:]:
        points.append((
            x2 - radius * corner_y,
            y2 - radius + radius * corner_x))

    points.append((x1 + radius, y2))
    for corner_x, corner_y in corner[1:]:
        points.append((
            x1 + radius - radius * corner_x,
            y2 - radius * corner_y))

    points.append((x1, y1 + radius))
    for corner_x, corner_y in corner[1:-1]:
        points.append((
            x1 + radius * corner_y,
            y1 + radius - radius * corner_x))
    return points


class RoundedButton(tk.Canvas):
    """Canvas 自绘圆角按钮，样式不受系统按钮主题限制。"""

    def __init__(
            self, parent, text, command, *, width, height, radius,
            fill, active_fill, foreground, outline=None,
            active_outline=None, inset_shadow=None,
            inset_shadow_soft=None, font=FONT_BOLD):
        self._parent_bg = parent.cget("bg")
        super().__init__(
            parent, width=width, height=height, bg=self._parent_bg,
            highlightthickness=0, bd=0, cursor="hand2", takefocus=1)
        self.text = text
        self.command = command
        self.radius = radius
        self.fill = fill
        self.active_fill = active_fill
        self.foreground = foreground
        self.outline = outline
        self.active_outline = active_outline or outline
        self.inset_shadow = inset_shadow
        self.inset_shadow_soft = inset_shadow_soft or inset_shadow
        self.font = font
        self._hovered = False
        self._pressed = False

        self.bind("<Configure>", lambda _event: self._redraw())
        self.bind("<Enter>", lambda _event: self._set_hover(True))
        self.bind("<Leave>", lambda _event: self._set_hover(False))
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Return>", lambda _event: self.invoke())
        self.bind("<space>", lambda _event: self.invoke())
        self.after_idle(self._redraw)

    def _set_hover(self, hovered):
        self._hovered = hovered
        self._redraw()

    def _on_press(self, event):
        self._pressed = True
        self.focus_set()
        self._redraw()

    def _on_release(self, event):
        was_pressed = self._pressed
        self._pressed = False
        self._redraw()
        if (was_pressed and 0 <= event.x <= self.winfo_width()
                and 0 <= event.y <= self.winfo_height()):
            self.invoke()

    def invoke(self):
        if callable(self.command):
            self.command()

    @staticmethod
    def _rounded_rect(
            canvas, width, height, radius, fill, outline, line_width=1,
            inset=1):
        points = continuous_round_points(
            inset, inset, width - inset, height - inset, radius)
        canvas.create_polygon(
            points, fill=fill, outline=outline or fill,
            width=line_width if outline else 0)

    def _redraw(self):
        width = max(2, self.winfo_width())
        height = max(2, self.winfo_height())
        fill = self.active_fill if self._hovered or self._pressed else self.fill
        outline = (
            self.active_outline
            if self._hovered or self._pressed else self.outline)
        self.delete("all")
        if self.inset_shadow:
            self._rounded_rect(
                self, width, height, self.radius,
                self.inset_shadow, None, inset=0)
            self._rounded_rect(
                self, width, height, max(1, self.radius - 1),
                self.inset_shadow_soft, None, inset=1)
            self._rounded_rect(
                self, width, height, max(1, self.radius - 2),
                fill, None, inset=2)
        else:
            self._rounded_rect(
                self, width, height, self.radius, fill, outline)
        self.create_text(
            width / 2, height / 2, text=self.text,
            fill=self.foreground, font=self.font)


# ---------------------------------------------------------------- 界面

class App:
    def __init__(self, root):
        self.root = root
        self.deadline = None        # 目标时间
        self.cancel_event = None    # 用于打断等待线程
        self._tick_id = None
        self._tick_n = 0
        self._worker = None
        self._topmost_id = None
        self._warning_popup = None
        self._warning_text_var = None
        self._warning_canvas = None
        self._warning_text_item = None
        self._warning_shown = False
        self._warning_closing = False
        self._warning_animation_id = None
        self._last_schedule = load_last_schedule()
        self._cycle_pending = bool(
            self._last_schedule
            and self._last_schedule.get("cycle_pending", False))

        self._build_ui()
        self.tray = TrayIcon(root, on_show=self.restore_from_tray,
                             on_cancel=self.cancel, on_quit=self.quit_app)
        self.action_var.trace_add("write", self._on_action_change)
        self._on_mode_change()
        self._on_action_change()
        self._sync_state()
        if self._cycle_pending:
            self.root.after(200, self._resume_cycle)

    # ---------- 构建界面 ----------

    def _build_ui(self):
        self.root.title("定时关机")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        outer = ttk.Frame(self.root, padding=16)
        outer.grid(row=0, column=0, sticky="nsew")

        ttk.Label(outer, text="⏰ 定时关机", font=FONT_TITLE).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

        # ---- 模式选择 ----
        saved = self._last_schedule or {}
        self.mode = tk.StringVar(value=saved.get("mode", "time"))
        modes = ttk.LabelFrame(outer, text=" 定时方式 ", padding=10)
        modes.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.radio_time = ttk.Radiobutton(
            modes, text="指定时间", value="time", variable=self.mode,
            command=self._on_mode_change)
        self.radio_time.grid(row=0, column=0, padx=(0, 16))
        self.radio_cd = ttk.Radiobutton(
            modes, text="倒计时", value="countdown", variable=self.mode,
            command=self._on_mode_change)
        self.radio_cd.grid(row=0, column=1)

        # ---- 指定时间面板 ----
        self.time_frame = ttk.Frame(outer, padding=(0, 12, 0, 0))
        self.time_frame.grid(row=2, column=0, columnspan=2, sticky="ew")
        ttk.Label(self.time_frame, text="在以下时间执行：", font=FONT).grid(
            row=0, column=0, sticky="w")
        row = ttk.Frame(self.time_frame)
        row.grid(row=1, column=0, sticky="w", pady=(6, 0))
        default_hour, default_minute = self._default_time()
        self.hour_var = tk.StringVar(value=saved.get("hour", default_hour))
        self.minute_var = tk.StringVar(
            value=saved.get("minute", default_minute))
        ttk.Spinbox(row, from_=0, to=23, width=4, textvariable=self.hour_var,
                    format="%02.0f", font=FONT).pack(side="left")
        ttk.Label(row, text="时", font=FONT).pack(side="left", padx=(4, 12))
        ttk.Spinbox(row, from_=0, to=59, width=4, textvariable=self.minute_var,
                    format="%02.0f", font=FONT).pack(side="left")
        ttk.Label(row, text="分", font=FONT).pack(side="left", padx=(4, 0))

        self.cycle_var = tk.BooleanVar(
            value=saved.get("cycle_enabled", False))
        self.cycle_check = ttk.Checkbutton(
            self.time_frame, text="循环计时", variable=self.cycle_var)
        self.cycle_check.grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Label(
            self.time_frame, text="开启后，电脑再次启动时会自动恢复该时间。",
            font=("Microsoft YaHei UI", 9), foreground="#777777").grid(
                row=3, column=0, sticky="w", pady=(2, 0))

        # ---- 倒计时面板 ----
        self.cd_frame = ttk.Frame(outer, padding=(0, 12, 0, 0))
        self.cd_frame.grid(row=3, column=0, columnspan=2, sticky="ew")
        ttk.Label(self.cd_frame, text="从现在开始倒计时：", font=FONT).grid(
            row=0, column=0, sticky="w")
        row2 = ttk.Frame(self.cd_frame)
        row2.grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.cd_h_var = tk.StringVar(
            value=saved.get("countdown_hour", "01"))
        self.cd_m_var = tk.StringVar(
            value=saved.get("countdown_minute", "00"))
        ttk.Spinbox(row2, from_=0, to=99, width=4, textvariable=self.cd_h_var,
                    format="%02.0f", font=FONT).pack(side="left")
        ttk.Label(row2, text="小时", font=FONT).pack(side="left", padx=(4, 12))
        ttk.Spinbox(row2, from_=0, to=59, width=4, textvariable=self.cd_m_var,
                    format="%02.0f", font=FONT).pack(side="left")
        ttk.Label(row2, text="分钟", font=FONT).pack(side="left", padx=(4, 0))

        # 快捷预设
        preset = ttk.Frame(self.cd_frame)
        preset.grid(row=2, column=0, sticky="w", pady=(10, 0))
        for text, mins in (("30 分钟", 30), ("1 小时", 60), ("2 小时", 120)):
            ttk.Button(preset, text=text, width=8,
                       command=lambda m=mins: self._apply_preset(m)).pack(
                side="left", padx=(0, 6))

        # ---- 动作 & 选项 ----
        act = ttk.LabelFrame(outer, text=" 执行动作 ", padding=10)
        act.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(14, 0))

        self.action_var = tk.StringVar(
            value=saved.get("action", ACTION_SHUTDOWN))
        self.action_box = ttk.Combobox(act, textvariable=self.action_var,
                                       values=ACTIONS, state="readonly",
                                       width=10, font=FONT)
        self.action_box.grid(row=0, column=0, sticky="w")

        self.force_var = tk.BooleanVar(value=saved.get("force", True))
        self.force_check = ttk.Checkbutton(
            act, text="强制关闭未保存的程序（不弹保存提示）",
            variable=self.force_var)
        self.force_check.grid(row=1, column=0, sticky="w", pady=(8, 0))

        self.startup_var = tk.BooleanVar(value=is_startup_enabled())
        self.startup_check = ttk.Checkbutton(
            act, text="开机时自动启动本程序",
            variable=self.startup_var, command=self._toggle_startup)
        self.startup_check.grid(row=2, column=0, sticky="w", pady=(8, 0))

        # ---- 按钮 ----
        btns = ttk.Frame(outer)
        btns.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        self.start_btn = ttk.Button(btns, text="开始定时", command=self.start)
        self.start_btn.pack(side="left", ipadx=18, ipady=4)
        self.cancel_btn = ttk.Button(btns, text="取消定时", command=self.cancel)
        self.cancel_btn.pack(side="left", padx=(10, 0), ipadx=18, ipady=4)

        # ---- 状态区 ----
        status = ttk.Frame(outer)
        status.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        self.status_var = tk.StringVar(value="未设置定时任务")
        self.status_lbl = ttk.Label(status, textvariable=self.status_var,
                                    font=FONT_BIG, foreground="#1a7f37")
        self.status_lbl.pack()

        self.detail_var = tk.StringVar(value="")
        ttk.Label(status, textvariable=self.detail_var, font=FONT,
                  foreground="#666666").pack(pady=(6, 0))

        ttk.Separator(outer, orient="horizontal").grid(
            row=7, column=0, columnspan=2, sticky="ew", pady=(14, 8))

        ttk.Label(outer,
                  text="By_Shucang",
                  font=("Microsoft YaHei UI", 9), foreground="#888888",
                  justify="left").grid(
            row=8, column=0, columnspan=2, sticky="w")

    # ---------- 小工具 ----------

    @staticmethod
    def _default_time():
        t = (datetime.now() + timedelta(hours=1)).replace(second=0, microsecond=0)
        return (f"{t.hour:02d}", f"{t.minute:02d}")

    def _apply_preset(self, minutes):
        self.cd_h_var.set(f"{minutes // 60:02d}")
        self.cd_m_var.set(f"{minutes % 60:02d}")

    def _remember_schedule(self):
        mode = self.mode.get()
        cycle_enabled = bool(self.cycle_var.get()) and mode == "time"
        schedule = {
            "mode": mode,
            "hour": self.hour_var.get(),
            "minute": self.minute_var.get(),
            "countdown_hour": self.cd_h_var.get(),
            "countdown_minute": self.cd_m_var.get(),
            "action": self.action_var.get(),
            "force": bool(self.force_var.get()),
            "cycle_enabled": cycle_enabled,
            "cycle_pending": bool(self._cycle_pending) and cycle_enabled,
        }
        save_last_schedule(schedule)

    def _on_mode_change(self):
        if self.mode.get() == "time":
            self.time_frame.grid()
            self.cd_frame.grid_remove()
        else:
            self.cd_frame.grid()
            self.time_frame.grid_remove()
        self.root.geometry("")  # 让窗口随内容收缩

    def _on_action_change(self, *_args):
        """注销/睡眠 用不上「强制关闭」选项。"""
        if self.deadline is not None:
            return
        needs_force = self.action_var.get() in (ACTION_SHUTDOWN, ACTION_RESTART)
        self.force_check.config(state="normal" if needs_force else "disabled")

    def _toggle_startup(self):
        enabled = self.startup_var.get()
        try:
            set_startup_enabled(enabled)
        except OSError as exc:
            self.startup_var.set(not enabled)
            action = "开启" if enabled else "关闭"
            messagebox.showerror(
                "设置失败", f"无法{action}开机自启动：\n{exc}", parent=self.root)

    def _sync_state(self):
        running = self.deadline is not None
        state = "disabled" if running else "normal"
        self.start_btn.config(state=state)
        self.cancel_btn.config(state="normal" if running else "disabled")
        self.action_box.config(state="disabled" if running else "readonly")
        self.radio_time.config(state=state)
        self.radio_cd.config(state=state)
        for w in (self.time_frame, self.cd_frame):
            for child in w.winfo_children():
                self._set_children_state(child, state)
        if running:
            self.force_check.config(state="disabled")
        else:
            self._on_action_change()

    def _set_children_state(self, widget, state):
        try:
            widget.config(state=state, values=widget.cget("values")) \
                if isinstance(widget, ttk.Button) else widget.config(state=state)
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self._set_children_state(child, state)

    # ---------- 定时逻辑 ----------

    def _compute_deadline(self):
        """根据界面输入计算目标时间；输入非法时弹窗并返回 None。"""
        now = datetime.now()
        if self.mode.get() == "time":
            try:
                h = int(self.hour_var.get())
                m = int(self.minute_var.get())
            except ValueError:
                self._error("时间格式不正确，请输入 0-23 时、0-59 分。")
                return None
            if not (0 <= h <= 23 and 0 <= m <= 59):
                self._error("时间超出范围：小时 0-23，分钟 0-59。")
                return None

            target = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)   # 已经过了，就安排到明天
        else:
            try:
                h = int(self.cd_h_var.get())
                m = int(self.cd_m_var.get())
            except ValueError:
                self._error("倒计时格式不正确，请输入整数。")
                return None
            if h < 0 or m < 0 or (h == 0 and m == 0):
                self._error("倒计时至少需要 1 分钟。")
                return None
            target = now + timedelta(hours=h, minutes=m)

        if (target - now).total_seconds() < 1:
            self._error("时间太近了，请重新设置。")
            return None
        return target

    def start(self):
        target = self._compute_deadline()
        if target is None:
            return

        self._destroy_shutdown_warning()
        self._warning_shown = False
        self._cycle_pending = (
            self.mode.get() == "time" and bool(self.cycle_var.get()))
        self._remember_schedule()
        self.deadline = target
        self.cancel_event = threading.Event()
        action = self.action_var.get()
        force = self.force_var.get()

        self._worker = threading.Thread(
            target=self._wait_loop, args=(target, action, force), daemon=True)
        self._worker.start()

        self._tick_n = 0
        self._sync_state()
        self._tick()
        self.hide_to_tray()          # 定时开始后自动缩到托盘

    def _resume_cycle(self):
        if self.deadline is not None or not self._has_active_cycle():
            return
        self.start()

    def _has_active_cycle(self):
        return (
            bool(self._cycle_pending) and self.mode.get() == "time"
            and bool(self.cycle_var.get()))

    # ---------- 关机前提醒 ----------

    def _destroy_shutdown_warning(self):
        if self._warning_animation_id is not None:
            try:
                self.root.after_cancel(self._warning_animation_id)
            except tk.TclError:
                pass
            self._warning_animation_id = None
        if self._warning_popup is not None:
            try:
                self._warning_popup.destroy()
            except tk.TclError:
                pass
        self._warning_popup = None
        self._warning_text_var = None
        self._warning_canvas = None
        self._warning_text_item = None
        self._warning_closing = False

    @staticmethod
    def _apply_rounded_region(popup, width, height, scale):
        try:
            hwnd = int(popup.wm_frame(), 0)
        except (TypeError, ValueError, tk.TclError):
            hwnd = popup.winfo_id()
        if not hwnd:
            hwnd = user32.GetParent(popup.winfo_id())
        if not hwnd:
            return
        radius = max(6, int(WARNING_CORNER_RADIUS * scale))
        points = continuous_round_points(
            0, 0, width, height, radius, samples=24)
        point_array = (wintypes.POINT * len(points))()
        for index, (x, y) in enumerate(points):
            point_array[index] = wintypes.POINT(
                int(round(x)), int(round(y)))
        region = gdi32.CreatePolygonRgn(
            point_array, len(points), 2)
        if region and not user32.SetWindowRgn(hwnd, region, True):
            gdi32.DeleteObject(region)

    def _animate_warning_alpha(
            self, popup, start, end, duration_ms=180, callback=None):
        if self._warning_animation_id is not None:
            try:
                self.root.after_cancel(self._warning_animation_id)
            except tk.TclError:
                pass
            self._warning_animation_id = None
        frames = max(1, duration_ms // 20)

        def set_alpha(frame):
            if self._warning_popup is not popup:
                return
            ratio = min(1.0, frame / frames)
            alpha = start + (end - start) * ratio
            try:
                popup.attributes("-alpha", alpha)
            except tk.TclError:
                return
            if frame < frames:
                self._warning_animation_id = self.root.after(
                    20, set_alpha, frame + 1)
            else:
                self._warning_animation_id = None
                if callback is not None:
                    callback()

        set_alpha(1)

    def _animate_warning_entrance(
            self, popup, width, height, start_x, end_x, y,
            duration_ms=280):
        if self._warning_animation_id is not None:
            try:
                self.root.after_cancel(self._warning_animation_id)
            except tk.TclError:
                pass
            self._warning_animation_id = None
        frames = max(1, duration_ms // 20)

        def move(frame):
            if self._warning_popup is not popup:
                return
            progress = min(1.0, frame / frames)
            eased = 1.0 - (1.0 - progress) ** 3
            current_x = round(start_x + (end_x - start_x) * eased)
            try:
                popup.geometry(
                    f"{width}x{height}+{current_x}+{y}")
                popup.attributes("-alpha", eased)
            except tk.TclError:
                return
            if frame < frames:
                self._warning_animation_id = self.root.after(
                    20, move, frame + 1)
            else:
                self._warning_animation_id = None

        move(1)

    def _fade_out_shutdown_warning(self, callback):
        popup = self._warning_popup
        if popup is None:
            callback()
            return
        if self._warning_closing:
            return
        self._warning_closing = True
        try:
            current_alpha = float(popup.attributes("-alpha"))
        except (TypeError, ValueError, tk.TclError):
            current_alpha = 1.0

        def finish():
            if self._warning_popup is popup:
                self._destroy_shutdown_warning()
            callback()

        self._animate_warning_alpha(
            popup, current_alpha, 0.0, 180, finish)

    def _show_shutdown_warning(self):
        if self._warning_popup is not None:
            return

        self._warning_shown = True
        scale = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        width = int(440 * scale)

        popup = tk.Toplevel(self.root)
        popup.withdraw()
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(bg="#ffffff")

        margin = int(WARNING_INNER_PADDING * scale)
        top_padding = margin
        icon_size = int(24 * scale)
        title_gap = int(8 * scale)
        body_gap = int(12 * scale)
        body_height = int(20 * scale)
        button_gap = int(12 * scale)
        button_height = int(38 * scale)
        bottom_padding = margin
        height = (
            top_padding + icon_size + body_gap + body_height
            + button_gap + button_height + bottom_padding)

        card = tk.Canvas(
            popup, width=width, height=height, bg="#ffffff",
            highlightthickness=0, bd=0)
        card.pack(fill="both", expand=True)
        card_radius = max(6, int(WARNING_CORNER_RADIUS * scale))
        shadow_layers = (
            (0, "#d8e1eb"),
            (1, "#e2e9f1"),
            (2, "#edf1f6"),
            (3, "#f7f9fc"),
            (4, "#ffffff"),
        )
        for inset, color in shadow_layers:
            RoundedButton._rounded_rect(
                card, width, height, max(1, card_radius - inset),
                color, None, inset=inset)

        icon_left = margin
        icon_top = top_padding
        icon_right = icon_left + icon_size
        icon_bottom = icon_top + icon_size
        icon_inset = int(4 * scale)
        card.create_oval(
            icon_left + icon_inset, icon_top + icon_inset,
            icon_right - icon_inset, icon_bottom - icon_inset,
            outline="#0b8cff", width=max(1, int(2 * scale)))
        center_x = (icon_left + icon_right) / 2
        center_y = (icon_top + icon_bottom) / 2
        card.create_line(
            center_x, center_y - int(5 * scale),
            center_x, center_y + int(1 * scale),
            center_x + int(4 * scale), center_y + int(3 * scale),
            fill="#0b8cff", width=max(1, int(2 * scale)),
            capstyle=tk.ROUND, joinstyle=tk.ROUND)
        card.create_text(
            icon_right + title_gap, center_y, text="定时关机",
            font=("Microsoft YaHei UI", 13, "bold"),
            fill="#0b8cff", anchor="w")

        self._warning_text_var = tk.StringVar()
        body_y = (
            top_padding + icon_size + body_gap + body_height / 2)
        self._warning_text_item = card.create_text(
            margin, body_y, text="",
            font=FONT_BOLD, fill="#293241", anchor="w",
            width=width - margin * 2)
        self._warning_canvas = card

        button_y = (
            top_padding + icon_size + body_gap + body_height + button_gap)
        buttons_width = width - margin * 2
        button_width = (buttons_width - int(8 * scale)) // 2
        button_radius = max(5, int(WARNING_BUTTON_RADIUS * scale))
        self._warning_delay_button = RoundedButton(
            card, text="延时10分钟", command=self.delay_shutdown,
            width=button_width, height=button_height, radius=button_radius,
            fill="#ffffff", active_fill="#f3f7fc", foreground="#273142",
            outline="#cbd5e1", active_outline="#94a3b8")
        card.create_window(
            margin, button_y, anchor="nw",
            window=self._warning_delay_button,
            width=button_width, height=button_height)
        self._warning_cancel_button = RoundedButton(
            card, text="取消本次关机",
            command=self.cancel_shutdown_from_warning,
            width=button_width, height=button_height, radius=button_radius,
            fill="#ffffff", active_fill="#f3f7fc", foreground="#273142",
            outline="#cbd5e1", active_outline="#94a3b8")
        card.create_window(
            margin + button_width + int(8 * scale), button_y,
            anchor="nw", window=self._warning_cancel_button,
            width=button_width, height=button_height)

        self._warning_popup = popup
        self._warning_closing = False
        self._update_shutdown_warning()
        popup.update_idletasks()

        work_area = wintypes.RECT()
        if user32.SystemParametersInfoW(
                0x0030, 0, ctypes.byref(work_area), 0):
            right, bottom = work_area.right, work_area.bottom
            left, top = work_area.left, work_area.top
        else:
            right = self.root.winfo_screenwidth()
            bottom = self.root.winfo_screenheight()
            left = top = 0
        x = max(left, right - width - 20)
        y = max(top, bottom - height - 20)
        popup.geometry(f"{width}x{height}+{right}+{y}")
        try:
            popup.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        popup.deiconify()
        popup.update_idletasks()
        self._apply_rounded_region(popup, width, height, scale)
        popup.lift()
        self._animate_warning_entrance(
            popup, width, height, right, x, y)

    def _update_shutdown_warning(self):
        if self._warning_text_var is None or self.deadline is None:
            return
        remaining = max(
            0, int((self.deadline - datetime.now()).total_seconds()))
        minutes, seconds = divmod(remaining, 60)
        text = f"距关机还有：{minutes:02d}:{seconds:02d}"
        self._warning_text_var.set(text)
        if (self._warning_canvas is not None
                and self._warning_text_item is not None):
            self._warning_canvas.itemconfigure(
                self._warning_text_item, text=text)

    def delay_shutdown(self):
        self._fade_out_shutdown_warning(self._delay_shutdown_now)

    def _delay_shutdown_now(self):
        if self.deadline is None:
            self._destroy_shutdown_warning()
            return

        if self.cancel_event is not None:
            self.cancel_event.set()
        self.deadline += timedelta(minutes=10)
        action = self.action_var.get()
        force = self.force_var.get()
        self.cancel_event = threading.Event()
        self._worker = threading.Thread(
            target=self._wait_loop,
            args=(self.deadline, action, force), daemon=True)
        self._worker.start()

        self._warning_shown = False
        self._destroy_shutdown_warning()
        self.status_var.set(
            f"已延时 10 分钟，将于 {self.deadline:%H:%M:%S} 关机")
        self.detail_var.set("定时任务仍在继续，可在 5 分钟前再次调整。")
        self.tray.set_tip(self._tray_text())
        self.tray.notify(
            "定时关机已延时",
            f"新的关机时间：{self.deadline:%m月%d日 %H:%M:%S}")

    def cancel_shutdown_from_warning(self):
        self._fade_out_shutdown_warning(
            lambda: self.cancel(restore=False))

    # ---------- 托盘相关 ----------

    def hide_to_tray(self):
        if self.deadline is None:
            return
        if self.tray.show(self._tray_text()):
            self.tray.notify(
                "定时关机已启动",
                f"将于 {self.deadline:%m月%d日 %H:%M} {self.action_var.get()}。"
                f"双击托盘图标可重新打开窗口。")
            self.root.withdraw()
        else:
            self.root.iconify()      # 托盘不可用时退化为最小化到任务栏
            self.detail_var.set("（系统托盘不可用，已最小化到任务栏）")

    def restore_from_tray(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        self.root.attributes("-topmost", True)

        def clear_topmost():
            try:
                self.root.attributes("-topmost", False)
            except tk.TclError:
                pass           # 窗口已经销毁
            finally:
                self._topmost_id = None
        self._topmost_id = self.root.after(300, clear_topmost)

    def _tray_text(self):
        if self.deadline is None:
            return "定时关机"
        remaining = int((self.deadline - datetime.now()).total_seconds())
        h, rem = divmod(max(remaining, 0), 3600)
        m, s = divmod(rem, 60)
        return f"{self.action_var.get()}倒计时 {h:02d}:{m:02d}:{s:02d}"

    # ---------- 到点执行 ----------

    def _wait_loop(self, target, action, force):
        ev = self.cancel_event
        while True:
            remaining = (target - datetime.now()).total_seconds()
            if remaining <= 0:
                break
            # 每 0.5 秒醒来检查一次，保证取消能立刻生效
            if ev.wait(min(remaining, 0.5)):
                return
        # 到点执行（UI 更新交回主线程）
        self.root.after(0, lambda: self._fire(action, force))

    def _fire(self, action, force):
        self._stop_ticking()
        self._destroy_shutdown_warning()
        self._warning_shown = False
        hidden = self.root.state() == "withdrawn"
        self.tray.hide()
        if hidden:
            self.restore_from_tray()      # 让用户看到执行结果
        self.deadline = None
        self.cancel_event = None
        ok, err = run_action(action, force)
        self._sync_state()
        if ok:
            name = {"关机": "正在关机", "重启": "正在重启",
                    "注销": "正在注销", "睡眠": "正在进入睡眠"}[action]
            self.status_var.set(f"✅ 已触发：{name}")
            self.detail_var.set("系统已开始执行，若需中止请立即运行「shutdown /a」。"
                                if action in (ACTION_SHUTDOWN, ACTION_RESTART) else "")
        else:
            self.status_var.set("⚠️ 执行失败")
            self.detail_var.set(err)

    def cancel(self, restore=True):
        was_hidden = self.root.state() == "withdrawn"
        self._destroy_shutdown_warning()
        self._warning_shown = False
        if self.cancel_event is not None:
            self.cancel_event.set()
        self.cancel_event = None
        self.deadline = None
        self._cycle_pending = False
        self._remember_schedule()
        self._stop_ticking()
        self.tray.hide()
        self._sync_state()
        self.status_var.set("已取消定时任务")
        self.detail_var.set("")
        if was_hidden and restore:
            self.restore_from_tray()

    # ---------- 倒计时显示 ----------

    def _tick(self):
        if self.deadline is None:
            return
        remaining = int((self.deadline - datetime.now()).total_seconds())
        if remaining < 0:
            remaining = 0
        h, rem = divmod(remaining, 3600)
        m, s = divmod(rem, 60)
        self.status_var.set(f"{h:02d}:{m:02d}:{s:02d}")
        self.status_lbl.config(foreground="#c2410c")
        self.detail_var.set(
            f"{self.action_var.get()}时间：{self.deadline.strftime('%m月%d日 %H:%M:%S')}")
        if (self.action_var.get() == ACTION_SHUTDOWN
                and remaining <= SHUTDOWN_WARNING_SECONDS
                and not self._warning_shown):
            self._show_shutdown_warning()
        if self._warning_popup is not None:
            self._update_shutdown_warning()
        self._tick_n += 1
        if self._tick_n % 5 == 0:        # 每秒同步一次托盘提示
            self.tray.set_tip(self._tray_text())
        self._tick_id = self.root.after(200, self._tick)

    def _stop_ticking(self):
        if self._tick_id is not None:
            self.root.after_cancel(self._tick_id)
            self._tick_id = None
        self.status_lbl.config(foreground="#1a7f37")

    # ---------- 关闭窗口 ----------

    def _on_close(self):
        if self.deadline is not None:
            cycle_active = self._has_active_cycle()
            if cycle_active:
                prompt = (
                    "定时任务正在进行中，循环计时已开启。\n\n"
                    "是：隐藏到托盘，继续定时\n"
                    "否：退出程序，下次打开继续循环\n"
                    "取消：什么都不做")
            else:
                prompt = (
                    "定时任务正在进行中。\n\n"
                    "是：隐藏到托盘，继续定时\n"
                    "否：取消定时任务并退出\n"
                    "取消：什么都不做")
            ans = messagebox.askyesnocancel("确认退出", prompt)
            if ans is None:
                return
            if ans:
                self.hide_to_tray()
                return
            if cycle_active:
                self.quit_app()
                return
            self.cancel(restore=False)
        self.quit_app()

    def quit_app(self):
        self._remember_schedule()
        self._stop_ticking()
        self._destroy_shutdown_warning()
        if self._topmost_id is not None:
            try:
                self.root.after_cancel(self._topmost_id)
            except Exception:  # noqa: BLE001
                pass
            self._topmost_id = None
        self.tray.destroy()
        self.root.destroy()

    def _error(self, msg):
        messagebox.showwarning("输入有误", msg)


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)   # 高分屏文字清晰
    except Exception:
        pass
    root = tk.Tk()
    icon_path = resource_path("app_icon.ico")
    if icon_path.exists():
        try:
            root.iconbitmap(default=str(icon_path))
        except tk.TclError:
            pass
    App(root)
    root.update_idletasks()
    root.geometry("")
    root.mainloop()


if __name__ == "__main__":
    main()
