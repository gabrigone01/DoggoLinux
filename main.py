#!/usr/bin/env python3
"""Desktop Virtual Pet: un cane in 3D che vive sui tuoi schermi e chiacchiera via Gemini."""
import faulthandler
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
            "model": "gemini-flash-latest", "christmas": False}
# gatto: tiragraffi e lettiera (x, z) nello spazio della cuccia, vedi POST e LITTER in dog.frag
CAT_POST, CAT_LITTER, CAT_POST_TOP = (-17.0, 8.0), (14.0, 6.0), 66.0


def home_point(kx, ky, s, lx, lz):
    """Punto della casa (spazio dello shader: girato di -10°, spostato di 6 in z) → punto a terra sullo schermo."""
    a, lz = math.radians(-10), lz - 6.0
    x, z = math.cos(a) * lx - math.sin(a) * lz, math.sin(a) * lx + math.cos(a) * lz
    return kx + x * s, ky + z * s * math.sin(dog3d.ELEVATION)


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
    faulthandler.enable(sys.stderr)  # crash nativi (driver della scheda video): almeno la traccia nel log
    sys.excepthook = show_error
    qInstallMessageHandler(lambda _mode, _ctx, msg: print(msg))


def show_error(kind, err, tb):
    """Senza console un errore chiuderebbe il cane in silenzio: lo scrivo nel log, lo mostro ed esco."""
    import traceback
    text = "".join(traceback.format_exception(kind, err, tb))
    print(text)
    msg = f"Doggo si è fermato per un errore.\n\n{text[-1500:]}\nDettagli in: {LOG_PATH}"
    if sys.platform == "win32":  # funziona anche prima che Qt sia partito
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, msg, "Doggo", 0x10)
    elif QApplication.instance():
        QMessageBox.critical(None, "Doggo", msg)
    sys.stdout.flush()
    os._exit(1)  # niente finestre di errore a ripetizione a ogni fotogramma


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
        x0, y0 = toy.x - self.W / 2, toy.y - toy.h - self.GROUND
        x1, y1 = x0 + self.W, y0 + self.H
        if toy.thread:  # gomitolo: la finestra si allarga fino al filo srotolato (a terra o avvolto attorno al gatto)
            xs, ys = [q[0] for q in toy.thread], [q[1] - q[2] for q in toy.thread]
            x0, y0, x1, y1 = min(x0, min(xs) - 4), min(y0, min(ys) - 4), max(x1, max(xs) + 4), max(y1, max(ys) + 4)
        self.origin = (int(x0), int(y0))
        size = (int(x1) - self.origin[0] + 1, int(y1) - self.origin[1] + 1)
        if size != (self.width(), self.height()):
            self.resize(*size)
        self.move(*self.origin)
        self.show()
        self.update()

    def paintEvent(self, _):
        if self.toy is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        ox, oy = getattr(self, "origin", (self.toy.x - self.W / 2, self.toy.y - self.toy.h - self.GROUND))
        c = QPointF(self.toy.x - ox, self.toy.y - self.toy.h - oy)
        if self.toy.thread:  # filo di lana, dal capo libero fino sotto il gomitolo; dietro al gatto non si vede
            path, gap = QPainterPath(), True
            for x, y, lift, hidden in self.toy.thread:
                if hidden:
                    gap = True
                elif gap:
                    path.moveTo(x - ox, y - lift - oy)
                    gap = False
                else:
                    path.lineTo(x - ox, y - lift - oy)
            if not gap:
                path.lineTo(c.x(), c.y() + self.toy.h)
            p.setPen(QPen(QColor("#C23048"), 1.1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
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
        elif self.toy.kind == "yarn":  # gomitolo di lana con il filo che si srotola
            r = 5.0 * max(0.55, 1 - 0.45 * self.toy.unwound() / self.toy.THREAD)  # più filo a terra, più piccolo
            p.setPen(QPen(QColor("#B0283E"), 0.9))
            p.setBrush(Qt.BrushStyle.NoBrush)
            if not self.toy.thread:  # capo libero finché non comincia a srotolarsi
                tail = QPainterPath(QPointF(0, -0.5))
                tail.cubicTo(QPointF(-6, 1), QPointF(-9, -1), QPointF(-14, 0.5))
                p.drawPath(tail)
            g = QRadialGradient(QPointF(-1.5, -r - 1.5), r * 1.6)
            g.setColorAt(0, QColor("#F27A8E"))
            g.setColorAt(0.7, QColor("#D33A55"))
            g.setColorAt(1, QColor("#8E1B30"))
            p.setBrush(g)
            p.drawEllipse(QPointF(0, -r), r, r)
            p.translate(0, -r)
            p.rotate(math.degrees(self.toy.angle))
            p.setPen(QPen(QColor(255, 210, 220, 150), 0.6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            for k in range(3):
                p.rotate(60)
                p.drawArc(QRectF(-r * 0.9, -r * 0.45, r * 1.8, r * 0.9), 0, 180 * 16)
        elif self.toy.kind == "mouse":  # topolino a carica: grigio, orecchie rosa, chiavetta che gira
            face = 1 if self.toy.vx >= 0 else -1
            self.face = face if abs(self.toy.vx) > 1 else getattr(self, "face", 1)
            p.scale(self.face, 1)
            p.setPen(QPen(QColor("#6B6B70"), 0.8))
            p.setBrush(Qt.BrushStyle.NoBrush)
            tail = QPainterPath(QPointF(-6, -2))
            tail.cubicTo(QPointF(-11, -1), QPointF(-12, -6), QPointF(-16, -4 + math.sin(self.toy.t * 12) * 1.5))
            p.drawPath(tail)
            body = QPainterPath(QPointF(-7, -1))
            body.cubicTo(QPointF(-7, -8), QPointF(2, -8), QPointF(8, -2))
            body.quadTo(QPointF(9, -1), QPointF(7, 0))
            body.closeSubpath()
            g = QLinearGradient(0, -7, 0, 0)
            g.setColorAt(0, QColor("#B9B9BE"))
            g.setColorAt(1, QColor("#7E7E85"))
            p.setPen(QPen(QColor("#5C5C62"), 0.6))
            p.setBrush(g)
            p.drawPath(body)
            p.setBrush(QColor("#F2A7B3"))
            p.drawEllipse(QPointF(3, -6), 1.9, 1.9)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#1E1E22"))
            p.drawEllipse(QPointF(5.2, -3.6), 0.7, 0.7)
            p.setBrush(QColor("#E67F93"))
            p.drawEllipse(QPointF(8.4, -1.4), 0.9, 0.9)
            p.translate(-2, -7)  # chiavetta della carica
            p.rotate(math.degrees(self.toy.t * 9 if self.toy.spring > 0 else 0.4))
            p.setPen(QPen(QColor("#B8902E"), 1.0))
            p.drawLine(QPointF(0, 0), QPointF(0, -2.5))
            p.setBrush(QColor("#E0B84A"))
            p.drawEllipse(QPointF(0, -3.6), 1.8, 1.1)
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
        w, ground = (190, 120) if c.kind == "santa" else (self.W, self.GROUND)  # slitta con le renne
        if self.width() != w:
            self.resize(w, ground + 20)
        self.move(int(c.x - w / 2), int(c.y - c.h - ground))
        self.show()
        self.update()

    def paintEvent(self, _):
        c = self.c
        if c is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(self.width() / 2, self.height() - 20)
        if c.h < 60:  # ombra a terra
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, int(60 * (1 - c.h / 60))))
            w = dict(cat=28, santa=150).get(c.kind, 10)
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

    def draw_santa(self, p, c):
        """Slitta rossa con Babbo Natale e due renne davanti (verso +x)."""
        flying = c.h > 2 or c.state in ("scared", "flee")
        run = math.sin(c.t * (16 if flying else 6)) * (5 if flying or c.state == "arrive" else 0.6)
        ink = QPen(QColor(40, 25, 20), 0.8)
        for k, rx in enumerate((38, 66)):  # renne
            ph = run if k else -run
            p.setPen(ink)
            p.setBrush(QColor("#8B5A2B"))
            for lx, s in ((-8, 1), (-4, -1), (6, 1), (10, -1)):
                p.drawRect(QRectF(rx + lx + s * ph * 0.4, -14, 2.6, 14 - (abs(ph) * 0.5 if flying else 0)))
            p.drawEllipse(QRectF(rx - 12, -26, 26, 13))
            p.drawEllipse(QPointF(rx + 15, -31), 5.5, 4.5)
            p.drawRect(QRectF(rx + 9, -30, 5, 8))  # collo
            p.setPen(QPen(QColor("#5A3A1A"), 1.4))
            for dx in (-1, 2):  # corna
                p.drawLine(QPointF(rx + 14 + dx, -35), QPointF(rx + 12 + dx * 2, -43))
                p.drawLine(QPointF(rx + 12 + dx * 2, -40), QPointF(rx + 9 + dx * 2, -42))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#E0262A") if k else QColor("#2A1A12"))  # la prima ha il naso rosso
            p.drawEllipse(QPointF(rx + 20.5, -31), 1.8, 1.8)
        p.setPen(QPen(QColor("#6B4A2A"), 0.9))
        p.drawLine(QPointF(18, -22), QPointF(28, -22))  # finimenti
        p.drawLine(QPointF(48, -22), QPointF(56, -22))
        p.setPen(QPen(QColor("#C9A227"), 2.0))  # pattini
        p.drawLine(QPointF(-40, -2), QPointF(18, -2))
        p.drawArc(QRectF(12, -12, 12, 10), -90 * 16, 180 * 16)
        p.setPen(ink)
        p.setBrush(QColor("#7A2A1A"))
        p.drawEllipse(QRectF(-42, -40, 18, 18))  # sacco dei regali
        p.setBrush(QColor("#C8102E"))  # slitta
        sled = QPainterPath()
        sled.moveTo(-36, -6)
        sled.lineTo(14, -6)
        sled.quadTo(22, -10, 18, -24)
        sled.lineTo(-22, -24)
        sled.quadTo(-36, -24, -36, -6)
        p.drawPath(sled)
        p.setBrush(QColor("#C8102E"))  # Babbo Natale
        p.drawEllipse(QRectF(-16, -40, 20, 20))
        p.setBrush(QColor("#F3D2B5"))
        p.drawEllipse(QPointF(-4, -45), 6, 6)
        p.setBrush(QColor("white"))
        p.drawEllipse(QPointF(-1, -41), 5, 4.5)  # barba
        p.setBrush(QColor("#C8102E"))
        hat = QPolygon([QPoint(-11, -49), QPoint(3, -49), QPoint(-14, -60)])
        p.drawPolygon(hat)
        p.setBrush(QColor("white"))
        p.drawEllipse(QPointF(-14, -60), 2.2, 2.2)
        p.drawRect(QRectF(-12, -51, 16, 3))
        p.setBrush(QColor("black"))
        p.drawEllipse(QPointF(-2, -46.5), 0.8, 0.8)
        if c.state in ("scared", "flee"):  # agita il braccio: "ho ho, me ne vado!"
            p.setPen(QPen(QColor("#C8102E"), 3.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(-6, -34), QPointF(-12 + 4 * math.sin(c.t * 18), -52))

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


class SnowWindow(QWidget):
    """Modalità Natale su uno schermo: fiocchi che cadono, neve a terra, alberi addobbati, pupazzi di neve,
    buche e spruzzi quando il cane scava o si rotola. Sta sul fondo come uno sfondo animato: sotto la barra delle
    applicazioni e le finestre (cane e cuccia restano sopra a tutto); i clic ci passano attraverso."""

    def __init__(self, rect, pet):
        super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                         | Qt.WindowType.WindowStaysOnBottomHint | Qt.WindowType.WindowTransparentForInput)
        keep_visible(self)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setGeometry(QRect(*rect))
        self.pet = pet
        rng = pet.brain.rng
        w, h = self.width(), self.height()
        self.flakes = [[rng.uniform(0, w), rng.uniform(0, h), rng.uniform(1.0, 3.2), rng.uniform(0, 6.3)]
                       for _ in range(max(40, w * h // 16000))]
        self.drift = [rng.uniform(0, 1) for _ in range(w // 40 + 2)]  # gobbe della neve sul fondo
        self.bits = []   # [x, y, h, vx, vy, vh, r] spruzzi di neve (coordinate globali)
        self.marks = []  # [x, y, kind, t] buche e impronte di rotolate

    def trees(self):
        """Un solo albero, accanto alla cuccia, dal lato del centro dello schermo."""
        g = self.geometry()
        kx, ky = self.pet.kennel_pos
        if not g.contains(int(kx), int(ky)):
            return []
        side = 1 if kx > g.center().x() else -1
        return [(kx - side * (self.pet.kennel.width() * 0.5 + 40), ky - 6)]

    def step(self, dt):
        b, g = self.pet.brain, self.geometry()
        w, h = self.width(), self.height()
        for f in self.flakes:
            f[3] += dt
            f[1] += f[2] * 18 * dt
            f[0] += math.sin(f[3] * 0.8 + f[2]) * 12 * dt
            if f[1] > h:
                f[0], f[1] = b.rng.uniform(0, w), -5
        here = g.contains(int(b.x), int(b.y))
        if here and b.activity in ("dig", "roll") and b.goal is None:
            yaw = b.dog.yaw
            if b.activity == "dig":  # spruzzi all'indietro, tra le zampe posteriori
                fx, fy, back, n = b.x + math.cos(yaw) * 18, b.y + math.sin(yaw) * 9, yaw + math.pi, 3
            else:  # rotolata: sbuffi tutto intorno
                fx, fy, back, n = b.x, b.y, b.rng.uniform(0, math.tau), 2
            for _ in range(n):
                a = back + b.rng.uniform(-0.7, 0.7)
                v = b.rng.uniform(60, 160)
                self.bits.append([fx, fy, 4.0, math.cos(a) * v, math.sin(a) * v * 0.5, b.rng.uniform(120, 260),
                                  b.rng.uniform(1.5, 3.5)])
            kind = b.activity
            if not self.marks or math.hypot(self.marks[-1][0] - b.x, self.marks[-1][1] - b.y) > 30 \
                    or self.marks[-1][2] != kind:
                self.marks.append([fx, fy, kind, b.t])
        for s in b.snowmen:  # pupazzo appena travolto: palle di neve che volano
            if s["down"] is not None and not s.get("burst") and g.contains(int(s["x"]), int(s["y"])):
                s["burst"] = True
                for _ in range(40):
                    a = b.rng.uniform(0, math.tau)
                    v = b.rng.uniform(60, 240)
                    self.bits.append([s["x"], s["y"], b.rng.uniform(5, 40), math.cos(a) * v, math.sin(a) * v * 0.5,
                                      b.rng.uniform(100, 320), b.rng.uniform(2, 6)])
        for bit in self.bits:
            bit[0] += bit[3] * dt
            bit[1] += bit[4] * dt
            bit[5] -= 900 * dt
            bit[2] += bit[5] * dt
        self.bits = [bit for bit in self.bits if bit[2] > 0][-400:]
        self.marks = [m for m in self.marks if b.t - m[3] < 60][-60:]
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        g = self.geometry()
        w, h = self.width(), self.height()
        snow, shade = QColor(250, 252, 255, 150), QColor(200, 214, 232, 150)  # manto semitrasparente
        # neve a terra sul fondo dello schermo, a gobbe
        drift = QPainterPath()
        drift.moveTo(0, h)
        for i, k in enumerate(self.drift):
            drift.lineTo(i * 40, h - 14 - 10 * k)
        drift.lineTo(w, h)
        drift.closeSubpath()
        p.setPen(QPen(shade, 1.5))
        p.setBrush(snow)
        p.drawPath(drift)
        p.translate(-g.x(), -g.y())  # da qui in coordinate globali
        t = self.pet.brain.t
        for x, y, kind, _ in self.marks:  # buche scavate e impronte delle rotolate
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(150, 170, 200, 150) if kind == "dig" else QColor(190, 205, 228, 120))
            r = 11 if kind == "dig" else 22
            p.drawEllipse(QPointF(x, y), r, r * 0.4)
        for x, y in self.trees():
            self.draw_tree(p, x, y, t)
        for s in self.pet.brain.snowmen:
            self.draw_snowman(p, s, t)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(snow)
        for x, y, hh, *_, r in self.bits:
            p.drawEllipse(QPointF(x, y - hh), r, r)
        p.resetTransform()
        p.setBrush(QColor(255, 255, 255, 220))
        for x, y, r, _ in self.flakes:
            p.drawEllipse(QPointF(x, y), r, r)

    @staticmethod
    def draw_tree(p, x, y, t):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 50))
        p.drawEllipse(QPointF(x, y), 34, 7)
        p.setBrush(QColor("#5C3B1E"))
        p.drawRect(QRectF(x - 5, y - 16, 10, 16))
        for i, (wd, top, bot) in enumerate(((40, -70, -14), (32, -96, -50), (23, -118, -78))):
            p.setBrush(QColor("#1F6B34").darker(100 + i * 8))
            p.drawPolygon(QPolygon([QPoint(int(x - wd), int(y + bot)), QPoint(int(x + wd), int(y + bot)),
                                    QPoint(int(x), int(y + top))]))
            p.setBrush(QColor(250, 252, 255))  # neve sui rami
            p.drawPolygon(QPolygon([QPoint(int(x - wd * 0.55), int(y + (top + bot) / 2 + 6)),
                                    QPoint(int(x), int(y + top)), QPoint(int(x + wd * 0.55), int(y + (top + bot) / 2 + 6)),
                                    QPoint(int(x), int(y + (top + bot) / 2))]))
        cols = ("#E53935", "#FDD835", "#1E88E5", "#E040FB")
        for i, (dx, dy) in enumerate(((-22, -24), (14, -30), (-6, -46), (20, -58), (-16, -64), (8, -84), (-8, -98))):
            on = math.sin(t * 3 + i * 1.7) > -0.2
            c = QColor(cols[i % 4])
            p.setBrush(c if on else c.darker(220))
            p.drawEllipse(QPointF(x + dx, y + dy), 3.4, 3.4)
        star = QPainterPath()
        for k in range(10):
            a, r = -math.pi / 2 + k * math.pi / 5, 9 if k % 2 == 0 else 4
            pt = QPointF(x + math.cos(a) * r, y - 122 + math.sin(a) * r)
            star.moveTo(pt) if k == 0 else star.lineTo(pt)
        star.closeSubpath()
        p.setBrush(QColor("#FFD54F"))
        p.drawPath(star)

    @staticmethod
    def draw_snowman(p, s, t):
        x, y = s["x"], s["y"]
        p.setPen(QPen(QColor(190, 205, 228), 1.2))
        p.setBrush(QColor(250, 252, 255))
        if s["down"] is not None:  # travolto: resta un mucchietto con la carota e il cappello
            k = min((t - s["down"]) / 0.4, 1.0)
            p.drawEllipse(QPointF(x, y - 6), 30 + 6 * k, 10)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#F57C00"))
            p.drawPolygon(QPolygon([QPoint(int(x + 18), int(y - 6)), QPoint(int(x + 30), int(y - 4)),
                                    QPoint(int(x + 18), int(y - 2))]))
            p.setBrush(QColor("#222"))
            p.drawRect(QRectF(x - 26, y - 14, 12, 8))
            return
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 45))
        p.drawEllipse(QPointF(x, y), 26, 6)
        p.setPen(QPen(QColor(190, 205, 228), 1.2))
        p.setBrush(QColor(250, 252, 255))
        for r, cy in ((22, -20), (16, -54), (11, -78)):
            p.drawEllipse(QPointF(x, y + cy), r, r)
        p.setPen(QPen(QColor("#5C3B1E"), 2))  # braccia di rametto
        p.drawLine(QPointF(x - 14, y - 56), QPointF(x - 32, y - 68))
        p.drawLine(QPointF(x + 14, y - 56), QPointF(x + 32, y - 66 + 3 * math.sin(t * 2)))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#222"))
        for dx in (-4, 4):
            p.drawEllipse(QPointF(x + dx, y - 81), 1.6, 1.6)
        for dy in (-60, -50, -40):
            p.drawEllipse(QPointF(x, y + dy), 1.8, 1.8)
        p.drawRect(QRectF(x - 9, y - 90, 18, 3))  # cappello
        p.drawRect(QRectF(x - 6, y - 104, 12, 14))
        p.setBrush(QColor("#F57C00"))
        p.drawPolygon(QPolygon([QPoint(int(x), int(y - 79)), QPoint(int(x + 13), int(y - 77)), QPoint(int(x), int(y - 75))]))
        p.setBrush(QColor("#C62828"))  # sciarpa
        p.drawRoundedRect(QRectF(x - 12, y - 69, 24, 5), 2, 2)
        p.drawRect(QRectF(x + 4, y - 67, 5, 12))


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
        self.toy_on_top = False
        self.critter_windows = []
        self.friend_view = FriendView()
        self.friend_in_front = None
        self.pickers = []
        self.snow = []  # finestre della neve, una per schermo (modalità Natale)
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
        self.set_christmas(cfg["christmas"], save=False)

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
        if self.snow:  # schermi cambiati: neve da rifare
            self.set_christmas(True, save=False)
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
        s = self.dog.b["kscale"]
        cat = self.dog.b.get("cat", False)
        if cat:  # il gatto deve poter stare accanto al palo senza uscire dallo schermo
            dx = home_point(0, 0, s, *CAT_POST)[0]
            kx = max(kx, self.areas.rects[i][0] + self.dog.window_size()[0] / 2 + 8 - dx)
        kh0 = view3d.kennel_size(self.dog.b)[1]  # a Natale la finestra è più alta: la casa resta in fondo
        house = QPolygon([QPoint(int(kw * x), int(kh - kh0 * (1 - y))) for x, y in
                          ((0.12, 1.0), (0.12, 0.4), (0.5, 0.08), (0.88, 0.4), (0.88, 1.0))])
        mask = QRegion(house)  # clic solo sulla sagoma della casetta
        if cat:  # tiragraffi più la striscia in basso con lettiera e ciotole
            px = int(kw / 2 + home_point(0, 0, s, *CAT_POST)[0])
            mask = QRegion(px - int(17 * s), int(kh - kh0 * 0.92), int(34 * s), int(kh0 * 0.92)).united(
                QRegion(0, int(kh - 34 * s), kw, int(34 * s)))
        elif self.kennel.xmas:  # più il fumo del comignolo
            mask = mask.united(QRegion(int(kw * 0.5), 0, int(kw * 0.4), int(kh - kh0 * 0.75)))
        self.kennel.setMask(mask)
        self.kennel_pos = (kx, ky)
        self.kennel.move(int(kx - kw / 2), int(ky + dog3d.BASE - kh))
        # il cane si sdraia davanti alla porta, girato verso il centro dello schermo
        rx, ry, rw, rh = self.areas.rects[i]
        side = 1 if kx > rx + rw / 2 else -1
        self.brain.set_home(kx, ky + 12 * s, side)
        self.brain.post = home_point(kx, ky, s, *CAT_POST) if cat else None
        self.brain.litter = home_point(kx, ky, s, *CAT_LITTER) if cat else None
        self.brain.post_h, self.brain.post_r = CAT_POST_TOP * s, 4.2 * s
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
        if self.dog.fit(rig):  # mossa più grande della finestra: la allargo invece di tagliare il cane
            self.view.resize(*self.dog.window_size())
            self._mask = None
        w, h = self.view.width(), self.view.height()
        self.view.dog, self.view.rig = self.dog, rig
        self.view.move(int(self.brain.x - w / 2), int(self.brain.y + self.dog.below - h))
        # chi è più in basso è più vicino a te; il gatto sul tiragraffi sta sempre davanti al palo
        in_front = self.brain.y >= self.kennel_pos[1] or self.brain.activity in ("climb", "post", "litter")
        if in_front != self.dog_in_front:
            self.dog_in_front = in_front
            (self.view if in_front else self.kennel).raise_()
        self.update_mask(rig, w, h)
        self.view.update()
        if self.bubble.isVisible():
            self.place_bubble()
        toy = self.brain.toy
        self.toy_window.follow(toy)
        held = bool(toy and toy.pins)
        if held and (not self.toy_on_top or self.dog_in_front != getattr(self, "_front_seen", None)):
            self.toy_window.raise_()  # il filo che tiene o che lo avvolge si vede sopra al gatto
        elif self.toy_on_top and not held:
            self.view.raise_()  # tornato a terra: il gatto ci cammina sopra
        self.toy_on_top, self._front_seen = held, self.dog_in_front
        self.show_visitors()
        self.send_window_moves()
        for name in self.brain.sfx:
            self.sound.play(name)
        self.brain.sfx = []
        if abs(self.kennel.food - self.brain.food) > 0.03 or self.kennel.xmas:  # a Natale lucine e fumo si muovono
            self.kennel.food = self.brain.food
            self.kennel.time = self.brain.t
            self.kennel.update()
        for w in self.snow:
            w.step(dt)

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
        if f.dog.fit(v.rig):
            v.resize(*f.dog.window_size())
        v.move(int(f.x - v.width() / 2), int(f.y + f.dog.below - v.height()))
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
            ys.append(h - self.dog.below - sy)
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
            self.chat = GeminiChat(self.api_key(), system_prompt(b["label"], b["personality"], self.cfg["name"], b.get("cat", False)),
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
        if self.brain.cat:  # giochi da gatto
            menu.addAction("Lancia il gomitolo", lambda: self.pick_throw("yarn"))
            menu.addAction("Carica il topolino", lambda: self.pick_throw("mouse"))
        else:
            menu.addAction("Tira rametto", lambda: self.pick_throw("stick"))
            menu.addAction("Lancia pallina", lambda: self.pick_throw("ball"))
        menu.addAction("Sali sul tiragraffi" if self.brain.cat else "Torna nella cuccia", self.brain.go_home)
        menu.addSeparator()
        xmas = menu.addAction("Modalità Natale (neve, Babbo Natale, cuccia addobbata)")
        xmas.setCheckable(True)
        xmas.setChecked(self.cfg["christmas"])
        xmas.triggered.connect(self.set_christmas)
        play = menu.addAction("Gioca con le finestre (ci sale sopra, le tira)")
        play.setCheckable(True)
        play.setChecked(self.cfg["windows"])
        play.setEnabled(self.bridge is not None)
        play.triggered.connect(self.toggle_windows)
        menu.addAction("Nome del gatto…" if self.brain.cat else "Nome del cane…", self.ask_name)
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
        what = dict(stick="il rametto", ball="la pallina", yarn="il gomitolo", mouse="il topolino")[kind]
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

    def set_christmas(self, on, save=True):
        on = bool(on)
        if on and not self.cfg["christmas"] and save:
            self.brain.next_scene = self.brain.t + 15  # appena acceso: presto una scenetta (magari Babbo Natale)
        self.cfg["christmas"] = self.brain.xmas = self.kennel.xmas = on
        if not on:
            self.brain.snowmen = []
        for w in self.snow:
            w.close()
        self.snow = [SnowWindow(r, self) for r in self.areas.rects] if on else []
        for w in self.snow:
            w.show()
        self.kennel.resize(*view3d.kennel_size(self.dog.b, on))
        self.kennel.update()
        self.place_kennel()
        if save:
            save_config(self.cfg)

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
        self.kennel.resize(*view3d.kennel_size(self.dog.b, self.kennel.xmas))
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
