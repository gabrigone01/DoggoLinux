#!/usr/bin/env python3
"""Desktop Virtual Pet: un cane in 3D che vive sui tuoi schermi e chiacchiera via Gemini."""
import json
import math
import os
import shlex
import signal
import sys
import threading
from pathlib import Path

# Su Wayland le finestre non possono posizionarsi né restare sopra le altre: usiamo XWayland.
if os.environ.get("XDG_SESSION_TYPE") == "wayland":
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PyQt6.QtCore import (QDir, QElapsedTimer, QLockFile, QObject, QPoint, QPointF, QRect, QRectF, Qt, QTimer,
                          pyqtSignal, qInstallMessageHandler)
from PyQt6.QtGui import (QActionGroup, QColor, QCursor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPolygon,
                         QRadialGradient, QRegion, QSurfaceFormat)
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QMessageBox,
                             QPushButton, QVBoxLayout, QWidget)

import dog3d
import sounds
import view3d
from ai_handler import ChatError, GeminiChat, parse_reply, system_prompt
from brain import Areas, Brain

if sys.platform == "win32":
    CONFIG_PATH = Path(os.environ.get("APPDATA") or Path.home()) / "Doggo" / "config.json"
elif sys.platform == "darwin":
    CONFIG_PATH = Path.home() / "Library" / "Application Support" / "Doggo" / "config.json"
else:  # nella home: funziona anche installato in /usr/share
    CONFIG_PATH = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "doggo" / "config.json"
OLD_CONFIG = Path(__file__).with_name("config.json")  # versioni precedenti: accanto al programma
if sys.platform == "darwin":
    AUTOSTART = Path.home() / "Library" / "LaunchAgents" / "com.github.gabrigone01.doggo.plist"
else:
    AUTOSTART = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart" / "doggo.desktop"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"  # avvio automatico su Windows
DEFAULTS = {"breed": dog3d.DEFAULT_BREED, "name": "", "kennel": "right", "windows": True, "sounds": True, "api_key": "",
            "model": "gemini-flash-latest"}
FLAGS = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool


def keep_visible(w):
    """Su macOS le finestre "strumento" spariscono quando si passa a un'altra app: le teniamo visibili."""
    if sys.platform == "darwin":
        w.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
    return w


def load_config(path=CONFIG_PATH):
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    cfg = {**DEFAULTS, **data}
    if cfg["breed"] not in dog3d.BREEDS:
        cfg["breed"] = dog3d.DEFAULT_BREED
    return cfg


def save_config(cfg, path=CONFIG_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # contiene la chiave API
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


LOG_PATH = CONFIG_PATH.parent / "doggo.log"


def setup_log():
    """Senza console (Doggo.exe, Doggo.app) errori e avvisi di Qt finiscono in doggo.log accanto alla configurazione."""
    if sys.stderr is not None:
        return
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(LOG_PATH, "w", buffering=1, encoding="utf-8")
    qInstallMessageHandler(lambda _mode, _ctx, msg: print(msg))


def launch_command():
    """Come rilanciare il cane: l'eseguibile impacchettato oppure python + main.py."""
    if getattr(sys, "frozen", False):  # Doggo.exe / Doggo.app
        return [sys.executable]
    exe = sys.executable
    if sys.platform == "win32" and exe.lower().endswith("python.exe"):
        exe = exe[:-len("python.exe")] + "pythonw.exe"  # senza finestra del terminale
    return [exe, str(Path(__file__).resolve())]


def autostart_enabled():
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
                winreg.QueryValueEx(key, "Doggo")
            return True
        except OSError:
            return False
    return AUTOSTART.exists()


def set_autostart(on):
    """Avvio automatico al login: Run del registro (Windows), LaunchAgent (macOS), ~/.config/autostart (Linux)."""
    cmd = launch_command()
    if sys.platform == "win32":
        import subprocess
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if on:
                winreg.SetValueEx(key, "Doggo", 0, winreg.REG_SZ, subprocess.list2cmdline(cmd))
            else:
                try:
                    winreg.DeleteValue(key, "Doggo")
                except FileNotFoundError:
                    pass
        return
    if not on:
        AUTOSTART.unlink(missing_ok=True)
        return
    AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        import plistlib
        AUTOSTART.write_bytes(plistlib.dumps({"Label": "com.github.gabrigone01.doggo",
                                              "ProgramArguments": cmd, "RunAtLoad": True}))
        return
    AUTOSTART.write_text(
        "[Desktop Entry]\nType=Application\nName=Doggo\nComment=Il cane da scrivania\n"
        f"Exec={' '.join(shlex.quote(c) for c in cmd)}\n"
        f"Icon={Path(__file__).resolve().with_name('icon.png')}\nTerminal=false\nX-GNOME-Autostart-enabled=true\n")


class Bubble(QWidget):
    TAIL = 12

    def __init__(self, ctl):
        super().__init__(None, FLAGS)
        self.ctl = ctl
        self.tail_x = 40
        keep_visible(self)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(330)
        self.setStyleSheet("""
            QLabel { color: #2A2320; font-size: 14px; }
            QLineEdit { border: 1px solid #C9BFA9; border-radius: 10px; padding: 5px 8px;
                        background: white; color: #2A2320; font-size: 13px; }
            QPushButton { border: none; color: #8A7F6A; font-size: 16px; background: transparent; }
        """)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        close = QPushButton("×")
        close.setFixedSize(22, 22)
        close.setAccessibleName("Chiudi chat")
        close.clicked.connect(ctl.close_chat)
        top = QHBoxLayout()
        top.addWidget(self.text, 1)
        top.addWidget(close, 0, Qt.AlignmentFlag.AlignTop)
        self.input = QLineEdit()
        self.input.setPlaceholderText("Scrivi qualcosa e premi Invio…")
        self.input.returnPressed.connect(ctl.send_message)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 10, 12 + self.TAIL)
        lay.addLayout(top)
        lay.addWidget(self.input)

    def say(self, text):
        self.text.setText(text)
        self.adjustSize()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1 - self.TAIL)
        path = QPainterPath()
        path.addRoundedRect(r, 16, 16)
        tx = min(max(self.tail_x, r.left() + 24), r.right() - 24)
        tail = QPainterPath()
        tail.moveTo(tx - 10, r.bottom() - 1)
        tail.lineTo(tx, r.bottom() + self.TAIL)
        tail.lineTo(tx + 10, r.bottom() - 1)
        tail.closeSubpath()
        p.setPen(QPen(QColor("#2A2320"), 2))
        p.setBrush(QColor("#FFFDF7"))
        p.drawPath(path.united(tail))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.ctl.close_chat()
        else:
            super().keyPressEvent(e)


class ToyWindow(QWidget):
    """Pallina o rametto: piccola finestra trasparente ai clic che segue la fisica del giocattolo."""
    W, H, GROUND = 44, 90, 46  # il giocattolo sta in (W/2, GROUND); l'ombra scende di h

    def __init__(self):
        super().__init__(None, FLAGS | Qt.WindowType.WindowTransparentForInput)
        keep_visible(self)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.resize(self.W, self.H)
        self.toy = None
        self.height_above = 0.0

    def follow(self, toy):
        self.toy = toy
        if toy is None or toy.state == "carried":
            self.hide()
            return
        self.height_above = toy.h
        self.move(int(toy.x - self.W / 2), int(toy.y - toy.h - self.GROUND))
        self.show()
        self.update()

    def paintEvent(self, _):
        if self.toy is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.W / 2, self.GROUND)
        if self.height_above < 38:  # ombra a terra, sotto il giocattolo in volo
            k = 1 - self.height_above / 38
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, int(70 * k)))
            p.drawEllipse(QRectF(c.x() - 8, c.y() + self.height_above - 0.5, 16, 4))
        p.translate(c.x(), c.y())
        if self.toy.kind == "ball":
            r = 4.5
            g = QRadialGradient(QPointF(-1.5, -r - 1.5), r * 1.6)
            g.setColorAt(0, QColor("#F2FA8C"))
            g.setColorAt(0.6, QColor("#C9DC2E"))
            g.setColorAt(1, QColor("#7E8E14"))
            p.setBrush(g)
            p.setPen(QPen(QColor(90, 100, 20, 160), 0.6))
            p.drawEllipse(QPointF(0, -r), r, r)
            p.rotate(math.degrees(self.toy.angle))
            p.setPen(QPen(QColor(255, 255, 255, 200), 0.8))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawArc(QRectF(-r * 0.7, -r * 1.7, r * 1.4, r * 1.4), 200 * 16, 140 * 16)
        elif self.toy.kind == "bone":
            p.translate(0, -3)
            p.rotate(math.degrees(self.toy.angle) * 0.3)
            p.setPen(QPen(QColor("#8C7F68"), 0.7))
            p.setBrush(QColor("#EFE6D2"))
            path = QPainterPath()
            path.addRoundedRect(QRectF(-9, -1.8, 18, 3.6), 1.5, 1.5)
            for x in (-9.5, 9.5):
                for y in (-2, 2):
                    path.addEllipse(QPointF(x, y), 2.6, 2.6)
            p.drawPath(path.simplified())
        elif self.toy.kind == "sock":
            p.translate(0, -3)
            p.rotate(math.degrees(self.toy.angle) * 0.4)
            sock = QPainterPath()
            sock.moveTo(-3, -9)
            sock.lineTo(3, -9)
            sock.lineTo(3, 1)
            sock.quadTo(10, 1, 10, 5)
            sock.quadTo(10, 8, 4, 8)
            sock.lineTo(-1, 8)
            sock.quadTo(-3, 8, -3, 5)
            sock.closeSubpath()
            p.setPen(QPen(QColor("#6E1A1A"), 0.7))
            p.setBrush(QColor("#C93434"))
            p.drawPath(sock)
            p.setPen(QPen(QColor("white"), 1.6))
            for y in (-7, -4, -1):
                p.drawLine(QPointF(-2.5, y), QPointF(2.5, y))
        else:
            p.translate(0, -2.2)
            p.rotate(math.degrees(self.toy.angle))
            g = QLinearGradient(0, -2, 0, 2)
            g.setColorAt(0, QColor("#9B6B3F"))
            g.setColorAt(1, QColor("#5C3B1E"))
            p.setPen(QPen(QColor("#3E2712"), 0.6))
            p.setBrush(g)
            p.drawRoundedRect(QRectF(-13, -1.8, 26, 3.6), 1.8, 1.8)
            p.drawLine(QPointF(4, -1.5), QPointF(8, -5))  # rametto laterale
            p.setPen(QPen(QColor(255, 255, 255, 50), 0.6))
            p.drawLine(QPointF(-11, -1), QPointF(11, -1))


class CritterWindow(QWidget):
    """Uccellino, gatto o farfalla di passaggio: disegnati a mano, trasparenti ai clic."""
    W, H, GROUND = 80, 110, 90
    BIRD = (("#8A6A4A", "#E0733A"), ("#6F7A86", "#F1D7A8"), ("#3C3A38", "#C9A227"))  # dorso, petto
    CAT = (("#E39A4C", "#B86A28"), ("#8E8E92", "#5E5E63"), ("#2C2A2B", "#141314"))   # pelo, strisce
    WING = ("#F2B33D", "#7FB3E6", "#F08CB4")

    def __init__(self):
        super().__init__(None, FLAGS | Qt.WindowType.WindowTransparentForInput)
        keep_visible(self)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.resize(self.W, self.H)
        self.c = None

    def follow(self, c):
        self.c = c
        if c is None:
            self.hide()
            return
        self.move(int(c.x - self.W / 2), int(c.y - c.h - self.GROUND))
        self.show()
        self.update()

    def paintEvent(self, _):
        c = self.c
        if c is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(self.W / 2, self.GROUND)
        if c.h < 60:  # ombra a terra
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, int(60 * (1 - c.h / 60))))
            w = 28 if c.kind == "cat" else 10
            p.drawEllipse(QRectF(-w / 2, c.h - 1.5, w, 4))
        p.scale(c.face, 1)
        getattr(self, "draw_" + c.kind)(p, c)

    def draw_bird(self, p, c):
        back, breast = self.BIRD[c.color]
        flying = c.h > 2 or c.state == "flee"
        peck = not flying and math.sin(c.t * 7) > 0.6
        p.setPen(QPen(QColor(40, 30, 20), 0.6))
        p.setBrush(QColor(back))
        p.drawPolygon(QPolygon([QPoint(-6, -6), QPoint(-13, -9), QPoint(-12, -5)]))  # coda
        p.drawEllipse(QRectF(-8, -10, 14, 9))
        p.setBrush(QColor(breast))
        p.drawEllipse(QRectF(-2, -8, 7, 6))
        hx, hy = (6, -6) if peck else (5, -11)
        p.setBrush(QColor(back))
        p.drawEllipse(QPointF(hx, hy), 3.6, 3.6)
        p.setBrush(QColor("#E8B33A"))
        p.drawPolygon(QPolygon([QPoint(hx + 3, hy - 1), QPoint(hx + 7, hy + 1), QPoint(hx + 3, hy + 1)]))
        p.setBrush(QColor("black"))
        p.drawEllipse(QPointF(hx + 1.2, hy - 0.8), 0.8, 0.8)
        if flying:  # ali che sbattono
            up = math.sin(c.t * 30) * 9
            p.setBrush(QColor(back).darker(115))
            p.drawPolygon(QPolygon([QPoint(-4, -8), QPoint(2, -8), QPoint(-3, int(-8 - up))]))
        if not flying:
            p.drawLine(QPointF(-1, -1.5), QPointF(-2, 0))
            p.drawLine(QPointF(1, -1.5), QPointF(1.5, 0))

    def draw_cat(self, p, c):
        fur, stripe = self.CAT[c.color]
        sitting, arched = c.state == "stay", c.state == "scared"
        walk = c.state in ("arrive", "flee")
        p.setPen(QPen(QColor(30, 25, 20), 0.8))
        p.setBrush(QColor(fur))
        tail = QPainterPath()  # coda
        if arched:
            tail.moveTo(-12, -20)
            tail.cubicTo(-18, -34, -14, -46, -10, -48)
        elif sitting:
            tail.moveTo(-8, -3)
            tail.cubicTo(-18, -2, -20, 2, -6, 1)
        else:
            sway = math.sin(c.t * 4) * 4
            tail.moveTo(-14, -16)
            tail.cubicTo(-24, -20, -26, -30 + sway, -20, -34 + sway)
        p.setPen(QPen(QColor(fur), 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(tail)
        p.setPen(QPen(QColor(30, 25, 20), 0.8))
        p.setBrush(QColor(fur))
        if sitting:
            p.drawEllipse(QRectF(-10, -22, 18, 22))  # seduto, di profilo
            hx, hy = 3, -25
        else:
            k = math.sin(c.t * (14 if c.state == "flee" else 7)) * 4 if walk else 0
            for x, ph in ((-10, 1), (-6, -1), (6, -1), (10, 1)):  # zampe
                p.drawRect(QRectF(x - 1.5 + ph * k * 0.5, -10, 3, 10))
            body = QRectF(-15, -26, 30, 14) if arched else QRectF(-15, -20, 30, 12)
            p.drawRoundedRect(body, 6, 6)
            p.setPen(QPen(QColor(stripe), 1.2))
            for x in (-8, -3, 2):
                p.drawLine(QPointF(x, body.top() + 1), QPointF(x + 1, body.top() + 5))
            p.setPen(QPen(QColor(30, 25, 20), 0.8))
            hx, hy = 15, (-24 if arched else -22)
        p.drawEllipse(QPointF(hx, hy), 7, 6.5)
        for ex in (-4.5, 3):  # orecchie
            p.drawPolygon(QPolygon([QPoint(int(hx + ex), int(hy - 4)), QPoint(int(hx + ex + 1.5), int(hy - 11)),
                                    QPoint(int(hx + ex + 4), int(hy - 5))]))
        p.setBrush(QColor("#7FB24A"))
        p.drawEllipse(QPointF(hx + 3, hy - 1), 1.4, 1.6 if not arched else 1.0)
        p.setBrush(QColor("#E58A8A"))
        p.drawEllipse(QPointF(hx + 6.5, hy + 1.5), 1, 0.8)
        if arched:  # bocca aperta: soffia
            p.setBrush(QColor("#5A1E1E"))
            p.drawEllipse(QPointF(hx + 5, hy + 3.5), 1.8, 1.4)

    def draw_butterfly(self, p, c):
        flap = abs(math.sin(c.t * 14))
        col = QColor(self.WING[c.color])
        p.setPen(QPen(col.darker(160), 0.7))
        p.setBrush(col)
        for sx in (-1, 1):
            p.save()
            p.scale(sx * (0.25 + 0.75 * flap), 1)
            p.drawEllipse(QRectF(0, -14, 9, 8))
            p.drawEllipse(QRectF(0, -7, 6, 6))
            p.restore()
        p.setPen(QPen(QColor(40, 30, 20), 1.6))
        p.drawLine(QPointF(0, -14), QPointF(0, -2))
        p.setPen(QPen(QColor(40, 30, 20), 0.6))
        p.drawLine(QPointF(0, -14), QPointF(2, -18))
        p.drawLine(QPointF(0, -14), QPointF(-2, -18))


class FriendView(view3d.SceneView):
    """Il cane amico in visita: solo da guardare, i clic passano attraverso."""

    def __init__(self):
        super().__init__(0, FLAGS | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        keep_visible(self)


class PickOverlay(QWidget):
    """Velo semitrasparente su uno schermo: il clic sceglie dove lanciare."""

    def __init__(self, screen, text, on_pick, on_cancel):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CursorShape.CrossCursor)
        keep_visible(self)
        self.text, self.on_pick, self.on_cancel = text, on_pick, on_cancel

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 45))
        f = p.font()
        f.setPixelSize(20)
        p.setFont(f)
        p.setPen(QColor("white"))
        p.drawText(self.rect().adjusted(0, 40, 0, 0), Qt.AlignmentFlag.AlignHCenter, self.text)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.on_pick(e.globalPosition().toPoint())
        else:
            self.on_cancel()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.on_cancel()


class DogWindow(view3d.SceneView):
    def __init__(self, ctl, scene):
        super().__init__(scene, FLAGS)
        self.ctl = ctl
        keep_visible(self)

    def mousePressEvent(self, e):
        self.ctl.pressed(self.scene, e.button(), e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        gpos = e.globalPosition().toPoint()
        self.ctl.drag_kennel(gpos) if self.scene == 1 else self.ctl.drag_dog(gpos)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.ctl.drop_kennel() if self.scene == 1 else self.ctl.release_dog()


class Pet(QObject):
    reply_ready = pyqtSignal(str, bool)

    def __init__(self, cfg, bridge):
        super().__init__()
        self.cfg = cfg
        self.bridge = bridge
        self.cursor = None
        self.chat = None
        self._mask = None
        self.drag = None
        self.dog_drag = None
        self.dog_in_front = None
        self.kennel_pos = (0, 0)
        self.dog = dog3d.Dog(cfg["breed"])
        self.areas = Areas(self.qt_areas())
        self.brain = Brain(self.dog, self.areas)
        self.kennel = DogWindow(self, 1)
        self.view = DogWindow(self, 0)
        self.bubble = Bubble(self)
        self.toy_window = ToyWindow()
        self.critter_windows = []
        self.friend_view = FriendView()
        self.friend_in_front = None
        self.pickers = []
        self.reply_ready.connect(self.on_reply)
        if bridge:
            bridge.cursorMoved.connect(lambda x, y: setattr(self, "cursor", (x, y)))
            bridge.areasChanged.connect(self.set_areas)
            bridge.windowsChanged.connect(lambda wins: setattr(self.brain, "windows", wins))
        self.brain.play_windows = cfg["windows"]
        self.cmd_rest = {}  # frazioni di pixel non ancora inviate
        self.sound = sounds.Player(CONFIG_PATH.parent / "sounds", cfg["breed"], cfg["sounds"])
        self.set_breed(cfg["breed"], save=False)
        self.brain.place_home()
        self.kennel.show()
        self.view.show()

        self.clock = QElapsedTimer()
        self.clock.start()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(33)
        QTimer.singleShot(4000, self.check_drawing)

    def check_drawing(self):
        """Se OpenGL o lo shader non partono, cane e cuccia restano invisibili: meglio dirlo."""
        broken = [v for v in (self.view, self.kennel) if v.prog is None]
        if not broken:
            return
        err = broken[0].error or "OpenGL non disponibile (scheda video o driver troppo vecchi?)"
        print("Disegno non riuscito:", err)
        QMessageBox.warning(None, "Doggo", f"Non riesco a disegnare il cane.\n\n{err[:1500]}\n\n"
                            f"Dettagli in: {LOG_PATH}")

    # ------------------------------------------------------------ schermi
    @staticmethod
    def qt_areas():
        return [s.availableGeometry().getRect() for s in QApplication.screens()]

    def set_areas(self, rects):
        self.areas.rects = [tuple(r) for r in rects]
        self.brain.goal = None
        self.place_kennel()
        if self.areas.at(self.brain.x, self.brain.y) is None:
            self.brain.place_home()

    KENNEL_MARGIN = 30  # distanza dal fondo dello schermo

    def place_kennel(self):
        kw = self.kennel.width()
        saved = self.cfg.get("kennel_pos")
        if saved and self.areas.at(saved[0], saved[1] - 1) is not None:  # posizione scelta trascinando la cuccia
            self.put_kennel(*saved)
            return
        primary = QApplication.primaryScreen().geometry().center()
        i = self.areas.at(primary.x(), primary.y())
        x, y, w, h = self.areas.rects[0 if i is None else i]
        right = self.cfg["kennel"] == "right"
        self.put_kennel(x + w - 24 - kw / 2 if right else x + 24 + kw / 2, y + h - self.KENNEL_MARGIN)

    def put_kennel(self, kx, ky):
        """(kx, ky) è il punto a terra al centro della cuccia; la cuccia resta dentro lo schermo."""
        kw, kh = self.kennel.width(), self.kennel.height()
        i = self.areas.at(kx, ky - 1)
        i = self.areas.nearest(kx, ky) if i is None else i
        kx, ky = self.areas.clamp(i, kx, ky, kw / 2, kh - dog3d.BASE, self.KENNEL_MARGIN * 0.4)
        house = QPolygon([QPoint(int(kw * x), int(kh * y)) for x, y in
                          ((0.12, 1.0), (0.12, 0.4), (0.5, 0.08), (0.88, 0.4), (0.88, 1.0))])
        self.kennel.setMask(QRegion(house))  # clic solo sulla sagoma della casetta
        self.kennel_pos = (kx, ky)
        self.kennel.move(int(kx - kw / 2), int(ky + dog3d.BASE - kh))
        # il cane si sdraia davanti alla porta, girato verso il centro dello schermo
        rx, ry, rw, rh = self.areas.rects[i]
        side = 1 if kx > rx + rw / 2 else -1
        s = self.dog.b["kscale"]
        self.brain.set_home(kx, ky + 12 * s, side)
        self.brain.bowl = (kx + 42.2 * s, ky + 3 * s)  # ciotola davanti a destra della cuccia (vedi dog.frag)
        self.brain.water = (kx - 36.6 * s, ky + 5.5 * s)  # acqua davanti a sinistra

    # ------------------------------------------------------------ ciclo
    def tick(self):
        dt = min(self.clock.restart() / 1000, 0.1)
        if self.bridge is None:
            pos = QCursor.pos()
            self.cursor = (pos.x(), pos.y())
        self.brain.update(dt, self.cursor)
        rig = self.dog.rig()
        w, h = self.view.width(), self.view.height()
        self.view.dog, self.view.rig = self.dog, rig
        self.view.move(int(self.brain.x - w / 2), int(self.brain.y + dog3d.BASE - h))
        in_front = self.brain.y >= self.kennel_pos[1]  # chi è più in basso sullo schermo è più vicino a te
        if in_front != self.dog_in_front:
            self.dog_in_front = in_front
            (self.view if in_front else self.kennel).raise_()
        self.update_mask(rig, w, h)
        self.view.update()
        if self.bubble.isVisible():
            self.place_bubble()
        toy = self.brain.toy
        self.toy_window.follow(toy)
        self.show_visitors()
        self.send_window_moves()
        for name in self.brain.sfx:
            self.sound.play(name)
        self.brain.sfx = []
        if abs(self.kennel.food - self.brain.food) > 0.03:
            self.kennel.food = self.brain.food
            self.kennel.update()

    def show_visitors(self):
        critters = self.brain.critters
        while len(self.critter_windows) < len(critters):
            self.critter_windows.append(CritterWindow())
        for i, w in enumerate(self.critter_windows):
            w.follow(critters[i] if i < len(critters) else None)
        f, v = self.brain.friend, self.friend_view
        if f is None:
            v.hide()
            v.dog = None
            return
        if v.dog is not f.dog:
            v.resize(*f.dog.window_size())
            v.dog, self.friend_in_front = f.dog, None
        v.rig = f.dog.rig()
        v.move(int(f.x - v.width() / 2), int(f.y + dog3d.BASE - v.height()))
        v.show()
        front = f.y >= self.brain.y  # chi è più in basso sta davanti
        if front != self.friend_in_front:
            self.friend_in_front = front
            (v if front else self.view).raise_()
        v.update()

    def send_window_moves(self):
        """Il cane tira una finestra: KWin la sposta di pixel interi, il resto si accumula."""
        cmds, self.brain.window_cmds = self.brain.window_cmds, []
        if self.bridge is None:
            return
        for wid, dx, dy in cmds:
            rx, ry = self.cmd_rest.get(wid, (0.0, 0.0))
            rx, ry = rx + dx, ry + dy
            ix, iy = int(rx), int(ry)
            if ix or iy:
                self.bridge.move_window(wid, ix, iy)
            self.cmd_rest[wid] = (rx - ix, ry - iy)

    def update_mask(self, rig, w, h):
        # I clic passano attraverso tutto tranne il cane (rettangolo che lo contiene, ombra inclusa).
        xs, ys = [], []
        for pt in self.dog.points(rig):
            sx, sy = dog3d.project(pt)
            xs.append(w / 2 + sx)
            ys.append(h - dog3d.BASE - sy)
        m = self.dog.b["R"] * 1.3
        q = 6
        x0, x1 = int(min(xs) - m) // q * q, int(max(xs) + m) // q * q + q
        y0 = int(min(ys) - m) // q * q
        region = QRegion(QRect(max(x0, 0), max(y0, 0), min(x1, w) - max(x0, 0), h - max(y0, 0)))
        if region != self._mask:
            self._mask = region
            self.view.setMask(region)

    # ------------------------------------------------------------ input
    def pressed(self, scene, button, gpos):
        if button == Qt.MouseButton.RightButton:
            self.show_menu(gpos)
        elif button == Qt.MouseButton.MiddleButton and scene == 0:
            self.brain.pet()  # carezza
        elif button == Qt.MouseButton.LeftButton and scene == 0:
            self.dog_drag = (gpos, False)  # clic o presa: si decide muovendo o rilasciando
        elif button == Qt.MouseButton.LeftButton and scene == 1:
            self.drag = (gpos, self.kennel.pos(), False)  # clic o trascinamento: si decide al rilascio

    def drag_dog(self, gpos):
        """Tasto sinistro tenuto premuto sul cane: lo prendi per la collottola e lo sposti."""
        if self.dog_drag is None:
            return
        start, lifted = self.dog_drag
        if not lifted:
            if (gpos - start).manhattanLength() < 6:
                return
            self.dog_drag = (start, True)
            self.close_chat()
            self.brain.pick_up()
        self.brain.hold_at(gpos.x(), gpos.y())

    def release_dog(self):
        if self.dog_drag is None:
            return
        lifted = self.dog_drag[1]
        self.dog_drag = None
        if lifted:
            self.brain.drop()  # lo appoggi: atterra, si scrolla e scodinzola
        elif self.bubble.isVisible():
            self.close_chat()
        else:
            self.brain.call()  # si gira verso di te, poi si apre il fumetto
            QTimer.singleShot(450, self.open_chat)

    def drag_kennel(self, gpos):
        if self.drag is None:
            return
        start, origin, moved = self.drag
        delta = gpos - start
        if not moved and delta.manhattanLength() < 5:
            return
        self.drag = (start, origin, True)
        kw, kh = self.kennel.width(), self.kennel.height()
        self.put_kennel(origin.x() + kw / 2 + delta.x(), origin.y() + kh - dog3d.BASE + delta.y())

    def drop_kennel(self):
        if self.drag is None:
            return
        moved = self.drag[2]
        self.drag = None
        if moved:
            self.cfg["kennel_pos"] = [round(v) for v in self.kennel_pos]
            save_config(self.cfg)
        else:
            self.brain.go_home(run=True)  # clic sulla cuccia: corre a casa

    def api_key(self):
        return os.environ.get("GEMINI_API_KEY") or self.cfg["api_key"]

    def open_chat(self):
        key = self.api_key()
        self.brain.listening = True
        if key:
            self.bubble.say(self.dog.b["greeting"])
            self.brain.perform([self.dog.b["greet_action"]])
        else:
            self.bubble.say("Per parlare mi serve una chiave API Gemini: tasto destro su di me → «Chiave API Gemini…».")
            self.brain.perform(["tilt"])
        self.bubble.input.setEnabled(bool(key))
        self.place_bubble()
        self.bubble.show()
        self.bubble.activateWindow()
        self.bubble.input.setFocus()

    def close_chat(self):
        self.bubble.hide()
        self.brain.listening = self.brain.thinking = False

    def place_bubble(self):
        hx, hy = self.brain.head_screen()
        x, y, w, h = self.areas.rects[self.areas.nearest(self.brain.x, self.brain.y)]
        bw, bh = self.bubble.width(), self.bubble.height()
        bx = int(min(max(hx - bw / 2, x + 8), x + w - bw - 8))
        by = int(max(hy - bh - self.dog.b["R"] * 1.5, y + 8))
        self.bubble.tail_x = hx - bx
        if (bx, by) != (self.bubble.x(), self.bubble.y()):
            self.bubble.move(bx, by)
            self.bubble.update()

    def send_message(self):
        text = self.bubble.input.text().strip()
        if not text:
            return
        if self.chat is None:
            b = self.dog.b
            self.chat = GeminiChat(self.api_key(), system_prompt(b["label"], b["personality"], self.cfg["name"]),
                                   self.cfg["model"])
        name = self.cfg["name"].strip().lower()
        if name and name in text.lower():
            self.brain.perform(["ears_up", "wag"])  # ha sentito il suo nome
        self.bubble.input.clear()
        self.bubble.input.setEnabled(False)
        self.bubble.say("…")
        self.brain.thinking = True
        chat = self.chat

        def work():
            try:
                self.reply_ready.emit(chat.send(text), True)
            except ChatError as err:
                self.reply_ready.emit(f"Qualcosa non va: {err}", False)

        threading.Thread(target=work, daemon=True).start()

    def on_reply(self, text, ok):
        self.brain.thinking = False
        if ok:
            text, actions = parse_reply(text)
        else:
            actions = ["whine"]
        self.brain.perform(actions)
        if self.bubble.isVisible():
            self.bubble.say(text or "…")
            self.bubble.input.setEnabled(True)
            self.bubble.input.setFocus()

    # ------------------------------------------------------------ menu e configurazione
    def show_menu(self, gpos):
        menu = QMenu()
        breeds = menu.addMenu("Razza")
        group = QActionGroup(menu)
        for key, b in dog3d.BREEDS.items():
            a = breeds.addAction(b["label"])
            a.setCheckable(True)
            a.setChecked(key == self.cfg["breed"])
            a.setActionGroup(group)
            a.triggered.connect(lambda _=False, k=key: self.set_breed(k))
        kennel = menu.addMenu("Cuccia nell'angolo (o trascinala dove vuoi)")
        for side, label in (("right", "In basso a destra"), ("left", "In basso a sinistra")):
            a = kennel.addAction(label)
            a.setCheckable(True)
            a.setChecked(self.cfg["kennel"] == side)
            a.triggered.connect(lambda _=False, s=side: self.set_kennel(s))
        menu.addAction("Tira rametto", lambda: self.pick_throw("stick"))
        menu.addAction("Lancia pallina", lambda: self.pick_throw("ball"))
        menu.addAction("Torna nella cuccia", self.brain.go_home)
        menu.addSeparator()
        play = menu.addAction("Gioca con le finestre (ci sale sopra, le tira)")
        play.setCheckable(True)
        play.setChecked(self.cfg["windows"])
        play.setEnabled(self.bridge is not None)
        play.triggered.connect(self.toggle_windows)
        menu.addAction("Nome del cane…", self.ask_name)
        snd = menu.addAction("Suoni")
        snd.setCheckable(True)
        snd.setChecked(self.cfg["sounds"])
        snd.triggered.connect(self.toggle_sounds)
        auto = menu.addAction("Avvia all'accensione del PC")
        auto.setCheckable(True)
        auto.setChecked(autostart_enabled())
        auto.triggered.connect(set_autostart)
        menu.addAction("Chiave API Gemini…", self.ask_api_key)
        menu.addSeparator()
        menu.addAction("Esci", QApplication.quit)
        menu.exec(gpos)

    def pick_throw(self, kind):
        """Copre gli schermi con un velo: il clic sceglie dove cade il giocattolo."""
        what = "il rametto" if kind == "stick" else "la pallina"
        self.close_chat()

        def done(pos=None):
            for w in self.pickers:
                w.close()
            self.pickers = []
            if pos is not None:
                self.brain.throw(kind, pos.x(), pos.y())

        self.pickers = [PickOverlay(sc, f"Clicca dove lanciare {what}  ·  Esc per annullare", done, done)
                        for sc in QApplication.screens()]
        for w in self.pickers:
            w.show()
        under = QApplication.screenAt(QCursor.pos())
        for w in self.pickers:
            if under and w.geometry() == under.geometry():
                w.activateWindow()

    def toggle_sounds(self, on):
        self.cfg["sounds"] = self.sound.enabled = bool(on)
        save_config(self.cfg)

    def toggle_windows(self, on):
        self.cfg["windows"] = self.brain.play_windows = bool(on)
        save_config(self.cfg)

    def ask_name(self):
        name, ok = QInputDialog.getText(None, "Nome del cane", "Come si chiama?", QLineEdit.EchoMode.Normal,
                                        self.cfg["name"])
        if ok:
            self.cfg["name"] = name.strip()[:30]
            self.chat = None
            save_config(self.cfg)
            self.brain.perform(["ears_up", "wag"])

    def set_breed(self, key, save=True):
        self.cfg["breed"] = key
        self.dog.set_breed(key)
        if hasattr(self, "sound"):
            self.sound.set_breed(key)  # voce della razza
        self.view.resize(*self.dog.window_size())
        self.kennel.breed = self.dog.b
        self.kennel.resize(*view3d.kennel_size(self.dog.b))
        self.kennel.update()
        self._mask = None
        self.chat = None  # nuova personalità, nuova conversazione
        self.place_kennel()
        if save:
            save_config(self.cfg)

    def set_kennel(self, side):
        self.cfg["kennel"] = side
        self.cfg.pop("kennel_pos", None)
        save_config(self.cfg)
        self.place_kennel()
        self.brain.go_home()

    def ask_api_key(self):
        key, ok = QInputDialog.getText(None, "Chiave API Gemini",
                                       "Incolla la chiave (https://aistudio.google.com/apikey).\n"
                                       "La variabile d'ambiente GEMINI_API_KEY ha la precedenza.",
                                       QLineEdit.EchoMode.Password, self.cfg["api_key"])
        if ok:
            self.cfg["api_key"] = key.strip()
            self.chat = None
            save_config(self.cfg)


def main():
    for sig in (signal.SIGINT, signal.SIGTERM):  # uscita pulita: rimuove anche lo script KWin
        signal.signal(sig, lambda *_: QApplication.quit())
    setup_log()
    QSurfaceFormat.setDefaultFormat(view3d.surface_format())
    app = QApplication(sys.argv)
    app.setApplicationName("desktop-pet")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(QIcon(str(Path(__file__).with_name("icon.png"))))
    lock = QLockFile(QDir.temp().filePath("doggo.lock"))
    if not lock.tryLock(200):
        print("Il cane è già in giro sul desktop.")  # aperto due volte: un solo cane
        if sys.platform in ("win32", "darwin"):  # senza console il messaggio sopra non lo vedrebbe nessuno
            QMessageBox.information(None, "Doggo", "Doggo è già aperto.\n\nSe non lo vedi, chiudi tutti i processi "
                                    "«Doggo» (Gestione attività → Dettagli) e riaprilo.")
        return
    cfg = load_config()
    if not CONFIG_PATH.exists():
        if OLD_CONFIG.exists():  # porta con sé razza, nome e chiave delle versioni precedenti
            cfg = load_config(OLD_CONFIG)
        save_config(cfg)
    bridge = None
    if sys.platform.startswith("linux"):  # cursore e finestre da KWin: solo KDE Plasma su Wayland
        import kwin_bridge
        bridge = kwin_bridge.start()
        if bridge:
            app.aboutToQuit.connect(kwin_bridge.stop)
    pet = Pet(cfg, bridge)  # noqa: F841 (resta vivo finché gira l'app)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
