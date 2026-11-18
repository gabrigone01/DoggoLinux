"""Su KDE Plasma (Wayland) le app non vedono il mouse né le altre finestre.

Carichiamo un piccolo script KWin che ci manda via D-Bus la posizione globale del cursore, le aree di lavoro
di ogni schermo (pannelli esclusi) e le finestre aperte; e che sposta una finestra quando il cane la tira.
"""
import json
import os
import tempfile
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtClassInfo, pyqtSignal, pyqtSlot
from PyQt6.QtDBus import QDBusConnection, QDBusInterface

SERVICE = "org.doggo.DesktopPet"
PLUGIN = "doggo-desktop-pet"

SCRIPT = """
var SVC = "%s";
function sendAreas() {
    var out = [];
    var screens = workspace.screens;
    for (var i = 0; i < screens.length; i++) {
        var a = workspace.clientArea(KWin.MaximizeArea, screens[i], workspace.currentDesktop);
        out.push([a.x, a.y, a.width, a.height]);
    }
    callDBus(SVC, "/", SVC, "areas", JSON.stringify(out));
}
var lastWindows = "";
function sendWindows() {
    var out = [];
    var list = workspace.stackingOrder;  // dal basso verso l'alto
    for (var i = 0; i < list.length; i++) {
        var w = list[i];
        if (!w.normalWindow || w.minimized || w.skipTaskbar || w.fullScreen) continue;
        if (!(w.onAllDesktops || w.desktops.indexOf(workspace.currentDesktop) >= 0)) continue;
        var g = w.frameGeometry;
        out.push([String(w.internalId), Math.round(g.x), Math.round(g.y), Math.round(g.width), Math.round(g.height),
                  String(w.resourceClass)]);
    }
    var text = JSON.stringify(out);
    if (text !== lastWindows) {
        lastWindows = text;
        callDBus(SVC, "/", SVC, "windows", text);
    }
}
function applyCommands(reply) {
    // il cane sposta una finestra: [id, dx, dy]
    var cmds = JSON.parse(reply || "[]");
    if (!cmds.length) return;
    var all = workspace.windowList();
    for (var c = 0; c < cmds.length; c++) {
        for (var j = 0; j < all.length; j++) {
            var w = all[j];
            if (String(w.internalId) !== cmds[c][0] || w.fullScreen || !w.moveable) continue;
            var g = w.frameGeometry;
            w.frameGeometry = {x: g.x + cmds[c][1], y: g.y + cmds[c][2], width: g.width, height: g.height};
        }
    }
}
var ticks = 0;
var timer = new QTimer();
timer.interval = 40;
timer.timeout.connect(function () {
    var p = workspace.cursorPos;
    callDBus(SVC, "/", SVC, "tick", p.x, p.y, applyCommands);
    if (++ticks %% 4 === 0) sendWindows();
    if (ticks %% 125 === 0) sendAreas();  // ogni 5 s: pannelli o schermi cambiati
});
timer.start();
sendAreas();
sendWindows();
""" % SERVICE


@pyqtClassInfo("D-Bus Interface", SERVICE)
class KWinBridge(QObject):
    cursorMoved = pyqtSignal(int, int)
    areasChanged = pyqtSignal(list)
    windowsChanged = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self._areas = None
        self._cursor = None
        self.pending = []  # spostamenti di finestre da far eseguire a KWin

    @pyqtSlot(int, int, result=str)
    def tick(self, x, y):
        if (x, y) != self._cursor:
            self._cursor = (x, y)
            self.cursorMoved.emit(x, y)
        cmds, self.pending = self.pending, []
        return json.dumps(cmds)

    def move_window(self, wid, dx, dy):
        self.pending.append([wid, int(dx), int(dy)])

    @pyqtSlot(str)
    def windows(self, text):
        try:
            wins = [dict(id=w[0], x=int(w[1]), y=int(w[2]), w=int(w[3]), h=int(w[4]), cls=str(w[5]))
                    for w in json.loads(text)]
        except (ValueError, TypeError, IndexError, KeyError):
            return
        self.windowsChanged.emit([w for w in wins if "desktop-pet" not in w["cls"] and "python" not in w["cls"]])

    @pyqtSlot(str)
    def areas(self, text):
        try:
            rects = [tuple(int(v) for v in r) for r in json.loads(text)]
        except (ValueError, TypeError):
            return
        if rects and rects != self._areas:
            self._areas = rects
            self.areasChanged.emit(rects)


def _kwin(bus):
    return QDBusInterface("org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", bus)


def start():
    """Ritorna il ponte attivo, oppure None se non siamo su KWin/Wayland."""
    if os.environ.get("XDG_SESSION_TYPE") != "wayland" or "KDE" not in os.environ.get("XDG_CURRENT_DESKTOP", ""):
        return None
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected() or not bus.registerService(SERVICE):
        return None
    bridge = KWinBridge()
    bus.registerObject("/", bridge, QDBusConnection.RegisterOption.ExportAllSlots)
    path = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()) / f"{PLUGIN}.js"
    path.write_text(SCRIPT)
    kwin = _kwin(bus)
    kwin.call("unloadScript", PLUGIN)  # eventuale residuo di un'esecuzione precedente
    reply = kwin.call("loadScript", str(path), PLUGIN)
    if reply.errorMessage():
        bus.unregisterService(SERVICE)
        return None
    kwin.call("start")
    return bridge


def stop():
    _kwin(QDBusConnection.sessionBus()).call("unloadScript", PLUGIN)
