#version 330 core
// Cane e cuccia in 3D: ray marching di superfici implicite (SDF) con pelo procedurale, ombre morbide e AO.
out vec4 fragColor;

uniform vec2 uRes;
uniform float uBase;
uniform float uElev;
uniform int uScene;          // 0 cane, 1 cuccia

uniform mat3 uBodyRot;       // cane -> mondo
uniform vec3 uRoot;
uniform vec3 uChest, uHip, uNeck0, uHeadPos;
uniform vec2 uBodyR;
uniform mat3 uHeadRot;       // testa -> cane
uniform float uHeadR, uMuzzle, uJaw, uTongue, uEyeOpen, uFur, uNeckR;
uniform vec3 uLeg[16];
uniform vec4 uLegR;          // anteriore alto/basso, posteriore alto/basso
uniform float uMane;         // criniera su collo e petto (0 = pelo corto)
uniform int uCarry;          // in bocca: 0 niente, 1 pallina, 2 rametto, 3 osso, 4 calzino
uniform float uFood;         // crocchette nella ciotola (0..1)
uniform float uZoom;         // pixel per unità (1 nell'app, di più nelle anteprime)
uniform vec3 uTail[6];
uniform float uTailR, uTailFur;
uniform vec3 uEarB[2];
uniform vec3 uEarD[2];
uniform vec3 uEarN[2];
uniform vec4 uEarDim;        // lunghezza, larghezza, spessore, rastremazione
uniform int uPattern;
uniform vec3 uCoat, uCoat2, uMark;
uniform vec3 uBoundC;
uniform float uBound;

uniform vec3 uWood, uRoof;
uniform float uKScale;
uniform int uXmas;           // cuccia di Natale: neve, luci, vischio, comignolo che fuma
uniform float uTime;

// ------------------------------------------------------------------ utilità
float hash(vec3 p) {
    p = fract(p * 0.3183099 + 0.1);
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}
float noise(vec3 x) {
    vec3 i = floor(x), f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(hash(i), hash(i + vec3(1, 0, 0)), f.x), mix(hash(i + vec3(0, 1, 0)), hash(i + vec3(1, 1, 0)), f.x), f.y),
               mix(mix(hash(i + vec3(0, 0, 1)), hash(i + vec3(1, 0, 1)), f.x), mix(hash(i + vec3(0, 1, 1)), hash(i + vec3(1, 1, 1)), f.x), f.y), f.z);
}
float furN(vec3 p) { return noise(p * 0.32) * 0.65 + noise(p * 0.85) * 0.35; }
// ciocche allungate in verticale: il pelo lungo cade verso il basso
float locks(vec3 p) { return noise(p * vec3(0.5, 0.14, 0.5)) * 0.65 + noise(p * vec3(1.2, 0.3, 1.2)) * 0.35; }
// ciocche fini solo per il colore, non per la forma
float strand(vec3 p) { return noise(p * vec3(2.2, 0.6, 2.2)); }

float smin(float a, float b, float k) {
    float h = max(k - abs(a - b), 0.0) / k;
    return min(a, b) - h * h * k * 0.25;
}
float smax(float a, float b, float k) { return -smin(-a, -b, k); }  // intersezione con spigoli arrotondati
float sdEllipsoid(vec3 p, vec3 r) {
    float k0 = length(p / r);
    float k1 = length(p / (r * r));
    return k0 * (k0 - 1.0) / k1;
}
float sdRoundCone(vec3 p, vec3 a, vec3 b, float r1, float r2) {
    vec3 ba = b - a;
    float l2 = max(dot(ba, ba), 1e-4);
    float rr = r1 - r2;
    float a2 = l2 - rr * rr;
    float il2 = 1.0 / l2;
    vec3 pa = p - a;
    float y = dot(pa, ba);
    float z = y - l2;
    vec3 xv = pa * l2 - ba * y;
    float x2 = dot(xv, xv);
    float y2 = y * y * l2;
    float z2 = z * z * l2;
    float k = sign(rr) * rr * rr * x2;
    if (sign(z) * a2 * z2 > k) return sqrt(x2 + z2) * il2 - r2;
    if (sign(y) * a2 * y2 < k) return sqrt(x2 + y2) * il2 - r1;
    return (sqrt(x2 * a2 * il2) + y * rr) * il2 - r1;
}
float sdBox(vec3 p, vec3 b) {
    vec3 q = abs(p) - b;
    return length(max(q, 0.0)) + min(max(q.x, max(q.y, q.z)), 0.0);
}
vec2 opU(vec2 a, vec2 b) { return a.x < b.x ? a : b; }

// ------------------------------------------------------------------ cane
// materiali: 1 corpo, 2 zampe, 3 coda, 4 testa, 5 naso, 6 occhio, 7 bocca, 8 lingua, 9 orecchio
float sdEar(vec3 q, int i) {
    vec3 d = uEarD[i], n = uEarN[i], w = cross(d, n);
    vec3 r = q - uEarB[i];
    float L = uEarDim.x;
    float far = length(r - d * L * 0.5) - L * 0.6 - uEarDim.y;
    if (far > 1.5) return far;  // la deformazione sotto non è una distanza valida lontano dall'orecchio
    float u = dot(r, d), v = dot(r, n), s = dot(r, w);
    float t = clamp(u / L, 0.0, 1.0);
    float taper = max(mix(1.0, 1.0 - uEarDim.w, t), 0.12);
    // leggera concavità: il padiglione si incurva
    v += (s * s) / (uEarDim.y * 3.0) * 0.6;
    return sdEllipsoid(vec3(u - L * 0.5, v, s / taper), vec3(L * 0.5, uEarDim.z, uEarDim.y)) * taper;
}

const float MOUTH_Y = -0.42, MOUTH_X = -0.38;  // l'angolo è dietro l'occhio, verso il collo
// larghezza del taglio della bocca: quanto il muso davanti, fino alle guance verso l'angolo (si vede di lato)
float mouthW(float x, float R) { return mix(0.7 * R, 0.4 * R, smoothstep(-0.3 * R, 0.3 * R, x)); }  // linea della bocca e suo angolo (spazio della testa, in R)
vec3 toHead(vec3 p) { return transpose(uHeadRot) * (p - uHeadPos); }
// occhi a mandorla rivolti in avanti, verso il muso, come nei cani veri
vec3 eyeC(float sg) { return vec3(0.63 * uHeadR, 0.2 * uHeadR, sg * 0.38 * uHeadR); }

vec2 mapDog(vec3 pw) {
    vec3 p = transpose(uBodyRot) * (pw - uRoot);
    float bd = length(p - uBoundC) - uBound;
    if (bd > 6.0) return vec2(bd, 0.0);

    float rc = uBodyR.x, rh = uBodyR.y;
    vec3 pz = vec3(p.x, p.y, p.z * 1.18);
    float body = sdEllipsoid(p - uChest, vec3(rc * 1.08, rc * 1.12, rc * 0.84));
    body = smin(body, sdEllipsoid(p - uHip, vec3(rh * 1.12, rh * 1.02, rh * 0.86)), rc * 0.7);
    body = smin(body, sdRoundCone(pz, uHip + vec3(0.0, rh * 0.15, 0.0), uChest + vec3(0.0, rc * 0.1, 0.0), rh * 0.78, rc * 0.8), rc * 0.5);

    float R = uHeadR;
    vec3 neckEnd = uHeadPos + uHeadRot * vec3(-R * 0.45, -R * 0.35, 0.0);
    float neck = sdRoundCone(pz, uNeck0, vec3(neckEnd.xy, neckEnd.z * 1.18), uNeckR, R * 0.62);
    body = smin(body, neck, rc * 0.5);
    if (uMane > 0.0) {  // criniera: collo e petto voluminosi come nel maremmano
        vec3 mc = mix(uNeck0, uChest, 0.35) + vec3(rc * 0.15, 0.0, 0.0);
        body = smin(body, sdEllipsoid(p - mc, vec3(rc * 0.8, rc * 1.0, rc * 0.92) * uMane), rc * 0.6);
    }
    // pelo morbido: poco rilievo nella forma (tanto rilievo sembra muffa), il resto lo fa il colore
    float core = body - uFur * (0.3 + 0.6 * (locks(p) - 0.45));

    float legs = 1e9;
    for (int i = 0; i < 4; i++) {
        float r0 = i < 2 ? uLegR.x : uLegR.z;
        float r2 = i < 2 ? uLegR.y : uLegR.w;
        vec3 a = uLeg[i * 4], b = uLeg[i * 4 + 1], c = uLeg[i * 4 + 2], f = uLeg[i * 4 + 3];
        float rm = mix(r0, r2, 0.6);
        float l = sdRoundCone(p, a, b, r0, rm);
        l = smin(l, sdRoundCone(p, b, c, rm, r2), r2 * 0.8);
        l = smin(l, sdRoundCone(p, c, f, r2, r2 * 0.82), r2 * 0.6);
        l = smin(l, sdEllipsoid(p - (f + vec3(r2 * 0.55, -r2 * 0.05, 0.0)), vec3(r2 * 1.2, r2 * 0.78, r2 * 1.0)), r2 * 0.9);
        legs = min(legs, l);
    }
    legs -= uFur * (0.12 + 0.25 * (locks(p * 1.3) - 0.45)) * clamp(p.y / uLeg[0].y, 0.15, 1.0);  // stinchi asciutti, cosce pelose

    float tail = 1e9;
    for (int i = 0; i < 5; i++) {
        float t0 = float(i) / 5.0, t1 = float(i + 1) / 5.0;
        tail = min(tail, sdRoundCone(p, uTail[i], uTail[i + 1], uTailR * mix(1.0, 0.5, t0), uTailR * mix(1.0, 0.5, t1)));
    }
    tail -= uTailFur * (0.35 + 0.6 * (locks(p) - 0.45));

    vec3 q = toHead(p);
    // testa anatomica: cranio largo e piatto, arcate sopraccigliari, stop, muso alto, labbra, mascella
    float M = uMuzzle;
    float head = sdEllipsoid(q - vec3(-0.15 * R, 0.12 * R, 0.0), vec3(0.95 * R, 0.74 * R, 0.82 * R));
    vec3 bq = vec3(q.x, q.y, abs(q.z));
    head = smin(head, sdEllipsoid(bq - vec3(0.4 * R, 0.32 * R, 0.34 * R), vec3(0.28, 0.17, 0.24) * R), 0.22 * R);
    head = smin(head, sdEllipsoid(q - vec3(0.02 * R, -0.24 * R, 0.0), vec3(0.6 * R, 0.46 * R, 0.74 * R)), 0.3 * R);
    vec3 mq = vec3(q.x, q.y, q.z * 1.08);
    head = smin(head, sdRoundCone(mq, vec3(0.5 * R, -0.22 * R, 0.0), vec3(0.5 * R + M, -0.2 * R, 0.0), 0.42 * R, 0.25 * R), 0.38 * R);
    head = smin(head, sdEllipsoid(q - vec3(0.5 * R + M * 0.55, -0.42 * R, 0.0), vec3(M * 0.5, 0.17 * R, 0.36 * R)), 0.12 * R);
    // muso e guance tagliati lungo la linea della bocca, dall'angolo sotto l'occhio fino al naso:
    // sotto c'è solo la mascella, così quando si abbassa la bocca si apre per tutta la lunghezza
    head = max(head, -smax(smax(q.y - MOUTH_Y * R, MOUTH_X * R - q.x, 0.1 * R), abs(q.z) - mouthW(q.x, R), 0.2 * R));
    vec3 hinge = vec3(-0.55 * R, -0.39 * R, 0.0);
    float ja = uJaw * 0.5;  // cerniera più indietro: basta meno angolo per la stessa apertura
    vec3 jq = q - hinge;
    jq = vec3(cos(ja) * jq.x - sin(ja) * jq.y, sin(ja) * jq.x + cos(ja) * jq.y, jq.z) + hinge;
    float jaw = sdRoundCone(jq, vec3(-0.35 * R, -0.57 * R, 0.0), vec3(0.45 * R + M * 0.9, -0.53 * R, 0.0), 0.28 * R, 0.15 * R);
    // bocca chiusa: mento unito al muso; aperta: separati (k mai zero: smin dividerebbe per zero e la testa sparirebbe)
    head = smin(head, jaw, max(0.16 * R * (1.0 - uJaw * 4.0), 0.01));
    head -= uFur * (0.08 + 0.1 * (furN(q * 0.9) - 0.4));

    float fur = smin(smin(core, legs, rh * 0.45), tail, uTailR * 1.2);
    fur = smin(fur, head, R * 0.25);
    // bocca aperta: il cuneo tra mascella superiore e inferiore si svuota anche nel pelo di collo e criniera,
    // così l'apertura arriva fino all'angolo della bocca (a bocca chiusa il cuneo è vuoto)
    float wedge = smax(smax(max(q.y - MOUTH_Y * R, MOUTH_Y * R - jq.y), MOUTH_X * R - q.x, 0.12 * R),
                       abs(q.z) - mouthW(q.x, R), 0.2 * R);  // spigoli arrotondati: niente bocca "a scatola"
    fur = max(fur, -wedge);
    float part = 1.0;
    float best = core;
    if (legs < best) { best = legs; part = 2.0; }
    if (tail < best) { best = tail; part = 3.0; }
    if (head < best) { best = head; part = 4.0; }
    vec2 res = vec2(fur, part);

    vec3 nc = vec3(0.6 * R + uMuzzle, -0.08 * R, 0.0);
    res = opU(res, vec2(sdEllipsoid(q - nc, vec3(0.21 * R, 0.17 * R, 0.24 * R)), 5.0));
    for (int s = 0; s < 2; s++) {
        float sg = s == 0 ? 1.0 : -1.0;
        vec3 ec = eyeC(sg) * vec3(1.0, 1.0, mix(0.93, 1.0, uEyeOpen));
        res = opU(res, vec2(sdEllipsoid(q - ec, vec3(0.19, 0.12 * mix(0.25, 1.0, uEyeOpen), 0.21) * R), 6.0));
    }
    if (uJaw > 0.03) {  // interno della bocca, lungo quanto il taglio
        float mx0 = MOUTH_X * R, mx1 = 0.45 * R + uMuzzle;
        vec3 mc = vec3((mx0 + mx1) * 0.5, MOUTH_Y * R - uJaw * 0.2 * R, 0.0);
        res = opU(res, vec2(sdEllipsoid(q - mc, vec3((mx1 - mx0) * 0.5, 0.04 * R + uJaw * 0.24 * R, 0.3 * R)), 7.0));
    }
    if (uTongue > 0.03) {
        float tl = uMuzzle * (0.55 + 0.5 * uTongue);
        vec3 tc = vec3(0.3 * R + uMuzzle * 0.4 + tl * 0.5, MOUTH_Y * R - 0.08 * R - uJaw * 0.3 * R - uTongue * 0.1 * R, 0.0);
        float dr = -0.5 * uTongue;
        vec3 tq = q - tc;
        tq = vec3(cos(dr) * tq.x - sin(dr) * tq.y, sin(dr) * tq.x + cos(dr) * tq.y, tq.z);
        res = opU(res, vec2(sdEllipsoid(tq, vec3(tl * 0.5, 0.07 * R, 0.17 * R)), 8.0));
    }
    for (int i = 0; i < 2; i++) res = opU(res, vec2(sdEar(q, i) - uFur * 0.15, 9.0));
    if (uCarry == 1) res = opU(res, vec2(length(q - vec3(0.5 * R + M * 0.7, -0.42 * R, 0.0)) - 0.34 * R, 13.0));
    if (uCarry == 2) res = opU(res, vec2(sdRoundCone(q, vec3(0.45 * R + M * 0.6, -0.42 * R, -2.2 * R),
                                                     vec3(0.45 * R + M * 0.6, -0.36 * R, 2.0 * R), 0.13 * R, 0.1 * R), 14.0));
    if (uCarry == 3) {  // osso di traverso: stecca con due nodi per parte
        vec3 bq = q - vec3(0.45 * R + M * 0.6, -0.42 * R, 0.0);
        float bone = sdRoundCone(bq, vec3(0.0, 0.0, -1.1 * R), vec3(0.0, 0.0, 1.1 * R), 0.12 * R, 0.12 * R);
        vec3 kq = vec3(bq.x, abs(bq.y) - 0.12 * R, abs(bq.z) - 1.15 * R);
        res = opU(res, vec2(min(bone, length(kq) - 0.2 * R), 18.0));
    }
    if (uCarry == 4) res = opU(res, vec2(sdRoundCone(q, vec3(0.45 * R + M * 0.6, -0.42 * R, 0.0),
                                                     vec3(0.5 * R + M * 0.6, -1.3 * R, 0.5 * R), 0.17 * R, 0.21 * R), 19.0));
    return res;
}

// ------------------------------------------------------------------ cuccia
const float KW = 30.0, KD = 27.0, KH = 42.0, KROOF = 22.0;
vec3 roofR(vec3 p) {  // spazio di una falda del tetto: x lungo la falda (verso la gronda), y fuori dal tetto
    float ang = atan(KROOF, KW);
    vec3 r = vec3(abs(p.x), p.y, p.z) - vec3(KW * 0.5, KH + KROOF * 0.5 + 1.5, 0.0);
    return vec3(cos(ang) * r.x - sin(ang) * r.y, sin(ang) * r.x + cos(ang) * r.y, r.z);
}
vec3 rotZ(vec3 q, float a) { return vec3(cos(a) * q.x - sin(a) * q.y, sin(a) * q.x + cos(a) * q.y, q.z); }
float bulbIndex(vec3 r) { return clamp(floor(r.x / 4.2 + 0.5), -5.0, 5.0); }
const vec3 CHIMNEY = vec3(15.0, KH + KROOF * 0.6, -9.0);  // centro del comignolo (mezza altezza KROOF * 0.45)

vec2 mapKennel(vec3 pw) {
    float s = uKScale;
    vec3 p = pw / s;
    float a = radians(-10.0);  // porta quasi di fronte
    p = vec3(cos(a) * p.x + sin(a) * p.z, p.y, -sin(a) * p.x + cos(a) * p.z);
    p.z += 6.0;
    float W = KW, D = KD, H = KH, roofH = KROOF;
    float walls = sdBox(p - vec3(0.0, H * 0.5, 0.0), vec3(W, H * 0.5, D));
    walls = max(walls, -sdBox(p - vec3(0.0, H * 0.5 + 2.5, 0.0), vec3(W - 2.5, H * 0.5, D - 2.5)));
    float dw = 10.5, dh = 25.0;
    float door = min(sdBox(p - vec3(0.0, dh * 0.5, D), vec3(dw, dh * 0.5, 4.0)),
                     max(length(p.xy - vec2(0.0, dh)) - dw, abs(p.z - D) - 4.0));
    walls = max(walls, -door);
    // timpani triangolari davanti e dietro
    float gable = max(sdBox(p - vec3(0.0, H + roofH * 0.5, 0.0), vec3(W, roofH * 0.5, D)),
                      (abs(p.x) / W + (p.y - H) / roofH - 1.0) * 12.0);
    gable = max(gable, -sdBox(p - vec3(0.0, H + roofH * 0.5, 0.0), vec3(W, roofH, D - 2.5)));
    walls = min(walls, gable);
    vec3 r = roofR(p);
    float roof = sdBox(r, vec3(sqrt(W * W + roofH * roofH) * 0.5 + 5.0, 1.6, D + 5.0)) - 0.4;
    float base = sdBox(p - vec3(0.0, 1.0, 0.0), vec3(W + 1.5, 1.0, D + 1.5));
    vec2 res = opU(vec2(min(walls, base), 11.0), vec2(roof, 12.0));
    if (uXmas == 1) {
        float hl = sqrt(W * W + roofH * roofH) * 0.5;
        // neve morbida sulle falde e sul comignolo di mattoni
        float snow = sdBox(r - vec3(0.0, 2.3, 0.0), vec3(hl + 4.6, 0.9 + 0.7 * noise(p * 0.35), D + 4.6)) - 0.9;
        vec3 cp = p - CHIMNEY;
        snow = min(snow, sdBox(cp - vec3(0.0, roofH * 0.45 + 0.9, 0.0), vec3(4.0, 0.7 + 0.4 * noise(p), 4.0)) - 0.7);
        res = opU(res, vec2(snow, 20.0));
        res = opU(res, vec2(sdBox(cp, vec3(3.6, roofH * 0.45, 3.6)) - 0.3, 21.0));
        // filo di lucine sotto la gronda davanti
        vec3 lp = r - vec3(bulbIndex(r) * 4.2, -3.1, D + 4.4);
        res = opU(res, vec2(sdEllipsoid(lp, vec3(1.0, 1.4, 1.0)), 22.0));
        res = opU(res, vec2(sdBox(r - vec3(0.0, -2.1, D + 4.4), vec3(hl + 3.0, 0.25, 0.25)), 23.0));
        // vischio appeso sopra la porta: due foglie, tre bacche bianche e un fiocco rosso
        vec3 mp = p - vec3(0.0, 38.6, D + 1.4);
        float leaf = min(sdEllipsoid(rotZ(mp - vec3(-2.0, -1.2, 0.0), 0.55), vec3(3.0, 1.1, 0.6)),
                         sdEllipsoid(rotZ(mp - vec3(2.0, -1.2, 0.0), -0.55), vec3(3.0, 1.1, 0.6)));
        res = opU(res, vec2(leaf, 24.0));
        vec3 bq = vec3(abs(mp.x), mp.y, mp.z);
        res = opU(res, vec2(min(length(bq - vec3(0.8, -1.5, 0.9)) - 0.85, length(mp - vec3(0.0, -2.5, 1.0)) - 0.85), 25.0));
        res = opU(res, vec2(sdEllipsoid(rotZ(bq - vec3(1.3, 1.0, 0.6), 0.4), vec3(1.5, 0.9, 0.6)), 26.0));
    }
    vec3 bp = p - vec3(40.0, 0.0, 22.0);  // ciotola davanti a destra
    float bowl = max(sdEllipsoid(bp - vec3(0.0, 1.0, 0.0), vec3(9.0, 5.5, 9.0)), bp.y - 4.6);
    bowl = max(bowl, -sdEllipsoid(bp - vec3(0.0, 5.2, 0.0), vec3(7.6, 4.0, 7.6)));
    res = opU(res, vec2(max(bowl, -bp.y), 15.0));
    vec3 wp = p - vec3(-40.0, 0.0, 22.0);  // ciotola dell'acqua davanti a sinistra
    float wbowl = max(sdEllipsoid(wp - vec3(0.0, 1.0, 0.0), vec3(9.0, 5.5, 9.0)), wp.y - 4.6);
    wbowl = max(wbowl, -sdEllipsoid(wp - vec3(0.0, 5.2, 0.0), vec3(7.6, 4.0, 7.6)));
    res = opU(res, vec2(max(wbowl, -wp.y), 15.0));
    res = opU(res, vec2(sdEllipsoid(wp - vec3(0.0, 3.4, 0.0), vec3(7.2, 0.6, 7.2)), 17.0));
    if (uFood > 0.02) res = opU(res, vec2(sdEllipsoid(bp - vec3(0.0, 1.6 + 2.0 * uFood, 0.0), vec3(6.6, 1.6, 6.6)) - 0.4 * noise(bp * 1.5), 16.0));
    return vec2(res.x * s, res.y);
}

vec2 map(vec3 p) { return uScene == 0 ? mapDog(p) : mapKennel(p); }

vec3 calcNormal(vec3 p) {
    const vec2 k = vec2(1, -1);
    float e = 0.08;
    vec3 g = k.xyy * map(p + k.xyy * e).x + k.yyx * map(p + k.yyx * e).x +
             k.yxy * map(p + k.yxy * e).x + k.xxx * map(p + k.xxx * e).x;
    float l = length(g);
    return l > 1e-5 ? g / l : vec3(0.0, 0.0, 1.0);  // gradiente nullo: normalize darebbe NaN (pixel neri)
}
float softShadow(vec3 ro, vec3 rd) {
    float res = 1.0, t = 0.6;
    for (int i = 0; i < 36; i++) {
        float h = map(ro + rd * t).x;
        res = min(res, 9.0 * h / t);
        t += clamp(h, 0.4, 7.0);
        if (res < 0.02 || t > 140.0) break;
    }
    return clamp(res, 0.0, 1.0);
}
float calcAO(vec3 p, vec3 n) {
    float occ = 0.0, sca = 1.0;
    for (int i = 1; i <= 5; i++) {
        float h = 1.2 * float(i);
        occ += (h - map(p + n * h).x) * sca;
        sca *= 0.7;
    }
    return clamp(1.0 - occ * 0.09, 0.0, 1.0);
}


float segDist(vec2 p, vec2 a, vec2 b) {
    vec2 pa = p - a, ba = b - a;
    return length(pa - ba * clamp(dot(pa, ba) / max(dot(ba, ba), 1e-4), 0.0, 1.0));
}
float groundShadow(vec3 g) {
    if (uScene == 1) {
        vec3 p = g / uKScale;
        float a = radians(-10.0);  // porta quasi di fronte
        p = vec3(cos(a) * p.x + sin(a) * p.z, p.y, -sin(a) * p.x + cos(a) * p.z);
        p.z += 6.0;
        vec2 q = abs(p.xz + vec2(4.0, -4.0)) - vec2(31.0, 28.0);
        float d = length(max(q, 0.0)) + min(max(q.x, q.y), 0.0);
        float dbowl = min(length(p.xz - vec2(40.0, 16.0)), length(p.xz - vec2(-40.0, 16.0))) - 9.0;
        return max(0.32 * (1.0 - smoothstep(-4.0, 9.0, d)), 0.3 * (1.0 - smoothstep(-2.0, 4.0, dbowl)));
    }
    vec3 p = transpose(uBodyRot) * (g - vec3(uRoot.x, 0.0, uRoot.z));
    float lift = 1.0 - smoothstep(0.0, 40.0, uRoot.y);
    float rc = uBodyR.x;
    vec2 sq = vec2(p.x, p.z * 1.3);
    float d = segDist(sq, vec2(uHip.x - uBodyR.y * 0.6, 0.0), vec2(uChest.x + rc * 0.4, 0.0));
    float a = 0.3 * (1.0 - smoothstep(rc * 0.3, rc * 1.35, d));
    for (int i = 0; i < 4; i++) {
        vec3 f = uLeg[i * 4 + 3];
        float fd = length(p.xz - f.xz - vec2(uLegR.y * 0.4, 0.0));
        a = max(a, 0.42 * (1.0 - smoothstep(0.0, uLegR.y * 2.4, fd)) * (1.0 - smoothstep(0.0, 6.0, f.y + uRoot.y - uLegR.y)));
    }
    return a * lift;
}

vec3 lin(vec3 c) { return pow(c, vec3(2.2)); }

vec4 smoke(vec2 sp) {  // fumo del comignolo: sbuffi 2D che salgono, si allargano e svaniscono (alpha premoltiplicato)
    if (uScene != 1 || uXmas == 0) return vec4(0.0);
    float a = radians(-10.0);
    vec3 k = vec3(CHIMNEY.x, CHIMNEY.y + KROOF * 0.45 + 1.5, CHIMNEY.z - 6.0);  // in cima, nello spazio della cuccia
    vec3 c = vec3(cos(a) * k.x - sin(a) * k.z, k.y, sin(a) * k.x + cos(a) * k.z) * uKScale;
    vec2 top = vec2(c.x, c.y * cos(uElev) - c.z * sin(uElev));
    float acc = 0.0;
    for (int i = 0; i < 6; i++) {
        float ph = fract(uTime * 0.22 + float(i) / 6.0);
        vec2 pc = top + vec2(ph * 10.0 + sin(uTime * 1.3 + float(i) * 2.1) * 2.0 * ph, ph * 34.0) * uKScale;
        float d = length(sp - pc) / ((2.2 + ph * 5.5) * uKScale);
        acc += 0.42 * (1.0 - ph) * smoothstep(0.0, 0.12, ph) * (1.0 - smoothstep(0.4, 1.0, d));
    }
    acc = clamp(acc, 0.0, 0.75);
    return vec4(vec3(0.82, 0.83, 0.86) * acc, acc);
}

vec3 dogAlbedo(vec3 pw, float m) {
    vec3 p = transpose(uBodyRot) * (pw - uRoot);
    vec3 q = toHead(p);
    float R = uHeadR, rc = uBodyR.x;
    float n = furN(p * 1.5) * 0.4 + strand(p) * 0.6;
    if (m == 5.0) {  // naso: narici scure e tartufo leggermente granuloso
        vec3 nq = q - vec3(0.6 * R + uMuzzle, -0.08 * R, 0.0);
        float nostril = smoothstep(0.07 * R, 0.035 * R, length(vec2(nq.y + 0.04 * R, abs(nq.z) - 0.11 * R))) * step(0.08 * R, nq.x);
        return lin(vec3(0.08, 0.07, 0.07) * (0.85 + 0.3 * noise(q * 3.0)) * (1.0 - 0.8 * nostril));
    }
    if (m == 6.0) {  // occhio: pupilla, iride marrone calda, bordo scuro
        vec3 ec = eyeC(sign(q.z));
        float c = dot(normalize(q - ec), normalize(vec3(0.85, 0.05, sign(q.z) * 0.5)));
        // iride ambra con pupilla, bordo nero delle palpebre; piccolo riflesso uguale nei due occhi
        vec3 iris = mix(vec3(0.24, 0.11, 0.04), vec3(0.46, 0.24, 0.09), smoothstep(0.6, 0.85, c));
        float glint = dot(normalize(q - ec), normalize(vec3(0.75, 0.5, sign(q.z) * 0.42)));
        if (glint > 0.985) return vec3(0.9);
        return lin(c > 0.93 ? vec3(0.02) : c > 0.6 ? iris : vec3(0.03, 0.02, 0.02));
    }
    if (m == 7.0) return lin(mix(vec3(0.07, 0.05, 0.05), vec3(0.5, 0.17, 0.2), smoothstep(0.24 * R, 0.08 * R, abs(q.z))));
    if (m == 8.0) return lin(vec3(0.93, 0.5, 0.55));
    if (m == 13.0) {  // pallina da tennis con la cucitura
        vec3 bc = normalize(q - vec3(0.5 * R + uMuzzle * 0.7, -0.42 * R, 0.0));
        return lin(abs(bc.y + 0.6 * sin(atan(bc.z, bc.x) * 2.0) * 0.5) < 0.09 ? vec3(0.95) : vec3(0.82, 0.9, 0.22));
    }
    if (m == 14.0) return lin(vec3(0.45, 0.3, 0.17)) * (0.8 + 0.3 * noise(q * vec3(0.6, 0.6, 3.0)));
    if (m == 18.0) return lin(vec3(0.93, 0.89, 0.8)) * (0.9 + 0.15 * noise(q * 2.0));  // osso
    if (m == 19.0) return lin(fract(q.y / (0.3 * R)) < 0.5 ? vec3(0.8, 0.15, 0.15) : vec3(0.95));  // calzino a righe

    vec3 coat = lin(uCoat), coat2 = lin(uCoat2), mark = lin(uMark);
    float w = 0.0;  // quantità di "segno" (bianco/crema)
    float edge = (n - 0.5) * 0.35;
    float legH = uLeg[0].y;
    if (uPattern == 1) {         // border collie
        if (m == 4.0) {
            w = max(w, smoothstep(0.35 * R, 0.6 * R, q.x + edge * R));
            w = max(w, step(abs(q.z), 0.13 * R + edge * 0.1 * R) * step(-0.15 * R, q.x) * step(-0.25 * R, q.y));
            w = max(w, smoothstep(-0.2 * R, -0.45 * R, q.y + edge * R) * step(0.0, q.x));
        }
        if (m == 1.0) {
            w = max(w, smoothstep(uChest.x + rc * 0.25, uChest.x + rc * 0.6, p.x + edge * rc));
            w = max(w, smoothstep(uNeck0.y + rc * 0.1, uNeck0.y + rc * 0.4, p.y) * step(uChest.x, p.x));
        }
        if (m == 2.0) w = max(w, smoothstep(legH * 0.75, legH * 0.55, p.y + edge * 4.0));
        if (m == 3.0) w = max(w, smoothstep(uTailR * 3.0, uTailR * 1.8, length(p - uTail[5])));
    } else if (uPattern == 2) {  // shiba: urajiro
        if (m == 4.0) {
            w = max(w, smoothstep(-0.02 * R, -0.22 * R, q.y + edge * R) * smoothstep(-0.5 * R, -0.1 * R, q.x));
            w = max(w, smoothstep(0.1 * R, 0.06 * R, length(q - vec3(0.42 * R, 0.42 * R, sign(q.z) * 0.42 * R))));
        }
        if (m == 1.0) {
            w = max(w, smoothstep(uChest.x + rc * 0.3, uChest.x + rc * 0.75, p.x + edge * rc) * step(p.y, uNeck0.y + rc * 0.3));
            w = max(w, smoothstep(uChest.y - rc * 0.45, uChest.y - rc * 0.85, p.y + edge * rc));
        }
        if (m == 2.0) w = max(w, smoothstep(legH * 0.55, legH * 0.3, p.y + edge * 4.0));
        if (m == 3.0) w = max(w, step(p.y, uTail[1].y) * 0.6);
    } else if (uPattern == 3) {  // golden: più chiaro su muso, petto e frange
        if (m == 4.0) w = smoothstep(0.4 * R, 0.9 * R, q.x) * 0.6;
        if (m == 1.0) w = smoothstep(uChest.y - rc * 0.3, uChest.y - rc * 1.0, p.y) * 0.5;
        if (m == 3.0) w = 0.35;
    } else if (uPattern == 5) {  // meticcio arruffato: muso e barba chiari, ciocche più scure sul dorso, coda chiara
        if (m == 4.0) w = smoothstep(0.25 * R, 0.75 * R, q.x + edge * R) * 0.75;
        if (m == 1.0) w = -smoothstep(uChest.y - rc * 0.2, uChest.y + rc * 0.8, p.y) * (0.25 + 0.5 * n);
        if (m == 3.0) w = 0.55;
    } else if (uPattern == 4) {  // bassotto: dorso più scuro
        if (m == 1.0 || m == 4.0) w = -smoothstep(uChest.y + rc * 0.4, uChest.y + rc * 1.0, p.y) * 0.5;
    }
    vec3 c = w >= 0.0 ? mix(coat, mark, clamp(w, 0.0, 1.0)) : mix(coat, coat2, -w);
    if (m == 2.0 && p.y < uLegR.y * 1.4) {  // dita: solchi sulla punta della zampa
        float toes = smoothstep(0.75, 1.0, abs(sin(p.z * 3.14159 / (uLegR.y * 0.55))));
        c *= 1.0 - 0.35 * toes * smoothstep(uLegR.y * 1.4, uLegR.y * 0.4, p.y);
    }
    if (m == 9.0) c = uPattern == 1 ? coat : mix(coat, coat2, 0.75);
    if (m == 4.0) {  // labbra nere lungo la bocca, dall'angolo fino al naso
        float lip = smoothstep(0.07 * R, 0.02 * R, abs(q.y - MOUTH_Y * R)) * smoothstep(MOUTH_X * R, MOUTH_X * R + 0.12 * R, q.x)
                  * smoothstep(0.02 * R, -0.08 * R, abs(q.z) - mouthW(q.x, R));
        c = mix(c, vec3(0.05, 0.04, 0.04), 0.8 * lip);
    }
    if (uPattern == 0) {  // maremmano: avorio, sfumature biscotto attorno alle orecchie e nelle ciocche
        if (m == 4.0) c = mix(c, coat2, 0.45 * smoothstep(0.1 * R, -0.5 * R, q.x) * smoothstep(-0.1 * R, 0.4 * R, q.y));
        c = mix(c, coat2, 0.35 * (1.0 - n));
    }
    return c * clamp(0.88 + 0.24 * n, 0.6, 1.2);  // il rumore del pelo non deve mai annerire
}

vec3 kennelAlbedo(vec3 pw, float m) {
    vec3 p = pw / uKScale;
    vec3 k = p;
    float a = radians(-10.0);
    k = vec3(cos(a) * k.x + sin(a) * k.z, k.y, -sin(a) * k.x + cos(a) * k.z);
    k.z += 6.0;
    if (m == 20.0) return lin(vec3(0.93, 0.95, 1.0)) * (0.93 + 0.07 * noise(p * 1.7));  // neve
    if (m == 21.0) {  // mattoni del comignolo
        float row = k.y / 2.0;
        float bx = fract((k.x + k.z) / 4.0 + 0.5 * mod(floor(row), 2.0));
        float mortar = max(step(fract(row), 0.14), step(bx, 0.08));
        return lin(mix(vec3(0.6, 0.22, 0.15), vec3(0.78, 0.75, 0.7), mortar));
    }
    if (m == 22.0) {  // lucine colorate che si accendono a onda
        vec3 r = roofR(k);
        float side = step(0.0, k.x);
        float i = bulbIndex(r);
        float c = mod(i + 5.0 + side * 2.0, 4.0);
        vec3 col = c < 1.0 ? vec3(1.0, 0.12, 0.08) : c < 2.0 ? vec3(0.15, 1.0, 0.2) : c < 3.0 ? vec3(1.0, 0.75, 0.1) : vec3(0.2, 0.4, 1.0);
        float on = step(fract(uTime * 0.8 - i * 0.22 - side * 0.5), 0.6);
        return col * mix(0.2, 1.5, on);
    }
    if (m == 23.0) return lin(vec3(0.06, 0.14, 0.07));  // filo
    if (m == 24.0) return lin(vec3(0.24, 0.48, 0.17));  // foglie di vischio
    if (m == 25.0) return lin(vec3(0.96, 0.95, 0.88));  // bacche
    if (m == 26.0) return lin(vec3(0.82, 0.07, 0.1));   // fiocco
    if (m == 11.0 && abs(k.x) < 28.0 && abs(k.z) < 25.0 && k.y > 2.1 && k.y < 41.0) return lin(vec3(0.09, 0.06, 0.04));  // interno in ombra
    if (m == 15.0) return lin(vec3(0.72, 0.16, 0.12)) * (0.9 + 0.1 * noise(p));  // ciotola smaltata
    if (m == 17.0) return lin(vec3(0.3, 0.55, 0.8));  // acqua
    if (m == 16.0) return lin(vec3(0.5, 0.3, 0.15)) * (0.6 + 0.6 * noise(p * 2.5));  // crocchette
    if (m == 12.0) {
        float row = fract(p.y / 3.2 + 0.5 * step(0.5, fract(p.x / 7.0)));
        return lin(uRoof) * (0.75 + 0.25 * smoothstep(0.0, 0.25, row)) * (0.85 + 0.3 * noise(p * vec3(0.4, 2.0, 0.4)));
    }
    float groove = smoothstep(0.0, 0.12, abs(fract(p.y / 6.0) - 0.5) * 2.0 - 0.05);
    float grain = noise(p * vec3(0.08, 1.4, 0.08)) * 0.5 + noise(p * vec3(0.3, 3.0, 0.3)) * 0.5;
    return lin(uWood) * (0.6 + 0.4 * groove) * (0.8 + 0.35 * grain);
}

void main() {
    vec2 sp = vec2(gl_FragCoord.x - uRes.x * 0.5, gl_FragCoord.y - uBase) / max(uZoom, 1.0);
    vec3 fw = vec3(0.0, -sin(uElev), -cos(uElev));
    vec3 up = vec3(0.0, cos(uElev), -sin(uElev));
    vec3 ro = vec3(sp.x, 0.0, 0.0) + up * sp.y - fw * 300.0;
    vec3 rd = fw;

    float t = 150.0;
    vec2 h = vec2(1.0);
    bool hit = false;
    float minH = 1e9, tMin = t;
    vec2 hMin = h;
    for (int i = 0; i < 140; i++) {
        h = map(ro + rd * t);
        if (h.x < minH) { minH = h.x; tMin = t; hMin = h; }
        if (h.x < 0.04) { hit = true; break; }
        t += h.x * 0.75;
        if (t > 460.0) break;
    }
    float cover = 1.0;
    if (!hit && minH < 0.8) {  // pixel di bordo: colore del punto più vicino, coperto in parte
        hit = true;
        cover = 1.0 - minH / 0.8;
        t = tMin;
        h = hMin;
    }
    vec3 L = normalize(vec3(-0.45, 0.85, 0.55));
    vec4 ground = vec4(0.0);
    if (cover < 1.0 || !hit) {
        // ombra a terra analitica (piano y = 0), resa come trasparenza scura
        float tg = -ro.y / rd.y;
        float a = groundShadow(ro + rd * tg);
        ground = vec4(0.0, 0.0, 0.0, a);
        if (!hit) { vec4 sm = smoke(sp); fragColor = sm + ground * (1.0 - sm.a); return; }
    }
    vec3 pos = ro + rd * t;
    vec3 n = calcNormal(pos);
    if (dot(n, rd) > 0.0) {  // il raggio è entrato in una ciocca: torna in superficie, se no luce e AO sono zero (nero)
        pos -= rd * 0.6;
        n = normalize(n - 2.0 * dot(n, rd) * rd);
    }
    float m = h.y;
    vec3 alb = uScene == 0 ? dogAlbedo(pos, m) : kennelAlbedo(pos, m);
    float sh = softShadow(pos + n * 0.5, L);
    float ao = calcAO(pos, n);
    float wrap = (m <= 4.0 || m == 9.0) ? 0.6 : 0.15;
    float dif = clamp((dot(n, L) + wrap) / (1.0 + wrap), 0.0, 1.0);
    float sky = 0.55 + 0.45 * n.y;
    float rim = pow(clamp(1.0 + dot(n, rd), 0.0, 1.0), 3.0);
    vec3 col = alb * (vec3(1.0, 0.95, 0.86) * dif * mix(0.35, 1.0, sh) * 1.35 + vec3(0.6, 0.64, 0.72) * sky * 0.65 * ao);
    col += alb * rim * 0.45 * ao;
    if ((m >= 5.0 && m <= 8.0) || m == 15.0 || m == 17.0) {
        float spec = pow(clamp(dot(reflect(-L, n), -rd), 0.0, 1.0), m == 6.0 ? 70.0 : 25.0);
        col += vec3(1.0) * spec * (m == 6.0 ? 1.4 : 0.35) * sh;
        if (m == 6.0) col += vec3(1.0) * smoothstep(0.975, 0.99, dot(n, normalize(vec3(-0.3, 0.55, 1.0)))) * 0.8;  // riflesso vivo negli occhi
    }
    col *= mix(0.75, 1.0, ao);
    if (m == 22.0) col = alb;  // le lucine fanno luce da sole
    col = clamp(pow(max(col, 0.0), vec3(1.0 / 2.2)), 0.0, 1.0);  // >1 romperebbe l'alpha premoltiplicato
    vec4 sm = smoke(sp);
    fragColor = sm + (vec4(col, 1.0) * cover + ground * (1.0 - cover)) * (1.0 - sm.a);  // alpha premoltiplicato
}
