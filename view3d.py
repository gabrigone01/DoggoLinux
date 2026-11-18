"""Finestre OpenGL trasparenti che disegnano il cane o la cuccia con lo shader dog.frag."""
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QMatrix3x3, QSurfaceFormat, QVector2D, QVector3D, QVector4D
from PyQt6.QtOpenGL import (QOpenGLShader, QOpenGLShaderProgram, QOpenGLVersionFunctionsFactory,
                            QOpenGLVersionProfile, QOpenGLVertexArrayObject)
from PyQt6.QtOpenGLWidgets import QOpenGLWidget

import dog3d

FRAG = Path(__file__).with_name("dog.frag")
VERT = """#version 330 core
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}"""
GL_COLOR_BUFFER_BIT, GL_TRIANGLES = 0x4000, 0x0004


def surface_format():
    fmt = QSurfaceFormat()
    fmt.setVersion(4, 1)  # PyQt6 espone solo le funzioni GL 2.x e 4.1 core
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setAlphaBufferSize(8)
    return fmt


def gl_functions(ctx):
    return QOpenGLVersionFunctionsFactory.get(QOpenGLVersionProfile(surface_format()), ctx)


def build_program():
    prog = QOpenGLShaderProgram()
    ok = (prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Vertex, VERT)
          and prog.addShaderFromSourceCode(QOpenGLShader.ShaderTypeBit.Fragment, FRAG.read_text())
          and prog.link())
    if not ok:
        raise RuntimeError("Shader non compilato:\n" + prog.log())
    return prog


def _v3(v):
    return QVector3D(float(v[0]), float(v[1]), float(v[2]))


def _m3(cols):
    return QMatrix3x3([float(cols[c][r]) for r in range(3) for c in range(3)])


def _rgb(hexcolor):
    c = QColor(hexcolor)
    return QVector3D(c.redF(), c.greenF(), c.blueF())


def set_common(prog, w, h, scene, zoom=1.0):
    prog.setUniformValue("uRes", QVector2D(float(w), float(h)))
    prog.setUniformValue("uBase", float(dog3d.BASE * zoom))
    prog.setUniformValue("uElev", float(dog3d.ELEVATION))
    prog.setUniformValue("uScene", int(scene))
    prog.setUniformValue("uZoom", float(zoom))


def set_dog_uniforms(prog, dog, rig):
    b, P = dog.b, dog.p
    u = prog.setUniformValue
    u("uBodyRot", _m3(rig["body_rot"]))
    u("uRoot", _v3(rig["root"]))
    for name in ("chest", "hip", "neck0"):
        u("u" + name[0].upper() + name[1:], _v3(rig[name]))
    u("uHeadPos", _v3(rig["head_pos"]))
    u("uHeadRot", _m3(rig["head_rot"]))
    u("uBodyR", QVector2D(float(b["rc"]), float(b["rh"])))
    for k, v in (("uHeadR", b["R"]), ("uMuzzle", b["muzzle"]), ("uJaw", P["jaw"]), ("uTongue", P["tongue"]),
                 ("uEyeOpen", P["eyes"]), ("uFur", b["fur"]), ("uNeckR", b["neckR"]), ("uTailR", b["tailR"]),
                 ("uTailFur", b["tailFur"])):
        u(k, float(v))
    for i, pt in enumerate(rig["legs"]):
        u(f"uLeg[{i}]", _v3(pt))
    rc, rh, lr = b["rc"], b["rh"], b["legR"]
    u("uLegR", QVector4D(rc * 0.4, lr, rh * b.get("thigh", 0.55), lr * 0.95))
    u("uMane", float(b.get("mane", 0.0)))
    u("uCarry", int(rig.get("carry", 0)))
    for i, pt in enumerate(rig["tail"]):
        u(f"uTail[{i}]", _v3(pt))
    for i, (B, D, N) in enumerate(rig["ears"]):
        u(f"uEarB[{i}]", _v3(B))
        u(f"uEarD[{i}]", _v3(D))
        u(f"uEarN[{i}]", _v3(N))
    u("uEarDim", QVector4D(*(float(x) for x in rig["ear_dims"])))
    u("uPattern", int(b["pattern"]))
    for k in ("coat", "coat2", "mark"):
        u("u" + k[0].upper() + k[1:], _rgb(b[k]))
    pts = [rig["chest"], rig["hip"], rig["head_pos"], *rig["legs"], *rig["tail"]]
    c = tuple(sum(p[i] for p in pts) / len(pts) for i in range(3))
    u("uBoundC", _v3(c))
    u("uBound", float(max(dog3d.length(dog3d.sub(p, c)) for p in pts) + b["R"] * 1.8 + b["muzzle"]))


def set_kennel_uniforms(prog, b, food=1.0):
    prog.setUniformValue("uWood", _rgb(b["wood"]))
    prog.setUniformValue("uRoof", _rgb(b["roof"]))
    prog.setUniformValue("uKScale", float(b["kscale"]))
    prog.setUniformValue("uFood", float(food))


def kennel_size(b):
    s = b["kscale"]
    return int(125 * s), int(105 * s) + dog3d.BASE


class SceneView(QOpenGLWidget):
    """scene 0: cane (ridisegnato a ogni frame), scene 1: cuccia (statica)."""

    def __init__(self, scene, flags):
        super().__init__(None, flags)
        self.scene = scene
        self.setFormat(surface_format())
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop)
        self.prog = self.vao = self.gl = None
        self.dog = self.rig = self.breed = None
        self.food = 1.0
        self.error = None

    def initializeGL(self):
        try:
            self.gl = gl_functions(self.context())
            self.prog = build_program()
        except RuntimeError as e:
            self.error = str(e)
            print(self.error)
        self.vao = QOpenGLVertexArrayObject(self)
        self.vao.create()

    def paintGL(self):
        f = self.gl
        if f is None:
            return
        f.glClearColor(0, 0, 0, 0)
        f.glClear(GL_COLOR_BUFFER_BIT)
        if self.prog is None or (self.scene == 0 and self.rig is None) or (self.scene == 1 and self.breed is None):
            return
        self.prog.bind()
        dpr = self.devicePixelRatioF()  # Retina / scala di Windows: lo shader conta pixel fisici
        set_common(self.prog, self.width() * dpr, self.height() * dpr, self.scene, dpr)
        if self.scene == 0:
            set_dog_uniforms(self.prog, self.dog, self.rig)
        else:
            set_kennel_uniforms(self.prog, self.breed, self.food)
        self.vao.bind()
        f.glDrawArrays(GL_TRIANGLES, 0, 3)
        self.vao.release()
        self.prog.release()
