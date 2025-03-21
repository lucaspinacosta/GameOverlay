"""
Refactored script with extended recording configuration.
You can now set the file name, resolution, frame rate (Hz) and quality via a popup dialog.
Note: The "quality" setting is stored but not directly applied in OpenCV's VideoWriter.
"""

import sys
from typing import Optional, Dict, Any, Tuple
from PyQt5 import QtWidgets, QtCore, QtGui
from PyQt5.QtWebEngineWidgets import QWebEngineView
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

# For acrylic effect (Windows only)
try:
    from ctypes.wintypes import DWORD  # type: ignore
    ACCENT_ENABLE_ACRYLICBLURBEHIND: int = 4

    class ACCENTPOLICY(ctypes.Structure):
        """
        Structure for defining the accent policy used for the acrylic blur effect.
        """
        _fields_ = [
            ("AccentState", DWORD),
            ("AccentFlags", DWORD),
            ("GradientColor", DWORD),
            ("AnimationId", DWORD)
        ]

    class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
        """
        Structure for window composition attribute data used when applying effects.
        """
        _fields_ = [
            ("Attribute", DWORD),
            ("pData", ctypes.POINTER(ACCENTPOLICY)),
            ("SizeOfData", DWORD)
        ]
except Exception as e:
    # If not on Windows or necessary libraries are missing, skip acrylic effect definitions.
    pass


class RecordingConfigDialog(QtWidgets.QDialog):
    """
    Dialog to configure recording settings: file name, resolution, frame rate, and quality.
    """

    def __init__(self, current_file_name: str, current_resolution: Tuple[int, int],
                 current_fps: int, current_quality: int,
                 parent: Optional[QtWidgets.QWidget] = None) -> None:
        """
        Initialize the recording configuration dialog.

        Args:
            current_file_name (str): The current recording file name.
            current_resolution (Tuple[int, int]): The current recording resolution (width, height).
            current_fps (int): The current frame rate.
            current_quality (int): The current quality setting.
            parent (Optional[QtWidgets.QWidget]): Parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("Recording Configuration")
        self.resize(300, 200)

        layout: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        # File name input
        file_label: QtWidgets.QLabel = QtWidgets.QLabel("File Name:")
        self.file_line_edit: QtWidgets.QLineEdit = QtWidgets.QLineEdit(
            current_file_name)
        layout.addWidget(file_label)
        layout.addWidget(self.file_line_edit)

        # Resolution inputs (width and height)
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

        # Frame Rate input
        fps_layout: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        fps_label: QtWidgets.QLabel = QtWidgets.QLabel("Frame Rate (Hz):")
        self.fps_spin: QtWidgets.QSpinBox = QtWidgets.QSpinBox()
        self.fps_spin.setMinimum(1)
        self.fps_spin.setMaximum(120)
        self.fps_spin.setValue(current_fps)
        fps_layout.addWidget(fps_label)
        fps_layout.addWidget(self.fps_spin)
        layout.addLayout(fps_layout)

        # Quality input
        quality_layout: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        quality_label: QtWidgets.QLabel = QtWidgets.QLabel("Quality:")
        self.quality_spin: QtWidgets.QSpinBox = QtWidgets.QSpinBox()
        self.quality_spin.setMinimum(1)
        self.quality_spin.setMaximum(100)
        self.quality_spin.setValue(current_quality)
        quality_layout.addWidget(quality_label)
        quality_layout.addWidget(self.quality_spin)
        layout.addLayout(quality_layout)

        # Dialog buttons (OK and Cancel)
        self.button_box: QtWidgets.QDialogButtonBox = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def get_config(self) -> Tuple[str, Tuple[int, int], int, int]:
        """
        Return the configured file name, resolution, frame rate, and quality.

        Returns:
            Tuple[str, Tuple[int, int], int, int]: The file name, resolution, frame rate, and quality.
        """
        file_name: str = self.file_line_edit.text()
        resolution: Tuple[int, int] = (
            self.width_spin.value(), self.height_spin.value())
        fps: int = self.fps_spin.value()
        quality: int = self.quality_spin.value()
        return file_name, resolution, fps, quality


class SpotifyWidget(QtWidgets.QWidget):
    """
    Widget to display Spotify track information and control playback.
    """

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        self.sp: Optional[spotipy.Spotify] = None  # Spotify client instance
        # Currently playing track info
        self.current_track: Optional[Dict[str, Any]] = None
        # Load configuration data
        self.config: Dict[str, Any] = self.load_config()
        self.initUI()  # Set up UI components
        self.setup_spotify()  # Initialize Spotify connection

    def load_config(self) -> Dict[str, Any]:
        """
        Load configuration from a JSON file.

        Returns:
            dict: Configuration dictionary.
        """
        config_path: str = os.path.join(os.path.dirname(
            __file__), '..', 'config', 'config.json')
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
            return {}

    def initUI(self) -> None:
        """
        Initialize the user interface for the Spotify widget.
        """
        self.setStyleSheet("""
            background-color: rgba(40, 40, 40, 0.6);
            border-radius: 10px;
            padding: 15px;
        """)

        layout: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        # Album Art setup
        self.album_art: QtWidgets.QLabel = QtWidgets.QLabel()
        self.album_art.autoFillBackground()
        self.album_art.setFixedWidth(105)
        self.album_art.setFixedHeight(105)
        self.album_art.setStyleSheet("""
            border-radius: 8px;
            border: 1px solid #333;
        """)
        layout.addWidget(self.album_art)

        # Track info layout
        info_layout: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        info_layout.setSpacing(1)

        self.track_label: QtWidgets.QLabel = QtWidgets.QLabel(
            "No track playing")
        self.track_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 12px;
                font-weight: bold;
                max-height: 13px;
                max-width: 300px;
            }
        """)
        self.artist_label: QtWidgets.QLabel = QtWidgets.QLabel("")
        self.artist_label.setStyleSheet("""
            QLabel {
                color: #aaaaaa;
                font-size: 12px;
                max-height: 10px;
                max-width: 300px;
            }
        """)
        self.progress: QtWidgets.QProgressBar = QtWidgets.QProgressBar()
        self.progress.setFixedHeight(5)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet("""
            QProgressBar {
                background: rgba(255, 255, 255, 0.2);
                border-radius: 2px;
            }
            QProgressBar::chunk {
                background: #1DB954;
                border-radius: 2px;
            }
        """)

        info_layout.addWidget(self.track_label)
        info_layout.addWidget(self.artist_label)
        info_layout.addWidget(self.progress)
        layout.addLayout(info_layout)

        # Control buttons layout
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
            QPushButton {
                background-color: #1DB954;
                border-radius: 20px;
                border: none;
            }
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
            QPushButton {
                background-color: rgba(255, 255, 255, 0.1);
                border-radius: 20px;
                border: none;
            }
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
        """
        Setup the Spotify connection using SpotifyOAuth.
        """
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
        """
        Update the current track information by querying Spotify.
        """
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
                        artist.get('name', '') for artist in self.current_track.get('artists', [])
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
        """
        Load an image from the given URL and display it in the album art label.

        Args:
            url (str): URL of the image.
        """
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
        """
        Toggle playback between playing and paused states.
        """
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
        """
        Skip to the next track.
        """
        if not self.sp:
            self.show_error("Not connected to Spotify")
            return

        try:
            self.sp.next_track()
            QtCore.QTimer.singleShot(500, self.update_track_info)
        except Exception as e:
            self.show_error(f"Skip error: {str(e)}")

    def show_error(self, message: str) -> None:
        """
        Display an error message on the status label for a brief period.

        Args:
            message (str): The error message to display.
        """
        self.status_label.setText(message)
        QtCore.QTimer.singleShot(3000, lambda: self.status_label.setText(""))


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
        """
        Set up the UI elements for the timer widget.
        """
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
            QLabel {
                color: white;
                font-size: 24px;
                font-weight: bold;
                margin-bottom: 10px;
            }
        """)
        layout.addWidget(self.time_label)

        button_layout: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        self.start_button: QtWidgets.QPushButton = QtWidgets.QPushButton(
            "Start")
        self.start_button.setStyleSheet('''
            QPushButton {
                background-color: #1DB954;
                border-radius: 5px;
                color: white;
                padding: 5px 10px;
            }
            QPushButton:hover { background-color: #1ED760; }
        ''')
        self.start_button.clicked.connect(self.start_timer)

        self.pause_button: QtWidgets.QPushButton = QtWidgets.QPushButton(
            "Pause")
        self.pause_button.setStyleSheet('''
            QPushButton {
                background-color: #FFC107;
                border-radius: 5px;
                color: white;
                padding: 5px 10px;
            }
            QPushButton:hover { background-color: #FFCA28; }
        ''')
        self.pause_button.clicked.connect(self.pause_timer)

        self.stop_button: QtWidgets.QPushButton = QtWidgets.QPushButton("Stop")
        self.stop_button.setStyleSheet('''
            QPushButton {
                background-color: #DC3545;
                border-radius: 5px;
                color: white;
                padding: 5px 10px;
            }
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
        """
        Start the timer if it is not already running.
        """
        if not self.is_running:
            self.timer.start(1000)
            self.is_running = True

    def pause_timer(self) -> None:
        """
        Pause the timer if it is running.
        """
        if self.is_running:
            self.timer.stop()
            self.is_running = False

    def stop_timer(self) -> None:
        """
        Stop the timer and reset the elapsed time.
        """
        self.timer.stop()
        self.elapsed_time = 0
        self.is_running = False
        self.update_display()

    def update_timer(self) -> None:
        """
        Increment the elapsed time and update the display.
        """
        self.elapsed_time += 1
        self.update_display()

    def update_display(self) -> None:
        """
        Update the timer display label with the formatted elapsed time.
        """
        hours: int = self.elapsed_time // 3600
        minutes: int = (self.elapsed_time % 3600) // 60
        seconds: int = self.elapsed_time % 60
        self.time_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")


class GameOverlay(QtWidgets.QWidget):
    """
    Main overlay widget that combines the game timer, Spotify widget, and recording controls.
    """
    SCREEN_INDEX: int = 2
    WINDOW_X: int = 0
    WINDOW_Y: int = 0
    WINDOW_WIDTH: int = 300
    WINDOW_HEIGHT: int = 200
    POSITION_ALIGMENT: str = "TOP_LEFT"

    def __init__(self) -> None:
        super().__init__()
        self.recording: bool = False
        # Default recording configuration
        self.record_file_name: str = "output.avi"
        screen_size = pyautogui.size()
        self.record_resolution: Tuple[int, int] = (
            screen_size.width, screen_size.height)
        self.record_fps: int = 20  # Frame rate (Hz)
        self.record_quality: int = 95  # Quality (stored, not directly applied)
        self.initUI()

    def initUI(self) -> None:
        """
        Set up the UI components for the overlay.
        """
        self.setWindowFlags(
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)

        # Debugging: print available screens
        screens: int = QtWidgets.QDesktopWidget().screenCount()
        for i in range(screens):
            geom: QtCore.QRect = QtWidgets.QDesktopWidget().screenGeometry(i)
            print(
                f"Screen {i}: {geom.x()}x{geom.y()} ({geom.width()}x{geom.height()})")

        if screens > self.SCREEN_INDEX and self.POSITION_ALIGMENT == "CENTER":
            screen_geometry: QtCore.QRect = QtWidgets.QDesktopWidget(
            ).screenGeometry(self.SCREEN_INDEX)
            x: int = screen_geometry.x() + (screen_geometry.width() - self.WINDOW_WIDTH) // 2
            y: int = screen_geometry.y() + (screen_geometry.height() - self.WINDOW_HEIGHT) // 2
            self.setGeometry(x, y, self.WINDOW_WIDTH, self.WINDOW_HEIGHT)
        elif screens > self.SCREEN_INDEX and self.POSITION_ALIGMENT == "TOP_LEFT":
            screen_geometry = QtWidgets.QDesktopWidget().screenGeometry(self.SCREEN_INDEX)
            x = screen_geometry.x() + self.WINDOW_X
            y = screen_geometry.y() + self.WINDOW_Y
            self.setGeometry(x, y, self.WINDOW_WIDTH, self.WINDOW_HEIGHT)
        elif screens > self.SCREEN_INDEX and self.POSITION_ALIGMENT == "TOP_RIGHT":
            screen_geometry = QtWidgets.QDesktopWidget().screenGeometry(self.SCREEN_INDEX)
            x = screen_geometry.x() + screen_geometry.width() - \
                self.WINDOW_X - self.WINDOW_WIDTH
            y = screen_geometry.y() + self.WINDOW_Y
            self.setGeometry(x, y, self.WINDOW_WIDTH, self.WINDOW_HEIGHT)
        elif screens > self.SCREEN_INDEX and self.POSITION_ALIGMENT == "BOTTOM_LEFT":
            screen_geometry = QtWidgets.QDesktopWidget().screenGeometry(self.SCREEN_INDEX)
            x = screen_geometry.x() + self.WINDOW_X
            y = screen_geometry.y() + screen_geometry.height() - \
                self.WINDOW_Y - self.WINDOW_HEIGHT
            self.setGeometry(x, y, self.WINDOW_WIDTH, self.WINDOW_HEIGHT)
        elif screens > self.SCREEN_INDEX and self.POSITION_ALIGMENT == "BOTTOM_RIGHT":
            screen_geometry = QtWidgets.QDesktopWidget().screenGeometry(self.SCREEN_INDEX)
            x = screen_geometry.x() + screen_geometry.width() - \
                self.WINDOW_X - self.WINDOW_WIDTH
            y = screen_geometry.y() + screen_geometry.height() - \
                self.WINDOW_Y - self.WINDOW_HEIGHT
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

        # Layout for recording controls
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
        """
        Apply the acrylic blur effect on Windows if supported.
        """
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

    def open_record_config(self) -> None:
        """
        Open the recording configuration dialog to set file name, resolution, frame rate, and quality.
        """
        dialog: RecordingConfigDialog = RecordingConfigDialog(
            self.record_file_name, self.record_resolution, self.record_fps, self.record_quality, self
        )
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            (self.record_file_name, self.record_resolution,
             self.record_fps, self.record_quality) = dialog.get_config()
            print(f"Recording configuration updated: {self.record_file_name}, {self.record_resolution}, "
                  f"{self.record_fps} Hz, Quality: {self.record_quality}")

    def toggle_overlay(self) -> None:
        """
        Toggle the overlay's visibility.
        """
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
        """
        Toggle the recording state and update the recording button text.
        """
        self.recording = not self.recording
        self.record_btn.setText(
            "Stop Recording" if self.recording else "Start Recording")
        if self.recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self) -> None:
        """
        Start screen recording using OpenCV and pyautogui with the configured parameters.
        """
        self.fourcc: int = cv2.VideoWriter_fourcc(*'XVID')
        self.out: cv2.VideoWriter = cv2.VideoWriter(self.record_file_name, self.fourcc,
                                                    self.record_fps, self.record_resolution)
        print(
            f"Recording started at {self.record_fps} Hz with quality {self.record_quality}")
        self.record_frame()

    def stop_recording(self) -> None:
        """
        Stop screen recording and release the video writer.
        """
        if hasattr(self, 'out'):
            self.out.release()

    def record_frame(self) -> None:
        """
        Capture the current screen frame and write it to the video file.
        """
        if self.recording:
            img = pyautogui.screenshot()
            frame: np.ndarray = np.array(img)
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            self.out.write(frame)
            QtCore.QTimer.singleShot(50, self.record_frame)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        """
        Capture the initial mouse position when pressed for moving the overlay.

        Args:
            event (QtGui.QMouseEvent): The mouse press event.
        """
        self.old_pos = event.globalPos()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        """
        Handle mouse movement to allow the overlay to be dragged.

        Args:
            event (QtGui.QMouseEvent): The mouse move event.
        """
        delta: QtCore.QPoint = event.globalPos() - self.old_pos
        self.move(self.x() + delta.x(), self.y() + delta.y())
        self.old_pos = event.globalPos()


if __name__ == "__main__":
    """
    Main entry point for the application.
    """
    app: QtWidgets.QApplication = QtWidgets.QApplication(sys.argv)
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling)
    overlay: GameOverlay = GameOverlay()
    overlay.show()
    sys.exit(app.exec_())
