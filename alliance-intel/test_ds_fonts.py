import csv
import io
import unittest
from unittest.mock import patch
from PIL import Image
from ds_fonts import choose_fonts, FontUnavailable, installed_candidates, SAMPLE_CJK, SAMPLE_LATIN, load_font, glyph_exists
from ds_intel import plan
from ds_intel_render import render_png


class FakeMask:
    size=(1,1)
    def __init__(self,present):self.present=present
    def __bytes__(self):return b'1' if self.present else b'0'


class FakeFont:
    def __init__(self,chars):self.chars=chars
    def getmask(self,ch):return FakeMask(ch in self.chars)


class FontTests(unittest.TestCase):
    @patch('ds_fonts.load_font')
    def test_combined_coverage(self,loader):
        loader.side_effect=lambda name,size:FakeFont(SAMPLE_CJK if name=='cjk' else SAMPLE_LATIN)
        self.assertEqual(choose_fonts(['cjk','latin']),('cjk','latin'))
    @patch('ds_fonts.load_font')
    def test_split_latin_coverage(self,loader):
        loader.side_effect=lambda name,size:FakeFont({'cjk':SAMPLE_CJK,'lat1':SAMPLE_LATIN[:5],'lat2':SAMPLE_LATIN[5:]}[name])
        self.assertEqual(choose_fonts(['cjk','lat1','lat2']),('cjk','lat1','lat2'))
    @patch('ds_fonts.load_font')
    def test_missing_fonts_fail_closed(self,loader):
        loader.return_value=FakeFont(SAMPLE_CJK)
        with self.assertRaises(FontUnavailable):choose_fonts(['cjk'])
    @patch('ds_fonts.load_font')
    def test_broken_font_is_skipped(self,loader):
        def load(name,size):
            if name=='broken':raise OSError('bad font')
            return FakeFont(SAMPLE_LATIN+SAMPLE_CJK)
        loader.side_effect=load
        self.assertEqual(choose_fonts(['broken','good']),('good',))
    def test_real_multilingual_png(self):
        # Synthetic names exercise the scripts present in real DS rosters.
        names=['Player 1','\u5c0f\u7ea2','Jo\u00e3o','\u011e\u00fc\u015f\u0130', '\u0110\u1ed9', '\u039e\u03a9', '\u10e6','\u0f5e','\u4e98','\uff4e\uff41','\u0253\u0267','\u1d4f\u1d52']
        names=(names*3)[:30]
        players=[dict(uid=str(i),name=n,hero_power=1000-i,army_power=100,total_power=2000) for i,n in enumerate(names)]
        match=dict(team='B',own={'tag':'ALLY','server_id':1},enemy={'tag':'RIVAL','server_id':2},starters=players[:20],reserves=players[20:])
        paths=choose_fonts(installed_candidates())
        fonts=[load_font(p,24) for p in paths]
        for ch in set(''.join(names)):
            self.assertTrue(any(glyph_exists(f,ch) for f in fonts),f'Missing glyph U+{ord(ch):04X}')
        result=plan(match)
        for lang in ('en','pt','tr','zh'):
            out=io.BytesIO();render_png(out,match,result,lang);out.seek(0)
            with Image.open(out) as im:
                self.assertEqual(im.format,'PNG');self.assertEqual(im.size,(2200,2640));im.verify()

if __name__=='__main__':unittest.main()
