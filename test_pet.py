"""Test rapidi: python3 test_pet.py (nessuna rete; il test dello shader serve un display con OpenGL)."""
import io
import json
import math
import os
import random
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

if not os.environ.get("DISPLAY"):
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

import ai_handler
import dog3d
from brain import Areas, Brain

# disposizione reale: HDMI sopra, portatile sotto a sinistra, DP-4 sotto a destra (pannello sul portatile)
SCREENS = [(0, 1080, 1920, 1156), (0, 0, 1920, 1080), (1920, 1080, 1920, 1080)]


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class GeminiTest(unittest.TestCase):
    def test_send_builds_request_and_keeps_history(self):
        sent = []

        def fake_urlopen(req, timeout):
            sent.append((req, json.loads(req.data)))
            return FakeResp(json.dumps({"candidates": [{"content": {"parts": [{"text": "Ciao!"}]}}]}).encode())

        chat = ai_handler.GeminiChat("KEY", "sei un cane", "m1")
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            self.assertEqual(chat.send("ciao"), "Ciao!")
            chat.send("come stai?")
        req, body = sent[1]
        self.assertIn("/models/m1:generateContent", req.full_url)
        self.assertEqual(req.get_header("X-goog-api-key"), "KEY")
        self.assertEqual([c["role"] for c in body["contents"]], ["user", "model", "user"])
        self.assertEqual(len(chat.history), 4)

    def test_http_error_becomes_chat_error_and_history_untouched(self):
        err = urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b'{"error":{"message":"API key not valid"}}'))
        chat = ai_handler.GeminiChat("bad", "x")
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaisesRegex(ai_handler.ChatError, "chiave API non è valida"):
                chat.send("ciao")
        self.assertEqual(chat.history, [])

    def test_reply_actions_are_performed_not_written(self):
        P = ai_handler.parse_reply
        self.assertEqual(P("[scodinzola][orecchie] Certo! Ecco."), ("Certo! Ecco.", ["wag", "ears_up"]))
        self.assertEqual(P("*scodinzola* Bau bau! Ciao."), ("Ciao.", ["wag", "bark"]))
        self.assertEqual(P("Woof! *si siede* Vediamo."), ("Vediamo.", ["sit", "bark"]))
        self.assertEqual(P("Vedi la nota [1] e [boh]."), ("Vedi la nota [1] e [boh].", []))
        self.assertEqual(P("Il baule è pieno."), ("Il baule è pieno.", []))
        self.assertTrue(ai_handler.system_prompt("Golden", "allegro", "Ettore").startswith("Ti chiami Ettore."))


class RigTest(unittest.TestCase):
    def test_bones_keep_length_and_feet_touch_ground(self):
        for key in dog3d.BREEDS:
            for pose in (dict(), dict(rear=1.0), dict(front=1.0, rear=1.0), dict(front=1.0)):
                dog = dog3d.Dog(key)
                dog.p.update(pose)
                rig = dog.rig()
                legs = rig["legs"]
                for i in range(4):
                    top, mid, low, foot = legs[i * 4:i * 4 + 4]
                    l1, l2 = (dog.fU, dog.fL) if i < 2 else (dog.tT, dog.tS)
                    self.assertAlmostEqual(dog3d.length(dog3d.sub(mid, top)), l1, places=3, msg=key)
                    self.assertLessEqual(dog3d.length(dog3d.sub(low, mid)), l2 + 1e-3, msg=key)
                    self.assertAlmostEqual(foot[1], dog.b["legR"] * 0.9, places=3, msg=(key, pose))
                w, h = dog.window_size()
                self.assertTrue(80 < w < 340 and 60 < h < 250, (key, w, h))

    def test_look_at_camera_turns_head_toward_viewer(self):
        dog = dog3d.Dog("golden")
        dog.yaw = 0.0  # di profilo, guarda a destra
        yaw, pitch = dog3d.look_angles(dog, dog.rig(), (0.0, math.sin(dog3d.ELEVATION), math.cos(dog3d.ELEVATION)))
        self.assertAlmostEqual(yaw, math.pi / 2, places=3)
        self.assertLess(pitch, 0)  # la camera è un po' più in alto


class BrainTest(unittest.TestCase):
    def setUp(self):
        self.areas = Areas(SCREENS)
        self.dog = dog3d.Dog("collie")
        self.brain = Brain(self.dog, self.areas, random.Random(1))
        self.brain.set_home(1700, 2200, 1)
        self.brain.place_home()
        self.brain.next_scene = 1e9  # niente scenette spontanee, tranne dove servono

    def run_until(self, cond, seconds=200):
        for _ in range(int(seconds * 30)):
            self.brain.update(1 / 30)
            if cond():
                return True
        return False

    def arrive(self, x, y, seconds=120):
        self.brain.choose = lambda: None  # arrivato resta lì
        self.brain.go(x, y)
        self.brain.activity = "wander"
        self.assertTrue(self.run_until(lambda: self.brain.goal is None, seconds))
        return self.brain.x, self.brain.y

    def test_screen_graph(self):
        self.assertEqual(self.areas.edge(0, 2)[2], (1, 0))    # DP-4 a destra del portatile
        self.assertEqual(self.areas.edge(0, 1)[2], (0, -1))   # HDMI sopra il portatile
        self.assertIsNone(self.areas.edge(1, 2))              # si toccano solo in un angolo
        self.assertEqual(self.areas.route(1, 2), [1, 0, 2])

    def test_walks_anywhere_on_the_screen(self):
        x, y = self.arrive(800, 1500)
        self.assertAlmostEqual(x, 800, delta=1)
        self.assertAlmostEqual(y, 1500, delta=1)

    def test_walks_to_the_screen_above_and_across_screens(self):
        self.assertEqual(self.areas.at(*self.arrive(900, 600)), 1)      # HDMI, sopra
        self.assertEqual(self.areas.at(*self.arrive(3000, 1600)), 2)    # DP-4, passando dal portatile

    def test_goals_keep_the_dog_inside_the_screen(self):
        x, y = self.arrive(5, 5000)
        w, h = self.dog.window_size()
        self.assertGreaterEqual(x - w / 2, 0)
        self.assertLessEqual(y + dog3d.BASE, 1080 + 1156)

    def test_mouse_wiggle_calls_the_dog(self):
        for i in range(30):
            self.brain.update(1 / 30, (2500 + (60 if i % 4 < 2 else -60), 1700))
        self.assertEqual(self.brain.activity, "come")
        self.assertEqual(self.areas.at(*self.brain.goal), 2)

    def test_does_not_scoot_while_sitting(self):
        self.brain.start("sit", 10)
        self.run_until(lambda: False, 2)
        self.brain.perform(["sit"])
        self.brain.go(1000, 2000)
        y0 = self.brain.x
        moved_while_low = 0
        for _ in range(60):
            x_before = self.brain.x
            self.brain.update(1 / 30)
            if self.dog.p["rear"] > 0.45 and abs(self.brain.x - x_before) > 0.01:
                moved_while_low += 1
        self.assertEqual(moved_while_low, 0)
        self.assertNotEqual(self.brain.x, y0)  # poi si alza e parte

    def test_click_on_kennel_makes_the_dog_run_home(self):
        self.brain.set_home(3500, 2100, 1)  # cuccia spostata sull'altro schermo
        self.brain.go_home(run=True)
        top_speed = []
        self.assertTrue(self.run_until(lambda: top_speed.append(self.dog.speed) or self.brain.activity == "lie", 60))
        self.assertEqual((round(self.brain.x), round(self.brain.y)), (3500, 2100))
        self.assertGreater(max(top_speed), 120)

    def test_fetch_stick_on_another_screen_and_bring_it_back(self):
        self.brain.throw("stick", 2900, 1500)
        self.assertTrue(self.run_until(lambda: self.brain.activity == "attend", 90))
        self.assertEqual((round(self.brain.x), round(self.brain.y)), (1700, 2200))  # tornato da dove l'aveva lanciato
        toy = self.brain.toy
        self.assertEqual(toy.state, "rest")
        self.assertLess(math.hypot(toy.x - self.brain.x, toy.y - self.brain.y), 60)  # lasciato davanti a sé
        self.assertEqual(self.dog.carry, 0)

    def test_thrown_toy_lands_where_you_clicked(self):
        from brain import Toy
        self.brain.throw("stick", 900, 1400)
        toy = self.brain.toy
        for _ in range(23):  # 0.75 s
            toy.step(1 / 30, self.areas)
        self.assertLess(math.hypot(toy.x - 900, toy.y - 1400), 25)
        ball = Toy("ball", 500, 1500, 0.0, 300, 50, 400)
        for _ in range(30 * 10):
            ball.step(1 / 30, self.areas)
        self.assertEqual((ball.state, ball.h), ("rest", 0.0))

    def test_pick_up_and_move_the_dog(self):
        self.brain.throw("ball", 600, 1500)
        self.run_until(lambda: False, 1)
        self.brain.pick_up()
        for gx in range(800, 1200, 40):  # trascinato col mouse
            self.brain.hold_at(gx, 1400)
            self.brain.update(1 / 30)
        self.assertEqual(self.brain.activity, "held")
        self.assertGreater(self.dog.p["hop"], 10)  # sollevato da terra
        self.brain.drop()
        self.run_until(lambda: False, 1)
        self.assertFalse(self.brain.held)
        self.assertIsNotNone(self.areas.at(self.brain.x, self.brain.y))
        self.assertLess(abs(self.brain.x - 1160), 1)
        self.assertLess(self.dog.p["hop"], 2)  # appoggiato

    def test_petting_reactions(self):
        seen = set()
        for _ in range(20):
            self.brain.pet()
            seen.add(self.brain.activity)
            self.run_until(lambda: False, 1)
        self.assertEqual(seen, {"petted", "givepaw", "bellyrub"})

    def test_eats_from_the_bowl(self):
        self.brain.bowl = (1500, 2000)
        self.brain.food = 1.0
        self.brain.choose = lambda: None
        self.brain.go(1500 + self.brain.reach(), 2000)
        self.brain.activity, self.brain.phase = "eat", "go"
        self.assertTrue(self.run_until(lambda: self.brain.activity == "sit", 40))
        self.assertLess(self.brain.food, 0.7)

    def test_actions_play_and_finish(self):
        self.brain.perform(["bark", "nonexistent", "wag"])
        seen = set()
        for _ in range(150):
            self.brain.update(1 / 30)
            seen.update(o[0] for o in self.brain.overlays)
        self.assertEqual(seen, {"bark", "wag"})
        self.assertEqual(self.brain.overlays, [])

    def test_walks_diagonally_instead_of_straight_up(self):
        self.brain.choose = lambda: None
        self.brain.go(1700, 1300)  # 900 px dritto in su
        self.brain.activity = "wander"
        slopes = []
        for _ in range(30 * 60):
            x0, y0 = self.brain.x, self.brain.y
            self.brain.update(1 / 30)
            dx, dy = self.brain.x - x0, self.brain.y - y0
            if math.hypot(dx, dy) > 0.5:
                slopes.append(abs(dy) / max(abs(dx), 1e-6))
            if self.brain.goal is None:
                break
        self.assertIsNone(self.brain.goal)
        self.assertLess(sorted(slopes)[int(len(slopes) * 0.95)], 1.0)  # quasi sempre in diagonale

    WINDOWS = [dict(id="a", x=200, y=1500, w=700, h=500, cls="dolphin"),       # libera
               dict(id="max", x=0, y=1080, w=1920, h=1156, cls="chrome")]     # massimizzata: da non toccare

    def test_sits_on_a_window_and_follows_it(self):
        self.brain.windows = [self.WINDOWS[1], self.WINDOWS[0]]
        spot = self.brain.perch_spot()
        self.assertEqual(spot[0]["id"], "a")
        win, px = self.WINDOWS[0], 550
        self.brain.target = (win["id"], px - win["x"])
        self.brain.go(px, win["y"] + 45)
        self.brain.activity, self.brain.timer, self.brain.phase = "perch", 60.0, "go"
        self.assertTrue(self.run_until(lambda: self.brain.perch is not None, 90))
        self.assertEqual((round(self.brain.x), round(self.brain.y)), (550, 1500))
        moved = dict(self.WINDOWS[0], x=300, y=1450)  # l'utente sposta la finestra
        self.brain.windows = [self.WINDOWS[1], moved]
        self.brain.update(1 / 30)
        self.assertEqual((round(self.brain.x), round(self.brain.y)), (650, 1450))
        self.brain.windows = [self.WINDOWS[1]]  # chiusa: scende con un salto
        self.run_until(lambda: self.brain.leap is None and self.brain.perch is None, 3)
        self.assertIsNone(self.brain.perch)
        self.assertGreater(self.brain.y, 1450)

    def test_bites_a_window_and_pulls_it_aside(self):
        self.brain.windows = [self.WINDOWS[1], self.WINDOWS[0]]
        plan = self.brain.tug_plan()
        self.assertEqual(plan["id"], "a")  # mai la finestra massimizzata
        self.brain.choose = lambda: None
        self.brain.target = plan
        self.brain.go(plan["x"], plan["y"])
        self.brain.activity, self.brain.timer, self.brain.phase = "tug", 40.0, "go"
        moved = 0.0
        for _ in range(30 * 30):
            self.brain.update(1 / 30)
            for wid, dx, dy in self.brain.window_cmds:
                self.assertEqual(wid, "a")
                moved += dx
            self.brain.window_cmds = []
            if self.brain.activity != "tug":
                break
        self.assertAlmostEqual(abs(moved), plan["pull"], delta=2)
        self.assertEqual(math.copysign(1, moved), plan["side"])  # tirata verso l'esterno

    def test_prefers_free_desktop_and_respects_switch(self):
        self.brain.windows = [dict(id="big", x=0, y=1080, w=1500, h=1156, cls="x")]
        for _ in range(20):
            x, y = self.brain.random_point(0)
            self.assertGreaterEqual(x, 1500)
        self.brain.play_windows = False
        self.brain.windows = list(self.WINDOWS)
        self.assertIsNone(self.brain.perch_spot())
        self.assertIsNone(self.brain.tug_plan())

    def test_window_stays_on_screen_across_offset_screens(self):
        # schermo in alto spostato e schermi sotto di altezza diversa: la finestra non deve mai uscire
        areas = Areas([(0, 1080, 1920, 1200), (667, 0, 1920, 1080), (1920, 1080, 1920, 1080)])
        for key in ("maremmano", "dachshund"):
            brain = Brain(dog3d.Dog(key), areas, random.Random(3))
            brain.set_home(3656, 2170, 1)  # cuccia in fondo allo schermo: il posto davanti resta dentro
            self.assertTrue(brain.fits(*brain.home[:2]))
            brain.place_home()
            brain.choose, brain.next_scene = (lambda: None), 1e9
            w, h = brain.dog.window_size()
            for gx, gy in ((900, 500), (120, 2250), (2500, 600), (3700, 1200)):
                brain.go(gx, gy)
                brain.activity = "wander"
                for _ in range(30 * 120):
                    brain.update(1 / 30)
                    corners = [(brain.x + sx * (w / 2 - 1), brain.y + dog3d.BASE - dy) for sx in (-1, 1) for dy in (1, h - 1)]
                    self.assertTrue(all(areas.at(*c) is not None for c in corners), (key, gx, gy, brain.x, brain.y))
                    if brain.goal is None:
                        break
                self.assertIsNone(brain.goal, (key, gx, gy))

    def test_birds_and_cat_get_chased_away(self):
        for kind in ("birds", "cat"):
            self.brain.sfx = []
            self.brain.scene(kind)
            self.assertTrue(self.brain.critters)
            self.assertTrue(self.run_until(lambda: not self.brain.critters and self.brain.activity != "guard", 90), kind)
            self.assertIn("bark", self.brain.sfx)
            self.assertIn("chirp" if kind == "birds" else "hiss", self.brain.sfx)

    def test_chases_a_butterfly(self):
        self.brain.scene("butterfly")
        self.assertTrue(self.run_until(lambda: self.brain.phase == "play", 20))
        self.assertTrue(self.run_until(lambda: not self.brain.critters and self.brain.activity != "flutter", 60))

    def test_a_friend_comes_to_play_and_leaves(self):
        self.brain.scene("friend")
        friend = self.brain.friend
        self.assertNotEqual(friend.dog.key, self.dog.key)
        self.assertTrue(self.run_until(lambda: self.brain.phase == "romp", 60))
        self.assertTrue(self.run_until(lambda: self.brain.friend is None, 200))
        self.assertIsNone(self.areas.at(friend.x, friend.y))  # uscito dallo schermo
        self.assertIsNotNone(self.areas.at(self.brain.x, self.brain.y))

    def test_visitors_leave_if_you_pick_him_up(self):
        self.brain.scene("cat")
        self.brain.update(1 / 30)
        self.brain.pick_up()
        self.assertTrue(self.run_until(lambda: not self.brain.critters, 30))

    def test_finds_things_and_plays_with_them(self):
        for item, end in (("bone", "lie"), ("sock", "stand")):
            self.brain.scene("find", item)
            self.assertTrue(self.run_until(lambda: self.brain.activity == end, 120), item)
            self.assertEqual(self.dog.carry, 0)
            self.assertEqual(self.brain.toy.state, "rest")
            self.brain.toy = None
        self.brain.scene("find", "ball")
        self.assertTrue(self.run_until(lambda: self.brain.activity == "play", 20))

    def test_drinks_when_thirsty(self):
        self.brain.water = (1500, 2000)
        self.brain.thirst = 1.0
        self.brain.choose = lambda: None
        self.brain.go(1500 + self.brain.reach(), 2000)
        self.brain.activity, self.brain.phase = "drink", "go"
        self.assertTrue(self.run_until(lambda: self.brain.activity == "sit", 40))
        self.assertLess(self.brain.thirst, 0.1)

    def test_scenes_happen_on_their_own(self):
        self.brain.bowl, self.brain.water = (1800, 2200), (1600, 2200)
        self.brain.next_scene = 0.0
        seen = set()
        for _ in range(int(900 * 30)):
            self.brain.update(1 / 30)
            seen.add(self.brain.activity)
            self.assertIsNotNone(self.areas.at(self.brain.x, self.brain.y))
        self.assertTrue(seen & {"guard", "flutter", "friend", "find"})

    def test_autonomous_life_does_not_crash(self):
        self.brain.windows = list(self.WINDOWS)
        self.brain.bowl = (1800, 2200)
        for key in dog3d.BREEDS:
            self.dog.set_breed(key)
            self.run_until(lambda: False, seconds=90)
            self.assertTrue(math.isfinite(self.brain.x) and math.isfinite(self.brain.y))
            self.assertIsNotNone(self.areas.at(self.brain.x, self.brain.y))


class ConfigTest(unittest.TestCase):
    def test_config_roundtrip_private(self):
        import main
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.json"
            self.assertEqual(main.load_config(path), main.DEFAULTS)
            main.save_config({**main.DEFAULTS, "breed": "shiba", "api_key": "k"}, path)
            self.assertEqual(main.load_config(path)["breed"], "shiba")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            path.write_text('{"breed": "chihuahua"}')
            self.assertEqual(main.load_config(path)["breed"], dog3d.DEFAULT_BREED)


class SoundTest(unittest.TestCase):
    def test_every_sound_is_audible_and_written(self):
        import wave
        import sounds
        with tempfile.TemporaryDirectory() as d:
            for name in sounds.NAMES:
                xs = sounds.make(name, 300)
                self.assertGreater(len(xs), sounds.RATE * 0.05, name)
                self.assertGreater(max(abs(v) for v in xs), 1e-3, name)
                path = Path(d) / f"{name}.wav"
                sounds.write_wav(path, xs)
                with wave.open(str(path)) as w:
                    self.assertEqual((w.getframerate(), w.getnchannels()), (sounds.RATE, 1))

    def test_real_recordings_are_used_and_tuned_per_breed(self):
        import sounds
        big = sounds.recorded("bark", "maremmano")
        small = sounds.recorded("bark", "shiba")
        self.assertIsNotNone(big)
        self.assertIsNotNone(small)
        self.assertNotEqual(len(big), len(small))  # registrazioni diverse per cani grandi e piccoli
        golden = sounds.recorded("bark", "golden")
        self.assertGreater(len(big), len(golden))  # il maremmano è intonato più grave (più lento)
        self.assertIsNone(sounds.recorded("thud", "golden"))  # questo resta sintetizzato

    def test_brain_asks_for_sounds(self):
        brain = Brain(dog3d.Dog("shiba"), Areas(SCREENS), random.Random(0))
        brain.perform(["bark"])
        brain.throw("ball", 600, 1500)
        for _ in range(60):
            brain.update(1 / 30)
        self.assertIn("bark", brain.sfx)
        self.assertIn("yip", brain.sfx)
        self.assertIn("bounce", brain.sfx)

    def test_player_is_silent_when_disabled(self):
        import sounds
        with tempfile.TemporaryDirectory() as d, mock.patch("subprocess.Popen") as popen:
            p = sounds.Player(d, "golden", enabled=False)
            p.ready.add(("bark", "golden"))
            p.play("bark")
            popen.assert_not_called()


class AutostartTest(unittest.TestCase):
    def test_autostart_toggle_writes_a_launcher(self):
        import main
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "autostart" / "doggo.desktop"
            with mock.patch.object(main, "AUTOSTART", target), mock.patch.object(main.sys, "platform", "linux"):
                main.set_autostart(True)
                text = target.read_text()
                self.assertIn("Exec=", text)
                self.assertIn(str(Path(main.__file__).resolve()), text)
                main.set_autostart(False)
                self.assertFalse(target.exists())


class PlatformTest(unittest.TestCase):
    def test_macos_autostart_is_a_launch_agent(self):
        import plistlib
        import main
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "LaunchAgents" / "doggo.plist"
            with mock.patch.object(main, "AUTOSTART", target), mock.patch.object(main.sys, "platform", "darwin"):
                main.set_autostart(True)
                plist = plistlib.loads(target.read_bytes())
                self.assertTrue(plist["RunAtLoad"])
                self.assertEqual(plist["ProgramArguments"][-1], str(Path(main.__file__).resolve()))
                self.assertTrue(main.autostart_enabled())
                main.set_autostart(False)
                self.assertFalse(target.exists())

    def test_windows_autostart_uses_the_run_key(self):
        import types
        import main
        reg = {}
        key = mock.MagicMock()
        key.__enter__ = lambda *a: key
        key.__exit__ = lambda *a: False
        fake = types.SimpleNamespace(
            HKEY_CURRENT_USER=0, KEY_SET_VALUE=2, REG_SZ=1, OpenKey=lambda *a: key,
            SetValueEx=lambda k, name, _, __, value: reg.__setitem__(name, value),
            DeleteValue=lambda k, name: reg.pop(name),
            QueryValueEx=lambda k, name: (reg[name], 1) if name in reg else (_ for _ in ()).throw(OSError()))
        with mock.patch.dict(sys.modules, {"winreg": fake}), mock.patch.object(main.sys, "platform", "win32"), \
                mock.patch.object(main.sys, "frozen", True, create=True), \
                mock.patch.object(main.sys, "executable", r"C:\Program Files\Doggo\Doggo.exe"):
            main.set_autostart(True)
            self.assertEqual(reg["Doggo"], '"C:\\Program Files\\Doggo\\Doggo.exe"')
            self.assertTrue(main.autostart_enabled())
            main.set_autostart(False)
            self.assertFalse(main.autostart_enabled())


class ShaderTest(unittest.TestCase):
    def test_shader_compiles_and_draws_the_dog(self):
        from PyQt6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext
        from PyQt6.QtOpenGL import (QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat,
                                    QOpenGLVertexArrayObject)
        import view3d
        app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
        ctx = QOpenGLContext()
        ctx.setFormat(view3d.surface_format())
        surf = QOffscreenSurface()
        surf.setFormat(view3d.surface_format())
        surf.create()
        if not ctx.create() or not ctx.makeCurrent(surf):
            self.skipTest("OpenGL non disponibile")
        prog = view3d.build_program(view3d.gl_version(ctx))
        vao = QOpenGLVertexArrayObject()
        vao.create()
        f = view3d.gl_functions(ctx)
        dog = dog3d.Dog("maremmano")
        w, h = dog.window_size()
        fbo = QOpenGLFramebufferObject(w, h, QOpenGLFramebufferObjectFormat())
        fbo.bind()
        f.glViewport(0, 0, w, h)
        prog.bind()
        view3d.set_common(prog, w, h, 0)
        view3d.set_dog_uniforms(prog, dog, dog.rig())
        vao.bind()
        f.glDrawArrays(view3d.GL_TRIANGLES, 0, 3)
        img = fbo.toImage()
        opaque = sum(img.pixelColor(x, y).alpha() == 255 for x in range(0, w, 3) for y in range(0, h, 3))
        self.assertGreater(opaque, 150)

    def test_shader_works_with_opengl_3_0(self):
        # PC con driver vecchi o macchine virtuali: contesto 3.0, GLSL 1.30, funzioni del profilo 2.0
        import subprocess
        code = (
            "from PyQt6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext, QSurfaceFormat\n"
            "import view3d\n"
            "app = QGuiApplication([])\n"
            "fmt = QSurfaceFormat(); fmt.setVersion(3, 0)\n"
            "ctx = QOpenGLContext(); ctx.setFormat(fmt)\n"
            "surf = QOffscreenSurface(); surf.setFormat(fmt); surf.create()\n"
            "assert ctx.create() and ctx.makeCurrent(surf)\n"
            "assert view3d.gl_version(ctx) == (3, 0), view3d.gl_version(ctx)\n"
            "view3d.build_program(view3d.gl_version(ctx))\n"
            "assert view3d.gl_functions(ctx) is not None\n")
        env = dict(os.environ, MESA_GL_VERSION_OVERRIDE="3.0", MESA_GLSL_VERSION_OVERRIDE="130",
                   QT_QPA_PLATFORM="offscreen")
        r = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).parent, env=env, capture_output=True, text=True)
        if "Could not create" in r.stderr or "ctx.create()" in r.stderr:
            self.skipTest("OpenGL non disponibile")
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
