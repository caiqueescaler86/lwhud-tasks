import unittest
from ds_web_i18n import LABELS, LANGS, ui, diagnostic_label, validation_label
from string import Formatter

class LanguageTests(unittest.TestCase):
    def test_all_strings_have_four_languages(self):
        for key,labels in LABELS.items():
            self.assertEqual(len(labels),len(LANGS),key)
            self.assertTrue(all(labels),key)
            fields=lambda s:{name for _,name,_,_ in Formatter().parse(s) if name}
            self.assertTrue(all(fields(x)==fields(labels[0]) for x in labels),key)
    def test_labels_preserve_code_and_variables(self):
        for lang in LANGS:
            self.assertIn("DS-TLS:",diagnostic_label(lang,"DS-TLS"))
            self.assertIn("NWG",ui(lang,"capture_rival",tag="NWG",server=1512))
            self.assertIn("1512",ui(lang,"capture_rival",tag="NWG",server=1512))
            self.assertEqual(validation_label(lang,ValueError("Unknown objective")),ui(lang,"Unknown objective"))
            self.assertEqual(validation_label(lang,ValueError("hidden detail")),ui(lang,"validation"))

if __name__=='__main__':unittest.main()
