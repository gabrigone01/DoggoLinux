"""Comportamento del cane: attività autonome, sguardo, richiami, giochi, azioni dalla chat e movimento su tutti gli schermi."""
import math
import random
from collections import deque

import dog3d

# durata (s) delle azioni "espressive" sovrapposte all'attività in corso
ACTIONS = dict(wag=2.5, ears_up=2.0, tilt=2.0, bark=1.1, whine=2.5, bow=1.8, jump=1.2, spin=1.6, sit=4.0,
               lie=5.0, sniff=2.5, lick=1.6, yawn=2.2, happy=3.0, think=1.0, shake=1.4, scratch=2.6)
TOWARD_CAMERA = (0.0, math.sin(dog3d.ELEVATION), math.cos(dog3d.ELEVATION))


class Areas:
    """Gli schermi sono un pavimento visto in prospettiva: il cane cammina su tutta l'area di lavoro."""

    def __init__(self, rects):
        self.rects = [tuple(r) for r in rects]  # (x, y, w, h)

    def __len__(self):
        return len(self.rects)

    def at(self, x, y):
        for i, (rx, ry, rw, rh) in enumerate(self.rects):
            if rx <= x < rx + rw and ry <= y < ry + rh:
                return i
        return None

    def nearest(self, x, y):
        def dist(r):
            rx, ry, rw, rh = r
            return math.hypot(max(rx - x, 0, x - rx - rw), max(ry - y, 0, y - ry - rh))
        return min(range(len(self.rects)), key=lambda i: dist(self.rects[i]))

    def clamp(self, i, x, y, mx=0.0, top=0.0, bottom=0.0):
        rx, ry, rw, rh = self.rects[i]
        x0, x1 = rx + mx, rx + rw - mx
        y0, y1 = ry + top, ry + rh - bottom
        return min(max(x, x0), max(x0, x1)), min(max(y, y0), max(y0, y1))

    def edge(self, a, b):
        """Bordo in comune tra due schermi: ((x0, y0), (x1, y1), normale da a verso b) oppure None."""
        ax, ay, aw, ah = self.rects[a]
        bx, by, bw, bh = self.rects[b]
        if abs(ax + aw - bx) <= 2 or abs(bx + bw - ax) <= 2:
            lo, hi = max(ay, by), min(ay + ah, by + bh)
            if hi - lo >= 60:
                x = ax + aw if abs(ax + aw - bx) <= 2 else ax
                return (x, lo), (x, hi), (1 if x == ax + aw else -1, 0)
        if abs(ay + ah - by) <= 2 or abs(by + bh - ay) <= 2:
            lo, hi = max(ax, bx), min(ax + aw, bx + bw)
            if hi - lo >= 60:
                y = ay + ah if abs(ay + ah - by) <= 2 else ay
                return (lo, y), (hi, y), (0, 1 if y == ay + ah else -1)
        return None

    def route(self, a, b):
        """Percorso a piedi tra due schermi (lista di indici) o None se non si toccano."""
        prev, todo = {a: None}, deque([a])
        while todo:
            i = todo.popleft()
            if i == b:
                path = []
                while i is not None:
                    path.append(i)
                    i = prev[i]
                return path[::-1]
            for j in range(len(self.rects)):
                if j not in prev and self.edge(i, j):
                    prev[j] = i
                    todo.append(j)
        return None


GRAVITY = 1500.0  # px/s² (sull'altezza da terra)


class Toy:
    """Pallina o rametto: (x, y) è il punto a terra sullo schermo, h l'altezza in volo."""

    def __init__(self, kind, x, y, h=0.0, vx=0.0, vy=0.0, vh=0.0):
        self.kind, self.x, self.y, self.h = kind, x, y, h
        self.vx, self.vy, self.vh = vx, vy, vh
        self.angle, self.spin = 0.0, (9.0 if kind == "stick" else 0.0)
        self.state = "flying"   # flying, rest, carried
        self.idle = 0.0

    def step(self, dt, areas):
        if self.state != "flying":
            return
        nx, ny = self.x + self.vx * dt, self.y + self.vy * dt
        if areas.at(nx, ny) is None:  # bordo degli schermi: rimbalza
            if areas.at(nx, self.y) is None:
                self.vx = -self.vx * 0.5
            if areas.at(self.x, ny) is None:
                self.vy = -self.vy * 0.5
            nx, ny = self.x, self.y
        self.x, self.y = nx, ny
        self.vh -= GRAVITY * dt
        self.h += self.vh * dt
        self.angle += self.spin * dt
        if self.h <= 0:
            self.h = 0.0
            if self.kind == "ball" and self.vh < -150:
                self.vh = -self.vh * 0.5
                self.vx, self.vy = self.vx * 0.8, self.vy * 0.8
            else:
                self.vh = 0.0
                self.spin *= 0.5
                k = math.exp(-(1.3 if self.kind == "ball" else 7.0) * dt)
                self.vx, self.vy = self.vx * k, self.vy * k
                if self.kind == "ball":
                    self.angle += math.hypot(self.vx, self.vy) * dt / 4.5
                if math.hypot(self.vx, self.vy) < 6:
                    self.vx = self.vy = 0.0
                    self.state = "rest"


class Brain:
    def __init__(self, dog, areas, rng=None):
        self.dog = dog
        self.rng = rng or random.Random()
        self.areas = areas
        rx, ry, rw, rh = areas.rects[0]
        self.x, self.y = rx + rw / 2, ry + rh - 40   # punto a terra sotto il cane (coordinate globali)
        self.home = (self.x, self.y, 1)  # davanti alla cuccia; lato dello schermo in cui si trova
        self.goal = None                # (x, y)
        self.run = False
        self.activity, self.timer = "stand", 2.0
        self.overlays = []              # [nome, tempo trascorso, durata]
        self.queue = deque()
        self.gaze, self.gaze_timer, self.gaze_dir = None, 0.0, (1.0, 0.0, 0.0)
        self.listening = self.thinking = False
        self.cursor = None
        self.cursor_moved_at = -99.0
        self.cursor_trail = deque()
        self.t = 0.0
        self.next_blink = 2.0
        self.home_run = False
        self.toy = None
        self.phase = None               # fase del gioco in corso
        self.count = 0
        self.food = 1.0                 # crocchette nella ciotola
        self.bowl = None                # (x, y) della ciotola
        self.origin = None
        self.windows = []               # finestre aperte, dal basso verso l'alto: dict(id, x, y, w, h)
        self.window_cmds = []           # spostamenti da far eseguire: [id, dx, dy]
        self.play_windows = True
        self.leap = None                # salto: (t, durata, x0, y0, x1, y1)
        self.perch = None               # seduto su una finestra: (id, distanza dal bordo sinistro)
        self.target = None              # finestra scelta per giocare
        self.zig = 1                    # lato dello zig-zag quando la meta è quasi in verticale
        self.held = False               # preso in braccio col mouse

    # ------------------------------------------------------------ comandi esterni
    @property
    def ground_y(self):
        return self.y

    def set_home(self, x, y, side):
        self.home = (x, y, side)

    def place_home(self):
        self.x, self.y = self.home[0], self.home[1]

    def call(self):
        """Clic sul cane: si ferma, si gira e ti guarda."""
        self.goal = None
        self.start("attend", 6.0)
        self.perform(["ears_up", "wag"])

    def come_to(self, gx, gy):
        """Richiamo col mouse (scuotendolo): corre sotto al cursore e poi ti guarda."""
        if self.areas.at(gx, gy) is None:
            return
        self.go(gx, gy + 30, run=True)  # si ferma col muso sotto al cursore
        self.activity, self.timer = "come", 30.0
        self.perform(["ears_up"])

    def go_home(self, run=False):
        self.go(self.home[0], self.home[1], run=run)
        self.activity, self.timer = "home", 60.0
        self.home_run = run

    def pet(self):
        """Clic con la rotella: una carezza. Reagisce a modo suo."""
        self.goal = None
        kind = self.rng.choices(["petted", "givepaw", "bellyrub"], weights=[45, 35, 20])[0]
        self.start(kind, 4.5)

    def throw(self, kind, tx, ty):
        """Lancia rametto o pallina verso un punto dello schermo; lui lo rincorre e lo riporta."""
        _, hy = self.head_screen()
        T = 0.75
        h0 = max(self.y - hy, 0.0)  # parte dalla bocca e atterra proprio dove hai cliccato
        self.toy = Toy(kind, self.x, self.y, h0, (tx - self.x) / T, (ty - self.y) / T, (0.5 * GRAVITY * T * T - h0) / T)
        self.origin = (self.x, self.y)
        self.goal = None
        self.dog.carry = 0
        self.activity, self.timer, self.phase = "fetch", 60.0, "watch"
        self.perform(["ears_up"])

    LIFT = 22  # di quanto lo sollevi da terra (px): resta l'ombra sotto

    def pick_up(self):
        """Preso per la collottola: smette quello che stava facendo."""
        self.held = True
        self.goal = self.perch = self.leap = None
        self.dog.carry = 0
        if self.activity in ("fetch", "play"):
            self.toy = None if self.activity == "play" else self.toy
        self.activity, self.timer, self.phase = "held", 1e9, None

    def hold_at(self, gx, gy):
        """Il cursore tiene il cane sul dorso: il punto a terra sta sotto."""
        b = self.dog.b
        self.x, self.y = gx, gy + b["Hs"] + b["rc"] * 1.4 + self.LIFT

    def drop(self):
        self.held = False
        i = self.areas.at(self.x, self.y)
        i = self.areas.nearest(self.x, self.y) if i is None else i
        self.x, self.y = self.areas.clamp(i, self.x, self.y, *self.margins())
        self.start("stand", 2.0)
        self.perform(["shake", "wag"])

    def perform(self, actions):
        for a in actions:
            if a in ACTIONS:
                self.queue.append(a)

    # ------------------------------------------------------------ ciclo
    def update(self, dt, cursor=None):
        self.t += dt
        self.track_cursor(cursor)
        self.follow_perch()
        if self.toy:
            self.toy.step(dt, self.areas)
            if self.toy.state == "rest" and self.activity not in ("fetch", "play"):
                self.toy.idle += dt
                if self.toy.idle > 25:
                    self.toy = None  # dopo un po' il gioco abbandonato sparisce
        self.food = min(1.0, self.food + dt / 900)  # la ciotola si riempie piano piano
        dog = self.dog
        T = dict(dog3d.POSE_DEFAULTS)
        if self.held:  # in braccio: zampe penzoloni, coda giù che scodinzola, ti guarda
            T.update(hop=self.LIFT, tailUp=-0.5, wagAmp=0.45, wagFreq=3.5, ears=-0.4, jaw=0.3, tongue=0.5,
                     headRoll=0.12 * math.sin(self.t * 2.0))
            dog.speed = 0.0
            self.gaze = "camera"
            self.run_overlays(dt, T)
            self.look(dt, T)
            dog.target = T
            dog.step(dt)
            return
        moved = self.move(dt)
        if not moved:
            dog.speed = 0.0 if self.activity != "spin" else 70.0
        self.run_activity(dt, T)
        self.run_overlays(dt, T)
        if self.goal is not None:  # per camminare si alza: niente pose a terra mentre si sposta
            T.update(front=0.0, rear=0.0, belly=0.0, paw=0.0, dig=0.0, scratch=0.0)
        if self.leap:  # salto: arco in aria con le zampe raccolte
            t, dur, x0, y0, x1, y1 = self.leap
            t = min(t + dt, dur)
            k = t / dur
            self.x, self.y = lerp(x0, x1, k), lerp(y0, y1, k)
            T.update(hop=math.sin(math.pi * k) * (22 + 0.25 * abs(y1 - y0)), rear=0.3, front=0.2, ears=0.6, tailUp=0.7)
            self.leap = (t, *self.leap[1:]) if t < dur else None
            self.dog.speed = 0.0
        self.look(dt, T)
        if self.t > self.next_blink:
            T["eyes"] = 0.0
            if self.t > self.next_blink + 0.12:
                self.next_blink = self.t + self.rng.uniform(2.5, 6.0)
        dog.target = T
        dog.step(dt)

    # ------------------------------------------------------------ attività autonome
    def start(self, activity, duration):
        self.activity, self.timer = activity, duration
        if activity == "spin":
            self.dog.yaw_target += math.tau * self.rng.choice((1, -1))

    def choose(self):
        """Il cane si fa gli affari suoi: sceglie la prossima attività."""
        ind = self.dog.b["independence"]
        options = [("wander", 26), ("stand", 12), ("sit", 10), ("lie", 7), ("sniff", 10), ("scratch", 4),
                   ("stretch", 4), ("shake", 3), ("spin", 2 + 3 * ind), ("home", 5), ("explore", 5 + 5 * ind),
                   ("eat", 5 * self.food), ("play", 6), ("dig", 4), ("howl", 1.5), ("roll", 3), ("zoom", 3),
                   ("hop", 2), ("perch", 6 if self.perch_spot() else 0), ("tug", 4 if self.tug_plan() else 0)]
        r = self.rng.uniform(0, sum(w for _, w in options))
        for name, w in options:
            r -= w
            if r <= 0:
                break
        if name == "eat" and not self.bowl:
            name = "sit"  # niente ciotola (ancora): si siede e basta
        if name == "wander":
            self.go(*self.random_point(self.here()))
            self.activity, self.timer = "wander", 40.0
        elif name == "explore" and len(self.areas) > 1:
            self.go(*self.random_point(self.rng.choice([i for i in range(len(self.areas)) if i != self.here()])))
            self.activity, self.timer = "wander", 60.0
        elif name == "home":
            self.go_home()
        elif name == "eat" and self.bowl:
            bx, by = self.bowl
            i = self.areas.nearest(bx, by)
            mx = self.dog.window_size()[0] / 2
            right = bx + self.reach() + mx <= self.areas.rects[i][0] + self.areas.rects[i][2]
            self.go(bx + self.reach() if right else bx - self.reach(), by)
            self.activity, self.timer, self.phase = "eat", 60.0, "go"
        elif name == "play" and self.home:
            hx, hy, side = self.home
            a = math.pi + self.rng.uniform(-1.0, 1.0) if side > 0 else self.rng.uniform(-1.0, 1.0)
            v = self.rng.uniform(170, 300)
            self.toy = Toy("ball", hx, hy, 6.0, math.cos(a) * v, math.sin(a) * v * 0.6, 260.0)
            self.activity, self.timer, self.phase, self.count = "play", 60.0, "chase", self.rng.randint(3, 5)
            self.origin = (hx, hy)
            self.perform(["bow"])
        elif name == "perch":
            win, px = self.perch_spot()
            self.target = (win["id"], px - win["x"])
            self.go(px, win["y"] + 45)
            self.activity, self.timer, self.phase = "perch", 60.0, "go"
        elif name == "tug":
            plan = self.tug_plan()
            self.target = plan
            self.go(plan["x"], plan["y"])
            self.activity, self.timer, self.phase = "tug", 40.0, "go"
        elif name == "zoom":
            self.activity, self.timer, self.count = "zoom", 30.0, self.rng.randint(3, 5)
            self.zoom_next()
        elif name == "hop":
            self.start("stand", 2.0)
            self.perform(["jump", "wag"])
        elif name == "sniff":
            a, d = self.rng.uniform(0, math.tau), self.rng.uniform(40, 140)
            self.go(self.x + math.cos(a) * d, self.y + math.sin(a) * d * 0.5)
            self.activity, self.timer = "sniff", 9.0
        else:
            dur = dict(stand=(3, 8), sit=(5, 14), lie=(8, 20), scratch=(2, 3), stretch=(1.6, 2.2),
                       shake=(1.2, 1.5), spin=(1.6, 2.2), dig=(2.5, 4), howl=(2.2, 3), roll=(3, 4.5)).get(name, (3, 6))
            self.start(name, self.rng.uniform(*dur))

    def run_activity(self, dt, T):
        a = self.activity
        self.timer -= dt
        # di base è un cane contento: bocca socchiusa con la lingua, coda su che scodinzola piano
        T.update(tailUp=0.35, wagAmp=0.28, wagFreq=3.5, jaw=self.dog.b.get("smile", 0.3), tongue=0.6, ears=0.15)
        if a in ("fetch", "play", "eat", "zoom"):
            self.games(dt, T)
            a = self.activity
        if a in ("perch", "tug"):
            self.window_games(dt, T)
            a = self.activity
        if a in ("wander", "home", "come", "sniff") and self.goal is None:
            if a == "home":
                # davanti alla porta, di tre quarti verso di te; se è corso qui resta sveglio un po'
                self.dog.yaw_target = nearest_angle(self.dog.yaw, math.pi / 2 - 0.5 * self.home[2])
                if self.home_run:
                    self.start("lie", self.rng.uniform(10, 20))
                    self.perform(["happy"])
                else:
                    self.start("sleep", self.rng.uniform(30, 90))
            elif a == "come":
                self.start("attend", 8.0)
            elif a == "sniff":
                self.start("sniffing", self.rng.uniform(2, 4))
            else:
                self.choose()
            a = self.activity
        if self.listening and a not in ("petted", "givepaw", "bellyrub"):
            a = "attend"
        POSES = dict(
            petted=dict(rear=1.0, eyes=0.12, headPitch=-0.35, headRoll=0.25 * math.sin(self.t * 1.5), ears=-0.6,
                        wagAmp=0.6, wagFreq=4.0, jaw=0.35, tongue=0.5, tailUp=0.5),
            givepaw=dict(rear=1.0, paw=1.0, ears=0.6, wagAmp=0.5, wagFreq=4.0, tailUp=0.5),
            bellyrub=dict(front=1.0, rear=1.0, belly=1.0, jaw=0.5, tongue=0.8, eyes=0.5, wagAmp=0.5, wagFreq=4.0),
            dig=dict(front=0.25, dig=1.0, headPitch=0.7, jaw=0.0, tongue=0.0, ears=0.4, tailUp=0.6, wagAmp=0.3),
            howl=dict(rear=1.0, headPitch=-0.95, jaw=0.5 + 0.08 * math.sin(self.t * 5), tongue=0.0, ears=-0.5, eyes=0.3),
            roll=dict(front=1.0, rear=1.0, belly=1.0, jaw=0.4, tongue=0.6, wagAmp=0.4, wagFreq=3.0),
        )
        if a in POSES:
            T.update(POSES[a])
            if a in ("petted", "givepaw", "bellyrub"):
                self.gaze = "camera"
        if a in ("sit", "attend"):
            T["rear"] = 1.0
        if a in ("lie", "sleep"):
            T["front"] = T["rear"] = 1.0
        if a == "sleep":
            T.update(eyes=0.0, headPitch=0.35, ears=-0.3, tailUp=-0.6, wagAmp=0.0, breath=0.8, jaw=0.0, tongue=0.0)
        if a in ("sniff", "sniffing"):
            T.update(headPitch=0.75, jaw=0.0, tongue=0.0)
            T["headYaw"] = 0.25 * math.sin(self.t * 5)
            T["ears"] = 0.3
        if a == "scratch":
            T.update(rear=1.0, scratch=1.0, headRoll=0.35, headYaw=0.35, eyes=0.35, tongue=0.0)
        if a == "stretch":
            T.update(front=1.0, tailUp=0.8, wagAmp=0.35, wagFreq=6, jaw=0.25)
        if a == "shake":
            T.update(shake=1.0, eyes=0.4)
        if a == "attend":
            T.update(ears=0.8, tailUp=0.6, wagAmp=0.5, wagFreq=8)
            if self.dog.key == "golden":
                T.update(jaw=0.35, tongue=0.5, breath=2.0)
        if self.goal and self.run:
            T.update(jaw=0.4, tongue=0.6, breath=2.0, ears=-0.2, tailUp=0.4)
        if self.thinking:
            T.update(headRoll=0.3, ears=0.7)
        if self.timer <= 0 and not self.listening:
            if a in ("attend", "sleep", "sniffing", "stand", "sit", "lie", "scratch", "stretch", "shake", "spin",
                     "petted", "givepaw", "bellyrub", "dig", "howl", "roll"):
                if a == "roll":
                    self.perform(["shake"])
                if a == "dig":
                    self.perform(["sniff"])
                self.choose()

    # ------------------------------------------------------------ giochi e pappa
    def reach(self):
        """Distanza tra il punto a terra del cane e la sua bocca (muso abbassato)."""
        b = self.dog.b
        return b["Lb"] * 0.5 + b["rc"] * 0.5 + b["neck"] * 0.5 + b["R"] * 0.6 + b["muzzle"] * 0.6

    def zoom_next(self):
        self.go(*self.random_point(self.here()), run=True)

    def chase_toy(self):
        """Corre fino ad avere la bocca sul giocattolo, arrivando dal lato in cui si trova."""
        toy = self.toy
        dx, dy = self.x - toy.x, self.y - toy.y
        n = math.hypot(dx, dy) or 1.0
        self.go(toy.x + dx / n * self.reach(), toy.y + dy / n * self.reach() * 0.5, run=True)

    def face(self, tx, ty):
        self.dog.yaw_target = nearest_angle(self.dog.yaw, math.atan2(ty - self.y, tx - self.x))

    def games(self, dt, T):
        a, ph = self.activity, self.phase
        self.phase_t = getattr(self, "phase_t", 0.0) + dt
        if a == "zoom":
            T.update(jaw=0.5, tongue=0.8, ears=-0.4, tailUp=0.5, wagAmp=0.4, breath=2.0)
            if self.goal is None:
                self.count -= 1
                if self.count <= 0:
                    self.perform(["bow"])
                    self.start("stand", 2.0)
                else:
                    self.zoom_next()
            return
        if a == "eat":
            if ph == "go" and self.goal is None:
                self.face(*self.bowl)
                self.phase, self.phase_t = "eating", 0.0
            elif ph == "eating":
                chew = 0.32 * max(0.0, math.sin(self.t * 9))
                T.update(headPitch=0.95, jaw=chew, tongue=0.0, ears=0.1, tailUp=0.5, wagAmp=0.35, wagFreq=3.0)
                self.food = max(0.0, self.food - dt / 14)
                if self.phase_t > 7 or self.food <= 0:
                    self.perform(["lick"])
                    self.start("sit", 4.0)
            return
        toy = self.toy
        if toy is None:
            self.start("stand", 2.0)
            return
        if ph == "watch":  # segue il volo con lo sguardo, poi parte di corsa
            T.update(ears=1.0, tailUp=0.8, wagAmp=0.5, wagFreq=4.0, front=0.35)
            if self.phase_t > 0.35:
                self.phase, self.phase_t = "chase", 0.0
        elif ph == "chase":
            T.update(jaw=0.45, tongue=0.6, ears=0.3, tailUp=0.6, breath=2.0)
            self.chase_toy()
            if self.goal is not None and math.hypot(self.goal[0] - self.x, self.goal[1] - self.y) < 2:
                self.goal = None
            if self.goal is None and toy.state == "rest":  # arrivato: muso sul giocattolo
                self.face(toy.x, toy.y)
                nudge = a == "play" and self.count > 0
                self.phase, self.phase_t = ("nudge" if nudge else "pick"), 0.0
        elif ph in ("pick", "nudge"):
            T.update(headPitch=0.95, jaw=0.3, tongue=0.0, ears=0.5, tailUp=0.7, wagAmp=0.5, wagFreq=4.0)
            if self.phase_t > 0.45:
                if ph == "nudge":  # colpo di muso: la pallina riparte e lui la rincorre
                    self.count -= 1
                    a = math.atan2(toy.y - self.y, toy.x - self.x) + self.rng.uniform(-0.5, 0.5)
                    v = self.rng.uniform(220, 420)
                    toy.state, toy.vx, toy.vy, toy.vh = "flying", math.cos(a) * v, math.sin(a) * v * 0.6, self.rng.uniform(120, 260)
                    self.phase, self.phase_t = "chase", 0.0
                else:
                    toy.state = "carried"
                    self.dog.carry = 1 if toy.kind == "ball" else 2
                    self.go(*self.origin, run=a == "fetch")
                    self.phase, self.phase_t = "return", 0.0
        elif ph == "return":
            T.update(jaw=0.28, tongue=0.0, tailUp=0.75, wagAmp=0.5, wagFreq=4.0, ears=0.4)
            if self.goal is None:
                self.dog.yaw_target = nearest_angle(self.dog.yaw, math.pi / 2)
                self.phase, self.phase_t = "drop", 0.0
        elif ph == "drop":
            T.update(headPitch=0.8, jaw=0.4, tongue=0.0)
            if self.phase_t > 0.5:
                self.dog.carry = 0
                if a == "play":
                    self.toy = None  # la rimette in cuccia
                    self.start("lie", self.rng.uniform(6, 12))
                else:
                    toy.state, toy.h, toy.vx, toy.vy, toy.vh = "rest", 0.0, 0.0, 0.0, 0.0
                    toy.x = self.x + math.cos(self.dog.yaw) * self.reach()
                    toy.y = self.y + math.sin(self.dog.yaw) * self.reach() * 0.5
                    toy.idle = 0.0
                    self.start("attend", 7.0)  # seduto, ti guarda: "ancora!"
                    self.perform(["wag"])
        # mentre gioca segue la pallina con lo sguardo
        if ph in ("watch", "chase") and toy.state != "carried":
            self.gaze, self.gaze_timer = "toy", 0.5

    # ------------------------------------------------------------ finestre
    def window_at(self, x, y):
        """Finestra visibile in quel punto (la più in alto), oppure None."""
        for w in reversed(self.windows):
            if w["x"] <= x < w["x"] + w["w"] and w["y"] <= y < w["y"] + w["h"]:
                return w
        return None

    def maximized(self, w):
        i = self.areas.nearest(w["x"] + w["w"] / 2, w["y"] + w["h"] / 2)
        rx, ry, rw, rh = self.areas.rects[i]
        return w["w"] >= rw - 12 and w["h"] >= rh - 12

    def perch_spot(self):
        """Un punto libero sul bordo superiore di una finestra dove sedersi, oppure None."""
        if not self.play_windows:
            return None
        mx, top, _ = self.margins()
        spots = []
        for w in self.windows:
            if self.maximized(w) or w["w"] < 200:
                continue
            for k in (0.12, 0.25, 0.38, 0.5, 0.62, 0.75, 0.88):
                px = w["x"] + w["w"] * k
                i = self.areas.at(px, w["y"] + 1)
                # sopra la finestra serve spazio visibile per il cane: anche su un altro schermo (es. quello sopra)
                if i is None or self.areas.at(px, w["y"] - top - 4) is None:
                    continue
                x0, x1 = self.areas.rects[i][0] + mx, self.areas.rects[i][0] + self.areas.rects[i][2] - mx
                if x0 <= px <= x1 and self.window_at(px, w["y"] + 2) is w:  # bordo non coperto da altre finestre
                    spots.append((w, px))
        return self.rng.choice(spots) if spots else None

    def tug_plan(self):
        """Una finestra da addentare per un bordo laterale e tirare di lato, oppure None."""
        if not self.play_windows:
            return None
        mx, top, bottom = self.margins()
        reach = self.reach()
        plans = []
        for w in self.windows:
            if self.maximized(w):
                continue
            gy = w["y"] + w["h"] - 30
            for side in (1, -1):
                edge = w["x"] + w["w"] if side > 0 else w["x"]
                i = self.areas.at(edge + side * 4, gy)
                if i is None or self.window_at(edge - side * 2, gy) is not w:
                    continue
                rx, ry, rw, rh = self.areas.rects[i]
                room = (rx + rw - mx - (edge + reach)) if side > 0 else (edge - reach - (rx + mx))
                if room < 90 or not (ry + top <= gy <= ry + rh - bottom):
                    continue
                pull = min(room - 10, self.rng.uniform(80, 140))
                plans.append(dict(id=w["id"], side=side, x=edge + side * reach, y=gy, pull=pull))
        return self.rng.choice(plans) if plans else None

    def find_window(self, wid):
        return next((w for w in self.windows if w["id"] == wid), None)

    def follow_perch(self):
        """Seduto su una finestra: la segue se la sposti, scende se sparisce."""
        if not self.perch or self.leap:
            return
        w = self.find_window(self.perch[0])
        if w is None or self.window_at(w["x"] + self.perch[1], w["y"] + 2) is not w:
            self.perch = None
            self.jump_to(self.x, self.y + 60)
            self.start("stand", 1.5)
            return
        self.x, self.y = w["x"] + self.perch[1], w["y"]

    def jump_to(self, x, y, dur=0.55):
        self.goal = None
        self.leap = (0.0, dur, self.x, self.y, x, y)

    def window_games(self, dt, T):
        a, ph = self.activity, self.phase
        self.phase_t = getattr(self, "phase_t", 0.0) + dt
        if a == "perch":
            wid, off = self.target
            w = self.find_window(wid)
            if w is None and ph != "down":
                self.perch = None
                self.start("stand", 1.0)
                return
            if ph == "go" and self.goal is None:
                self.face(w["x"] + off, w["y"])
                self.jump_to(w["x"] + off, w["y"])
                self.phase, self.phase_t = "up", 0.0
            elif ph == "up" and not self.leap:
                self.perch = (wid, off)
                self.phase, self.phase_t = "sit", 0.0
                self.timer = self.rng.uniform(10, 25)
                self.sit_pose = self.rng.choice(["sit", "sit", "lie"])
                self.perform(["wag"])
            elif ph == "sit":
                T["rear"] = 1.0
                if self.sit_pose == "lie":
                    T["front"] = 1.0
                if self.timer <= 0:
                    self.perch = None
                    self.jump_to(self.x + self.rng.uniform(-30, 30), min(self.y + 70, self.areas.rects[self.here()][1] + self.areas.rects[self.here()][3] - dog3d.BASE))
                    self.phase = "down"
            elif ph == "down" and not self.leap:
                self.choose()
            return
        plan = self.target
        w = self.find_window(plan["id"])
        if w is None:
            self.start("stand", 1.0)
            return
        if ph == "go" and self.goal is None:
            self.dog.yaw_target = nearest_angle(self.dog.yaw, 0.0 if plan["side"] < 0 else math.pi)  # verso la finestra
            self.phase, self.phase_t = "bite", 0.0
            self.pulled = 0.0
        elif ph == "bite":  # addenta il bordo
            T.update(front=0.3, headPitch=0.15, jaw=0.6 if self.phase_t < 0.3 else 0.12, tongue=0.0, ears=-0.3,
                     tailUp=0.7, wagAmp=0.5, wagFreq=4.0)
            if self.phase_t > 0.6:
                self.phase, self.phase_t = "pull", 0.0
        elif ph == "pull":  # cammina all'indietro tirando la finestra
            T.update(front=0.35, headPitch=0.1, headYaw=0.18 * math.sin(self.t * 9), jaw=0.12, tongue=0.0,
                     ears=-0.5, tailUp=0.8, wagAmp=0.6, wagFreq=4.0)
            step = 38 * dt
            self.x += plan["side"] * step
            self.dog.speed = -38.0
            self.pulled += step
            self.window_cmds.append([plan["id"], plan["side"] * step, 0.0])
            if self.pulled >= plan["pull"]:
                self.dog.speed = 0.0
                self.perform(["shake", "wag"])
                self.start("stand", 2.0)

    # ------------------------------------------------------------ azioni espressive
    def run_overlays(self, dt, T):
        if self.queue and not self.overlays:
            name = self.queue.popleft()
            self.overlays.append([name, 0.0, ACTIONS[name]])
            if name == "spin":
                self.dog.yaw_target += math.tau
        for ov in self.overlays:
            ov[1] += dt
            name, tau, dur = ov
            k = tau / dur
            if name == "wag":
                T.update(wagAmp=0.65, wagFreq=10, tailUp=0.75)
            elif name == "ears_up":
                T["ears"] = 1.0
            elif name == "tilt":
                T.update(headRoll=0.45, ears=0.7)
            elif name == "bark":
                pulse = (tau * 3.2) % 1.0 < 0.45 and tau < 0.95
                T.update(jaw=1.0 if pulse else 0.05, ears=0.9, tailUp=0.6, headPitch=-0.25 if pulse else -0.1)
                T["hop"] = 2.0 if pulse else 0.0
            elif name == "whine":
                T.update(ears=-1.0, headPitch=0.45, tailUp=-0.9, wagAmp=0.12, wagFreq=2, eyes=0.6,
                         jaw=0.08 * (1 + math.sin(tau * 9)))
            elif name == "bow":
                T.update(front=1.0, rear=0.0, tailUp=0.9, wagAmp=0.6, wagFreq=9, jaw=0.35, tongue=0.4)
            elif name == "jump":
                T["hop"] = 16 * math.sin(math.pi * ((tau % 0.6) / 0.6))
                T.update(rear=0.25, ears=0.8, tailUp=0.8, wagAmp=0.5, wagFreq=9)
            elif name == "sit":
                T["rear"] = 1.0
            elif name == "lie":
                T["front"] = T["rear"] = 1.0
            elif name == "sniff":
                T.update(headPitch=0.75, headYaw=0.25 * math.sin(tau * 9), ears=0.3)
            elif name == "lick":
                T.update(jaw=0.3, tongue=1.0 if (tau * 2.5) % 1.0 < 0.5 else 0.0)
            elif name == "yawn":
                T.update(jaw=math.sin(math.pi * k) ** 0.7, eyes=0.0, headPitch=-0.35, tongue=0.4, ears=-0.4)
            elif name == "happy":
                T.update(jaw=0.5, tongue=0.85, breath=2.0, wagAmp=0.6, wagFreq=10, tailUp=0.7)
            elif name == "think":
                T.update(headRoll=0.35, ears=0.7)
            elif name == "shake":
                T.update(shake=1.0, eyes=0.4)
            elif name == "scratch":
                T.update(rear=1.0, scratch=1.0, headRoll=0.35, headYaw=0.35, eyes=0.35)
        self.overlays = [ov for ov in self.overlays if ov[1] < ov[2]]

    # ------------------------------------------------------------ sguardo
    def track_cursor(self, cursor):
        if cursor is None:
            return
        if self.cursor is None or abs(cursor[0] - self.cursor[0]) + abs(cursor[1] - self.cursor[1]) > 3:
            self.cursor_moved_at = self.t
        self.cursor = cursor
        trail = self.cursor_trail
        trail.append((self.t, cursor[0]))
        while trail and self.t - trail[0][0] > 0.9:
            trail.popleft()
        # richiamo: mouse scosso a destra e sinistra
        turns, last_dir, last_x = 0, 0, None
        for _, x in trail:
            if last_x is not None and abs(x - last_x) > 12:
                d = 1 if x > last_x else -1
                if last_dir and d != last_dir:
                    turns += 1
                last_dir, last_x = d, x
            elif last_x is None:
                last_x = x
        if turns >= 4 and self.activity != "come" and not self.listening:
            trail.clear()
            self.come_to(*cursor)

    def head_screen(self):
        """Posizione della testa sullo schermo (coordinate globali)."""
        hx, hy = dog3d.project(self.dog.head_world(self.dog.rig()))
        return self.x + hx, self.ground_y - hy

    def look(self, dt, T):
        if self.activity == "sleep" and not self.listening:
            return
        self.gaze_timer -= dt
        hx, hy = self.head_screen()
        near_cursor = False
        if self.cursor:
            dx, dy = self.cursor[0] - hx, self.cursor[1] - hy
            near_cursor = math.hypot(dx, dy) < 380
        moving_cursor = self.t - self.cursor_moved_at < 1.2
        if self.listening or self.activity in ("attend", "petted", "givepaw", "bellyrub"):
            self.gaze = "camera"
        elif self.gaze == "toy" and self.toy and self.activity in ("fetch", "play"):
            pass
        elif self.gaze_timer <= 0:
            ind = self.dog.b["independence"]
            r = self.rng.random()
            if near_cursor and moving_cursor and r > ind * 0.7:
                self.gaze = "cursor"
            elif r < 0.12:
                self.gaze = "camera"
            elif r < 0.55:
                self.gaze = "around"
                yaw, pitch = self.rng.uniform(-1.0, 1.0), self.rng.uniform(-0.35, 0.25)
                self.gaze_dir = (math.cos(yaw) * math.cos(pitch), -math.sin(pitch), math.sin(yaw) * math.cos(pitch))
            else:
                self.gaze = None
            self.gaze_timer = self.rng.uniform(1.2, 3.5)
        elif self.gaze is None and near_cursor and moving_cursor and self.rng.random() < dt * 3 * (1 - self.dog.b["independence"]):
            self.gaze, self.gaze_timer = "cursor", self.rng.uniform(1.5, 3.0)
        if T["headPitch"] > 0.5 or T["scratch"] > 0.5:
            return  # muso a terra o grattata: niente sguardo
        rig = self.dog.rig()
        if self.gaze == "camera":
            d = TOWARD_CAMERA
        elif self.gaze == "cursor" and self.cursor:
            d = (self.cursor[0] - hx, hy - self.cursor[1], 90.0)
        elif self.gaze == "toy" and self.toy:
            d = (self.toy.x - hx, hy - (self.toy.y - self.toy.h), 25.0 + (self.toy.y - self.y))
        elif self.gaze == "around":
            d = dog3d.mat_vec(rig["body_rot"], self.gaze_dir)
        else:
            return
        yaw, pitch = dog3d.look_angles(self.dog, rig, d)
        T["headYaw"] = max(-1.2, min(1.2, yaw))
        T["headPitch"] = max(-0.7, min(0.6, pitch)) + T["headPitch"] * 0.3
        if abs(yaw) > 1.2 and self.goal is None and self.activity not in ("spin",):
            self.dog.yaw_target = self.dog.yaw + (yaw - math.copysign(1.0, yaw))  # gira anche il corpo
        if self.gaze == "camera" and self.goal is None and self.activity != "spin":
            # di tre quarti verso di te
            facing_right = math.cos(self.dog.yaw) >= 0
            want = math.pi / 2 + (-0.55 if facing_right else 0.55)
            self.dog.yaw_target = nearest_angle(self.dog.yaw, want)

    # ------------------------------------------------------------ movimento
    def margins(self):
        """Margini perché la finestra del cane resti dentro lo schermo: (lati, sopra, sotto)."""
        w, h = self.dog.window_size()
        return w / 2 + 4, h - dog3d.BASE + 4, dog3d.BASE + 2

    def here(self):
        return self.areas.nearest(self.x, self.y)

    def random_point(self, i):
        """Punto a caso sullo schermo, preferendo il desktop libero da finestre."""
        mx, top, bottom = self.margins()
        rx, ry, rw, rh = self.areas.rects[i]
        for _ in range(40):
            p = self.areas.clamp(i, self.rng.uniform(rx, rx + rw), self.rng.uniform(ry, ry + rh), mx, top, bottom)
            if self.window_at(*p) is None:
                return p
        return p

    def go(self, x, y, run=False):
        if self.perch:  # era seduto su una finestra: prima scende con un salto
            self.perch = None
            r = self.areas.rects[self.here()]
            self.leap = (0.0, 0.5, self.x, self.y, self.x, min(self.y + 60, r[1] + r[3] - dog3d.BASE - 2))
        i = self.areas.at(x, y)
        i = self.areas.nearest(x, y) if i is None else i
        self.goal = self.areas.clamp(i, x, y, *self.margins())
        self.run = run

    def straight(self, x, y):
        n = max(int(math.hypot(x - self.x, y - self.y) / 30), 1)
        return all(self.areas.at(lerp(self.x, x, k / n), lerp(self.y, y, k / n)) is not None for k in range(n + 1))

    def waypoint(self):
        """Prossimo punto verso la meta: dritto se si può, altrimenti dal bordo in comune con lo schermo dopo."""
        gx, gy = self.goal
        if self.straight(gx, gy):
            return gx, gy, True
        cur, dst = self.here(), self.areas.nearest(gx, gy)
        path = self.areas.route(cur, dst) if cur != dst else None
        if not path:
            return gx, gy, True
        (x0, y0), (x1, y1), (nx, ny) = self.areas.edge(cur, path[1])
        inset = 50
        if x0 == x1:  # bordo verticale
            px, py = x0, min(max(gy, y0 + inset), y1 - inset)
        else:
            px, py = min(max(gx, x0 + inset), x1 - inset), y0
        return px + nx * 20, py + ny * 20, False

    def move(self, dt):
        if self.goal is None or self.leap:
            return self.leap is not None
        wx, wy, final = self.waypoint()
        dx, dy = wx - self.x, wy - self.y
        dist = math.hypot(dx, dy)
        hx, hy = (dx / dist, dy / dist) if dist > 0.5 else (0.0, 0.0)
        if abs(dy) > abs(dx) * 0.84 and abs(dy) > 25:  # quasi in verticale: zig-zag in diagonale (~35°)
            if (self.x - wx) * self.zig > max(30.0, abs(dy) * 0.35) or self.areas.at(self.x + self.zig * 40, self.y) is None:
                self.zig = -self.zig
            hx, hy = self.zig * 0.82, math.copysign(0.57, dy)
        if dist > 0.5:
            self.dog.yaw_target = nearest_angle(self.dog.yaw, math.atan2(hy, hx))  # giù sullo schermo = verso di te
        facing = max(0.0, math.cos(self.dog.yaw - self.dog.yaw_target))
        size = self.dog.b["Hs"] / 30
        base = 175 if self.run and self.activity == "home" else 115 if self.run else 16 if self.activity == "sniff" else 46
        P = self.dog.p
        standing = max(0.0, 1.0 - 2.5 * max(P["rear"], P["front"], P["belly"]))  # non striscia: parte quando è in piedi
        speed = base * (0.6 + 0.4 * size) * facing ** 3 * standing
        step = speed * dt
        self.dog.speed = speed
        if dist <= step:
            self.x, self.y = wx, wy
            if final:
                self.goal = None
                self.run = False
                self.dog.speed = 0.0
            return True
        self.x += hx * step
        self.y += hy * step
        return True


def lerp(a, b, t):
    return a + (b - a) * t


def nearest_angle(current, target):
    """Equivalente di `target` (modulo 2π) più vicino a `current`."""
    k = round((current - target) / math.tau)
    return target + k * math.tau
