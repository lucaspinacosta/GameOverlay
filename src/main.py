"""
Refactored script with extended recording configuration + game FPS counter.
- Game FPS via PresentMon (prints to terminal + overlay label).
- Capture FPS fallback (prints to terminal) if PresentMon isn't available.
- Time-synchronized recording loop (records at the configured FPS; no "fast" playback).
"""

import sys
from typing import Optional, Dict, Any, Tuple
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtWebEngineWidgets import QWebEngineView  # kept if you need it elsewhere
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

# For acrylic effect (Windows only)
try:
    from ctypes.wintypes import DWORD  # type: ignore
    ACCENT_ENABLE_ACRYLICBLURBEHIND: int = 4

    class ACCENTPOLICY(ctypes.Structure):
        _fields_ = [
            ("AccentState", DWORD),
            ("AccentFlags", DWORD),
            ("GradientColor", DWORD),
            ("AnimationId", DWORD)
        ]

    class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
        _fields_ = [
            ("Attribute", DWORD),
            ("pData", ctypes.POINTER(ACCENTPOLICY)),
            ("SizeOfData", DWORD)
        ]
except Exception:
    pass


class RecordingConfigDialog(QtWidgets.QDialog):
    def __init__(self, current_file_name: str, current_resolution: Tuple[int, int],
                 current_fps: int, current_quality: int,
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Recording Configuration")
        self.resize(300, 200)

        layout: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        file_label: QtWidgets.QLabel = QtWidgets.QLabel("File Name:")
        self.file_line_edit: QtWidgets.QLineEdit = QtWidgets.QLineEdit(
            current_file_name)
        layout.addWidget(file_label)
        layout.addWidget(self.file_line_edit)

        res_layout: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        width_label: QtWidgets.QLabel = QtWidgets.QLabel("Width:")
        self.width_spin: QtWidgets.QSpinBox = QtWidgets.QSpinBox()
        self.width_spin.setMinimum(100)
        self.width_spin.setMaximum(10000)
        self.width_spin.setValue(current_resolution[0])
        height_label: QtWidgets.QLabel = QtWidgets.QLabel("Height:")
        self.height_spin: QtWidgets.QSpinBox = QtWidgets.QSpinBox()
        self.height_spin.setMinimum(100)
        self.height_spin.setMaximum(10000)
        self.height_spin.setValue(current_resolution[1])
        res_layout.addWidget(width_label)
        res_layout.addWidget(self.width_spin)
        res_layout.addWidget(height_label)
        res_layout.addWidget(self.height_spin)
        layout.addLayout(res_layout)

        fps_layout: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        fps_label: QtWidgets.QLabel = QtWidgets.QLabel("Frame Rate (Hz):")
        self.fps_spin: QtWidgets.QSpinBox = QtWidgets.QSpinBox()
        self.fps_spin.setMinimum(1)
        self.fps_spin.setMaximum(240)
        self.fps_spin.setValue(current_fps)
        fps_layout.addWidget(fps_label)
        fps_layout.addWidget(self.fps_spin)
        layout.addLayout(fps_layout)

        quality_layout: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        quality_label: QtWidgets.QLabel = QtWidgets.QLabel("Quality:")
        self.quality_spin: QtWidgets.QSpinBox = QtWidgets.QSpinBox()
        self.quality_spin.setMinimum(1)
        self.quality_spin.setMaximum(100)
        self.quality_spin.setValue(current_quality)
        quality_layout.addWidget(quality_label)
        quality_layout.addWidget(self.quality_spin)
        layout.addLayout(quality_layout)

        self.button_box: QtWidgets.QDialogButtonBox = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def get_config(self) -> Tuple[str, Tuple[int, int], int, int]:
        file_name: str = self.file_line_edit.text()
        resolution: Tuple[int, int] = (
            self.width_spin.value(), self.height_spin.value())
        fps: int = self.fps_spin.value()
        quality: int = self.quality_spin.value()
        return file_name, resolution, fps, quality


class SpotifyWidget(QtWidgets.QWidget):
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.sp: Optional[spotipy.Spotify] = None
        self.current_track: Optional[Dict[str, Any]] = None
        self.config: Dict[str, Any] = self.load_config()
        self.initUI()
        self.setup_spotify()

    def load_config(self) -> Dict[str, Any]:
        config_path: str = os.path.join(os.path.dirname(
            __file__), '..', 'config', 'config.json')
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
            return {}

    def initUI(self) -> None:
        self.setStyleSheet("""
            background-color: rgba(40, 40, 40, 0.6);
            border-radius: 10px;
            padding: 15px;
        """)

        layout: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        self.album_art: QtWidgets.QLabel = QtWidgets.QLabel()
        self.album_art.autoFillBackground()
        self.album_art.setFixedWidth(105)
        self.album_art.setFixedHeight(105)
        self.album_art.setStyleSheet("""
            border-radius: 8px;
            border: 1px solid #333;
        """)
        layout.addWidget(self.album_art)

        info_layout: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        info_layout.setSpacing(1)

        self.track_label: QtWidgets.QLabel = QtWidgets.QLabel(
            "No track playing")
        self.track_label.setStyleSheet(
            "QLabel { color: white; font-size: 12px; font-weight: bold; }")
        self.artist_label: QtWidgets.QLabel = QtWidgets.QLabel("")
        self.artist_label.setStyleSheet(
            "QLabel { color: #aaaaaa; font-size: 12px; }")
        self.progress: QtWidgets.QProgressBar = QtWidgets.QProgressBar()
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

        control_layout: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        control_layout.setSpacing(8)

        self.play_btn: QtWidgets.QPushButton = QtWidgets.QPushButton()
        play_icon_path: str = os.path.join(
            os.path.dirname(__file__), "..", 'images', 'play.png')
        self.play_btn.setIcon(QtGui.QIcon(play_icon_path))
        self.play_btn.setIconSize(QtCore.QSize(24, 24))
        self.play_btn.setFixedSize(40, 40)
        self.play_btn.clicked.connect(self.toggle_playback)
        self.play_btn.setStyleSheet('''
            QPushButton { background-color: #1DB954; border-radius: 20px; border: none; }
            QPushButton:hover { background-color: #1ED760; }
            QPushButton:pressed { background-color: #1AA34A; }
        ''')

        self.next_btn: QtWidgets.QPushButton = QtWidgets.QPushButton()
        next_icon_path: str = os.path.join(os.path.dirname(
            __file__), "..", 'images', 'next-button.png')
        self.next_btn.setIcon(QtGui.QIcon(next_icon_path))
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

        self.status_label: QtWidgets.QLabel = QtWidgets.QLabel()
        self.status_label.setStyleSheet("color: #ff4444; font-size: 10px;")
        layout.addWidget(self.status_label)

        self.timer: QtCore.QTimer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_track_info)
        self.timer.start(1000)

    def setup_spotify(self) -> None:
        try:
            client_id: Optional[str] = self.config.get(
                'spotify', {}).get('client_id')
            client_secret: Optional[str] = self.config.get(
                'spotify', {}).get('client_secret')

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
            current: Optional[Dict[str, Any]] = self.sp.current_playback()
            if current and current.get('is_playing', False):
                self.current_track = current.get('item')
                if self.current_track:
                    track_name: str = self.current_track.get('name', '')[:30]
                    track_name += '...' if len(
                        self.current_track.get('name', '')) > 30 else ''
                    self.track_label.setText(track_name)
                    artist_names: str = ", ".join(
                        a.get('name', '') for a in self.current_track.get('artists', [])
                    )[:40]
                    self.artist_label.setText(artist_names + '...')

                    progress_ms: int = current.get('progress_ms', 0)
                    duration_ms: int = self.current_track.get('duration_ms', 0)
                    self.progress.setMaximum(duration_ms)
                    self.progress.setValue(progress_ms)

                    if self.current_track.get('album', {}).get('images'):
                        image_url: str = self.current_track['album']['images'][0]['url']
                        self.load_image_from_url(image_url)

                    pause_icon_path: str = os.path.join(
                        os.path.dirname(__file__), "..", 'images', 'pause.png')
                    self.play_btn.setIcon(QtGui.QIcon(pause_icon_path))
            else:
                play_icon_path: str = os.path.join(
                    os.path.dirname(__file__), "..", 'images', 'play.png')
                self.play_btn.setIcon(QtGui.QIcon(play_icon_path))
        except Exception as e:
            self.show_error(f"Update error: {str(e)}")

    def load_image_from_url(self, url: str) -> None:
        try:
            data: bytes = urlopen(url).read()
            image: QtGui.QImage = QtGui.QImage()
            image.loadFromData(data)
            pixmap: QtGui.QPixmap = QtGui.QPixmap.fromImage(image).scaled(
                75, 75,
                QtCore.Qt.KeepAspectRatioByExpanding,
                QtCore.Qt.SmoothTransformation
            )
            self.album_art.setPixmap(pixmap)
        except Exception as e:
            print("Error loading album art:", e)
            placeholder: str = "placeholder.png"
            self.album_art.setPixmap(
                QtGui.QPixmap(placeholder).scaled(100, 100))

    def toggle_playback(self) -> None:
        if not self.sp:
            self.show_error("Not connected to Spotify")
            return
        try:
            playback: Optional[Dict[str, Any]] = self.sp.current_playback()
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


class GameFpsMonitor(QtCore.QObject):
    """
    Wrap PresentMon to read true render FPS for a target process.
    Prints raw PresentMon lines if debug is enabled. Emits fps_updated(fps).
    """
    fps_updated = QtCore.pyqtSignal(float)
    error = QtCore.pyqtSignal(str)

    def __init__(self, presentmon_path: str, debug: bool = False,
                 parent: Optional[QtCore.QObject] = None):
        super().__init__(parent)
        self.presentmon_path = presentmon_path
        self.debug = debug
        self.proc: Optional[subprocess.Popen] = None
        self.reader_timer = QtCore.QTimer(self)
        self.reader_timer.timeout.connect(self._read_stdout)
        self.target_name: Optional[str] = None
        self.buffer = b""

    def start(self, process_name: Optional[str]) -> None:
        self.stop()
        self.target_name = process_name
        if not self.presentmon_path or not os.path.isfile(self.presentmon_path):
            self.error.emit("PresentMon not found")
            print("[FPS] PresentMon path not found; using capture-FPS fallback.")
            return

        # Prefer -simple if available; fallback flags still work for many builds.
        args = [self.presentmon_path, "-output_stdout", "-no_csv"]
        if process_name:
            args += ["-process_name", process_name]
        else:
            args += ["-captureall"]

        try:
            self.proc = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0
            )
            self.reader_timer.start(100)  # poll output
            print(
                f"[FPS] PresentMon started. Target={process_name or 'foreground'}")
        except Exception as e:
            self.error.emit(f"Failed to start PresentMon: {e}")
            print(f"[FPS] Failed to start PresentMon: {e}")

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
                text = line.decode(errors="ignore").strip()
                if self.debug:
                    print("[PresentMon]", text)
                self._parse_line(text)
        except Exception as e:
            if self.debug:
                print("[PresentMon] read error:", e)

    def _parse_line(self, line: str) -> None:
        """
        Heuristic parse: find a numeric field that looks like msBetweenPresents (0.5..1000 ms).
        Prefer lines that mention the target exe if we have one.
        """
        if not line or "," not in line:
            return

        # If a specific process is targeted, keep only lines that mention it (defensive).
        if self.target_name:
            if self.target_name.lower() not in line.lower():
                return
        else:
            # When capturing all, ignore lines from python/pythonw to avoid self-noise
            if "python.exe" in line.lower() or "pythonw.exe" in line.lower():
                return

        # Try to pick a reasonable msBetweenPresents value
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

        if ms_val is not None and ms_val > 0:
            fps = 1000.0 / ms_val
            print(f"[FPS] Game FPS: {fps:.1f}")
            self.fps_updated.emit(fps)


class FpsCounterWidget(QtWidgets.QLabel):
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
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        p = psutil.Process(pid)
        name = os.path.basename(p.exe())
        # Avoid picking ourselves when the overlay is focused
        if name.lower() in ("python.exe", "pythonw.exe"):
            return None
        return name
    except Exception:
        return None


class GameOverlay(QtWidgets.QWidget):
    SCREEN_INDEX: int = 2
    WINDOW_X: int = 0
    WINDOW_Y: int = 0
    WINDOW_WIDTH: int = 300
    WINDOW_HEIGHT: int = 200
    POSITION_ALIGMENT: str = "TOP_LEFT"

    def __init__(self) -> None:
        super().__init__()
        self.recording: bool = False
        self.config: Dict[str, Any] = self.load_config()

        fps_cfg = self.config.get("fps", {})
        self._presentmon_path = fps_cfg.get("presentmon_path", "")
        self._preferred_proc = fps_cfg.get("process_name", "").strip() or None
        self._pm_debug = bool(fps_cfg.get("debug", False))

        screen_size = pyautogui.size()
        self.record_resolution: Tuple[int, int] = (
            screen_size.width, screen_size.height)
        rec_config = self.config.get("recording", {})
        self.record_file_name = rec_config.get("file_name", "output.avi")
        self.record_resolution = tuple(rec_config.get(
            "resolution", (screen_size.width, screen_size.height)))
        self.record_fps = int(rec_config.get("fps", 30))
        self.record_quality = rec_config.get("quality", 95)

        # Capture-FPS fallback counters
        self._frame_counter: int = 0
        self._last_game_fps_ts = 0.0
        self._ema_fps: Optional[float] = None

        # Recording scheduler state
        self._record_start_t = 0.0
        self._record_frame_idx = 0

        # Fallback FPS print/update once per second
        self._fps_timer: QtCore.QTimer = QtCore.QTimer(self)
        self._fps_timer.timeout.connect(self._update_fps_label)
        self._fps_timer.start(1000)

        # PresentMon monitor (start after UI is ready)
        self._game_fps_monitor = GameFpsMonitor(
            self._presentmon_path, debug=self._pm_debug, parent=self)
        self._game_fps_monitor.fps_updated.connect(self._on_game_fps)
        self._game_fps_monitor.error.connect(self._on_game_fps_error)

        self._fg_refresh = QtCore.QTimer(self)
        self._fg_refresh.timeout.connect(self._ensure_presentmon_target)
        self._fg_refresh.start(2000)

        self.initUI()

        # Start PresentMon after UI exists (and give focus back to the game)
        QtCore.QTimer.singleShot(1200, self._ensure_presentmon_target)

    def load_config(self) -> Dict[str, Any]:
        config_path: str = os.path.join(os.path.dirname(
            __file__), '..', 'config', 'config.json')
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
            return {}

    def initUI(self) -> None:
        self.setWindowFlags(
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)

        screens: int = QtWidgets.QDesktopWidget().screenCount()
        for i in range(screens):
            geom: QtCore.QRect = QtWidgets.QDesktopWidget().screenGeometry(i)
            print(
                f"Screen {i}: {geom.x()}x{geom.y()} ({geom.width()}x{geom.height()})")

        if screens > self.SCREEN_INDEX and self.POSITION_ALIGMENT == "CENTER":
            sg: QtCore.QRect = QtWidgets.QDesktopWidget().screenGeometry(self.SCREEN_INDEX)
            x: int = sg.x() + (sg.width() - self.WINDOW_WIDTH) // 2
            y: int = sg.y() + (sg.height() - self.WINDOW_HEIGHT) // 2
            self.setGeometry(x, y, self.WINDOW_WIDTH, self.WINDOW_HEIGHT)
        elif screens > self.SCREEN_INDEX and self.POSITION_ALIGMENT == "TOP_LEFT":
            sg = QtWidgets.QDesktopWidget().screenGeometry(self.SCREEN_INDEX)
            x = sg.x() + self.WINDOW_X
            y = sg.y() + self.WINDOW_Y
            self.setGeometry(x, y, self.WINDOW_WIDTH, self.WINDOW_HEIGHT)
        elif screens > self.SCREEN_INDEX and self.POSITION_ALIGMENT == "TOP_RIGHT":
            sg = QtWidgets.QDesktopWidget().screenGeometry(self.SCREEN_INDEX)
            x = sg.x() + sg.width() - self.WINDOW_X - self.WINDOW_WIDTH
            y = sg.y() + self.WINDOW_Y
            self.setGeometry(x, y, self.WINDOW_WIDTH, self.WINDOW_HEIGHT)
        elif screens > self.SCREEN_INDEX and self.POSITION_ALIGMENT == "BOTTOM_LEFT":
            sg = QtWidgets.QDesktopWidget().screenGeometry(self.SCREEN_INDEX)
            x = sg.x() + self.WINDOW_X
            y = sg.y() + sg.height() - self.WINDOW_Y - self.WINDOW_HEIGHT
            self.setGeometry(x, y, self.WINDOW_WIDTH, self.WINDOW_HEIGHT)
        elif screens > self.SCREEN_INDEX and self.POSITION_ALIGMENT == "BOTTOM_RIGHT":
            sg = QtWidgets.QDesktopWidget().screenGeometry(self.SCREEN_INDEX)
            x = sg.x() + sg.width() - self.WINDOW_X - self.WINDOW_WIDTH
            y = sg.y() + sg.height() - self.WINDOW_Y - self.WINDOW_HEIGHT
            self.setGeometry(x, y, self.WINDOW_WIDTH, self.WINDOW_HEIGHT)
        else:
            self.setGeometry(100, 100, 300, 200)

        self.setAcrylicEffect()

        layout: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        self.timer_widget: GameTimerWidget = GameTimerWidget()
        layout.addWidget(self.timer_widget)

        self.spotify_widget: SpotifyWidget = SpotifyWidget()
        layout.addWidget(self.spotify_widget)

        self.fps_widget: FpsCounterWidget = FpsCounterWidget()
        layout.addWidget(self.fps_widget)

        record_layout: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        self.record_btn: QtWidgets.QPushButton = QtWidgets.QPushButton(
            "Start Recording")
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
        record_layout.addWidget(self.record_btn)

        self.record_config_btn: QtWidgets.QPushButton = QtWidgets.QPushButton(
            "Recording Config")
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
        record_layout.addWidget(self.record_config_btn)

        layout.addLayout(record_layout)

        self.shortcut: QtWidgets.QShortcut = QtWidgets.QShortcut(
            QtGui.QKeySequence("Ctrl+~"), self)
        self.shortcut.setContext(QtCore.Qt.ApplicationShortcut)
        self.shortcut.activated.connect(self.toggle_overlay)

    def setAcrylicEffect(self) -> None:
        try:
            hwnd: int = self.winId().__int__()
            accent: ACCENTPOLICY = ACCENTPOLICY()
            accent.AccentState = ACCENT_ENABLE_ACRYLICBLURBEHIND
            accent.GradientColor = 0xBF000000

            data: WINDOWCOMPOSITIONATTRIBDATA = WINDOWCOMPOSITIONATTRIBDATA()
            data.Attribute = 19
            data.pData = ctypes.pointer(accent)
            data.SizeOfData = ctypes.sizeof(accent)

            ctypes.windll.user32.SetWindowCompositionAttribute(
                hwnd, ctypes.pointer(data))
        except Exception as e:
            print("Acrylic effect not supported:", e)
            self.setStyleSheet("background: rgba(50, 50, 50, 0.75);")

    def _ensure_presentmon_target(self) -> None:
        if self._preferred_proc:
            target = self._preferred_proc
        else:
            target = get_foreground_process_name()
        self._game_fps_monitor.start(target)

    @QtCore.pyqtSlot(float)
    def _on_game_fps(self, fps: float) -> None:
        self._last_game_fps_ts = time.perf_counter()
        if self._ema_fps is None:
            self._ema_fps = fps
        else:
            self._ema_fps = 0.7 * self._ema_fps + 0.3 * fps
        if hasattr(self, "fps_widget"):
            self.fps_widget.set_fps_value(self._ema_fps)

    @QtCore.pyqtSlot(str)
    def _on_game_fps_error(self, msg: str) -> None:
        # PresentMon missing or failed; fallback will show capture FPS when recording
        print("[FPS] Error:", msg)
        if not self.recording and hasattr(self, "fps_widget"):
            self.fps_widget.set_fps_value(0.0)

    def _update_fps_label(self) -> None:
        """
        Fallback updater used once per second. If we didn't receive game FPS recently,
        print and show capture FPS (during recording) or 0 (idle).
        """
        now = time.perf_counter()
        using_fallback = (now - self._last_game_fps_ts) > 1.5
        if using_fallback:
            fps_now = float(self._frame_counter) if self.recording else 0.0
            print(f"[FPS] Capture FPS: {fps_now:.1f}")
            if hasattr(self, "fps_widget"):
                self.fps_widget.set_fps_value(fps_now)
        self._frame_counter = 0

    def open_record_config(self) -> None:
        dialog: RecordingConfigDialog = RecordingConfigDialog(
            self.record_file_name, self.record_resolution, self.record_fps, self.record_quality, self
        )
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            (self.record_file_name, self.record_resolution,
             self.record_fps, self.record_quality) = dialog.get_config()
            print(f"[REC] Updated: {self.record_file_name}, {self.record_resolution}, "
                  f"{self.record_fps} Hz, Quality {self.record_quality}")

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
        self.recording = not self.recording
        self.record_btn.setText(
            "Stop Recording" if self.recording else "Start Recording")
        if self.recording:
            self.start_recording()
        else:
            self.stop_recording()

    # ---- Time-synchronized recording scheduler ----
    def start_recording(self) -> None:
        self.fourcc: int = cv2.VideoWriter_fourcc(*'XVID')
        self.out: cv2.VideoWriter = cv2.VideoWriter(
            self.record_file_name, self.fourcc, float(
                self.record_fps), self.record_resolution
        )
        if not self.out or not self.out.isOpened():
            QtWidgets.QMessageBox.critical(self, "Recording Error",
                                           "Failed to open video writer. Check file path/codec.")
            return

        self._record_start_t = time.perf_counter()
        self._record_frame_idx = 0
        self._frame_counter = 0
        print(
            f"[REC] Started @ {self.record_fps} FPS, res={self.record_resolution}, file={self.record_file_name}")
        self._record_tick()  # kick off the scheduler

    def stop_recording(self) -> None:
        if hasattr(self, 'out'):
            try:
                self.out.release()
            except Exception:
                pass
        if time.perf_counter() - self._last_game_fps_ts > 1.5 and hasattr(self, "fps_widget"):
            self.fps_widget.set_fps_value(0.0)
        print("[REC] Stopped.")
        self._frame_counter = 0

    def _record_tick(self) -> None:
        """
        Schedules captures to hit target FPS based on wall-clock, avoiding fast playback.
        """
        if not self.recording:
            return

        period = 1.0 / max(1, int(self.record_fps))
        now = time.perf_counter()
        next_frame_time = self._record_start_t + \
            (self._record_frame_idx + 1) * period
        due_time_for_this_frame = self._record_start_t + self._record_frame_idx * period

        # If we're due (or late) for the current frame, capture it.
        if now >= due_time_for_this_frame:
            try:
                img = pyautogui.screenshot()
                frame: np.ndarray = np.array(img)
                frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                if hasattr(self, 'out') and self.out:
                    self.out.write(frame)
                self._frame_counter += 1
                self._record_frame_idx += 1
            except Exception as e:
                print("[REC] Capture error:", e)

        # Compute delay to next frame boundary
        delay_s = max(0.0, next_frame_time - time.perf_counter())
        delay_ms = int(delay_s * 1000)
        QtCore.QTimer.singleShot(max(1, delay_ms), self._record_tick)

    # ----------------------------------------------

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        self.old_pos = event.globalPos()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        delta: QtCore.QPoint = event.globalPos() - self.old_pos
        self.move(self.x() + delta.x(), self.y() + delta.y())
        self.old_pos = event.globalPos()


class GameTimerWidget(QtWidgets.QWidget):
    """
    Widget for displaying and controlling a game timer.
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.elapsed_time: int = 0
        self.is_running: bool = False
        self.initUI()

    def initUI(self) -> None:
        self.setStyleSheet("""
            background-color: rgba(40, 40, 40, 0.6);
            border-radius: 10px;
            padding: 15px;
        """)
        layout: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        self.time_label: QtWidgets.QLabel = QtWidgets.QLabel("00:00:00")
        self.time_label.setAlignment(QtCore.Qt.AlignCenter)
        self.time_label.setStyleSheet("""
            QLabel { color: white; font-size: 24px; font-weight: bold; margin-bottom: 10px; }
        """)
        layout.addWidget(self.time_label)

        button_layout: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        self.start_button: QtWidgets.QPushButton = QtWidgets.QPushButton(
            "Start")
        self.start_button.setStyleSheet('''
            QPushButton { background-color: #1DB954; border-radius: 5px; color: white; padding: 5px 10px; }
            QPushButton:hover { background-color: #1ED760; }
        ''')
        self.start_button.clicked.connect(self.start_timer)

        self.pause_button: QtWidgets.QPushButton = QtWidgets.QPushButton(
            "Pause")
        self.pause_button.setStyleSheet('''
            QPushButton { background-color: #FFC107; border-radius: 5px; color: white; padding: 5px 10px; }
            QPushButton:hover { background-color: #FFCA28; }
        ''')
        self.pause_button.clicked.connect(self.pause_timer)

        self.stop_button: QtWidgets.QPushButton = QtWidgets.QPushButton("Stop")
        self.stop_button.setStyleSheet('''
            QPushButton { background-color: #DC3545; border-radius: 5px; color: white; padding: 5px 10px; }
            QPushButton:hover { background-color: #E53935; }
        ''')
        self.stop_button.clicked.connect(self.stop_timer)

        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.pause_button)
        button_layout.addWidget(self.stop_button)
        layout.addLayout(button_layout)

        self.timer: QtCore.QTimer = QtCore.QTimer(self)
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
        hours: int = self.elapsed_time // 3600
        minutes: int = (self.elapsed_time % 3600) // 60
        seconds: int = self.elapsed_time % 60
        self.time_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")


if __name__ == "__main__":
    app: QtWidgets.QApplication = QtWidgets.QApplication(sys.argv)
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling)
    overlay: GameOverlay = GameOverlay()
    overlay.show()
    sys.exit(app.exec_())
