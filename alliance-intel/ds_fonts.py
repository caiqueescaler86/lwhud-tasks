"""Resolve installed multilingual fonts. No network requests at render time."""
from functools import lru_cache
from pathlib import Path
import threading

SAMPLE_CJK = '\u6c99\u6f20\u98ce\u66b4\u8054\u76df'
SAMPLE_LATIN = 'Aa\u00c7\u00e3\u0130\u011f\u015f\u0110\u1ed9'
FONT_LOCK = threading.RLock()


class FontUnavailable(RuntimeError):
    pass


def installed_candidates():
    paths = [
        '/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/noto/NotoSerifTibetan-Regular.ttf',
        '/usr/share/fonts/truetype/noto/NotoSansGeorgian-Regular.ttf',
        '/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf',
        'C:/Windows/Fonts/arial.ttf', 'C:/Windows/Fonts/msyh.ttc',
        'C:/Windows/Fonts/simsun.ttc', 'C:/Windows/Fonts/seguisym.ttf',
        'C:/Windows/Fonts/himalaya.ttf', 'C:/Windows/Fonts/cambria.ttc',
    ]
    for root in (Path('/usr/share/fonts'), Path('/usr/local/share/fonts')):
        if root.is_dir():
            for pattern in ('NotoSansCJK*Regular*', 'NotoSansSC*', 'NotoSans*Regular.*',
                            'NotoSerif*Regular.*', 'DejaVuSans.ttf', 'uming.ttc', 'gbsn00lp.ttf'):
                paths.extend(str(p) for p in sorted(root.rglob(pattern))
                             if p.suffix.lower() in ('.ttf','.ttc','.otf'))
    return tuple(p for p in dict.fromkeys(paths) if Path(p).is_file())


def load_font(path, size):
    from PIL import ImageFont
    if Path(path).name == 'NotoSansCJK-Regular.ttc':
        try:
            return ImageFont.truetype(path,size,index=2)  # Simplified Chinese face
        except (OSError,ValueError):
            pass
    return ImageFont.truetype(path,size)


def glyph_exists(font, ch):
    if ch.isspace():
        return True
    mask = font.getmask(ch)
    missing = font.getmask('\U0010ffff')
    return (mask.size,bytes(mask)) != (missing.size,bytes(missing))


def choose_fonts(candidates):
    paths = []
    remaining = set(SAMPLE_LATIN+SAMPLE_CJK)
    for path in dict.fromkeys(candidates):
        try:
            f = load_font(path,24)
            remaining.difference_update(ch for ch in tuple(remaining) if glyph_exists(f,ch))
        except (OSError,ValueError,RuntimeError):
            continue
        paths.append(path)
    if remaining:
        raise FontUnavailable('Installed fonts lack required multilingual coverage')
    return tuple(paths)


@lru_cache(maxsize=1)
def _resolve_fonts():
    return choose_fonts(installed_candidates())


def resolve_fonts():
    with FONT_LOCK:
        return _resolve_fonts()
