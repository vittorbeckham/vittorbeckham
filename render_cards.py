"""Gera as cartas SVG animadas do perfil em cartas/.

    python render_cards.py            # cartas animadas em cartas/ (+ atualiza o README)
    STATIC=1 python render_cards.py   # quadro final, sem animação, em preview/

Lê data/profile.json (textos), data/contributions.json e data/repos.json
(atualizados pela Action diária). As cartas são exibidas via <img>, então
cada SVG é autossuficiente: <style> inline com keyframes, SMIL e fontes
recortadas com pyftsubset e embutidas como WOFF em base64.

O espaçamento entre cartas já vem dentro de cada SVG: no README as <img>
ficam separadas só por <br>, e as que dividem uma linha ficam coladas.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent
STATIC = os.environ.get("STATIC") == "1"
OUT = ROOT / (os.environ.get("OUT") or ("preview" if STATIC else "cartas"))

# ── Identidade ──────────────────────────────────────────────────────────────
# Papel e tinta (a tinta vem do azul-noite #1B1B3A do perfil antigo) + os
# acentos de sempre: coral, amarelo e verde. Índigo é a cor da marca.
PAPER, LINE, RULE = "#F6F3EC", "#E3DDD0", "#D9D3C6"
INK, INK2, INK3 = "#16162E", "#4A4B63", "#8A8B9C"
INDIGO, GLOW = "#4646C6", "#8C8CF5"
COLORS = {"coral": "#FF6B6B", "sun": "#FFD93D", "mint": "#6BCB77", "sky": "#6BE0FF", "indigo": INDIGO}
LANG_COLORS = {"Python": "#3776AB", "Jupyter Notebook": "#F37626", "JavaScript": "#F1E05A",
               "HTML": "#E34C26", "CSS": "#563D7C", "TypeScript": "#3178C6", "Shell": "#89E051"}
MESES = "jan fev mar abr mai jun jul ago set out nov dez".split()
W, GAP, RADIUS = 880, 14, 12


# ── Fontes ──────────────────────────────────────────────────────────────────
class Font:
    def __init__(self, key: str, file: str):
        self.key, self.path = key, ROOT / "fonts" / file
        tt = TTFont(self.path)
        self.cmap, self.hmtx, self.upm = tt.getBestCmap(), tt["hmtx"], tt["head"].unitsPerEm

    def width(self, text: str, size: float, ls: float = 0) -> float:
        adv = sum(self.hmtx[self.cmap[ord(c)]][0] if ord(c) in self.cmap else self.upm * .5 for c in text)
        return adv * size / self.upm + ls * len(text)

    def wrap(self, text: str, size: float, max_w: float) -> list[str]:
        lines, cur = [], ""
        for word in text.split():
            nxt = f"{cur} {word}".strip()
            if cur and self.width(nxt, size) > max_w:
                lines.append(cur)
                cur = word
            else:
                cur = nxt
        return lines + ([cur] if cur else [])


SERIF = Font("se", "DMSerifDisplay-Regular.ttf")
ITALIC = Font("si", "DMSerifDisplay-Italic.ttf")
SANS = Font("sa", "IBMPlexSans-Regular.ttf")
SANS_M = Font("sm", "IBMPlexSans-Medium.ttf")
MONO = Font("mo", "IBMPlexMono-Regular.ttf")
MONO_M = Font("mm", "IBMPlexMono-Medium.ttf")
PIXEL = Font("px", "PressStart2P-Regular.ttf")  # só nos detalhes 8-bit da carta final
FONTS = [SERIF, ITALIC, SANS, SANS_M, MONO, MONO_M, PIXEL]
_SUBSETS: dict[tuple, str] = {}


def woff_b64(font: Font, chars: set[str]) -> str:
    """Recorta a fonte com pyftsubset só com os glifos usados e devolve WOFF em base64."""
    text = "".join(sorted(chars | {" "}))
    key = (font.key, text)
    if key not in _SUBSETS:
        with tempfile.TemporaryDirectory() as tmp:
            txt, out = Path(tmp, "chars.txt"), Path(tmp, "sub.woff")
            txt.write_text(text, encoding="utf-8")
            # python -m fontTools.subset == pyftsubset (funciona mesmo sem Scripts/ no PATH)
            subprocess.run([sys.executable, "-m", "fontTools.subset", str(font.path),
                            f"--text-file={txt}", "--flavor=woff", "--no-hinting",
                            "--desubroutinize", "--layout-features=", f"--output-file={out}"],
                           check=True, capture_output=True)
            _SUBSETS[key] = base64.b64encode(out.read_bytes()).decode()
    return _SUBSETS[key]


# ── Animação ────────────────────────────────────────────────────────────────
# O estado "natural" de todo elemento é o quadro final: sob reduced-motion as
# animações CSS são desligadas e os grupos SMIL trocados pela versão parada.
EASE = "cubic-bezier(.2,.7,.2,1)"
ANIM_CSS = f"""
.a{{animation-fill-mode:both;animation-duration:.8s;animation-timing-function:{EASE}}}
.rise{{animation-name:rise}}.fade{{animation-name:fade;animation-duration:.9s;animation-timing-function:ease-out}}
.slide{{animation-name:slide}}
.pop{{animation-name:pop;animation-duration:.45s;animation-timing-function:ease-out;transform-box:fill-box;transform-origin:center}}
.grow{{animation-name:grow;transform-box:fill-box;transform-origin:50% 100%}}
.growx{{animation-name:growx;transform-box:fill-box;transform-origin:0 50%;animation-duration:1.1s}}
.tilein{{animation-name:tilein;animation-duration:1.15s;animation-timing-function:ease-out;transform-box:fill-box;transform-origin:50% 100%}}
.live{{animation:live 1.6s ease-in-out infinite}}
.ring{{animation:ring 2.6s ease-out infinite;transform-box:fill-box;transform-origin:center}}
.sheen{{animation:sheen 6s ease-in-out infinite}}
.nudge{{animation:nudge 1.8s ease-in-out infinite;transform-box:fill-box}}
.nudgeup{{animation:nudgeup 1.8s ease-in-out infinite;transform-box:fill-box}}
.crt{{animation:crt 4.5s linear infinite}}
@keyframes crt{{0%{{transform:translateY(-60px)}}45%,100%{{transform:translateY(400px)}}}}
@keyframes rise{{from{{opacity:0;transform:translateY(16px)}}to{{opacity:1;transform:none}}}}
@keyframes fade{{from{{opacity:0}}to{{opacity:1}}}}
@keyframes slide{{from{{opacity:0;transform:translateX(-24px)}}to{{opacity:1;transform:none}}}}
@keyframes pop{{0%{{opacity:0;transform:scale(.3)}}70%{{opacity:1;transform:scale(1.18)}}100%{{opacity:1;transform:none}}}}
@keyframes grow{{from{{transform:scaleY(0)}}to{{transform:none}}}}
@keyframes growx{{from{{transform:scaleX(0)}}to{{transform:none}}}}
@keyframes tilein{{0%{{opacity:0;transform:translateY(80px) scale(.65) rotate(-8deg)}}55%{{opacity:1;transform:translateY(-9px) scale(1.04) rotate(1.8deg)}}78%{{transform:translateY(3px) scale(.985) rotate(-.6deg)}}100%{{opacity:1;transform:none}}}}
@keyframes live{{0%,100%{{opacity:1}}50%{{opacity:.25}}}}
@keyframes ring{{0%{{opacity:.55;transform:scale(.35)}}70%,100%{{opacity:0;transform:scale(2.3)}}}}
@keyframes sheen{{0%{{transform:translateX(-140px) skewX(-20deg)}}28%,100%{{transform:translateX(420px) skewX(-20deg)}}}}
@keyframes nudge{{0%,100%{{transform:none}}50%{{transform:translateX(3px)}}}}
@keyframes nudgeup{{0%,100%{{transform:none}}50%{{transform:translate(2px,-2px)}}}}
.still{{display:none}}
@media (prefers-reduced-motion:reduce){{.a,.live,.ring,.sheen,.nudge,.nudgeup,.crt{{animation:none!important}}.smil{{display:none}}.still{{display:inline}}}}
"""


def delays(n_repos: int) -> dict[str, float]:
    """Atraso-base de cada carta: a página "toca" de cima para baixo."""
    d = {"hero": 0.0, "grafico": 0.9, "contribuicoes": 1.5,
         "tile-1": 2.2, "tile-2": 2.35, "tile-3": 2.5, "titulo": 2.9}
    for i in range(n_repos):
        d[f"repo-{i}"] = 3.1 + 0.15 * i
    d["personagem"] = 3.1 + 0.15 * n_repos + 0.3
    return d


class Card:
    def __init__(self, slug: str, w: float, h: float, label: str, delay: float):
        self.slug, self.w, self.h, self.label, self.delay = slug, w, h, label, delay
        self.parts: list[str] = []
        self.chars: dict[str, set[str]] = defaultdict(set)

    def add(self, *markup: str) -> None:
        self.parts.extend(markup)

    def at(self, t: float) -> str:  # instante absoluto para begin= do SMIL
        return f"{self.delay + t:.3f}s"

    def anim(self, kind: str, t: float = 0.0) -> str:
        return "" if STATIC else f' class="a {kind}" style="animation-delay:{self.delay + t:.3f}s"'

    def loop(self, kind: str, t: float = 0.0) -> str:  # animações infinitas
        return "" if STATIC else f' class="{kind}" style="animation-delay:{self.delay + t:.3f}s"'

    def g(self, kind: str, t: float, inner: str) -> str:
        return f"<g{self.anim(kind, t)}>{inner}</g>"

    def smil(self, animated: str, still: str) -> str:
        """SMIL não obedece CSS: some sob reduced-motion e dá lugar à versão parada."""
        return still if STATIC else f'<g class="smil">{animated}</g><g class="still">{still}</g>'

    def text(self, x, y, s, font: Font, size, fill, anchor="start", ls=0.0, extra="") -> str:
        self.chars[font.key] |= set(s)
        a = "" if anchor == "start" else f' text-anchor="{anchor}"'
        sp = f' letter-spacing="{ls}"' if ls else ""
        return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{font.key}" font-size="{size}" '
                f'fill="{fill}"{a}{sp}{extra}>{escape(s)}</text>')

    def runs(self, x, y, parts: list[tuple], anchor="start", extra="") -> str:
        """Um <text> com trechos em fontes/cores diferentes: [(texto, fonte, tamanho, cor)]."""
        spans = []
        for s, font, size, fill in parts:
            self.chars[font.key] |= set(s)
            spans.append(f'<tspan font-family="{font.key}" font-size="{size}" fill="{fill}">{escape(s)}</tspan>')
        a = "" if anchor == "start" else f' text-anchor="{anchor}"'
        return f'<text x="{x:.1f}" y="{y:.1f}"{a}{extra}>{"".join(spans)}</text>'

    def count(self, x, y, value: int, font: Font, size, fill, t: float, dur=1.1, frames=18) -> str:
        """Número que conta de 0 até value (CSS não muda texto, então: um <text> por quadro + <set>)."""
        fmt = lambda v: f"{v:,}".replace(",", ".")
        final = self.text(x, y, fmt(value), font, size, fill, "end")
        if STATIC or value <= 1:
            return final
        vals = sorted({round(value * (1 - (1 - i / frames) ** 3)) for i in range(1, frames + 1)})
        out = []
        for i, v in enumerate(vals):
            b = self.at(t + dur * i / len(vals))
            hide = "" if v == value else f'<set attributeName="opacity" to="0" begin="{self.at(t + dur * (i + 1) / len(vals))}"/>'
            out.append(self.text(x, y, fmt(v), font, size, fill, "end", extra=' opacity="0"').replace(
                "</text>", f'<set attributeName="opacity" to="1" begin="{b}"/>{hide}</text>'))
        return self.smil("".join(out), final)

    def svg(self) -> str:
        faces = "".join(
            f'@font-face{{font-family:{f.key};src:url(data:font/woff;base64,'
            f'{woff_b64(f, self.chars[f.key])}) format("woff")}}' for f in FONTS if self.chars[f.key])
        css = faces + "text{font-kerning:none}" + ("" if STATIC else ANIM_CSS)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w:.3f}" height="{self.h}" '
                f'viewBox="0 0 {self.w:.3f} {self.h}" role="img" aria-labelledby="t">'
                f'<title id="t">{escape(self.label)}</title><style>{css}</style>{"".join(self.parts)}</svg>')


def rect(x, y, w, h, fill, rx=0, extra="") -> str:
    r = f' rx="{rx}"' if rx else ""
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}"{r} fill="{fill}"{extra}/>'


def paper(w, h) -> str:
    return rect(.5, .5, w - 1, h - 1, PAPER, RADIUS, f' stroke="{LINE}"')


def star(cx, cy, r, fill) -> str:
    import math
    pts = []
    for k in range(10):
        rr = r if k % 2 == 0 else r * .45
        a = -math.pi / 2 + k * math.pi / 5
        pts.append(f"{cx + rr * math.cos(a):.2f},{cy + rr * math.sin(a):.2f}")
    return f'<polygon points="{" ".join(pts)}" fill="{fill}"/>'


def mix(a: str, b: str, t: float) -> str:
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(ca, cb))


def d_short(d: date) -> str:
    return f"{d.day} {MESES[d.month - 1]}"


def row_slot(i: int, n: int) -> tuple[float, float, float]:
    """Largura do SVG, deslocamento e largura do corpo para a i-ésima de n cartas numa linha."""
    slot = W / n
    body = (W - GAP * (n - 1)) / n
    return slot, i * (body + GAP) - i * slot, body


# ── Retrato em meio-tom ─────────────────────────────────────────────────────
def load_image(src: str, login: str) -> bytes | None:
    if not src:
        return None
    if src == "github":
        src = f"https://github.com/{login}.png?size=460"
    if src.startswith(("http://", "https://")):
        req = urllib.request.Request(src, headers={"User-Agent": "profile-cards-script"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    return (ROOT / src).read_bytes()


# Pixel art em duas paletas: você em tons quentes (coral → amarelo), as telas
# ao fundo em tons frios (índigo → ciano). Cada paleta tem os próprios limiares
# (quantis), para o rosto não virar um bloco só.
WARM = ["#1B1B36", "#3B2456", "#9E3F6E", COLORS["coral"], "#FFA06B", COLORS["sun"]]
COOL = [None, "#1D1D52", "#2E2E8C", INDIGO, "#6E8CF0", COLORS["sky"]]
SCREEN = "#0B0B1A"


def pixel_portrait(raw: bytes, focus=(.5, .5, 1.0), n: int = 48) -> list[dict[str, list[int]]]:
    """Foto → n×n pixels. Devolve, por linha, {cor: [colunas]} (None = fundo da tela)."""
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    w, h = im.size
    s = int(min(w, h) * focus[2])
    x0, y0 = max(0, min(w - s, int(focus[0] * w - s / 2))), max(0, min(h - s, int(focus[1] * h - s / 2)))
    small = im.crop((x0, y0, x0 + s, y0 + s)).resize((n, n), Image.LANCZOS)
    lum, rgb = ImageOps.autocontrast(small.convert("L"), cutoff=1).load(), small.load()
    cool = [[(lambda r, g, b: b - (r + g) / 2 > 18 and b > 45)(*rgb[i, j]) for i in range(n)] for j in range(n)]

    def thresholds(flag: bool, qs: list[float]) -> list[int]:
        v = sorted(lum[i, j] for j in range(n) for i in range(n) if cool[j][i] == flag) or [0, 255]
        return [v[int(q * (len(v) - 1))] for q in qs]

    tw = thresholds(False, [.32, .5, .64, .77, .89])
    tc = thresholds(True, [.3, .55, .75, .88, .96])
    rows = []
    for j in range(n):
        row: dict[str, list[int]] = defaultdict(list)
        for i in range(n):
            pal, th = (COOL, tc) if cool[j][i] else (WARM, tw)
            col = pal[sum(lum[i, j] > t for t in th)]
            if col:
                row[col].append(i)
        rows.append(row)
    return rows


# ── Janela de código com digitação ─────────────────────────────────────────
CODE_BG, CODE_BAR, CODE_FG, CODE_DIM, CODE_PUNCT = "#16162E", "#0F0F24", "#E6E3DA", "#6E6F86", "#A9A8BE"
TOKEN = re.compile(r'(#.*$)|("[^"]*")|\b(class|def|return|self|import|from|for|in|if|else|True|False|None)\b'
                   r'|([A-Za-z_]\w*)(?=\s*=[^=])|([A-Za-z_]\w*)(?=\()|([\[\](){},:=.])')


def highlight(line: str) -> list[tuple[str, str]]:
    colors = {1: CODE_DIM, 2: COLORS["mint"], 3: GLOW, 4: COLORS["sky"], 5: COLORS["sun"], 6: CODE_PUNCT}
    out, pos = [], 0
    for m in TOKEN.finditer(line):
        if m.start() > pos:
            out.append((line[pos:m.start()], CODE_FG))
        out.append((m.group(0), colors[m.lastindex]))
        pos = m.end()
    if pos < len(line):
        out.append((line[pos:], CODE_FG))
    return out


def code_window(c: Card, lines: list[str], x: float, y: float, w: float, h: float, t0: float) -> str:
    """Editor escuro que 'digita' o código linha a linha (SMIL: o recorte cresce um caractere por vez)."""
    size, lh = 11.5, 22
    cw = MONO.width("M", size)
    g = [rect(x, y, w, h, CODE_BG, RADIUS), rect(x, y, w, 30, CODE_BAR, RADIUS), rect(x, y + 18, w, 12, CODE_BAR)]
    g += [f'<circle cx="{x + 18 + 15 * k}" cy="{y + 15}" r="4.5" fill="{col}"/>'
          for k, col in enumerate((COLORS["coral"], COLORS["sun"], COLORS["mint"]))]
    g.append(c.text(x + w / 2, y + 19, "vittor.py", MONO, 10.5, CODE_DIM, "middle"))
    lx, ly = x + 40, y + 58
    t, last_end = t0, (lx, ly)
    for k, line in enumerate(lines):
        yy = ly + lh * k
        g.append(c.text(x + 26, yy, str(k + 1), MONO, 10, "#4A4B63", "end"))
        body = line.lstrip(" ")
        if not body:
            t += .12
            continue
        bx = lx + cw * (len(line) - len(body))
        txt = c.runs(bx, yy, [(s, MONO, size, col) for s, col in highlight(body)])
        n = len(body)
        dur = max(.1, n * .024)
        steps = ";".join(f"{cw * i:.1f}" for i in range(n + 1))
        typed = (f'<clipPath id="ty{k}"><rect x="{bx - 1:.1f}" y="{yy - 13}" width="0" height="18">'
                 f'<animate attributeName="width" values="{steps}" calcMode="discrete" dur="{dur:.2f}s" '
                 f'begin="{c.at(t)}" fill="freeze"/></rect></clipPath><g clip-path="url(#ty{k})">{txt}</g>')
        g.append(c.smil(typed, txt))
        t += dur + .1
        last_end = (bx + cw * n, yy)
    cur = rect(last_end[0] + 3, last_end[1] - 11, 7, 14, COLORS["sun"])
    blink = (f'<set attributeName="opacity" to="1" begin="{c.at(t)}"/>'
             f'<animate attributeName="opacity" values="1;0" keyTimes="0;.5" calcMode="discrete" dur="1s" '
             f'begin="{c.at(t)}" repeatCount="indefinite"/>')
    g.append(c.smil(cur.replace("/>", f' opacity="0">{blink}</rect>'), cur))
    # barra de status
    sy = y + h - 14
    g.append(rect(x, y + h - 30, w, 1, "#24243F"))
    g.append(f'<circle cx="{x + 18}" cy="{sy - 3.5}" r="3" fill="{COLORS["mint"]}"/>')
    g.append(c.text(x + 28, sy, "python 3.12", MONO, 9.5, CODE_DIM))
    g.append(c.text(x + w - 16, sy, f"UTF-8 · ln {len(lines)}", MONO, 9.5, CODE_DIM, "end"))
    return "".join(g)


# ── Cartas ──────────────────────────────────────────────────────────────────
def card_hero(p: dict, delay: float) -> Card:
    H = 380
    c = Card("hero", W, H + GAP, f"{p['name']}. {p['tagline']}", delay)
    c.add(paper(W, H))

    # à direita: o editor que digita vittor.py
    if p.get("code"):
        c.add(c.g("rise", .35, code_window(c, p["code"], 500, 34, 348, 312, 1.0)))

    x = 40
    c.add(c.g("fade", .05, rect(x, 44, 8, 8, INDIGO, 1.5) + c.text(x + 18, 52, p["kicker"], MONO_M, 10.5, INK2, ls=1.4)))
    first, last = p["name"].rsplit(" ", 1) if " " in p["name"] else (p["name"], "")
    c.add(c.g("rise", .15, c.text(x - 3, 150, first, SERIF, 94, INK)))
    if last:
        plain = c.text(x - 3, 236, last, ITALIC, 94, INK)
        # brilho índigo que atravessa o sobrenome de tempos em tempos (gradiente animado)
        shine = (f'<defs><linearGradient id="sh" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="170" y2="0">'
                 f'<stop offset="0" stop-color="{INK}"/><stop offset=".5" stop-color="{GLOW}"/>'
                 f'<stop offset="1" stop-color="{INK}"/>'
                 f'<animateTransform attributeName="gradientTransform" type="translate" values="-240 0;560 0;560 0" '
                 f'keyTimes="0;.3;1" dur="5s" begin="{c.at(1.2)}" repeatCount="indefinite"/></linearGradient></defs>'
                 + plain.replace(f'fill="{INK}"', 'fill="url(#sh)"'))
        c.add(c.g("rise", .3, c.smil(shine, plain)))

    for j, line in enumerate(SANS.wrap(p["tagline"], 15.5, 450)[:2]):
        c.add(c.g("rise", .5 + .08 * j, c.text(x, 284 + 23 * j, line, SANS, 15.5, INK2)))

    yb = 344
    dot = f'<circle cx="{x + 4}" cy="{yb - 4}" r="4" fill="{COLORS["mint"]}"/>'
    ring = (f'<circle cx="{x + 4}" cy="{yb - 4}" r="4" fill="none" stroke="{COLORS["mint"]}" stroke-width="1.5" '
            f'opacity="0"{c.loop("ring", 1.0)}/>')
    now = p.get("now", "")
    link = f"github.com/{p['login']}"
    c.add(c.g("fade", .75, f'<g{c.loop("live", 1.0)}>{dot}</g>' + ring
              + c.text(x + 16, yb, now, MONO, 11, INK)
              + c.text(x + 16 + MONO.width(now + "   ", 11), yb, link + " ↗", MONO, 11, INK3)))
    return c


def contribution_stats(days: list[dict]) -> dict:
    by = {date.fromisoformat(d["date"]): d["count"] for d in days}
    seq = sorted(by)
    last = seq[-1]
    d = last if by[last] else last - timedelta(days=1)  # hoje ainda sem contribuição não quebra a sequência
    cur = 0
    while by.get(d, 0) > 0:
        cur, d = cur + 1, d - timedelta(days=1)
    best, run = 0, 0
    for d in seq:
        run = run + 1 if by[d] else 0
        best = max(best, run)
    months, (y, m) = [], (last.year, last.month)
    for _ in range(12):
        months.append((y, m, sum(v for k, v in by.items() if (k.year, k.month) == (y, m))))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    busiest = sorted((d for d in seq if by[d]), key=lambda d: (-by[d], -d.toordinal()))[:3]
    return {"by": by, "first": seq[0], "last": last, "current": cur, "longest": best,
            "active": sum(1 for v in by.values() if v), "n_days": len(seq), "total": sum(by.values()),
            "months": months[::-1], "busiest": [(d, by[d]) for d in busiest]}


def card_graph(s: dict, generated_at: str, delay: float) -> Card:
    H = 254
    c = Card("grafico", W, H + GAP, f"Mapa de contribuições: {s['total']} contribuições em {s['n_days']} dias, em índigo.", delay)
    c.add(paper(W, H))
    c.add(c.g("rise", 0, c.runs(32, 56, [("Todo dia, ", SERIF, 28, INK), ("em índigo", ITALIC, 28, INDIGO)])))

    row = lambda d: (d.weekday() + 1) % 7  # domingo = linha 0, como no GitHub
    start = s["first"] - timedelta(days=row(s["first"]))
    ncols = (s["last"] - start).days // 7 + 1
    keep = min(ncols, 53)
    start += timedelta(weeks=ncols - keep)
    x0, y0 = 62, 80
    pitch = (W - x0 - 32 + 3) / keep
    cell = pitch - 3
    mx = max(1, max(s["by"].values()))
    ramp = ["#E7E5EE"] + [mix("#E7E5EE", INDIGO, t) for t in (.3, .55, .8)] + [mix(INDIGO, INK, .35)]

    for k, lab in ((1, "seg"), (3, "qua"), (5, "sex")):
        c.add(c.text(32, y0 + pitch * k + cell - 1.5, lab, MONO, 9, INK3))
    seen = None
    for d, v in sorted(s["by"].items()):
        if d < start:
            continue
        col = (d - start).days // 7
        if row(d) == 0 and d.month != seen and col < keep - 2:
            seen = d.month
            c.add(c.text(x0 + pitch * col, y0 + pitch * 7 + 14, MESES[d.month - 1], MONO, 9, INK3))
        lvl = 0 if v == 0 else min(4, 1 + int(4 * (v - 1) / mx))
        c.add(c.g("pop", .25 + .016 * col + .01 * row(d),
                  rect(x0 + pitch * col, y0 + pitch * row(d), cell, cell, ramp[lvl], 2.2)))

    # legenda no canto superior direito
    ly = 51
    lx = W - 32 - MONO.width("mais", 9)
    legend = c.text(W - 32, ly, "mais", MONO, 9, INK3, "end")
    lx -= 6 + 5 * (cell + 3)
    legend += "".join(rect(lx + k * (cell + 3), ly - cell + 1.5, cell, cell, col, 2.2) for k, col in enumerate(ramp))
    legend += c.text(lx - 6, ly, "menos", MONO, 9, INK3, "end")
    c.add(c.g("fade", .3, legend))
    # rodapé: resumo + data da última atualização (feita pela Action)
    fy = H - 22
    gen = datetime.fromisoformat(generated_at).date() if generated_at else s["last"]
    c.add(rect(32, fy - 20, W - 64, 1, LINE))
    c.add(c.g("fade", 1.2, c.text(32, fy, f"{s['total']} CONTRIBUIÇÕES EM {s['n_days']} DIAS", MONO_M, 9.5, INK2, ls=1.2)
                         + c.text(W - 32, fy, f"ATUALIZADO DIARIAMENTE · {d_short(gen).upper()} {gen.year}",
                                  MONO, 9.5, INK3, "end", ls=1.2)))
    return c


def card_activity(s: dict, delay: float) -> Card:
    H = 320
    total12 = sum(v for _, _, v in s["months"])
    c = Card("contribuicoes", W, H + GAP,
             f"{total12} contribuições nos últimos 12 meses; sequência atual de {s['current']} dias, "
             f"{s['active']} de {s['n_days']} dias com contribuição.", delay)
    c.add(paper(W, H))
    c.add(c.g("fade", 0, c.text(32, 46, "ÚLTIMOS 12 MESES NO GITHUB", MONO_M, 9.5, INK3, ls=1.3)))
    num_w = SERIF.width(f"{total12:,}".replace(",", "."), 46)
    c.add(c.g("rise", .1, c.count(30 + num_w, 100, total12, SERIF, 46, INK, .2)
                         + c.text(30 + num_w + 12, 100, "contribuições", ITALIC, 46, INK)))

    # barras por mês: tinta; o melhor mês em índigo, o mês corrente (parcial) em cinza
    base, top, x0, pitch, bw = 268, 140, 32, 44, 30
    vals = [v for _, _, v in s["months"]]
    mx, best_i = max(1, max(vals)), vals.index(max(vals))
    for i, (yy, mm, v) in enumerate(s["months"]):
        x = x0 + pitch * i
        partial = i == 11 and i != best_i
        col = INDIGO if i == best_i and v else ("#C9C4B8" if partial else INK)
        h = (base - top) * v / mx
        bar = rect(x, base - h, bw, h, col, 2) if v else rect(x, base - 2, bw, 2, RULE)
        c.add(c.g("grow", .35 + .06 * i, bar))
        if i == best_i and v:
            c.add(c.g("pop", 1.15, c.text(x + bw / 2, base - h - 7, str(v), MONO_M, 10, INDIGO, "middle")))
        c.add(c.text(x + bw / 2, base + 18, MESES[mm - 1], MONO, 9.5, INK2 if i == 11 else INK3, "middle"))

    # coluna de números, separada por fios
    sx = 610
    c.add(rect(sx - 36, 74, 1, 214, LINE))

    def stat(y, value, suffix, caption, t, extra_line=None):
        vw = SERIF.width(str(value), 32)
        g = (c.count(sx + vw, y, value, SERIF, 32, INK, t + .1, dur=.8)
             + c.runs(sx + vw + 6, y, suffix) + c.text(sx, y + 20, caption, SANS, 11.5, INK3))
        if extra_line:
            g += c.text(sx, y + 37, extra_line, MONO, 9.5, INK3, ls=.6)
        return c.g("rise", t, g)

    dias = lambda n: "dia" if n == 1 else "dias"
    c.add(stat(104, s["current"], [(dias(s["current"]), ITALIC, 32, INK)],
               f"sequência atual · recorde de {s['longest']} {dias(s['longest'])}", .5))
    c.add(rect(sx, 134, 238, 1, LINE))
    c.add(stat(176, s["active"], [("/ " + str(s["n_days"]), SERIF, 32, INK3)], "dias com pelo menos uma contribuição", .65))
    c.add(rect(sx, 206, 238, 1, LINE))
    if s["busiest"]:
        (d0, v0), rest = s["busiest"][0], s["busiest"][1:]
        others = "  ·  ".join(f"{d_short(d).upper()} ({v})" for d, v in rest)
        c.add(stat(248, v0, [("contribuições", ITALIC, 32, INK)] if v0 != 1 else [("contribuição", ITALIC, 32, INK)],
                   f"no dia mais movimentado, {d_short(d0)} {d0.year}", .8,
                   ("DEPOIS: " + others) if others else None))
    return c


def card_tile(i: int, n: int, t: dict, value: int | None, delay: float) -> Card:
    H = 208
    slot, off, bw = row_slot(i, n)
    acc = COLORS[t["color"]]
    head = f"{value} {t['unit']}" if value is not None else t["unit"]
    c = Card(f"tile-{i + 1}", slot, H + GAP, f"{t['label']}: {head}. {t['text']}", delay)
    cid = f"clip{i}"
    body = [f'<defs><clipPath id="{cid}">{rect(off, 0, bw, H, "#000", RADIUS)}</clipPath></defs>',
            rect(off, 0, bw, H, acc, RADIUS)]
    if not STATIC:  # brilho que cruza a peça periodicamente (fora da carta no estado natural)
        body.append(f'<g clip-path="url(#{cid})"><rect x="{off}" y="-20" width="46" height="{H + 40}" fill="#fff" '
                    f'opacity=".28" transform="translate(-300 0)"{c.loop("sheen", 1.6 + .7 * i)}/></g>')
    body.append(c.text(off + 20, 34, t["label"], MONO_M, 10, INK, ls=1.3))
    ax, ay = off + bw - 22, 34
    body.append(f'<circle cx="{ax - 5}" cy="{ay - 4}" r="9" fill="none" stroke="{INK}" stroke-width="1.2" opacity="0"'
                f'{c.loop("ring", 1.3 + .3 * i)}/>')
    body.append(f'<g{c.loop("nudge", 1.2)}>{c.text(ax, ay, "→", MONO_M, 13, INK, "end")}</g>')
    if value is not None:
        vw = ITALIC.width(str(value), 40)
        body.append(c.count(off + 18 + vw, 104, value, ITALIC, 40, INK, .5, dur=.7, frames=max(2, value))
                    + c.text(off + 18 + vw + 10, 104, t["unit"], ITALIC, 40, INK))
    else:
        body.append(c.text(off + 18, 104, t["unit"], ITALIC, 40, INK))
    for j, line in enumerate(SANS_M.wrap(t["text"], 12, bw - 40)[:4]):
        body.append(c.text(off + 20, 136 + 17 * j, line, SANS_M, 12, INK, extra=' fill-opacity=".82"'))
    c.add(c.g("tilein", 0, "".join(body)))
    return c


def card_title(text: str, accent: str, dark: bool, delay: float) -> Card:
    H = 58
    c = Card("titulo-projetos-" + ("escuro" if dark else "claro"), W, H, f"{text} {accent}", delay)
    ink = "#F0EDE6" if dark else INK
    c.add(c.g("rise", 0, c.runs(4, 40, [(text + " ", SERIF, 28, ink), (accent, ITALIC, 28, GLOW if dark else INDIGO)])))
    return c


def card_repo(i: int, n_per_row: int, r: dict, meta: dict, delay: float) -> Card:
    H = 178
    slot, off, bw = row_slot(i % n_per_row, n_per_row)
    acc = COLORS.get(r.get("color"), INDIGO)
    desc = r.get("description") or meta.get("description") or ""
    c = Card(f"repo-{r['repo']}", slot, H + GAP, f"{r['repo']}: {r['title']}. {desc}", delay)
    g = [rect(off + .5, .5, bw - 1, H - 1, PAPER, RADIUS, f' stroke="{LINE}"'),
         rect(off + 20, 25, 9, 9, acc, 2),
         c.text(off + 37, 34, r["repo"], MONO_M, 12.5, INK)]
    ax = off + bw - 20
    g.append(f'<g{c.loop("nudgeup", 1.0)}>{c.text(ax, 34, "↗", MONO_M, 13, INK3, "end")}</g>')
    g.append(c.text(ax - 22, 33, r.get("phase", "").upper(), MONO, 9.5, INK3, "end", ls=1.1))
    g.append(c.text(off + 20, 70, r["title"], SERIF, 22, INK))
    for j, line in enumerate(SANS.wrap(desc, 12.5, bw - 40)[:3]):
        g.append(c.text(off + 20, 96 + 17.5 * j, line, SANS, 12.5, INK2))
    # rodapé: linguagem (ou primeira tag) · estrelas · última atualização
    x, y = off + 20, H - 20
    lang = meta.get("language")
    label = lang or (r.get("tags") or [""])[0]
    if lang:
        g.append(f'<circle cx="{x + 4}" cy="{y - 3.5}" r="4" fill="{LANG_COLORS.get(lang, INK3)}"/>')
        x += 14
    g.append(c.text(x, y, label, MONO, 10.5, INK2))
    x += MONO.width(label, 10.5) + 14
    if meta:
        g.append(star(x + 5, y - 4, 5.2, INK3))
        g.append(c.text(x + 14, y, str(meta.get("stargazers_count") or 0), MONO, 10.5, INK2))
        x += 14 + MONO.width(str(meta.get("stargazers_count") or 0), 10.5) + 14
    if meta.get("pushed_at"):
        d = datetime.fromisoformat(meta["pushed_at"].replace("Z", "+00:00")).date()
        g.append(c.text(off + bw - 20, y, f"atualizado {MESES[d.month - 1]} {d.year}", MONO, 10.5, INK3, "end"))
    c.add(c.g("rise", 0, "".join(g)))
    return c


def card_player(p: dict, raw: bytes | None, score: int, delay: float) -> Card:
    """Carta final: 'seleção de personagem' com o retrato em pixel art numa tela CRT."""
    H = 380
    pl = p.get("player") or {}
    c = Card("personagem", W, H + GAP,
             f"Seleção de personagem: {p['name']}, {pl.get('class', '')}. " + " ".join(pl.get("title", [])) + ".", delay)
    c.add(paper(W, H))

    # tela
    sx, sy, ss = 28, 28, 324
    c.add(f'<defs><clipPath id="scr">{rect(sx, sy, ss, ss, "#000", RADIUS)}</clipPath>'
          f'<pattern id="scan" width="4" height="3" patternUnits="userSpaceOnUse">'
          f'<rect width="4" height="1" fill="#000" opacity=".16"/></pattern></defs>')
    c.add(rect(sx, sy, ss, ss, SCREEN, RADIUS))
    px0, py0, psz = sx + 24, sy + 26, 276
    if raw:
        rows = pixel_portrait(raw, tuple(p.get("portrait_focus") or (.5, .5, 1.0)))
        cell = psz / len(rows)
        for j, row in enumerate(rows):  # a imagem "carrega" de cima para baixo, como num console
            paths = "".join(
                f'<path fill="{col}" d="' + "".join(f"M{px0 + i * cell:.1f} {py0 + j * cell:.1f}h{cell - .7:.2f}v{cell - .7:.2f}h-{cell - .7:.2f}z" for i in cols) + '"/>'
                for col, cols in row.items())
            c.add(c.g("fade", .25 + .022 * j, paths))
    else:
        initials = "".join(w[0] for w in p["name"].split()[:2])
        c.add(c.text(sx + ss / 2, sy + ss / 2 + 24, initials, PIXEL, 64, COLORS["sun"], "middle"))
    c.add(f'<g clip-path="url(#scr)"><rect x="{sx}" y="{sy}" width="{ss}" height="{ss}" fill="url(#scan)"/>')
    if not STATIC:  # faixa de brilho que varre a tela (fica fora dela no estado natural)
        c.add(f'<rect x="{sx}" y="{sy - 60}" width="{ss}" height="46" fill="#fff" opacity=".07" '
              f'transform="translate(0 -400)"{c.loop("crt", 1.6)}/>')
    c.add("</g>")
    # HUD do jogo
    hud = (c.text(sx + 16, sy + 20, "PLAYER 1", PIXEL, 7, COLORS["sun"])
           + c.text(sx + ss - 16, sy + 20, "♥ ♥ ♥", PIXEL, 7, COLORS["coral"], "end")
           + c.text(sx + 16, sy + ss - 11, "LVL ADS", PIXEL, 7, COLORS["mint"])
           + c.text(sx + ss - 16, sy + ss - 11, f"SCORE {score:06d}", PIXEL, 7, COLORS["sky"], "end"))
    c.add(c.g("fade", .2, hud))

    # ficha à direita
    x0 = 390
    tri = c.text(x0, 58, "▶", PIXEL, 8, COLORS["coral"])
    c.add(c.g("fade", .3, tri + c.text(x0 + 16, 58, "SELEÇÃO DE PERSONAGEM", MONO_M, 9.5, INK3, ls=1.3)))
    title = pl.get("title") or ["Pronto para a", "próxima fase"]
    c.add(c.g("rise", .4, c.text(x0 - 2, 104, title[0], SERIF, 40, INK)))
    if len(title) > 1:
        c.add(c.g("rise", .5, c.text(x0 - 2, 148, title[1], ITALIC, 40, INDIGO)))
    info = []
    if pl.get("class"):
        info += [("CLASSE  ", MONO_M, 9.5, INK3), (pl["class"], MONO, 11, INK), ("     ", MONO, 11, INK)]
    if pl.get("base"):
        info += [("BASE  ", MONO_M, 9.5, INK3), (pl["base"], MONO, 11, INK)]
    c.add(c.g("fade", .6, c.runs(x0, 184, info, extra=' xml:space="preserve"') + rect(x0, 202, W - 28 - x0, 1, LINE)))

    # atributos em blocos de pixel (níveis definidos em profile.json → player.stats)
    seg, gap, nseg = 16, 3, 10
    for k, st in enumerate(pl.get("stats", [])[:4]):
        y = 234 + 31 * k
        col = COLORS.get(st.get("color"), INDIGO)
        lvl = max(0, min(nseg, int(st.get("level", 0))))
        g = c.text(x0, y, st["label"], SANS_M, 13, INK)
        bx = x0 + 64
        g += "".join(rect(bx + b * (seg + gap), y - 10, seg, 10, "#E6E1D6", 1.5) for b in range(nseg))
        g += "".join(c.g("pop", .95 + .14 * k + .045 * b, rect(bx + b * (seg + gap), y - 10, seg, 10, col, 1.5))
                     for b in range(lvl))
        g += c.text(bx + nseg * (seg + gap) + 10, y, st.get("detail", ""), SANS, 11, INK3)
        c.add(c.g("fade", .8 + .1 * k, g))

    # "continuar?" piscando, como no fim de fase dos fliperamas
    cont = c.text(x0, 358, "▶ CONTINUAR?", PIXEL, 9, COLORS["coral"])
    blink = ('<animate attributeName="opacity" values="1;0" keyTimes="0;.5" calcMode="discrete" dur="1.1s" '
             f'begin="{c.at(2.2)}" repeatCount="indefinite"/>')
    c.add(c.g("fade", 1.6, c.smil(cont.replace("</text>", blink + "</text>"), cont)
              + c.text(x0 + PIXEL.width("▶ CONTINUAR?", 9) + 16, 357, pl.get("mission", ""), MONO, 10.5, INK3)))
    return c


# ── README e preview ───────────────────────────────────────────────────────
def readme_block(p: dict, cards: dict[str, Card]) -> str:
    alt = lambda slug: escape(cards[slug].label, quote=True)
    img = lambda slug, w: f'<img src="cartas/{slug}.svg" width="{w}" alt="{alt(slug)}" />'
    tiles = "".join(f'<a href="{t.get("href") or "#"}">{img(f"tile-{i + 1}", "33.333%")}</a>'
                    for i, t in enumerate(p["tiles"][:3]))
    repos, row = [], []
    for k, r in enumerate(p["featured"]):
        row.append(f'<a href="https://github.com/{p["login"]}/{r["repo"]}">{img("repo-" + r["repo"], "50%")}</a>')
        if len(row) == 2 or k == len(p["featured"]) - 1:
            repos.append("".join(row))
            row = []
    lines = [
        "<!-- cartas:start — gerado por render_cards.py. Sem linhas em branco aqui dentro:",
        "     o espaçamento já está nos SVGs, e cartas da mesma linha ficam coladas. -->",
        '<div align="center">',
        f'<a href="https://github.com/{p["login"]}">{img("hero", "100%")}</a><br>',
        img("grafico", "100%") + "<br>",
        img("contribuicoes", "100%") + "<br>",
        tiles + "<br>",
        '<picture><source media="(prefers-color-scheme: dark)" srcset="cartas/titulo-projetos-escuro.svg" />'
        + img("titulo-projetos-claro", "100%") + "</picture><br>",
        "<br>\n".join(repos) + "<br>",
        img("personagem", "100%"),
        "</div>",
        "<!-- cartas:end -->",
    ]
    return "\n".join(lines)


def update_readme(block: str) -> None:
    path = ROOT / "README.md"
    if not path.exists():
        return
    txt = path.read_text(encoding="utf-8")
    new = re.sub(r"<!-- cartas:start.*?<!-- cartas:end -->", lambda _: block, txt, flags=re.S)
    if new != txt:
        path.write_text(new, encoding="utf-8")


def write_preview(block: str) -> None:
    body = re.sub(r"<!--.*?-->", "", block, flags=re.S).replace('cartas/', './')
    mode = "STATIC=1 · quadro final" if STATIC else "animado"
    (OUT / "_preview.html").write_text(f"""<!doctype html><meta charset="utf-8"><title>Preview das cartas</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{margin:0;background:#0d1117;color:#8b949e;font:13px system-ui}}
@media (prefers-color-scheme:light){{body{{background:#fff}}}}
main{{max-width:880px;margin:24px auto;padding:0 16px}}img{{vertical-align:top}}p{{text-align:center}}</style>
<main><p>Preview ({mode}) — mesma estrutura do README</p>{body}</main>""", encoding="utf-8")


def tile_value(t: dict, p: dict) -> int | None:
    v = t.get("value")
    return len(p["featured"]) if v == "featured" else v


def main() -> None:
    p = json.loads((ROOT / "data" / "profile.json").read_text(encoding="utf-8"))
    contrib = json.loads((ROOT / "data" / "contributions.json").read_text(encoding="utf-8"))
    repos_path = ROOT / "data" / "repos.json"
    repos = json.loads(repos_path.read_text(encoding="utf-8")) if repos_path.exists() else {}
    s = contribution_stats(contrib["days"])
    D = delays(len(p["featured"]))

    cards = [card_hero(p, D["hero"]), card_graph(s, contrib.get("generated_at", ""), D["grafico"]),
             card_activity(s, D["contribuicoes"])]
    tiles = p["tiles"][:3]
    cards += [card_tile(i, len(tiles), t, tile_value(t, p), D[f"tile-{i + 1}"]) for i, t in enumerate(tiles)]
    cards += [card_title("Projetos em", "destaque", dark, D["titulo"]) for dark in (False, True)]
    cards += [card_repo(i, 2, r, repos.get(r["repo"]) or {}, D[f"repo-{i}"]) for i, r in enumerate(p["featured"])]
    cards.append(card_player(p, load_image(p.get("portrait"), p["login"]), s["total"], D["personagem"]))

    OUT.mkdir(exist_ok=True)
    keep = {f"{c.slug}.svg" for c in cards}
    for old in OUT.glob("*.svg"):  # remove cartas que saíram do perfil
        if old.name not in keep:
            old.unlink()
    for c in cards:
        (OUT / f"{c.slug}.svg").write_text(c.svg(), encoding="utf-8")
    block = readme_block(p, {c.slug: c for c in cards})
    write_preview(block)
    if not STATIC:
        update_readme(block)
    size = sum((OUT / k).stat().st_size for k in keep)
    print(f"{len(cards)} cartas em {OUT.relative_to(ROOT)}/ ({size / 1024:.0f} KB)" + (" — STATIC" if STATIC else ""))


if __name__ == "__main__":
    main()
