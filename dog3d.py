"""Razze, scheletro e posa 3D del cane (solo calcoli, nessun disegno).

Spazio del cane: unità = pixel, y in alto, il cane guarda verso +x, +z è il fianco verso lo schermo
quando bodyYaw = 0. Il mondo usa la stessa convenzione con la camera davanti (+z) leggermente in alto.
"""
import math

ELEVATION = math.radians(14)  # inclinazione della camera, condivisa con lo shader

BREEDS = {
    "maremmano": dict(
        label="Pastore Maremmano Abruzzese", Hs=36, rc=14, rh=12.5, Lb=42, R=13.6, muzzle=11, neck=13,
        neckR=10.5, tail=31, tailR=4.0, tailFur=4.2, legR=4.4, fur=2.4, ear="floppy", earLen=0.8, earTaper=0.6, tailBias=-0.75,
        mane=1.0, thigh=0.68, tail_kind="low", pattern=0, coat="#EFE8D8", coat2="#D6BF96", mark="#F8F4EC",
        roof="#5E3A22", wood="#9C6B3E", independence=0.4, kscale=1.15,
        personality="saggio, calmo e protettivo; parli con la pacatezza di un guardiano di greggi abruzzese",
        greeting="Ciao. Veglio io qui. Di cosa hai bisogno?", greet_action="wag",
    ),
    "golden": dict(
        label="Golden Retriever", Hs=31, rc=13, rh=11.5, Lb=36, R=11.6, muzzle=9.4, neck=11,
        neckR=9, tail=28, tailR=3.0, tailFur=2.6, legR=4.0, fur=1.4, mane=0.6, thigh=0.6, ear="floppy", earLen=1.15,
        tail_kind="plume", pattern=3, coat="#D99A4E", coat2="#C07F38", mark="#EFC88D",
        roof="#A8402C", wood="#C9A06A", independence=0.15, kscale=1.05,
        personality="sempre allegro, entusiasta e affettuosissimo; tutto ti sembra una splendida avventura",
        greeting="Ciao ciao ciao! Giochiamo? Chiedimi quello che vuoi!", greet_action="bow",
    ),
    "collie": dict(
        label="Border Collie", Hs=29, rc=11.5, rh=10, Lb=34, R=10.7, muzzle=8.5, neck=11,
        neckR=7.4, tail=27, tailR=2.6, tailFur=2.0, legR=3.5, fur=1.2, mane=0.7, ear="semi", earLen=0.68,
        tail_kind="low", pattern=1, coat="#1E1F22", coat2="#151618", mark="#F4F3EF",
        roof="#2E5A86", wood="#BBA88C", independence=0.1, kscale=1.0,
        personality="intelligentissimo, attento a ogni movimento, iperattivo; ami organizzare e risolvere problemi",
        greeting="Pronto! Che lavoro facciamo oggi?", greet_action="ears_up",
    ),
    "dachshund": dict(
        label="Bassotto (Dachshund)", Hs=11, rc=10, rh=8.5, Lb=42, R=9.7, muzzle=10, neck=9,
        neckR=6.4, tail=19, tailR=2.4, tailFur=0.3, legR=3.4, fur=0.3, ear="floppy", earLen=1.35,
        tail_kind="thin", pattern=4, coat="#8A4521", coat2="#5E2C13", mark="#A65A2E",
        roof="#4C7738", wood="#BD9364", independence=0.3, kscale=0.85,
        personality="curioso, testardo, buffo e un po' melodrammatico; ti senti un grande cane da caccia",
        greeting="Ehi! Ho sentito odore di domande. Dimmi!", greet_action="sniff",
    ),
    "shiba": dict(
        label="Shiba Inu", Hs=23, rc=10, rh=9, Lb=26, R=10, muzzle=6.3, neck=9,
        neckR=6.8, tail=17, tailR=3.0, tailFur=1.4, legR=3.2, fur=0.8, ear="pointy", earLen=0.65,
        tail_kind="curl", pattern=2, coat="#C8692A", coat2="#A9531D", mark="#F7E6CC",
        roof="#962D2D", wood="#D4B386", independence=0.6, kscale=0.9,
        personality="furbo, indipendente e sornione, leggermente snob; aiuti, ma facendolo sembrare un favore",
        greeting="Hm. Va bene, ti concedo qualche minuto.", greet_action="tilt",
    ),
    "meticcio": dict(
        label="Meticcio arruffato", Hs=21, rc=10, rh=9, Lb=28, R=10.5, muzzle=6.2, neck=8.5,
        neckR=7.2, tail=19, tailR=3.2, tailFur=3.0, legR=3.3, fur=1.9, mane=0.45, ear="floppy", earLen=0.7, earTaper=0.35,
        tail_kind="curl", pattern=5, coat="#A9733F", coat2="#7A4E28", mark="#DCC39C",
        roof="#3F6E8C", wood="#C7A57A", independence=0.3, kscale=0.9,
        personality="un meticcio piccolo e arruffato, dolcissimo e curioso di tutto; un po' timido con gli "
                    "sconosciuti ma affettuosissimo con chi ami, e felice per ogni passeggiata",
        greeting="Eccomi! Ti ho sentito subito. Andiamo a fare un giro?", greet_action="wag",
    ),
}
DEFAULT_BREED = "maremmano"
# andature: sfasamento di ogni zampa (anteriore vicina, anteriore lontana, posteriore vicina, posteriore lontana)
# e frazione del ciclo in appoggio
GAITS = (((0.25, 0.75, 0.0, 0.5), 0.62),   # passo
         ((0.0, 0.5, 0.5, 0.0), 0.44),     # trotto: diagonali insieme
         ((0.58, 0.48, 0.0, 0.1), 0.3))    # galoppo: posteriori, poi anteriori, poi in volo
SCALE = 1.25  # grandezza del cane sullo schermo
SIZED = {"Hs", "rc", "rh", "Lb", "R", "muzzle", "neck", "neckR", "tail", "tailR", "tailFur", "legR", "fur", "kscale"}
# proporzioni da cucciolone, uguali per tutte le razze: testa più grande, muso corto, zampe e schiena più corte
CUTE = dict(R=1.25, muzzle=0.75, Hs=0.88, Lb=0.9)


# ------------------------------------------------------------------ vettori (tuple x, y, z)
def add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def mul(a, k): return (a[0] * k, a[1] * k, a[2] * k)
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def length(a): return math.sqrt(dot(a, a))
def lerp(a, b, t): return a + (b - a) * t
def vlerp(a, b, t): return (lerp(a[0], b[0], t), lerp(a[1], b[1], t), lerp(a[2], b[2], t))
def cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def norm(a):
    n = length(a)
    return mul(a, 1 / n) if n > 1e-9 else (1.0, 0.0, 0.0)


def rot_yaw(a):  # +x verso +z per angoli positivi
    c, s = math.cos(a), math.sin(a)
    return ((c, 0, s), (0, 1, 0), (-s, 0, c))  # colonne: immagini di x, y, z


def rot_pitch(a):  # muso in giù per angoli positivi (rotazione attorno a z)
    c, s = math.cos(a), math.sin(a)
    return ((c, -s, 0), (s, c, 0), (0, 0, 1))


def rot_roll(a):  # rotazione attorno all'asse x
    c, s = math.cos(a), math.sin(a)
    return ((1, 0, 0), (0, c, s), (0, -s, c))


def mat_vec(m, v):
    return add(add(mul(m[0], v[0]), mul(m[1], v[1])), mul(m[2], v[2]))


def mat_mul(a, b):
    return tuple(mat_vec(a, col) for col in b)


def mat_t_vec(m, v):  # trasposta (= inversa per rotazioni) per vettore
    return (dot(m[0], v), dot(m[1], v), dot(m[2], v))


def ik2(a, target, l1, l2, pole):
    """IK a due ossa: ritorna (giunto, estremo) con l'articolazione piegata verso `pole`."""
    d = sub(target, a)
    dist = min(max(length(d), abs(l1 - l2) + 1e-3), l1 + l2 - 1e-3)
    dirv = norm(d)
    end = add(a, mul(dirv, dist))
    x = (l1 * l1 + dist * dist - l2 * l2) / (2 * dist)
    h = math.sqrt(max(l1 * l1 - x * x, 0.0))
    p = sub(pole, mul(dirv, dot(pole, dirv)))
    p = norm(p) if length(p) > 1e-6 else norm(cross(dirv, (0, 0, 1)))
    return add(add(a, mul(dirv, x)), mul(p, h)), end


# ------------------------------------------------------------------ posa
# Parametri continui della posa: il cervello imposta i target, qui vengono ammorbiditi.
POSE_DEFAULTS = dict(
    front=0.0,      # 0 zampe anteriori dritte, 1 appoggiate a terra (sdraiato / inchino)
    rear=0.0,       # 0 in piedi, 1 seduto sul posteriore
    headYaw=0.0, headPitch=0.0, headRoll=0.0,
    jaw=0.0, tongue=0.0, eyes=1.0, ears=0.0,
    tailUp=0.0, wagAmp=0.15, wagFreq=3.0,
    scratch=0.0, shake=0.0, hop=0.0, breath=1.0,
    paw=0.0,        # dà la zampa (anteriore vicina sollevata verso di te)
    belly=0.0,      # pancia all'aria
    dig=0.0,        # scava con le zampe anteriori
)
RATES = dict(front=4, rear=4, headYaw=6, headPitch=6, headRoll=6, jaw=18, tongue=10, eyes=14, ears=7,
             tailUp=4, wagAmp=5, wagFreq=4, scratch=6, shake=8, hop=30, breath=2,
             paw=6, belly=3, dig=8)


class Dog:
    def __init__(self, breed_key):
        self.set_breed(breed_key)
        self.p = dict(POSE_DEFAULTS)
        self.target = dict(POSE_DEFAULTS)
        self.yaw = 0.0          # orientamento del corpo nel mondo
        self.yaw_target = 0.0
        self.t = 0.0
        self.gait = 0.0         # fase del passo
        self.speed = 0.0        # velocità attuale (px/s) per il passo
        self.wag_phase = 0.0
        self.carry = 0          # in bocca: 0 niente, 1 pallina, 2 rametto

    def set_breed(self, key):
        self.key = key
        # misure in pixel scalate tutte insieme (colori e rapporti restano uguali)
        self.b = {k: v * (SCALE if k in SIZED else 1) * CUTE.get(k, 1) if isinstance(v, (int, float)) else v
                  for k, v in BREEDS[key].items()}
        b = self.b
        b_hh = b["Hs"] * 1.02
        self.pastern = 0.15 * b["Hs"]
        self.fU = self.fL = max((b["Hs"] * 0.86 - b["legR"] * 0.9) / 1.94, 2.0)  # anteriori quasi dritte
        self.meta = 0.3 * b_hh
        self.tT = self.tS = max((b_hh - self.meta * 0.97 - b["legR"] * 0.9) / 1.8, 2.0)
        self.Hh = b_hh
        self.extent = None

    # ------------------------------------------------------------ animazione
    def step(self, dt):
        self.t += dt
        for k, v in self.target.items():
            self.p[k] += (v - self.p[k]) * min(1.0, dt * RATES[k])
        diff = self.yaw_target - self.yaw
        self.yaw += math.copysign(min(abs(diff), dt * math.radians(300), abs(diff) * dt * 7 + dt * 0.5), diff)
        self.wag_phase += dt * min(self.p["wagFreq"], 4.2) * math.tau  # oltre ~4 Hz a 30 fps sembra a scatti
        if abs(self.speed) > 0.1:  # velocità negativa = passi all'indietro
            freq = self.gait_params()[3]
            self.gait = (self.gait + math.copysign(freq * dt, self.speed)) % 1.0

    def gait_params(self):
        """Andatura secondo la velocità: (sfasamenti delle 4 zampe, appoggio, falcata, frequenza, pesi).

        Passo: zampe una alla volta. Trotto: coppie diagonali. Galoppo: spingono le posteriori,
        poi atterrano le anteriori, con un attimo in volo. La falcata è calcolata perché i piedi
        in appoggio restino fermi a terra (falcata = velocità × appoggio / frequenza).
        """
        size = (self.b["Hs"] / 37) ** 0.5  # i cani piccoli fanno passi più fitti
        v = abs(self.speed) / max(size, 0.4)
        trot = min(max((v - 60) / 35, 0.0), 1.0)
        gallop = min(max((v - 140) / 45, 0.0), 1.0)
        walk = 1 - trot
        trot *= 1 - gallop
        weights = (walk, trot, gallop)
        offsets = [walk * a + trot * b + gallop * c for a, b, c in zip(*(g[0] for g in GAITS))]
        duty = sum(w * g[1] for w, g in zip(weights, GAITS))
        freq = min(1.25 + v * 0.0115, 3.3) / size
        stride = abs(self.speed) * duty / freq
        return offsets, duty, stride, freq, weights

    def stride(self):
        return self.gait_params()[2]

    # ------------------------------------------------------------ scheletro
    def rig(self):
        b, P = self.b, self.p
        f, r = P["front"], P["rear"]
        rc, rh, Lb, R = b["rc"], b["rh"], b["Lb"], b["R"]
        r2 = b["legR"]
        moving = min(abs(self.speed) / 20.0, 1.0) * (1 - f) * (1 - r)
        offsets, duty, stride, _, (w_walk, w_trot, w_gallop) = self.gait_params()
        g = self.gait * math.tau
        bob = (-0.4 * w_walk - 1.0 * w_trot) * abs(math.sin(g * 2)) * moving
        flex = 0.06 * b["Hs"] * w_gallop * moving  # galoppo: la schiena si raccoglie e si distende
        bob += flex * 0.8 * math.sin(g + 1.2)       # in volo dopo la spinta delle posteriori
        breath = math.sin(self.t * (2.4 if P["breath"] > 1.5 else 1.4)) * 0.35 * P["breath"]

        cy = lerp(b["Hs"] + rc * 0.45, rc * 0.98 + 0.5, f) + bob + breath * 0.5 + flex * math.sin(g + 2.6)
        hy = lerp(self.Hh + rh * 0.4, rh * 0.95, r) + bob + flex * math.sin(g + 0.4)
        if f > 0.5 and r < 0.5:  # inchino: il posteriore resta alto
            hy = lerp(self.Hh + rh * 0.4, self.Hh + rh * 0.7, f)
        cx = Lb / 2
        hx = cx - math.sqrt(max(Lb * Lb - (cy - hy) ** 2, (Lb * 0.6) ** 2))
        chest, hip = (cx, cy, 0.0), (hx, hy, 0.0)

        legs = []
        lift = b["Hs"] * (0.08 * w_walk + 0.15 * w_trot + 0.2 * w_gallop)
        swing = 1 - duty
        for i, (front, side) in enumerate(((True, 1), (True, -1), (False, 1), (False, -1))):
            phase = (self.gait + offsets[i]) % 1.0
            if phase < duty:  # appoggio: il piede resta fermo mentre il corpo avanza
                off, up = stride * (0.5 - phase / duty), 0.0
            else:  # volo della zampa: si alza e va avanti
                v = (phase - duty) / swing
                off, up = stride * (-0.5 + (1 - math.cos(math.pi * v)) / 2), lift * math.sin(math.pi * v)
            off, up = off * moving, up * moving
            if front:
                top = (cx - rc * 0.15, cy - rc * 0.5, side * rc * 0.5)
                foot_s = (top[0] + off + 1, r2 * 0.9 + up, side * rc * 0.48)
                wrist_s = add(foot_s, (-0.04 * b["Hs"], self.pastern, 0))
                foot_l = (top[0] + self.fU + self.fL * 0.85, r2 * 0.9, side * rc * 0.42)
                wrist_l = add(foot_l, (-self.pastern - 1, 0.6, 0))
                if P["dig"] > 0.01:  # scava: zampe che raspano a turno
                    ph = self.t * 16 + (0 if side > 0 else math.pi)
                    foot_s = add(foot_s, (math.sin(ph) * stride * 0.45 * P["dig"], max(0.0, math.cos(ph)) * 4 * P["dig"], 0))
                    wrist_s = add(foot_s, (-0.04 * b["Hs"], self.pastern, 0))
                foot, wrist = vlerp(foot_s, foot_l, f), vlerp(wrist_s, wrist_l, f)
                if side == 1 and P["paw"] > 0.01:  # dà la zampa
                    reach = self.fU + self.fL
                    foot_p = (top[0] + reach * 0.75, top[1] - reach * 0.25 + math.sin(self.t * 3) * 0.8, rc * 0.75)
                    foot = vlerp(foot, foot_p, P["paw"])
                    wrist = vlerp(wrist, add(foot_p, (-self.pastern * 0.8, self.pastern * 0.3, 0)), P["paw"])
                if P["belly"] > 0.01:
                    kick = math.sin(self.t * 7 + i * 1.7) * 2.5
                    foot = vlerp(foot, add(top, (4 + kick, -self.fU * 0.9, side * 2)), P["belly"])
                    wrist = vlerp(wrist, add(top, (5 + kick, -self.fU * 0.7, side * 2)), P["belly"])
                mid, wrist = ik2(top, wrist, self.fU, self.fL, (-1, 0, 0))
                legs += [top, mid, wrist, foot]
            else:
                top = (hx - rh * 0.1, hy - rh * 0.3, side * rh * 0.55)
                foot_s = (top[0] + off - 0.5, r2 * 0.9 + up, side * rh * 0.52)
                hock_s = add(foot_s, (-self.meta * 0.25, self.meta * 0.97, 0))
                foot_l = (top[0] + self.tS * 0.95, r2 * 0.9, side * rh * 0.7)
                hock_l = add(foot_l, (-self.meta * 0.97, r2 * 0.25, 0))
                foot, hock = vlerp(foot_s, foot_l, r), vlerp(hock_s, hock_l, r)
                if side == 1 and P["scratch"] > 0.01:  # grattata dietro l'orecchio
                    sc = P["scratch"]
                    jitter = math.sin(self.t * 38) * 2.5
                    foot_k = (cx + rc * 0.3 + jitter, cy + rc * 0.7, rc * 0.95)
                    hock_k = add(foot_k, (-self.meta * 0.85, -self.meta * 0.3, 0.6))
                    foot, hock = vlerp(foot, foot_k, sc), vlerp(hock, hock_k, sc)
                if P["belly"] > 0.01:  # pancia all'aria: zampe raccolte che scalciano piano
                    kick = math.sin(self.t * 7 + i) * 2.5
                    foot = vlerp(foot, add(top, (3 + kick, -self.tT * 0.9, side * 2)), P["belly"])
                    hock = vlerp(hock, add(top, (-2, -self.tT * 0.6, side * 2)), P["belly"])
                mid, hock = ik2(top, hock, self.tT, self.tS, (1, 0, 0))
                legs += [top, mid, hock, foot]

        # collo e testa
        neck0 = (cx + rc * 0.5, cy + rc * 0.45, 0.0)
        head_yaw, head_pitch = P["headYaw"], P["headPitch"]
        head_pitch += 0.1 * w_gallop * moving * math.sin(g + 0.8)  # la testa accompagna il galoppo
        alpha = math.radians(60) - head_pitch * 0.55 + f * 0.1 - 0.25 * w_gallop * moving
        nd = mat_vec(rot_yaw(head_yaw * 0.45), (math.cos(alpha), math.sin(alpha), 0))
        head_pos = add(neck0, mul(nd, b["neck"]))
        head_rot = mat_mul(rot_yaw(head_yaw), mat_mul(rot_pitch(head_pitch - 0.12), rot_roll(P["headRoll"])))  # testa portata alta

        # coda
        tail = [(hx - rh * 0.95, hy + rh * 0.4, 0.0)]
        kind = b["tail_kind"]
        up = max(-1.0, min(1.0, P["tailUp"] + b.get("tailBias", 0.0)))  # il maremmano porta la coda bassa
        base = {"plume": lerp(-1.1, 0.8, (up + 1) / 2), "low": lerp(-1.3, 0.6, (up + 1) / 2),
                "thin": lerp(-0.9, 0.7, (up + 1) / 2), "curl": lerp(0.6, 1.35, (up + 1) / 2)}[kind]
        curl = {"plume": 0.05, "low": -0.04 + 0.08 * up, "thin": 0.04, "curl": 0.62}[kind]
        if kind == "low":  # punta leggermente rialzata
            curl = 0.1
        seg = b["tail"] / 5
        for i in range(5):
            a = base + curl * i
            w = P["wagAmp"] * math.sin(self.wag_phase - i * 0.55) * (0.5 + 0.18 * i)
            d = (-math.cos(a) * math.cos(w), math.sin(a), math.sin(w))
            tail.append(add(tail[-1], mul(d, seg)))

        # orecchie (spazio della testa)
        ears = []
        e = P["ears"]
        bounce = math.sin(self.gait * math.tau * 2) * 0.12 * moving
        for side in (1, -1):
            if b["ear"] == "floppy":
                B = (-0.22 * R, 0.56 * R, side * 0.66 * R)
                D = norm((-0.15 + 0.35 * e + bounce, -1 + 0.55 * max(e, 0), side * (0.32 + 0.1 * max(e, 0))))
                N = norm(sub((0, 0, side), mul(D, D[2] * side)))
                dims = (R * b["earLen"], R * 0.44, R * 0.1, b.get("earTaper", 0.15))
            else:
                back = max(-e, 0)
                B = (-0.12 * R, 0.62 * R, side * 0.42 * R)
                D = norm((0.12 + 0.12 * e - 0.95 * back, 1 - 0.55 * back, side * (0.3 + 0.1 * back)))
                N = norm(sub((1, 0, 0), mul(D, D[0])))
                dims = (R * b["earLen"], R * 0.36, R * 0.1, 0.85 if b["ear"] == "pointy" else 0.55)
            ears.append((B, D, N))

        roll = math.sin(self.t * 26) * 0.35 * P["shake"] - 2.6 * P["belly"] + math.sin(self.t * 2.2) * 0.12 * P["belly"]
        body_rot = mat_mul(rot_yaw(self.yaw), rot_roll(roll))
        lift_belly = P["belly"] * rc * 1.75  # ruotato sulla schiena il torace scende sotto terra: lo rialzo
        return dict(chest=chest, hip=hip, legs=legs, neck0=neck0, head_pos=head_pos, head_rot=head_rot,
                    tail=tail, ears=ears, ear_dims=dims, body_rot=body_rot, root=(0.0, P["hop"] + lift_belly, 0.0),
                    carry=self.carry)

    # ------------------------------------------------------------ proiezione
    def points(self, rig):
        """Punti del cane nel mondo (per ingombro, sguardo e fumetto)."""
        R = self.b["R"]
        local = [rig["chest"], rig["hip"], rig["neck0"], *rig["legs"], *rig["tail"]]
        hp, hr = rig["head_pos"], rig["head_rot"]
        local += [add(hp, mat_vec(hr, v)) for v in ((0, R, 0), (R * 0.5 + self.b["muzzle"] + R * 0.4, -R * 0.2, 0),
                                                    (-R, 0, 0), (0, R * 1.6, 0))]
        return [add(mat_vec(rig["body_rot"], v), rig["root"]) for v in local]

    def head_world(self, rig):
        return add(mat_vec(rig["body_rot"], rig["head_pos"]), rig["root"])

    def window_size(self):
        """Dimensione della finestra (px) sufficiente per ogni orientamento e posa."""
        if self.extent is None:
            saved = dict(self.p)
            self.p.update(POSE_DEFAULTS)
            self.p["ears"] = 1.0
            self.p["tailUp"] = 1.0
            rig = self.rig()
            pts = [rig["chest"], rig["hip"], rig["neck0"], *rig["legs"], *rig["tail"], rig["head_pos"]]
            R = self.b["R"]
            reach = max(math.hypot(p[0], p[2]) for p in pts) + R * 1.6 + self.b["muzzle"]
            top = max(p[1] for p in pts) + R * 1.9
            self.p = saved
            self.extent = (reach, top)
        reach, top = self.extent
        w = int(2 * reach + 24)
        h = int(top * math.cos(ELEVATION) + reach * math.sin(ELEVATION) + 26 + BASE)
        return w, h


BASE = 14  # pixel tra il bordo inferiore della finestra e il punto a terra sotto il cane


def project(p):
    """Mondo → coordinate schermo relative al punto a terra (x a destra, y in alto)."""
    e = ELEVATION
    return p[0], p[1] * math.cos(e) - p[2] * math.sin(e)


def look_angles(dog, rig, target_dir_world):
    """Angoli (yaw, pitch) della testa relativi al corpo per guardare in una direzione del mondo."""
    d = mat_t_vec(dog_rot_only(rig), norm(target_dir_world))
    return math.atan2(d[2], d[0]), -math.asin(max(-1.0, min(1.0, d[1])))


def dog_rot_only(rig):
    return rig["body_rot"]
