"""Draws the four header illustrations (core/grabit/web/art-*.svg). Run: python tools/make_art.py"""
import math
import os

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'core', 'grabit', 'web')
L, INK, C1, C2, ST = '#c8f542', '#10140a', '#1b1c1a', '#222420', '#34372f'
FONT = 'font-family="system-ui,Arial,sans-serif"'


def n(v):
    return ('%.1f' % v).rstrip('0').rstrip('.')


def save(name, body):
    head = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 520 400" fill="none"><defs>'
            '<radialGradient id="g" cx="50%" cy="50%" r="50%"><stop offset="0" stop-color="' + L + '" stop-opacity=".34"/>'
            '<stop offset="1" stop-color="' + L + '" stop-opacity="0"/></radialGradient></defs>')
    with open(os.path.join(OUT, 'art-%s.svg' % name), 'w', encoding='utf-8') as f:
        f.write(head + body + '</svg>')


def mountain(x, y, w, h, fill):
    return '<path d="M{} {}l{} {}l{} {}l{} {}l{} {}z" fill="{}"/>'.format(
        n(x), n(y + h), n(w * .36), n(-h), n(w * .2), n(h * .42), n(w * .14), n(-h * .3), n(w * .3), n(h * .88), fill)


def pill(x, y, w, text, lime=False):
    return ('<rect x="{}" y="{}" width="{}" height="26" rx="13" fill="{}" stroke="{}"/><text x="{}" y="{}" text-anchor="middle" '
            '{} font-size="12" font-weight="600" fill="{}">{}</text>').format(
        x, y, w, '#1c2210' if lime else '#131412', '#6f8a1f' if lime else ST, n(x + w / 2), n(y + 17.5), FONT,
        L if lime else '#8f9388', text)


# library: a stack of what you saved - sound, video, picture
wave = ''.join('<rect x="{}" y="{}" width="5" height="{}" rx="2.5" fill="#8f9388"/>'.format(78 + i * 10, n(150 - h / 2), h)
               for i, h in enumerate([22, 40, 64, 34, 82, 52, 96, 60, 38, 70, 30]))
save('library',
     '<ellipse cx="290" cy="290" rx="210" ry="46" fill="url(#g)"/>'
     '<g transform="rotate(-12 130 150)"><rect x="40" y="70" width="190" height="160" rx="18" fill="' + C1 + '" stroke="' + ST + '" stroke-width="1.5"/>' + wave + '</g>'
     '<g transform="rotate(13 400 140)"><rect x="310" y="56" width="190" height="160" rx="18" fill="' + C2 + '" stroke="' + ST + '" stroke-width="1.5"/>'
     '<circle cx="452" cy="100" r="13" fill="#8f9388"/>' + mountain(340, 150, 130, 52, '#5a5e53') + '</g>'
     '<rect x="170" y="92" width="220" height="160" rx="20" fill="#161815" stroke="' + L + '" stroke-width="2.5"/>'
     '<circle cx="280" cy="160" r="33" fill="' + L + '"/><path d="M270 143v34l28-17z" fill="' + INK + '"/>'
     '<rect x="200" y="226" width="160" height="4" rx="2" fill="#3a3d34"/><rect x="200" y="226" width="96" height="4" rx="2" fill="' + L + '"/>'
     '<circle cx="444" cy="24" r="4.5" fill="' + L + '"/><circle cx="470" cy="24" r="4.5" fill="' + L + '" opacity=".5"/>'
     '<circle cx="496" cy="24" r="4.5" fill="' + L + '" opacity=".25"/>')

# images: a wall of pictures, one picked out by the scanner
tiles = ''
for r in range(3):
    for c in range(4):
        x, y = 30 + c * 128 + (r % 2) * 10, 14 + r * 132
        tiles += '<g opacity="{}"><rect x="{}" y="{}" width="112" height="118" rx="14" fill="{}" stroke="{}"/>{}</g>'.format(
            n(.75 - .2 * r), x, y, C1, ST, mountain(x + 18, y + 62, 78, 26, '#3c4036'))
save('images', tiles +
     '<rect x="0" y="176" width="520" height="38" fill="' + L + '" opacity=".1"/><path d="M0 196h520" stroke="' + L + '" stroke-width="1.5" opacity=".8"/>'
     '<g transform="rotate(-4 285 200)"><rect x="196" y="104" width="178" height="200" rx="18" fill="#161815" stroke="' + L + '" stroke-width="2.5"/>'
     '<rect x="212" y="120" width="72" height="24" rx="12" fill="#0b0b0d"/><text x="248" y="137" text-anchor="middle" ' + FONT +
     ' font-size="12" font-weight="700" fill="' + L + '">PNG · 2K</text><circle cx="328" cy="162" r="18" fill="' + L + '"/>'
     + mountain(222, 206, 140, 74, '#59682a') +
     '<path d="M180 124v-36h30M390 124v-36h-30M180 284v36h30M390 284v36h-30" stroke="' + L + '" stroke-width="2.5" stroke-linecap="round"/>'
     '<circle cx="366" cy="92" r="16" fill="' + L + '"/><path d="m358 92 6 6 10-12" stroke="' + INK + '" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"/></g>')

# video: a film strip pulled through a play button and down into your device
frames = ''
for i in range(11):
    t = i / 10
    x, y = 20 + t * 500, 300 - 190 * math.sin(math.pi * t * .92 + .12)
    op = max(.2, 1 - abs(t - .5) * 1.5)
    frames += ('<g transform="translate({} {}) rotate({})" opacity="{}"><rect x="-21" y="-25" width="42" height="50" rx="5" fill="#141513" stroke="{}"/>'
               '<rect x="-13" y="-15" width="26" height="30" rx="3" fill="#3b3e36"/><circle cx="-16.5" cy="-20" r="1.8" fill="#6b6f62"/>'
               '<circle cx="16.5" cy="-20" r="1.8" fill="#6b6f62"/><circle cx="-16.5" cy="20" r="1.8" fill="#6b6f62"/>'
               '<circle cx="16.5" cy="20" r="1.8" fill="#6b6f62"/></g>').format(n(x), n(y), n(-38 + t * 70), n(op), ST)
save('video',
     '<circle cx="290" cy="170" r="190" fill="url(#g)" opacity=".7"/><circle cx="290" cy="170" r="188" stroke="' + ST + '" opacity=".7"/>'
     '<circle cx="290" cy="170" r="138" stroke="#4a5a1c" stroke-dasharray="3 9"/>' + frames +
     '<circle cx="290" cy="170" r="94" fill="#0f100e" stroke="#6f8a1f" stroke-width="1.5"/><circle cx="290" cy="170" r="110" fill="url(#g)"/>'
     '<circle cx="290" cy="170" r="62" fill="' + L + '"/><path d="M274 142v56l46-28z" fill="' + INK + '"/>'
     '<path d="M290 250v96m-26-28 26 28 26-28" stroke="#9dbf36" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>'
     '<rect x="244" y="368" width="92" height="7" rx="3.5" fill="#7c962b"/>'
     + pill(92, 60, 60, 'MP4') + pill(430, 38, 84, '1080p') + pill(448, 264, 68, '4:12', True))

# settings: switches, sliders and a tuning dial
ticks = ''
for i in range(61):
    a = math.radians(210 - i * 4)
    major, on = i % 5 == 0, i <= 38
    r1, r2 = 150, 150 + (20 if major else 11)
    ticks += '<path d="M{} {}L{} {}" stroke="{}" stroke-width="{}" stroke-linecap="round" opacity="{}"/>'.format(
        n(330 + r1 * math.cos(a)), n(205 - r1 * math.sin(a)), n(330 + r2 * math.cos(a)), n(205 - r2 * math.sin(a)),
        L if on else '#55594d', 2.5 if major else 1.6, 1 if on else .7)


def toggle(y, on):
    return '<rect x="70" y="{}" width="62" height="32" rx="16" fill="{}"/><circle cx="{}" cy="{}" r="11" fill="{}"/>'.format(
        y, L if on else '#2a2c27', 116 if on else 86, y + 16, INK if on else '#8f9388')


save('settings',
     '<circle cx="330" cy="205" r="215" fill="url(#g)" opacity=".45"/>' + ticks +
     '<circle cx="330" cy="205" r="138" fill="#1d1f1b" stroke="' + ST + '"/><circle cx="330" cy="205" r="112" fill="#161714" stroke="#2c2f28" stroke-width="18"/>'
     '<circle cx="330" cy="205" r="78" stroke="#33362e"/><path d="M349 182 400 122" stroke="' + L + '" stroke-width="6" stroke-linecap="round"/>'
     '<circle cx="330" cy="205" r="10" fill="' + L + '"/>' + toggle(84, True) + toggle(142, False) + toggle(200, True) +
     '<rect x="70" y="298" width="150" height="5" rx="2.5" fill="#2a2c27"/><rect x="70" y="298" width="98" height="5" rx="2.5" fill="' + L + '"/>'
     '<circle cx="168" cy="300.5" r="11" fill="#f3f2ec" stroke="' + L + '" stroke-width="3"/>'
     '<rect x="70" y="348" width="150" height="5" rx="2.5" fill="#2a2c27"/><rect x="70" y="348" width="46" height="5" rx="2.5" fill="#7c962b"/>'
     '<circle cx="116" cy="350.5" r="10" fill="#8f9388"/>')
