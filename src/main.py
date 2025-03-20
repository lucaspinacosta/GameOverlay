import sys
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
    from ctypes.wintypes import DWORD
    ACCENT_ENABLE_ACRYLICBLURBEHIND = 4

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
except:
    pass


class SpotifyWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sp = None
        self.current_track = None
        self.config = self.load_config()
        self.initUI()
        self.setup_spotify()

    def load_config(self):
        config_path = os.path.join(os.path.dirname(
            __file__), '..', 'config', 'config.json')
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
            return {}

    def initUI(self):
        self.setStyleSheet("""
            background-color: rgba(40, 40, 40, 0.6);
            border-radius: 10px;
            padding: 15px;
        """)

        layout = QtWidgets.QHBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(15)

        # Album Art
        self.album_art = QtWidgets.QLabel()
        self.album_art.setFixedSize(100, 100)
        self.album_art.setStyleSheet("border-radius: 5px;")
        layout.addWidget(self.album_art)

        # Track Info
        info_layout = QtWidgets.QVBoxLayout()
        info_layout.setSpacing(1)

        self.track_label = QtWidgets.QLabel("No track playing")
        self.track_label.setStyleSheet("""
            QLabel {
                color: white;
                font-size: 12px;
                font-weight: bold;
                max-height: 13px;
                max-width: 300px;
            }
        """)

        self.artist_label = QtWidgets.QLabel("")
        self.artist_label.setStyleSheet("""
            QLabel {
                color: #aaaaaa;
                font-size: 12px;
                max-height: 10px;
                max-width: 300px;
            }
        """)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setFixedHeight(4)
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

        # Controls
        control_layout = QtWidgets.QVBoxLayout()
        control_layout.setSpacing(8)

        # Play/Pause Button
        self.play_btn = QtWidgets.QPushButton()
        self.play_btn.setIcon(QtGui.QIcon(os.path.join(
            os.path.dirname(__file__), "..", 'images', 'play.png')))
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

        # Next Track Button
        self.next_btn = QtWidgets.QPushButton()
        self.next_btn.setIcon(QtGui.QIcon(os.path.join(
            os.path.dirname(__file__), "..", 'images', 'next-button.png')))
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

        # Status Label
        self.status_label = QtWidgets.QLabel()
        self.status_label.setStyleSheet("color: #ff4444; font-size: 10px;")
        layout.addWidget(self.status_label)

        # Update timer
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update_track_info)
        self.timer.start(1000)

    def setup_spotify(self):
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
                cache_path='.spotifycache'))

            # Force authentication if needed
            if not self.sp.current_user():
                self.sp.auth_manager.get_access_token(as_dict=False)

        except Exception as e:
            self.show_error(f"Spotify auth failed: {str(e)}")

    def update_track_info(self):
        if not self.sp:
            return

        try:
            current = self.sp.current_playback()
            if current and current['is_playing']:
                self.current_track = current['item']
                self.track_label.setText(
                    self.current_track['name'][:30] + ('...' if len(self.current_track['name']) > 30 else ''))
                self.artist_label.setText(", ".join(
                    [artist['name'] for artist in self.current_track['artists']])[:40] + '...')

                # Update progress
                progress = current['progress_ms']
                duration = self.current_track['duration_ms']
                self.progress.setMaximum(duration)
                self.progress.setValue(progress)

                # Load album art
                if self.current_track['album']['images']:
                    image_url = self.current_track['album']['images'][0]['url']
                    self.load_image_from_url(image_url)

                self.play_btn.setIcon(QtGui.QIcon(os.path.join(
                    os.path.dirname(__file__), "..", 'images', 'pause.png')))
            else:
                self.play_btn.setIcon(QtGui.QIcon(os.path.join(
                    os.path.dirname(__file__), "..", 'images', 'play.png')))

        except Exception as e:
            self.show_error(f"Update error: {str(e)}")

    def load_image_from_url(self, url):
        try:
            data = urlopen(url).read()
            image = QtGui.QImage()
            image.loadFromData(data)
            pixmap = QtGui.QPixmap.fromImage(image).scaled(
                100, 100,
                QtCore.Qt.KeepAspectRatioByExpanding,
                QtCore.Qt.SmoothTransformation
            )
            self.album_art.setPixmap(pixmap)
        except Exception as e:
            print("Error loading album art:", e)
            self.album_art.setPixmap(QtGui.QPixmap(
                "placeholder.png").scaled(100, 100))

    def toggle_playback(self):
        if not self.sp:
            self.show_error("Not connected to Spotify")
            return

        try:
            playback = self.sp.current_playback()
            if not playback:
                self.show_error("No active device")
                return

            if playback['is_playing']:
                self.sp.pause_playback()
            else:
                self.sp.start_playback()

            QtCore.QTimer.singleShot(500, self.update_track_info)
        except Exception as e:
            self.show_error(f"Playback error: {str(e)}")

    def next_track(self):
        if not self.sp:
            self.show_error("Not connected to Spotify")
            return

        try:
            self.sp.next_track()
            QtCore.QTimer.singleShot(500, self.update_track_info)
        except Exception as e:
            self.show_error(f"Skip error: {str(e)}")

    def show_error(self, message):
        self.status_label.setText(message)
        QtCore.QTimer.singleShot(3000, lambda: self.status_label.setText(""))


class GameOverlay(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()
        self.recording = False

    def initUI(self):
        self.setWindowFlags(
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setGeometry(100, 100, 300, 200)

        # Acrylic effect
        self.setAcrylicEffect()

        layout = QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        # Spotify Widget
        self.spotify_widget = SpotifyWidget()
        layout.addWidget(self.spotify_widget)

        # Recording Button
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
        layout.addWidget(self.record_btn)

        # Toggle Shortcut
        self.shortcut = QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+~"), self)
        self.shortcut.setContext(QtCore.Qt.ApplicationShortcut)
        self.shortcut.activated.connect(self.toggle_overlay)

    def setAcrylicEffect(self):
        try:
            hwnd = self.winId().__int__()
            accent = ACCENTPOLICY()
            accent.AccentState = ACCENT_ENABLE_ACRYLICBLURBEHIND
            accent.GradientColor = 0xBF000000  # 75% opacity

            data = WINDOWCOMPOSITIONATTRIBDATA()
            data.Attribute = 20  # Correct attribute value
            data.pData = ctypes.pointer(accent)
            data.SizeOfData = ctypes.sizeof(accent)

            ctypes.windll.user32.SetWindowCompositionAttribute(
                hwnd, ctypes.pointer(data))
        except Exception as e:
            print("Acrylic effect not supported:", e)
            self.setStyleSheet("background: rgba(50, 50, 50, 0.75);")

    def toggle_overlay(self):
        if self.isVisible():
            self.hide()
        else:
            # Re-apply window flags when showing
            self.setWindowFlags(
                QtCore.Qt.WindowStaysOnTopHint |
                QtCore.Qt.FramelessWindowHint |
                QtCore.Qt.Tool
            )
            self.show()
            self.activateWindow()  # Bring to front

    def toggle_recording(self):
        self.recording = not self.recording
        self.record_btn.setText(
            "Stop Recording" if self.recording else "Start Recording")
        if self.recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        self.fourcc = cv2.VideoWriter_fourcc(*'XVID')
        self.out = cv2.VideoWriter(
            'output.avi', self.fourcc, 20.0, pyautogui.size())
        self.record_frame()

    def stop_recording(self):
        if hasattr(self, 'out'):
            self.out.release()

    def record_frame(self):
        if self.recording:
            img = pyautogui.screenshot()
            frame = np.array(img)
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            self.out.write(frame)
            QtCore.QTimer.singleShot(50, self.record_frame)

    def mousePressEvent(self, event):
        self.old_pos = event.globalPos()

    def mouseMoveEvent(self, event):
        delta = QtCore.QPoint(event.globalPos() - self.old_pos)
        self.move(self.x() + delta.x(), self.y() + delta.y())
        self.old_pos = event.globalPos()


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling)
    overlay = GameOverlay()
    overlay.show()
    sys.exit(app.exec_())
