import unittest
from unittest.mock import patch
from ds_fonts import choose_fonts, FontUnavailable, installed_candidates, SAMPLE_CJK, SAMPLE_LATIN


class FakeFont:
    def __init__(self, cjk=False, latin=False):
        self.cjk, self.latin = cjk,latin
    def getmask(self,ch):
        if (self.cjk and ch in SAMPLE_CJK) or (self.latin and ch in SAMPLE_LATIN):
            return b'present'
        return b'missing'


class FontTests(unittest.TestCase):
    @patch('PIL.ImageFont.truetype')
    def test_installed_fonts_avoid_network(self, loader):
        loader.side_effect=lambda name,size:FakeFont(cjk=name=='cjk',latin=name=='latin')
        def fallback():self.fail('Do not download if installed fonts cover both scripts')
        self.assertEqual(choose_fonts(['cjk','latin'],fallback),('cjk','latin'))
    @patch('PIL.ImageFont.truetype')
    def test_missing_cjk_downloads_pinned_fallback(self,loader):
        loader.side_effect=lambda name,size:FakeFont(cjk=name=='fallback',latin=True)
        self.assertEqual(choose_fonts(['latin'],lambda:'fallback'),('fallback','latin'))
    @patch('PIL.ImageFont.truetype')
    def test_missing_fonts_fail_closed(self,loader):
        loader.return_value=FakeFont()
        with self.assertRaises(FontUnavailable):choose_fonts([],lambda:'broken')
    @patch('PIL.ImageFont.truetype')
    def test_bad_installed_font_is_skipped(self,loader):
        def load(name,size):
            if name=='broken':raise OSError('bad font')
            return FakeFont(cjk=True,latin=True)
        loader.side_effect=load
        self.assertEqual(choose_fonts(['broken','good'],lambda:self.fail('Unexpected download')),('good',))
    def test_real_installed_fonts(self):
        paths=installed_candidates()
        if not paths:self.skipTest('No system fonts on test host')
        try:
            result=choose_fonts(paths,lambda: (_ for _ in ()).throw(FontUnavailable('offline')))
        except FontUnavailable:
            self.skipTest('Multilingual font missing on test host')
        self.assertTrue(result)

if __name__=='__main__':unittest.main()
