import sys
from PyQt5 import QtWidgets, QtCore, QtGui
import cv2
import pyautogui
import numpy as np
import spotipy
from spotipy.oauth2 import SpotifyOAuth
import json
import os
from urllib.request import urlopen

# Spotify Widget Class


class SpotifyWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sp = None
        self.current_track = None
        self.config = self.load_config()
        self.initUI()
        self.setup_spotify()

    def load_config(self):
        config_path = os.path.join(os.path.expanduser(
            "~"), ".config", "game_overlay", "config.json")
        try:
            with open(config_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
            return {}

    def initUI(self):
        self.setStyleSheet("""
            background-color: rgba(40, 40, 40, 0.8);
            border-radius: 10px;
            padding: 15px;
        """)

        layout = QtWidgets.QHBoxLayout()
        self.setLayout(layout)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        # Album Art
        self.album_art = QtWidgets.QLabel()
        self.album_art.setFixedSize(90, 90)
        self.album_art.setStyleSheet(
            "border-radius: 8px; border: 1px solid #333;")
        layout.addWidget(self.album_art)

        # Track Info
        info_layout = QtWidgets.QVBoxLayout()
        info_layout.setSpacing(1)

        self.track_label = QtWidgets.QLabel("No track playing")
        self.track_label.setStyleSheet("""
            QLabel { color: white; font-size: 12px; font-weight: bold; max-width: 200px; }
        """)

        self.artist_label = QtWidgets.QLabel("")
        self.artist_label.setStyleSheet("""
            QLabel { color: #aaaaaa; font-size: 12px; max-width: 200px; }
        """)

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

        # Controls
        control_layout = QtWidgets.QVBoxLayout()
        control_layout.setSpacing(8)

        # Play/Pause Button
        self.play_btn = QtWidgets.QPushButton()
        self.play_btn.setIcon(QtGui.QIcon.fromTheme("media-playback-start"))
        self.play_btn.setIconSize(QtCore.QSize(24, 24))
        self.play_btn.setFixedSize(40, 40)
        self.play_btn.clicked.connect(self.toggle_playback)
        self.play_btn.setStyleSheet('''
            QPushButton { background-color: #1DB954; border-radius: 20px; border: none; }
            QPushButton:hover { background-color: #1ED760; }
            QPushButton:pressed { background-color: #1AA34A; }
        ''')

        # Next Track Button
        self.next_btn = QtWidgets.QPushButton()
        self.next_btn.setIcon(QtGui.QIcon.fromTheme("media-skip-forward"))
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
                redirect_uri='http://localhost:8080/callback',
                scope='user-read-playback-state,user-modify-playback-state,user-read-currently-playing',
                cache_path=os.path.join(os.path.expanduser("~"), ".config", "game_overlay", ".spotifycache")))

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
                track_name = self.current_track['name'][:30] + \
                    ('...' if len(self.current_track['name']) > 30 else '')
                artist_names = ", ".join([artist['name'] for artist in self.current_track['artists']])[:40] + '...'

                self.track_label.setText(track_name)
                self.artist_label.setText(artist_names)

                # Update progress
                progress=current['progress_ms']
                duration=self.current_track['duration_ms']
                self.progress.setMaximum(duration)
                self.progress.setValue(progress)

                # Load album art
                if self.current_track['album']['images']:
                    image_url=self.current_track['album']['images'][0]['url']
                    self.load_image_from_url(image_url)

                self.play_btn.setIcon(
                    QtGui.QIcon.fromTheme("media-playback-pause"))
            else:
                self.play_btn.setIcon(
                    QtGui.QIcon.fromTheme("media-playback-start"))

        except Exception as e:
            self.show_error(f"Update error: {str(e)}")

    def load_image_from_url(self, url):
        try:
            data=urlopen(url).read()
            image=QtGui.QImage()
            image.loadFromData(data)
            pixmap=QtGui.QPixmap.fromImage(image).scaled(
                90, 90,
                QtCore.Qt.KeepAspectRatioByExpanding,
                QtCore.Qt.SmoothTransformation
            )
            self.album_art.setPixmap(pixmap)
        except Exception as e:
            print("Error loading album art:", e)
            self.album_art.setPixmap(QtGui.QPixmap())

    def toggle_playback(self):
        if not self.sp:
            self.show_error("Not connected to Spotify")
            return

        try:
            playback=self.sp.current_playback()
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

# Game Timer Widget Class
class GameTimerWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.elapsed_time=0
        self.is_running=False
        self.initUI()

    def initUI(self):
        self.setStyleSheet("""
            background-color: rgba(40, 40, 40, 0.8);
            border-radius: 10px;
            padding: 15px;
        """)

        layout=QtWidgets.QVBoxLayout()
        self.setLayout(layout)

        # Time Display
        self.time_label=QtWidgets.QLabel("00:00:00")
        self.time_label.setAlignment(QtCore.Qt.AlignCenter)
        self.time_label.setStyleSheet("""
            QLabel { color: white; font-size: 24px; font-weight: bold; margin-bottom: 10px; }
        """)
        layout.addWidget(self.time_label)

        # Control Buttons
        button_layout=QtWidgets.QHBoxLayout()

        self.start_button=QtWidgets.QPushButton("Start")
        self.start_button.setIcon(
            QtGui.QIcon.fromTheme("media-playback-start"))
        self.start_button.setStyleSheet('''
            QPushButton { background-color: #1DB954; border-radius: 5px; color: white; padding: 5px 10px; }
            QPushButton:hover { background-color: #1ED760; }
        ''')
        self.start_button.clicked.connect(self.start_timer)

        self.pause_button=QtWidgets.QPushButton("Pause")
        self.pause_button.setIcon(
            QtGui.QIcon.fromTheme("media-playback-pause"))
        self.pause_button.setStyleSheet('''
            QPushButton { background-color: #FFC107; border-radius: 5px; color: white; padding: 5px 10px; }
            QPushButton:hover { background-color: #FFCA28; }
        ''')
        self.pause_button.clicked.connect(self.pause_timer)

        self.stop_button=QtWidgets.QPushButton("Stop")
        self.stop_button.setIcon(QtGui.QIcon.fromTheme("media-playback-stop"))
        self.stop_button.setStyleSheet('''
            QPushButton { background-color: #DC3545; border-radius: 5px; color: white; padding: 5px 10px; }
            QPushButton:hover { background-color: #E53935; }
        ''')
        self.stop_button.clicked.connect(self.stop_timer)

        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.pause_button)
        button_layout.addWidget(self.stop_button)
        layout.addLayout(button_layout)

        # Timer setup
        self.timer=QtCore.QTimer(self)
        self.timer.timeout.connect(self.update_timer)

    def start_timer(self):
        if not self.is_running:
            self.timer.start(1000)
            self.is_running=True

    def pause_timer(self):
        if self.is_running:
            self.timer.stop()
            self.is_running=False

    def stop_timer(self):
        self.timer.stop()
        self.elapsed_time=0
        self.is_running=False
        self.update_display()

    def update_timer(self):
        self.elapsed_time += 1
        self.update_display()

    def update_display(self):
        hours=self.elapsed_time // 3600
        minutes=(self.elapsed_time % 3600) // 60
        seconds=self.elapsed_time % 60
        self.time_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")

# Main Overlay Class
class GameOverlay(QtWidgets.QWidget):
    SCREEN_INDEX=0  # 0-based index (0=first screen)
    WINDOW_X=20    # Position from left edge
    WINDOW_Y=20    # Position from top edge
    WINDOW_WIDTH=300
    WINDOW_HEIGHT=400

    def __init__(self):
        super().__init__()
        self.recording=False
        self.initUI()

    def initUI(self):
        self.setWindowFlags(
            QtCore.Qt.WindowStaysOnTopHint |
            QtCore.Qt.FramelessWindowHint |
            QtCore.Qt.X11BypassWindowManagerHint
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")

        # Set window position and size
        screens=QtWidgets.QDesktopWidget().screenCount()
        if screens > self.SCREEN_INDEX:
            screen_geo=QtWidgets.QDesktopWidget().screenGeometry(self.SCREEN_INDEX)
            self.setGeometry(
                screen_geo.x() + self.WINDOW_X,
                screen_geo.y() + self.WINDOW_Y,
                self.WINDOW_WIDTH,
                self.WINDOW_HEIGHT
            )
        else:
            self.setGeometry(100, 100, self.WINDOW_WIDTH, self.WINDOW_HEIGHT)

        # Main layout
        layout=QtWidgets.QVBoxLayout()
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        self.setLayout(layout)

        # Add widgets
        self.timer_widget=GameTimerWidget()
        layout.addWidget(self.timer_widget)

        self.spotify_widget=SpotifyWidget()
        layout.addWidget(self.spotify_widget)

        # Recording Button
        self.record_btn=QtWidgets.QPushButton("Start Recording")
        self.record_btn.setIcon(QtGui.QIcon.fromTheme("media-record"))
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
        self.shortcut=QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+~"), self)
        self.shortcut.activated.connect(self.toggle_overlay)

    def toggle_overlay(self):
        self.setVisible(not self.isVisible())

    def toggle_recording(self):
        self.recording=not self.recording
        self.record_btn.setText(
            "Stop Recording" if self.recording else "Start Recording")
        if self.recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        self.fourcc=cv2.VideoWriter_fourcc(*'XVID')
        self.out=cv2.VideoWriter(
            'output.avi', self.fourcc, 20.0, pyautogui.size())
        self.record_frame()

    def stop_recording(self):
        if hasattr(self, 'out'):
            self.out.release()

    def record_frame(self):
        if self.recording:
            img=pyautogui.screenshot()
            frame=np.array(img)
            frame=cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
            self.out.write(frame)
            QtCore.QTimer.singleShot(50, self.record_frame)

    def mousePressEvent(self, event):
        self.old_pos=event.globalPos()

    def mouseMoveEvent(self, event):
        delta=QtCore.QPoint(event.globalPos() - self.old_pos)
        self.move(self.x() + delta.x(), self.y() + delta.y())
        self.old_pos=event.globalPos()

if __name__ == "__main__":
    app=QtWidgets.QApplication(sys.argv)
    app.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps)
    overlay=GameOverlay()
    overlay.show()
    sys.exit(app.exec_())
