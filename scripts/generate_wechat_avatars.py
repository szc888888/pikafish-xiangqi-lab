from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

OUT = Path('D:/chess/exports/wechat-avatars')
OUT.mkdir(parents=True, exist_ok=True)
S = 4
W = H = 144

def font(size):
    for path in ('C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/simhei.ttf'):
        if Path(path).exists():
            return ImageFont.truetype(path, size * S)
    return ImageFont.load_default()

def fit_text(draw, text, center, fnt, fill, stroke=0, stroke_fill=None):
    box = draw.textbbox((0, 0), text, font=fnt, stroke_width=stroke * S)
    x = center[0] * S - (box[2] - box[0]) / 2
    y = center[1] * S - (box[3] - box[1]) / 2 - box[1]
    draw.text((x, y), text, font=fnt, fill=fill, stroke_width=stroke * S, stroke_fill=stroke_fill)

def avatar_one():
    im = Image.new('RGB', (W * S, H * S), '#081526')
    d = ImageDraw.Draw(im)
    # Deep blue tech halo.
    d.ellipse((9*S, 9*S, 135*S, 135*S), fill='#0d2942', outline='#36c9d8', width=2*S)
    d.ellipse((18*S, 18*S, 126*S, 126*S), outline='#1d6f8b', width=S)
    # Abstract board, kept quiet so the mark reads at small size.
    left, top, cell = 29*S, 30*S, 10*S
    for i in range(6):
        d.line((left, top + i*cell, left + 5*cell, top + i*cell), fill='#337d91', width=S)
        d.line((left + i*cell, top, left + i*cell, top + 5*cell), fill='#337d91', width=S)
    # Central AI-style crown/king mark.
    d.rounded_rectangle((55*S, 49*S, 89*S, 96*S), radius=9*S, fill='#f5c45e', outline='#fff1b4', width=2*S)
    d.polygon([(59*S, 52*S), (63*S, 42*S), (72*S, 50*S), (80*S, 42*S), (85*S, 52*S)], fill='#f5c45e', outline='#fff1b4')
    d.ellipse((61*S, 60*S, 83*S, 82*S), fill='#0c2940')
    fit_text(d, 'AI', (72, 72), font(16), '#f5c45e')
    d.line((60*S, 88*S, 84*S, 88*S), fill='#0c2940', width=2*S)
    # Small circuit accents.
    for x, y in ((31, 105), (111, 40), (105, 111)):
        d.ellipse(((x-2)*S, (y-2)*S, (x+2)*S, (y+2)*S), fill='#63e2e5')
    return im.resize((W, H), Image.Resampling.LANCZOS)

def avatar_two():
    im = Image.new('RGB', (W * S, H * S), '#f4e8d1')
    d = ImageDraw.Draw(im)
    # Seal-like red field with a warm paper edge.
    d.rounded_rectangle((7*S, 7*S, 137*S, 137*S), radius=28*S, fill='#9e2928', outline='#6d171b', width=2*S)
    d.rounded_rectangle((15*S, 15*S, 129*S, 129*S), radius=23*S, outline='#d99650', width=S)
    # Simplified xiangqi board motif.
    for x in (33, 47, 97, 111):
        d.line((x*S, 31*S, x*S, 113*S), fill='#c95e40', width=S)
    for y in (39, 53, 91, 105):
        d.line((31*S, y*S, 113*S, y*S), fill='#c95e40', width=S)
    d.line((72*S, 31*S, 72*S, 53*S), fill='#d99650', width=S)
    d.line((72*S, 91*S, 72*S, 113*S), fill='#d99650', width=S)
    # Gold round piece and character.
    d.ellipse((39*S, 38*S, 105*S, 104*S), fill='#e7b65c', outline='#fff0b0', width=2*S)
    d.ellipse((45*S, 44*S, 99*S, 98*S), outline='#9e2928', width=2*S)
    fit_text(d, '帅', (72, 71), font(38), '#9e2928')
    # Tiny decorative dots for balance.
    for x, y in ((24, 72), (120, 72), (72, 24), (72, 120)):
        d.ellipse(((x-2)*S, (y-2)*S, (x+2)*S, (y+2)*S), fill='#f7d987')
    return im.resize((W, H), Image.Resampling.LANCZOS)

avatar_one().save(OUT / 'wechat-avatar-tech-ai.png', format='PNG', optimize=True)
avatar_two().save(OUT / 'wechat-avatar-xiangqi-red.png', format='PNG', optimize=True)
print(OUT / 'wechat-avatar-tech-ai.png')
print(OUT / 'wechat-avatar-xiangqi-red.png')
