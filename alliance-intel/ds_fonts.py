"""Resolve multilingual fonts once per web process, with a pinned upstream fallback."""
from pathlib import Path
from functools import lru_cache
import hashlib
import ssl
import tempfile
import threading
import time
from urllib.request import urlopen

# Noto Sans CJK SC Regular, official release Sans2.004. Verify the pinned Git blob.
FONT_URL = 'https://raw.githubusercontent.com/notofonts/noto-cjk/523d033d6cb47f4a80c58a35753646f5c3608a78/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf'
FONT_SIZE = 16437364
FONT_BLOB = 'dc15562470b4f842321894787a0d066879ccff8b'
SAMPLE_CJK = '\u6c99\u6f20\u98ce\u66b4\u8054\u76df'
SAMPLE_LATIN = 'Aa\u00c7\u00e3\u0130\u011f\u015f\u0110\u1ed9'
FONT_LOCK = threading.RLock()
_fonts = None
_retry_after = 0.0


class FontUnavailable(RuntimeError):
    pass


def installed_candidates():
    paths = [
        'C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/simsun.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        'C:/Windows/Fonts/arial.ttf', 'C:/Windows/Fonts/seguisym.ttf',
        'C:/Windows/Fonts/himalaya.ttf', 'C:/Windows/Fonts/cambria.ttc',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    ]
    for root in (Path('/usr/share/fonts'), Path('/usr/local/share/fonts')):
        if root.is_dir():
            for pattern in ('NotoSansCJK*Regular*', 'NotoSansSC*', 'NotoSans*Regular*', 'NotoSerif*Regular*', 'DejaVuSans.ttf', 'uming.ttc', 'gbsn00lp.ttf'):
                paths.extend(str(p) for p in sorted(root.rglob(pattern)) if p.suffix.lower() in ('.ttf','.ttc','.otf'))
    return tuple(p for p in dict.fromkeys(paths) if Path(p).is_file())


def supports(font, sample):
    missing = bytes(font.getmask('\U0010ffff'))
    return all(bytes(font.getmask(ch)) != missing for ch in sample)


@lru_cache(maxsize=1)
def upstream_font():
    import certifi
    context = ssl.create_default_context(cafile=certifi.where())
    with urlopen(FONT_URL, timeout=25, context=context) as response:
        if response.geturl() != FONT_URL:
            raise FontUnavailable('Unexpected font redirect')
        raw = response.read(FONT_SIZE+1)
    if len(raw) != FONT_SIZE:
        raise FontUnavailable('Unexpected font size')
    # This hash is a Git content identifier, not password cryptography.
    digest = hashlib.sha1(('blob %d\0' % len(raw)).encode('ascii')+raw).hexdigest()
    if digest != FONT_BLOB:
        raise FontUnavailable('Font content did not match the pinned release')
    # Hold the temporary directory for the lifetime of the process.
    directory = tempfile.TemporaryDirectory(prefix='ds-noto-')
    path = Path(directory.name)/'NotoSansCJKsc-Regular.otf'
    path.write_bytes(raw)
    return directory, str(path)


def choose_fonts(candidates, fallback):
    from PIL import ImageFont
    paths = []
    cjk = latin = False
    for p in dict.fromkeys(candidates):
        try:
            f = ImageFont.truetype(p,24)
            cjk_ok = supports(f,SAMPLE_CJK)
            latin_ok = supports(f,SAMPLE_LATIN)
        except (OSError, ValueError, RuntimeError):
            continue
        paths.append(p)
        cjk = cjk or cjk_ok
        latin = latin or latin_ok
    if not (cjk and latin):
        try:
            p = fallback()
            f = ImageFont.truetype(p,24)
            if not supports(f,SAMPLE_CJK) or not supports(f,SAMPLE_LATIN):
                raise FontUnavailable('Fallback font lacks required glyphs')
            paths.insert(0,p)
        except (OSError, ValueError, RuntimeError) as exc:
            raise FontUnavailable('Multilingual font unavailable') from exc
    return tuple(dict.fromkeys(paths))


def resolve_fonts():
    global _fonts, _retry_after
    with FONT_LOCK:
        if _fonts is not None:
            return _fonts
        if time.monotonic() < _retry_after:
            raise FontUnavailable('Font provisioning temporarily unavailable')
        try:
            _fonts = choose_fonts(installed_candidates(),lambda:upstream_font()[1])
            return _fonts
        except FontUnavailable:
            _retry_after = time.monotonic()+300
            raise
