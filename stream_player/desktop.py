"""Native Qt Widgets player. No browser, WebView or HTML interface."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys

from PySide6.QtCore import Qt, QTimer, QUrl, QObject, Signal, QRect
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QFileDialog, QFrame,
    QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QProgressBar, QPushButton, QSlider, QSplitter, QStackedWidget,
    QVBoxLayout, QWidget)

from .casting import Casting
from .media import EXTENSIONS, Library
from .streaming import MediaServer

ASSETS = Path(__file__).parent / 'assets'
STYLE = '''
QWidget { background:#141617; color:#eeece8; font-family:'Segoe UI'; font-size:13px; }
QMainWindow { background:#111314; }
QFrame#panel { background:#1b1e20; border:1px solid #303437; border-radius:12px; }
QLabel { background:transparent; }
QLabel#brand { font-size:28px; font-weight:750; color:#ebbd87; }
QLabel#title { font-size:16px; font-weight:600; }
QLabel#muted { color:#989fa4; font-size:12px; }
QLabel#emptyTitle { font-size:22px; font-weight:500; }
QPushButton { background:#282c2f; border:1px solid #3b4043; border-radius:7px; padding:9px 15px; }
QPushButton:hover { background:#363b3f; border-color:#81705a; }
QPushButton:disabled { color:#666d72; border-color:#303437; }
QPushButton#primary { background:#e9b97f; color:#211c16; font-weight:600; border:none; }
QPushButton#play { background:#e9b97f; color:#211c16; font-size:19px; min-width:30px; }
QPushButton:focus { border:1px solid #e9b97f; }
QListWidget { background:#1b1e20; border:0; outline:0; padding:4px; }
QListWidget::item { border-radius:7px; padding:13px 9px; margin:3px 0; }
QListWidget::item:selected { background:#3b3024; color:#f6d5ad; }
QListWidget::item:hover { background:#2d3235; }
QSlider::groove:horizontal { height:4px; background:#40464a; border-radius:2px; }
QSlider::sub-page:horizontal { background:#e9b97f; border-radius:2px; }
QSlider::handle:horizontal { width:12px; margin:-4px 0; background:#e9b97f; border-radius:6px; }
QComboBox { border:1px solid #40464a; border-radius:5px; padding:5px; background:#22272a; }
QProgressBar { background:#363c40; border:none; height:7px; border-radius:3px; text-align:center; }
QProgressBar::chunk { background:#e9b97f; border-radius:3px; }
QLineEdit { background:#202528; border:1px solid #485057; border-radius:6px; padding:9px; }
QToolTip { background:#282c2f; color:#eee; border:1px solid #555; }
'''


def clock(seconds):
    seconds = max(0, int(seconds or 0))
    return f'{seconds // 3600}:{seconds // 60 % 60:02}:{seconds % 60:02}' if seconds >= 3600 else f'{seconds // 60}:{seconds % 60:02}'


def label(text, name=None):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, slot, name=None, tip=None):
    widget = QPushButton(text)
    if name:
        widget.setObjectName(name)
    if tip:
        widget.setToolTip(tip)
        widget.setAccessibleName(tip)
    widget.clicked.connect(slot)
    return widget


class Banner(QWidget):
    def __init__(self):
        super().__init__()
        self.image = QPixmap(str(ASSETS / 'banner.png'))
        self.setMinimumHeight(165)
        self.setMaximumHeight(205)

    def paintEvent(self, event):
        painter = QPainter(self)
        scaled = self.image.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        painter.drawPixmap((self.width() - scaled.width()) // 2, (self.height() - scaled.height()) // 2, scaled)
        painter.fillRect(0, 0, self.width() // 2, self.height(), QColor(12, 15, 17, 65))
        painter.setPen(QColor('#bdb8b0'))
        painter.setFont(QFont('Segoe UI', 9, QFont.Weight.DemiBold))
        painter.drawText(26, 34, 'DEINE DATEIEN. DEIN HEIMNETZ.')
        painter.setPen(QColor('#f3eee6'))
        painter.setFont(QFont('Segoe UI', 27, QFont.Weight.DemiBold))
        painter.drawText(QRect(24, 43, 400, 92), 'Kleiner Player.\nGroßes Kino.')
        painter.setFont(QFont('Segoe UI', 10))
        painter.setPen(QColor('#c6c1b9'))
        painter.drawText(26, self.height() - 20, 'MP4 · MKV · AVI · und viele mehr')


class WorkerSignals(QObject):
    finished = Signal(str, object)
    failed = Signal(str)


class CastDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.owner = window
        self.setWindowTitle('Auf TV streamen')
        self.setMinimumSize(450, 350)
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.addWidget(label('Wohin darf’s gehen?', 'emptyTitle'))
        layout.addWidget(label('Google TV oder Chromecast im selben WLAN auswählen.', 'muted'))
        self.devices = QListWidget()
        self.devices.itemDoubleClicked.connect(self.connect_device)
        layout.addWidget(self.devices)
        self.notice = label('', 'muted')
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        row = QHBoxLayout()
        row.addWidget(button('Erneut suchen', self.scan))
        row.addWidget(button('TV-IP eingeben', self.manual))
        row.addWidget(button('Verbinden', self.connect_device, 'primary'))
        layout.addLayout(row)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(600)
        self.last = None
        self.scan()

    def scan(self):
        self.owner.casting.discover()
        self.refresh()

    def refresh(self):
        devices = self.owner.casting.devices()
        signature = json.dumps(devices, sort_keys=True)
        if signature != self.last:
            self.last = signature
            self.devices.clear()
            for device in devices:
                item = QListWidgetItem(f'{device["name"]}\n{device["model"] or "Google Cast"}')
                item.setData(Qt.ItemDataRole.UserRole, device['id'])
                self.devices.addItem(item)
            if devices:
                self.devices.setCurrentRow(0)
        self.notice.setText('Suche läuft …' if self.owner.casting.scanning else self.owner.casting.error or ('TV einschalten und WLAN prüfen, falls dein Gerät fehlt.' if not devices else 'Die aktuelle Position wird mitgenommen.'))

    def manual(self):
        host, ok = QInputDialog.getText(self, 'TV manuell verbinden', 'Lokale IPv4-Adresse des Fernsehers:')
        if ok and host:
            self.owner.run('manual', lambda: self.owner.casting.add_host(host.strip()))

    def connect_device(self, *args):
        item = self.devices.currentItem()
        if item:
            self.owner.cast_to(item.data(Qt.ItemDataRole.UserRole))
            self.accept()


class PlayerWindow(QMainWindow):
    def __init__(self, data_dir):
        super().__init__()
        self.setWindowTitle('Stream · Portable Player')
        self.setWindowIcon(QIcon(str(ASSETS / 'icon.svg')))
        self.resize(1160, 850)
        self.setMinimumSize(820, 640)
        self.setAcceptDrops(True)
        self.library = Library(data_dir / 'cache')
        self.casting = Casting()
        self.stream = MediaServer(self.library)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='cast-control')
        self.signals = WorkerSignals()
        self.signals.finished.connect(self.completed)
        self.signals.failed.connect(self.failed)
        self.selected = self.loaded = self.last_queue = self.resume_at = None
        self.busy = self.cast_finished = False
        self.audio = QAudioOutput(self)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        self.audio.setVolume(1)
        self.video = QVideoWidget()
        self.player.setVideoOutput(self.video)
        self.player.errorOccurred.connect(lambda error, message: self.status.setText('Wiedergabe fehlgeschlagen: ' + message))
        self.player.mediaStatusChanged.connect(self.media_status)
        self.build_ui()
        for sequence, callback in [('Space', self.toggle), ('Left', lambda: self.seek(-10, relative=True)), ('Right', lambda: self.seek(10, relative=True)), ('M', self.mute), ('F', self.fullscreen), ('Ctrl+O', self.open_files), ('Escape', lambda: self.video.setFullScreen(False))]:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(400)
        self.casting.discover()
        self.refresh()

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(15)
        header = QHBoxLayout()
        header.addWidget(label('▶ stream.', 'brand'))
        header.addStretch()
        header.addWidget(label('PORTABLE · DEIN HEIMNETZ', 'muted'))
        header.addSpacing(15)
        header.addWidget(button('+ Video öffnen', self.open_files, 'primary'))
        self.cast_button = button('Auf TV streamen', self.show_cast)
        self.cast_button.setIcon(QIcon(str(ASSETS / 'cast.svg')))
        header.addWidget(self.cast_button)
        layout.addLayout(header)
        layout.addWidget(Banner())
        split = QSplitter()
        split.setChildrenCollapsible(False)
        layout.addWidget(split, 1)
        panel = QFrame()
        panel.setObjectName('panel')
        player_layout = QVBoxLayout(panel)
        player_layout.setContentsMargins(15, 15, 15, 12)
        self.title = label('Platz für deinen nächsten Film', 'title')
        player_layout.addWidget(self.title)
        self.stack = QStackedWidget()
        self.stack.setMinimumHeight(220)
        self.empty = QWidget()
        empty_layout = QVBoxLayout(self.empty)
        empty_layout.addStretch()
        self.stage_title = label('Dein Film wartet auf dich.', 'emptyTitle')
        self.stage_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stage_note = label('Video öffnen oder eine Datei ins Fenster ziehen.', 'muted')
        self.stage_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stage_note.setWordWrap(True)
        empty_layout.addWidget(self.stage_title)
        empty_layout.addWidget(self.stage_note)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        empty_layout.addWidget(self.progress)
        self.return_button = button('Hier weitersehen', self.return_local)
        self.return_button.hide()
        empty_layout.addWidget(self.return_button, alignment=Qt.AlignmentFlag.AlignCenter)
        empty_layout.addStretch()
        self.stack.addWidget(self.empty)
        self.stack.addWidget(self.video)
        player_layout.addWidget(self.stack, 1)
        timeline = QHBoxLayout()
        self.elapsed = label('0:00', 'muted')
        self.duration_label = label('0:00', 'muted')
        self.seek_slider = QSlider(Qt.Orientation.Horizontal)
        self.seek_slider.setAccessibleName('Wiedergabeposition')
        self.seek_slider.sliderReleased.connect(lambda: self.seek(self.seek_slider.value() / 1000))
        timeline.addWidget(self.elapsed)
        timeline.addWidget(self.seek_slider, 1)
        timeline.addWidget(self.duration_label)
        player_layout.addLayout(timeline)
        controls = QHBoxLayout()
        self.play_button = button('▶', self.toggle, 'play', 'Abspielen / Pausieren')
        controls.addWidget(self.play_button)
        controls.addWidget(button('−10 s', lambda: self.seek(-10, relative=True), tip='10 Sekunden zurück'))
        controls.addWidget(button('+10 s', lambda: self.seek(10, relative=True), tip='10 Sekunden vor'))
        self.mute_button = button('Ton', self.mute, tip='Stummschalten')
        controls.addWidget(self.mute_button)
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setAccessibleName('Lautstärke')
        self.volume.setRange(0, 100)
        self.volume.setValue(100)
        self.volume.setMaximumWidth(85)
        self.volume.valueChanged.connect(self.change_volume)
        self.volume.sliderReleased.connect(lambda: self.change_volume(self.volume.value()))
        controls.addWidget(self.volume)
        controls.addStretch()
        self.speed = QComboBox()
        self.speed.setAccessibleName('Geschwindigkeit')
        for text, value in [('0,5×', .5), ('0,75×', .75), ('1×', 1), ('1,25×', 1.25), ('1,5×', 1.5), ('2×', 2)]:
            self.speed.addItem(text, value)
        self.speed.setCurrentIndex(2)
        self.speed.currentIndexChanged.connect(lambda: self.player.setPlaybackRate(self.speed.currentData()))
        controls.addWidget(self.speed)
        controls.addWidget(button('⛶', self.fullscreen, tip='Vollbild'))
        player_layout.addLayout(controls)
        split.addWidget(panel)
        side = QFrame()
        side.setObjectName('panel')
        side_layout = QVBoxLayout(side)
        side_layout.addWidget(label('Wiedergabeliste', 'title'))
        self.queue = QListWidget()
        self.queue.setMinimumWidth(205)
        self.queue.setMaximumWidth(340)
        self.queue.setAccessibleName('Wiedergabeliste')
        self.queue.currentItemChanged.connect(self.select_item)
        self.queue.itemDoubleClicked.connect(lambda _: self.toggle())
        side_layout.addWidget(self.queue, 1)
        side_layout.addWidget(button('+ Video hinzufügen', self.open_files))
        side_layout.addWidget(button('Aus Liste entfernen', self.remove_item))
        self.stop_button = button('Übertragung beenden', self.stop_cast)
        self.stop_button.hide()
        side_layout.addWidget(self.stop_button)
        side_layout.addWidget(button('Formate & Hilfe', self.help))
        split.addWidget(side)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        split.setSizes([800, 270])
        self.status = label('Alles bleibt auf deinem PC und in deinem Heimnetz.', 'muted')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def current(self):
        return next((x for x in self.library.list() if x['id'] == self.selected), None)

    def on_tv(self):
        return self.casting.cast is not None and self.casting.item_id == self.selected

    def position(self):
        return self.casting.status().get('position', 0) if self.on_tv() else self.player.position() / 1000

    def run(self, action, function):
        if self.busy:
            self.status.setText('Bitte kurz warten, der Fernseher antwortet noch …')
            return False
        self.busy = True
        def work():
            try:
                self.signals.finished.emit(action, function())
            except Exception as exc:
                self.signals.failed.emit(str(exc))
        self.executor.submit(work)
        return True

    def completed(self, action, result):
        self.busy = False
        if action == 'cast':
            self.player.pause()
            self.status.setText('Verbunden. Der PC muss während der Übertragung eingeschaltet bleiben.')
        elif action == 'return':
            self.stream.revoke()
            self.load_local()
            if self.player.mediaStatus() in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
                self.apply_resume()
        elif action == 'stop':
            self.stream.revoke()
            self.loaded = None
        self.refresh()

    def failed(self, message):
        self.busy = False
        self.status.setText('Aktion fehlgeschlagen: ' + message)

    def open_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, 'Videos öffnen', '', 'Videos (' + ' '.join('*' + ext for ext in sorted(EXTENSIONS)) + ');;Alle Dateien (*)')
        self.add_files(paths)

    def add_files(self, paths):
        first = None
        for path in paths:
            try:
                item = self.library.add(path)
                first = first or item['id']
            except (ValueError, OSError) as exc:
                self.status.setText(str(exc))
        if first and not self.selected:
            self.selected = first
        self.refresh()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and all(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()

    def dropEvent(self, event):
        self.add_files([url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()])
        event.acceptProposedAction()

    def select_item(self, item, previous):
        if item and item.data(Qt.ItemDataRole.UserRole) != self.selected:
            self.player.pause()
            self.selected = item.data(Qt.ItemDataRole.UserRole)
            self.loaded = None
            self.refresh()

    def remove_item(self):
        if self.selected == self.casting.item_id:
            self.status.setText('Bitte zuerst die Übertragung dieses Videos beenden.')
            return
        if self.selected:
            self.player.stop()
            self.player.setSource(QUrl())
            self.library.remove(self.selected)
            self.selected = self.loaded = None
            self.refresh()

    def load_local(self):
        item = self.current()
        if item and item['state'] == 'ready' and self.loaded != item['id']:
            self.loaded = item['id']
            self.player.setSource(QUrl.fromLocalFile(str(self.library.ready(item['id'])['output'])))

    def refresh(self):
        items = self.library.list()
        if not self.selected and items:
            self.selected = items[0]['id']
        signature = json.dumps(items, sort_keys=True) + str(self.selected)
        if signature != self.last_queue:
            self.last_queue = signature
            self.queue.blockSignals(True)
            self.queue.clear()
            for item in items:
                state = clock(item['duration']) if item['state'] == 'ready' else 'Fehler' if item['state'] == 'error' else f'{item["progress"]}% vorbereitet' if item['state'] == 'preparing' else 'Wartet …'
                row = QListWidgetItem(f'{item["name"]}\n{item["format"]} · {state}')
                row.setToolTip(item['name'])
                row.setData(Qt.ItemDataRole.UserRole, item['id'])
                self.queue.addItem(row)
                if item['id'] == self.selected:
                    self.queue.setCurrentItem(row)
            self.queue.blockSignals(False)
        item = self.current()
        ready = item and item['state'] == 'ready'
        tv = self.on_tv()
        self.title.setText(self.fontMetrics().elidedText(item['name'] if item else 'Platz für deinen nächsten Film', Qt.TextElideMode.ElideMiddle, max(200, self.stack.width() - 20)))
        self.title.setToolTip(item['name'] if item else '')
        self.play_button.setEnabled(bool(ready) and not self.busy)
        self.seek_slider.setEnabled(bool(ready) and not self.busy)
        self.cast_button.setEnabled(bool(ready) and not self.busy)
        self.speed.setEnabled(not tv)
        self.stop_button.setVisible(self.casting.cast is not None)
        self.return_button.setVisible(tv)
        self.progress.setVisible(bool(item) and item['state'] in {'queued', 'preparing'})
        if not ready:
            self.stack.setCurrentWidget(self.empty)
            self.stage_title.setText('Dein Film wartet auf dich.' if not item else 'Datei nicht abspielbar' if item['state'] == 'error' else 'Video wird vorbereitet …')
            self.stage_note.setText('Video öffnen oder eine Datei ins Fenster ziehen.' if not item else item['error'] or f'{item["mode"]} · {item["progress"]}%')
            if item:
                self.progress.setValue(item['progress'])
        elif tv:
            status = self.casting.status()
            self.stack.setCurrentWidget(self.empty)
            self.stage_title.setText('Wiedergabe auf ' + status['device'])
            self.stage_note.setText({'PLAYING': 'Dein Film läuft auf dem großen Bildschirm.', 'PAUSED': 'Pausiert', 'BUFFERING': 'Wird geladen …', 'IDLE': 'Wiedergabe beendet'}.get(status['state'], 'Verbindung wird hergestellt …'))
            if status['idle_reason'] == 'ERROR':
                self.stage_note.setText('Der TV kann den Stream nicht laden. WLAN und Firewall prüfen.')
            if status['idle_reason'] == 'FINISHED' and not self.cast_finished:
                self.cast_finished = True
                QTimer.singleShot(0, self.next_video)
            if status['state'] == 'PLAYING':
                self.cast_finished = False
        else:
            self.stack.setCurrentWidget(self.video)
            self.load_local()
        status = self.casting.status() if tv else {}
        paused = status.get('state') != 'PLAYING' if tv else self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState
        self.play_button.setText('▶' if paused else 'Ⅱ')
        duration = (status.get('duration', 0) if tv else self.player.duration() / 1000) or (item['duration'] if item else 0)
        position = self.position() if ready else 0
        self.elapsed.setText(clock(position))
        self.duration_label.setText(clock(duration))
        if not self.seek_slider.isSliderDown():
            self.seek_slider.setRange(0, max(1, int(duration * 1000)))
            self.seek_slider.setValue(int(position * 1000))
        if not self.volume.isSliderDown():
            self.volume.blockSignals(True)
            self.volume.setValue(round(100 * (status.get('volume', 1) if tv else self.audio.volume())))
            self.volume.blockSignals(False)
        self.mute_button.setText('Stumm' if (status.get('muted') if tv else self.audio.isMuted()) else 'Ton')

    def toggle(self):
        if not self.current() or self.current()['state'] != 'ready':
            return
        if self.on_tv():
            action = 'pause' if self.casting.status()['state'] == 'PLAYING' else 'play'
            self.run('control', lambda: self.casting.control(action))
        elif self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def seek(self, value, relative=False):
        if not self.current() or self.current()['state'] != 'ready':
            return
        value = max(0, (self.position() if relative else 0) + value)
        value = min(value, self.current()['duration'] or value)
        if self.on_tv():
            self.run('control', lambda: self.casting.control('seek', value))
        else:
            self.player.setPosition(int(value * 1000))

    def change_volume(self, value):
        if self.on_tv():
            if not self.volume.isSliderDown():
                self.run('control', lambda: self.casting.control('volume', value / 100))
        else:
            self.audio.setVolume(value / 100)

    def mute(self):
        if self.on_tv():
            self.run('control', lambda: self.casting.control('mute', not self.casting.status()['muted']))
        else:
            self.audio.setMuted(not self.audio.isMuted())

    def fullscreen(self):
        if self.current() and self.current()['state'] == 'ready' and not self.on_tv():
            self.video.setFullScreen(not self.video.isFullScreen())

    def show_cast(self):
        CastDialog(self).exec()

    def cast_to(self, device_id):
        item = self.current()
        if not item or item['state'] != 'ready':
            self.status.setText('Bitte zuerst ein Video auswählen und die Vorbereitung abwarten.')
            return
        position = self.position()
        self.status.setText('Verbindung zum Fernseher wird hergestellt …')
        self.run('cast', lambda: self.casting.play(device_id, item, lambda host: self.stream.share(item['id'], host), position))

    def stop_cast(self):
        if self.casting.cast:
            self.run('stop', lambda: self.casting.control('stop'))

    def return_local(self):
        if self.busy:
            return
        self.resume_at = self.position()
        self.loaded = None
        self.run('return', lambda: self.casting.control('stop'))

    def apply_resume(self):
        if self.resume_at is not None:
            at = self.resume_at
            self.resume_at = None
            self.player.setPosition(int(at * 1000))
            self.player.play()

    def media_status(self, status):
        if status in (QMediaPlayer.MediaStatus.LoadedMedia, QMediaPlayer.MediaStatus.BufferedMedia):
            self.apply_resume()
        if status == QMediaPlayer.MediaStatus.EndOfMedia and not self.on_tv():
            self.next_video()

    def next_video(self):
        items = self.library.list()
        index = next((i for i, item in enumerate(items) if item['id'] == self.selected), -1)
        if index < 0 or index + 1 >= len(items) or items[index + 1]['state'] != 'ready':
            return
        device = self.casting.status().get('device_id') if self.on_tv() else None
        self.selected = items[index + 1]['id']
        self.loaded = None
        self.refresh()
        if device:
            self.cast_to(device)
        else:
            self.player.play()

    def help(self):
        QMessageBox.information(self, 'Stream · Formate & Hilfe',
            'Video öffnen oder ins Fenster ziehen. MP4, MKV, AVI, MOV, WebM, WMV, FLV, MPEG, TS, M2TS, MTS, OGV, VOB und 3GP werden über FFmpeg verarbeitet.\n\n'
            'Kompatible Dateien starten direkt. Andere werden vor dem Abspielen vorbereitet (H.264/AAC, maximal 1080p/30 fps bei Konvertierung). Das benötigt Zeit und freien Speicher. Die erste Video- und Tonspur wird verwendet. DRM, Untertitel und HDR-Tonemapping werden nicht unterstützt.\n\n'
            'Cast: TV und PC ins gleiche WLAN, Fernseher einschalten, Cast-Symbol wählen. Falls Windows fragt, Stream für private Netzwerke zulassen. PC und App müssen während der Übertragung laufen.\n\n'
            'Leertaste: Play/Pause · Pfeile: ±10 Sekunden · M: stumm · F: Vollbild · Strg+O: öffnen\n\n'
            'Portable: Daten und Cache liegen im Ordner data neben Stream.exe. Originale werden nicht verändert. Kein Browser und keine Python-Installation nötig.')

    def closeEvent(self, event):
        self.timer.stop()
        self.player.stop()
        self.player.setSource(QUrl())
        self.stream.close()
        self.library.close()
        self.executor.shutdown(wait=True, cancel_futures=True)
        if self.casting.cast:
            try:
                self.casting.control('stop')
            except Exception:
                pass
        self.casting.close()
        event.accept()


def main(argv=None):
    app = QApplication(sys.argv if argv is None else argv)
    app.setApplicationName('Stream')
    app.setOrganizationName('StreamPlayer')
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    app.setWindowIcon(QIcon(str(ASSETS / 'icon.svg')))
    data = Path(sys.executable).parent / 'data' if getattr(sys, 'frozen', False) else Path(__file__).parent.parent / '.local' / 'desktop-data'
    try:
        data.mkdir(parents=True, exist_ok=True)
        window = PlayerWindow(data)
    except Exception as exc:
        QMessageBox.critical(None, 'Stream kann nicht starten', f'Bitte die ZIP vollständig in einen beschreibbaren Ordner entpacken.\n\n{exc}')
        return 1
    window.show()
    paths = [x for x in sys.argv[1:] if not x.startswith('-') and Path(x).is_file()]
    if paths:
        window.add_files(paths)
    return app.exec()
