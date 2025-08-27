"""
Refactored script with extended recording configuration + game FPS counter.
- FPS label shows true game render FPS via PresentMon when available (also prints to terminal).
- If PresentMon isn't found, it falls back to capture-FPS during recording (also prints to terminal).
- Recording paced with a Precise QTimer so playback matches real-time (no time-lapse).
"""

import sys
from typing import Optional, Dict, Any, Tuple
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtWebEngineWidgets import QWebEngineView  # kept if you use it elsewhere
import win32gui
import win32con
import ctypes
import cv2
import pyautogui
import numpy as np
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import json
import os
from urllib.request import urlopen
import time
import subprocess
import psutil
import win32process

# ---------- Windows Acrylic (best effort) ----------
try:
    from ctypes.wintypes import DWORD  # type: ignore
    ACCENT_ENABLE_ACRYLICBLURBEHIND: int = 4

    class ACCENTPOLICY(ctypes.Structure):
        _fields_ = [
            ("AccentState", DWORD),
            ("AccentFlags", DWORD),
            ("GradientColor", DWORD),
            ("AnimationId", DWORD),
        ]

    class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
        _fields_ = [
            ("Attribute", DWORD),
            ("pData", ctypes.POINTER(ACCENTPOLICY)),
            ("SizeOfData", DWORD),
        ]
except Exception:
    pass


# ---------- Dialogs / Widgets ----------
class RecordingConfigDialog(QtWidgets.QDialog):
    """Dialog to configure recording settings: file name, resolution, frame rate, and quality."""

    def __init__(self, current_file_name: str, current_resolution: Tuple[int, int],
                 current_fps: int, current_quality: int,
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Recording Configuration")
        self.resize(320, 220)

        layout: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout(self)

        # File name
        layout.addWidget(QtWidgets.QLabel("File Name:"))
        self.file_line_edit = QtWidgets.QLineEdit(current_file_name)
        layout.addWidget(self.file_line_edit)

        # Resolution
        res_layout = QtWidgets.QHBoxLayout()
        res_layout.addWidget(QtWidgets.QLabel("Width:"))
        self.width_spin = QtWidgets.QSpinBox()
        self.width_spin.setRange(100, 10000)
        self.width_spin.setValue(current_resolution[0])

        res_layout.addWidget(self.width_spin)
        res_layout.addWidget(QtWidgets.QLabel("Height:"))
        self.height_spin = QtWidgets.QSpinBox()
        self.height_spin.setRange(100, 10000)
        self.height_spin.setValue(current_resolution[1])
        res_layout.addWidget(self.height_spin)
        layout.addLayout(res_layout)

        # FPS
        fps_layout = QtWidgets.QHBoxLayout()
        fps_layout.addWidget(QtWidgets.QLabel("Frame Rate (Hz):"))
        self.fps_spin = QtWidgets.QSpinBox()
        self.fps_spin.setRange(1, 240)
        self.fps_spin.setValue(current_fps)
        fps_layout.addWidget(self.fps_spin)
        layout.addLayout(fps_layout)

        # Quality (stored only)
        q_layout = QtWidgets.QHBoxLayout()
        q_layout.addWidget(QtWidgets.QLabel("Quality:"))
        self.quality_spin = QtWidgets.QSpinBox()
        self.quality_spin.setRange(1, 100)
        self.quality_spin.setValue(current_quality)
        q_layout.addWidget(self.quality_spin)
        layout.addLayout(q_layout)

        # Buttons
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_config(self) -> Tuple[str, Tuple[int, int], int, int]:
        return (
            self.file_line_edit.text(),
            (self.width_spin.value(), self.height_spin.value()),
            self.fps_spin.value(),
            self.quality_spin.value(),
        )


class SpotifyWidget(QtWidgets.QWidget):
    """Widget to display Spotify track info and control playback."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.sp: Optional[spotipy.Spotify] = None
        self.current_track: Optional[Dict[str, Any]] = None
        self.config: Dict[str, Any] = self.load_config()
        self.initUI()
        self.setup_spotify()

    def load_config(self) -> Dict[str, Any]:
        cfg = os.path.join(os.path.dirname(__file__),
                           '..', 'config', 'config.json')
        try:
            with open(cfg, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"[CFG] Error loading config: {e}")
            return {}

    def initUI(self) -> None:
        self.setStyleSheet("""
            background-color: rgba(40, 40, 40, 0.6);
            border-radius: 10px;
            padding: 15px;
        """)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        self.album_art = QtWidgets.QLabel()
        self.album_art.setFixedSize(105, 105)
        self.album_art.setStyleSheet(
            "border-radius: 8px; border: 1px solid #333;")
        layout.addWidget(self.album_art)

        info_layout = QtWidgets.QVBoxLayout()
        self.track_label = QtWidgets.QLabel("No track playing")
        self.track_label.setStyleSheet(
            "QLabel { color: white; font-size: 12px; font-weight: bold; }")
        self.artist_label = QtWidgets.QLabel("")
        self.artist_label.setStyleSheet(
            "QLabel { color: #aaaaaa; font-size: 12px; }")
        self.progress = QtWidgets.QProgressBar()
        self.progress.setFixedHeight(5)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet("""
            QProgressBar { background: rgba(255, 255, 255, 0.2); border-radius: 2px; }
            QProgressBar::chunk { background: #1DB954; border-radius: 2px; }
        """)
        info_layout.addWidget(self.track_label)
        info_layout.addWidget(self.artist_label)
        info_layout.addWidget(self.progress)
        layout.addLayout(info_layout)

        control_layout = QtWidgets.QVBoxLayout()
        self.play_btn = QtWidgets.QPushButton()
        self.play_btn.setIcon(QtGui.QIcon(os.path.join(
            os.path.dirname(__file__), "..", "images", "play.png")))
        self.play_btn.setIconSize(QtCore.QSize(24, 24))
        self.play_btn.setFixedSize(40, 40)
        self.play_btn.clicked.connect(self.toggle_playback)
        self.play_btn.setStyleSheet('''
            QPushButton { background-color: #1DB954; border-radius: 20px; border: none; }
            QPushButton:hover { background-color: #1ED760; }
            QPushButton:pressed { background-color: #1AA34A; }
        ''')

        self.next_btn = QtWidgets.QPushButton()
        self.next_btn.setIcon(QtGui.QIcon(os.path.join(
            os.path.dirname(__file__), "..", "images", "next-button.png")))
        self.next_btn.setIconSize(QtCore.QSize(24, 24))
        self.next_btn.setFixedSize(40, 40)
        self.next_btn.clicked.connect(self.next_track)
        self.next_btn.setStyleSheet('''
            QPushButton { background-color: rgba(255, 255, 255, 0.1); border-radius: 20px; border: none; }
            QPushButton:hover { background-color: rgba(255, 255, 255, 0.2); }
            QPushButton:pressed { background-color: rgba(255, 255, 255, 0.05); }
        ''')

        control_layout.addWidget(self.play_btn)
        control_layout.addWidget(self.next_btn)
        layout.addLayout(control_layout)

        self.status_label = QtWidgets.QLabel()
        self.status_label.setStyleSheet("color: #ff4444; font-size: 10px;")
        layout.addWidget(self.status_label)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_track_info)
        self.timer.start(1000)

    def setup_spotify(self) -> None:
        try:
            client_id = self.config.get('spotify', {}).get('client_id')
            client_secret = self.config.get('spotify', {}).get('client_secret')
            if not client_id or not client_secret:
                raise ValueError("Missing Spotify credentials in config")

            self.sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
                client_id=client_id,
                client_secret=client_secret,
                redirect_uri='http://127.0.0.1:8888/callback',
                scope='user-read-playback-state,user-modify-playback-state,user-read-currently-playing',
                cache_path='.spotifycache'
            ))
            if not self.sp.current_user():
                self.sp.auth_manager.get_access_token(as_dict=False)
        except Exception as e:
            self.show_error(f"Spotify auth failed: {str(e)}")

    def update_track_info(self) -> None:
        if not self.sp:
            return
        try:
            current = self.sp.current_playback()
            if current and current.get('is_playing', False):
                self.current_track = current.get('item')
                if self.current_track:
                    name = self.current_track.get('name', '')
                    self.track_label.setText(
                        (name[:30] + '...') if len(name) > 30 else name)
                    artists = ", ".join(a.get('name', '')
                                        for a in self.current_track.get('artists', []))
                    self.artist_label.setText(
                        (artists[:40] + '...') if len(artists) > 40 else artists)

                    progress_ms = current.get('progress_ms', 0)
                    duration_ms = self.current_track.get('duration_ms', 0)
                    self.progress.setMaximum(max(1, duration_ms))
                    self.progress.setValue(progress_ms)

                    images = self.current_track.get(
                        'album', {}).get('images', [])
                    if images:
                        self.load_image_from_url(images[0]['url'])

                    self.play_btn.setIcon(QtGui.QIcon(os.path.join(
                        os.path.dirname(__file__), "..", "images", "pause.png")))
            else:
                self.play_btn.setIcon(QtGui.QIcon(os.path.join(
                    os.path.dirname(__file__), "..", "images", "play.png")))
        except Exception as e:
            self.show_error(f"Update error: {str(e)}")

    def load_image_from_url(self, url: str) -> None:
        try:
            data = urlopen(url).read()
            image = QtGui.QImage()
            image.loadFromData(data)
            pixmap = QtGui.QPixmap.fromImage(image).scaled(
                75, 75, QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation
            )
            self.album_art.setPixmap(pixmap)
        except Exception as e:
            print("[SPOTIFY] Album art error:", e)

    def toggle_playback(self) -> None:
        if not self.sp:
            self.show_error("Not connected to Spotify")
            return
        try:
            playback = self.sp.current_playback()
            if not playback:
                self.show_error("No active device")
                return
            if playback.get('is_playing', False):
                self.sp.pause_playback()
            else:
                self.sp.start_playback()
            QtCore.QTimer.singleShot(500, self.update_track_info)
        except Exception as e:
            self.show_error(f"Playback error: {str(e)}")

    def next_track(self) -> None:
        if not self.sp:
            self.show_error("Not connected to Spotify")
            return
        try:
            self.sp.next_track()
            QtCore.QTimer.singleShot(500, self.update_track_info)
        except Exception as e:
            self.show_error(f"Skip error: {str(e)}")

    def show_error(self, message: str) -> None:
        self.status_label.setText(message)
        QtCore.QTimer.singleShot(3000, lambda: self.status_label.setText(""))


class GameTimerWidget(QtWidgets.QWidget):
    """Simple game session timer."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.elapsed_time = 0
        self.is_running = False
        self.initUI()

    def initUI(self) -> None:
        self.setStyleSheet("""
            background-color: rgba(40, 40, 40, 0.6);
            border-radius: 10px;
            padding: 15px;
        """)
        layout = QtWidgets.QVBoxLayout(self)

        self.time_label = QtWidgets.QLabel("00:00:00")
        self.time_label.setAlignment(QtCore.Qt.AlignCenter)
        self.time_label.setStyleSheet(
            "QLabel { color: white; font-size: 24px; font-weight: bold; }")
        layout.addWidget(self.time_label)

        btns = QtWidgets.QHBoxLayout()
        self.start_button = QtWidgets.QPushButton("Start")
        self.start_button.setStyleSheet('''
            QPushButton { background-color: #1DB954; border-radius: 5px; color: white; padding: 5px 10px; }
            QPushButton:hover { background-color: #1ED760; }
        ''')
        self.start_button.clicked.connect(self.start_timer)

        self.pause_button = QtWidgets.QPushButton("Pause")
        self.pause_button.setStyleSheet('''
            QPushButton { background-color: #FFC107; border-radius: 5px; color: white; padding: 5px 10px; }
            QPushButton:hover { background-color: #FFCA28; }
        ''')
        self.pause_button.clicked.connect(self.pause_timer)

        self.stop_button = QtWidgets.QPushButton("Stop")
        self.stop_button.setStyleSheet('''
            QPushButton { background-color: #DC3545; border-radius: 5px; color: white; padding: 5px 10px; }
            QPushButton:hover { background-color: #E53935; }
        ''')
        self.stop_button.clicked.connect(self.stop_timer)

        btns.addWidget(self.start_button)
        btns.addWidget(self.pause_button)
        btns.addWidget(self.stop_button)
        layout.addLayout(btns)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_timer)

    def start_timer(self) -> None:
        if not self.is_running:
            self.timer.start(1000)
            self.is_running = True

    def pause_timer(self) -> None:
        if self.is_running:
            self.timer.stop()
            self.is_running = False

    def stop_timer(self) -> None:
        self.timer.stop()
        self.elapsed_time = 0
        self.is_running = False
        self.update_display()

    def update_timer(self) -> None:
        self.elapsed_time += 1
        self.update_display()

    def update_display(self) -> None:
        h = self.elapsed_time // 3600
        m = (self.elapsed_time % 3600) // 60
        s = self.elapsed_time % 60
        self.time_label.setText(f"{h:02d}:{m:02d}:{s:02d}")


# ---------- True Game FPS via PresentMon ----------
class GameFpsMonitor(QtCore.QObject):
    """
    Wraps PresentMon to read true render FPS for a target process.
    Emits fps_updated(float). Prints errors/info to terminal.
    """
    fps_updated = QtCore.pyqtSignal(float)
    error = QtCore.pyqtSignal(str)

    def __init__(self, presentmon_path: str, parent: Optional[QtCore.QObject] = None):
        super().__init__(parent)
        self.presentmon_path = presentmon_path
        self.proc: Optional[subprocess.Popen] = None
        self.reader_timer = QtCore.QTimer(self)
        self.reader_timer.timeout.connect(self._read_stdout)
        self.target_name: Optional[str] = None
        self.buffer = b""

    def start(self, process_name: Optional[str]) -> None:
        self.stop()
        self.target_name = process_name
        if not self.presentmon_path or not os.path.isfile(self.presentmon_path):
            print("[FPS] Error: PresentMon not found")
            self.error.emit("PresentMon not found")
            return

        args = [self.presentmon_path, "-output_stdout", "-no_csv"]
        if process_name:
            args += ["-process_name", process_name]
        else:
            args += ["-captureall"]

        try:
            self.proc = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0
            )
            self.reader_timer.start(100)
            print(
                f"[FPS] PresentMon started. Target = {process_name or 'foreground'}")
        except Exception as e:
            print(f"[FPS] Failed to start PresentMon: {e}")
            self.error.emit(f"Failed to start PresentMon: {e}")

    def stop(self) -> None:
        self.reader_timer.stop()
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass
            self.proc = None
        self.buffer = b""

    def _read_stdout(self) -> None:
        if not self.proc or not self.proc.stdout:
            return
        try:
            chunk = self.proc.stdout.read1(4096)
            if not chunk:
                return
            self.buffer += chunk
            while b"\n" in self.buffer:
                line, self.buffer = self.buffer.split(b"\n", 1)
                self._parse_line(line.decode(errors="ignore").strip())
        except Exception:
            pass

    def _parse_line(self, line: str) -> None:
        if not line or "," not in line:
            return
        if "msBetweenPresents" in line or "ProcessName" in line:
            return
        if "python.exe" in line.lower() or "pythonw.exe" in line.lower():
            return

        fields = [f.strip() for f in line.split(",") if f.strip()]
        ms_val = None
        for f in fields:
            try:
                v = float(f)
                if 0.5 <= v <= 1000.0:
                    ms_val = v
                    break
            except ValueError:
                continue

        if ms_val and ms_val > 0:
            fps = 1000.0 / ms_val
            print(f"[FPS] Game FPS: {fps:.1f}")
            self.fps_updated.emit(fps)


class FpsCounterWidget(QtWidgets.QLabel):
    """Simple label that shows FPS."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setText("FPS: --")
        self.setAlignment(QtCore.Qt.AlignCenter)
        self.setFixedHeight(22)
        self.setStyleSheet("""
            QLabel {
                color: white;
                background: rgba(20, 20, 20, 0.6);
                border: 1px solid rgba(255, 255, 255, 0.15);
                border-radius: 6px;
                padding: 2px 6px;
                font-weight: bold;
            }
        """)

    def set_fps_value(self, fps: float) -> None:
        self.setText(f"FPS: {fps:.1f}")


def get_foreground_process_name() -> Optional[str]:
    try:
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        p = psutil.Process(pid)
        name = os.path.basename(p.exe())
        if name.lower() in ("python.exe", "pythonw.exe"):
            return None
        return name
    except Exception:
        return None


# ---------- Main Overlay ----------
class GameOverlay(QtWidgets.QWidget):
    """
    Overlay combines: Game timer, Spotify, Recording controls, FPS label.
    Recording paced precisely to avoid fast playback.
    """
    SCREEN_INDEX: int = 2
    WINDOW_X: int = 0
    WINDOW_Y: int = 0
    WINDOW_WIDTH: int = 300
    WINDOW_HEIGHT: int = 220
    POSITION_ALIGMENT: str = "TOP_LEFT"

    def __init__(self) -> None:
        super().__init__()
        self.recording: bool = False
        self.config: Dict[str, Any] = self.load_config()

        # FPS (PresentMon) config
        fps_cfg = self.config.get("fps", {})
        self._presentmon_path = fps_cfg.get("presentmon_path", "")
        self._preferred_proc = (fps_cfg.get(
            "process_name", "") or "").strip() or None

        # Recording defaults
        screen_size = pyautogui.size()
        rec_cfg = self.config.get("recording", {})
        self.record_file_name = rec_cfg.get("file_name", "output.avi")
        self.record_resolution = tuple(rec_cfg.get(
            "resolution", (screen_size.width, screen_size.height)))
        self.requested_record_fps = int(rec_cfg.get("fps", 30))
        self.record_quality = int(rec_cfg.get("quality", 95))

        # State for FPS
        self._last_game_fps_ts = 0.0
        self._ema_fps: Optional[float] = None

        # Capture FPS counters (once/sec)
        self._cap_frames_this_sec = 0
        self._cap_sec_anchor = time.perf_counter()
        self._current_capture_fps = float(self.requested_record_fps)

        # Recording timer & writer
        self._rec_timer = QtCore.QTimer(self)
        self._rec_timer.setTimerType(QtCore.Qt.PreciseTimer)
        self._rec_timer.timeout.connect(self._capture_step)
        self._rec_period_ms = max(
            1, int(1000 / max(1, self.requested_record_fps)))
        self.out: Optional[cv2.VideoWriter] = None

        # Fallback updater: if no game FPS for 1.5s, show capture FPS
        self._fallback = QtCore.QTimer(self)
        self._fallback.timeout.connect(self._update_fallback_fps)
        self._fallback.start(500)

        self.initUI()

        # --- FIX: create PresentMon monitor BEFORE using it ---
        self._game_fps_monitor = GameFpsMonitor(self._presentmon_path, self)
        self._game_fps_monitor.fps_updated.connect(self._on_game_fps)
        self._game_fps_monitor.error.connect(self._on_game_fps_error)

        # Start game FPS monitor after the UI exists
        QtCore.QTimer.singleShot(800, self._ensure_presentmon_target)

    def load_config(self) -> Dict[str, Any]:
        cfg = os.path.join(os.path.dirname(__file__),
                           '..', 'config', 'config.json')
        try:
            with open(cfg, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"[CFG] Error loading config: {e}")
            return {}

    def initUI(self) -> None:
        self.setWindowFlags(
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)

        # Position
        screens = QtWidgets.QDesktopWidget().screenCount()
        if screens > self.SCREEN_INDEX and self.POSITION_ALIGMENT == "TOP_LEFT":
            sg = QtWidgets.QDesktopWidget().screenGeometry(self.SCREEN_INDEX)
            x = sg.x() + self.WINDOW_X
            y = sg.y() + self.WINDOW_Y
            self.setGeometry(x, y, self.WINDOW_WIDTH, self.WINDOW_HEIGHT)
        else:
            self.setGeometry(100, 100, self.WINDOW_WIDTH, self.WINDOW_HEIGHT)

        self.setAcrylicEffect()

        layout = QtWidgets.QVBoxLayout(self)

        # (Optional) game timer
        layout.addWidget(GameTimerWidget())

        # Spotify
        layout.addWidget(SpotifyWidget())

        # FPS Label
        self.fps_widget = FpsCounterWidget()
        layout.addWidget(self.fps_widget)

        # Recording controls
        rec_row = QtWidgets.QHBoxLayout()
        self.record_btn = QtWidgets.QPushButton("Start Recording")
        self.record_btn.setStyleSheet('''
            QPushButton {
                background: rgba(255, 0, 0, 0.5);
                border: 2px solid rgba(255, 255, 255, 0.5);
                border-radius: 5px;
                color: white;
                padding: 8px;
                margin-top: 10px;
            }
            QPushButton:hover { background: rgba(255, 0, 0, 0.7); }
        ''')
        self.record_btn.clicked.connect(self.toggle_recording)
        rec_row.addWidget(self.record_btn)

        self.record_config_btn = QtWidgets.QPushButton("Recording Config")
        self.record_config_btn.setStyleSheet('''
            QPushButton {
                background: rgba(0, 123, 255, 0.5);
                border: 2px solid rgba(255, 255, 255, 0.5);
                border-radius: 5px;
                color: white;
                padding: 8px;
                margin-top: 10px;
            }
            QPushButton:hover { background: rgba(0, 123, 255, 0.7); }
        ''')
        self.record_config_btn.clicked.connect(self.open_record_config)
        rec_row.addWidget(self.record_config_btn)

        layout.addLayout(rec_row)

        # Toggle overlay shortcut
        sc = QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+~"), self)
        sc.setContext(QtCore.Qt.ApplicationShortcut)
        sc.activated.connect(self.toggle_overlay)

    def setAcrylicEffect(self) -> None:
        try:
            hwnd: int = self.winId().__int__()
            accent = ACCENTPOLICY()
            accent.AccentState = ACCENT_ENABLE_ACRYLICBLURBEHIND
            accent.GradientColor = 0xBF000000
            data = WINDOWCOMPOSITIONATTRIBDATA()
            data.Attribute = 19
            data.pData = ctypes.pointer(accent)
            data.SizeOfData = ctypes.sizeof(accent)
            ctypes.windll.user32.SetWindowCompositionAttribute(
                hwnd, ctypes.pointer(data))
        except Exception as e:
            print("[UI] Acrylic not supported:", e)
            self.setStyleSheet("background: rgba(50, 50, 50, 0.75);")

    # ----- PresentMon -----
    def _ensure_presentmon_target(self) -> None:
        target = self._preferred_proc or get_foreground_process_name()
        if not self._presentmon_path:
            print("[FPS] PresentMon path not configured; using capture-FPS fallback.")
            return
        self._game_fps_monitor.start(target)

    @QtCore.pyqtSlot(float)
    def _on_game_fps(self, fps: float) -> None:
        self._last_game_fps_ts = time.perf_counter()
        if self._ema_fps is None:
            self._ema_fps = fps
        else:
            self._ema_fps = 0.7 * self._ema_fps + 0.3 * fps
        self.fps_widget.set_fps_value(self._ema_fps)

    @QtCore.pyqtSlot(str)
    def _on_game_fps_error(self, msg: str) -> None:
        if not self.recording:
            self.fps_widget.set_fps_value(0.0)

    def _update_fallback_fps(self) -> None:
        # If we haven't seen game FPS recently, show capture FPS instead
        if (time.perf_counter() - self._last_game_fps_ts) > 1.5:
            self.fps_widget.set_fps_value(
                self._current_capture_fps if self.recording else 0.0)

    # ----- Recording -----
    def open_record_config(self) -> None:
        dlg = RecordingConfigDialog(
            self.record_file_name, self.record_resolution, self.requested_record_fps, self.record_quality, self
        )
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            (self.record_file_name, self.record_resolution,
             self.requested_record_fps, self.record_quality) = dlg.get_config()
            self._rec_period_ms = max(
                1, int(1000 / max(1, self.requested_record_fps)))
            print(f"[REC] Updated: file={self.record_file_name}, res={self.record_resolution}, "
                  f"fps={self.requested_record_fps}, q={self.record_quality}")

    def toggle_overlay(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self.setWindowFlags(
                QtCore.Qt.WindowStaysOnTopHint |
                QtCore.Qt.FramelessWindowHint |
                QtCore.Qt.Tool
            )
            self.show()
            self.activateWindow()

    def toggle_recording(self) -> None:
        if self.recording:
            self.stop_recording()
        else:
            self.start_recording()

    def _ensure_output_dir(self, path: str) -> None:
        directory = os.path.dirname(path)
        if directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)

    def _choose_fourcc(self, filename: str) -> int:
        ext = os.path.splitext(filename)[1].lower()
        if ext == ".mp4":
            return cv2.VideoWriter_fourcc(*'mp4v')
        # default to avi/xvid
        return cv2.VideoWriter_fourcc(*'XVID')

    def start_recording(self) -> None:
        self._ensure_output_dir(self.record_file_name)
        fourcc = self._choose_fourcc(self.record_file_name)
        self.out = cv2.VideoWriter(
            self.record_file_name, fourcc, float(
                self.requested_record_fps), self.record_resolution
        )
        if not self.out or not self.out.isOpened():
            QtWidgets.QMessageBox.critical(self, "Recording Error",
                                           "Failed to open video writer. Check file path and codec.")
            self.out = None
            return

        self.recording = True
        self.record_btn.setText("Stop Recording")

        # Reset counters for per-second achieved FPS (for print + fallback label)
        self._cap_frames_this_sec = 0
        self._cap_sec_anchor = time.perf_counter()
        self._current_capture_fps = float(self.requested_record_fps)

        # Start precise timer
        self._rec_timer.start(self._rec_period_ms)
        print(
            f"[REC] Started @ target {self.requested_record_fps} fps, res={self.record_resolution}, file={self.record_file_name}")

    def stop_recording(self) -> None:
        self._rec_timer.stop()
        if self.out:
            try:
                self.out.release()
            except Exception:
                pass
            self.out = None

        self.recording = False
        self.record_btn.setText("Start Recording")
        # If PresentMon is inactive, show 0 FPS when idle
        if (time.perf_counter() - self._last_game_fps_ts) > 1.5:
            self.fps_widget.set_fps_value(0.0)
        print("[REC] Stopped.")

    def _capture_step(self) -> None:
        """Called by precise QTimer at the requested cadence."""
        if not self.recording or not self.out:
            return

        # Take screenshot
        img = pyautogui.screenshot()
        frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

        # Enforce target resolution
        if (frame.shape[1], frame.shape[0]) != self.record_resolution:
            frame = cv2.resize(frame, self.record_resolution,
                               interpolation=cv2.INTER_LINEAR)

        self.out.write(frame)

        # Count for achieved FPS (once per second)
        self._cap_frames_this_sec += 1
        now = time.perf_counter()
        if now - self._cap_sec_anchor >= 1.0:
            achieved = float(self._cap_frames_this_sec)
            self._current_capture_fps = achieved
            print(f"[FPS] Capture FPS: {achieved:.1f}")  # terminal print
            self._cap_frames_this_sec = 0
            self._cap_sec_anchor = now

            # If PresentMon hasn't updated recently, reflect capture FPS in label
            if (now - self._last_game_fps_ts) > 1.5:
                self.fps_widget.set_fps_value(achieved)

    # ----- Dragging -----
    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        self.old_pos = event.globalPos()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        delta = event.globalPos() - self.old_pos
        self.move(self.x() + delta.x(), self.y() + delta.y())
        self.old_pos = event.globalPos()


# ---------- Entrypoint ----------
if __name__ == "__main__":
    # IMPORTANT: set High-DPI scaling BEFORE creating the QApplication
    QtCore.QCoreApplication.setAttribute(
        QtCore.Qt.AA_EnableHighDpiScaling, True)
    app = QtWidgets.QApplication(sys.argv)

    overlay = GameOverlay()
    overlay.show()
    sys.exit(app.exec_())
