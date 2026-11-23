"""Offline checks for career fields from the LWHUD Members CSV.

Run from this directory: python -m unittest test_career -v
No API, Supabase, network, secrets or Streamlit startup are needed.
"""
import json
import unittest

from core import (
    allowed_plan, apply_filters, career_code, evaluate, local_fallback_plan,
    sanitize_csv,
)


def csv_bytes(*lines):
    header = "Tag;Aliança conhecida;Servidor;Jogador;UID;Cargo;Profissão (código);Nível profissão;Poder;Última obs."
    return ("\n".join([header, *lines]) + "\n").encode("utf-8-sig")


class CareerCsvTests(unittest.TestCase):
    def test_hud_export_recognizes_profession_and_never_returns_uid(self):
        blob = csv_bytes(
            'NWG;Night;1512;Player A;="1533176916001512";R4;Tipo 2;61;250000000;23/11/2026 15:44'
        )
        rows, meta = sanitize_csv(blob)
        self.assertEqual(meta["jogadores"], 1)
        self.assertEqual(rows[0]["Profissão (código)"], "Tipo 2")
        self.assertEqual(rows[0]["Nível profissão"], "61")
        self.assertEqual(rows[0]["Cargo"], "R4")
        self.assertEqual(rows[0]["Total Power"], "250000000")
        self.assertNotIn("UID", rows[0])
        self.assertNotIn("1533176916001512", json.dumps(rows))

    def test_legacy_csv_without_profession_is_still_supported(self):
        rows, _ = sanitize_csv("Jogador;Cargo;Total Power\nA;R5;100\n".encode())
        self.assertEqual(rows[0]["Profissão (código)"], "")
        self.assertEqual(rows[0]["Nível profissão"], "")

    def test_duplicate_uid_keeps_most_recent_career(self):
        blob = csv_bytes(
            'NWG;Night;1512;Player A;="1533176916001512";R4;Tipo 1;50;220000000;22/11/2026 15:44',
            'NWG;Night;1512;Player A;="1533176916001512";R4;Tipo 2;61;250000000;23/11/2026 15:44',
        )
        rows, meta = sanitize_csv(blob)
        self.assertEqual(len(rows), 1)
        self.assertEqual(meta["duplicados"], 1)
        self.assertEqual(rows[0]["Profissão (código)"], "Tipo 2")
        self.assertEqual(rows[0]["Nível profissão"], "61")

    def test_career_type_is_categorical_not_hq(self):
        self.assertEqual(career_code("Tipo 2"), 2)
        self.assertEqual(career_code("Type 2"), 2)
        self.assertIsNone(career_code("Engenheiro"))
        self.assertIsNone(career_code("R5"))
        self.assertEqual(
            allowed_plan({"operation": "list", "metric": "career_lv",
                          "filters": {"career_type": "Tipo 2"}})["filters"]["career_type"], 2,
        )

    def test_chat_filters_by_profession_and_level(self):
        rows, _ = sanitize_csv(csv_bytes(
            'NWG;Night;1512;Alice;="1533176916001512";R4;Tipo 2;61;250000000;23/11/2026 15:44',
            'NWG;Night;1512;Bob;="1198363469001533";R3;Tipo 1;45;200000000;23/11/2026 15:44',
            'NWG;Night;1512;Caro;="1982069008001533";R3;Tipo 2;58;210000000;23/11/2026 15:44',
        ))
        selected = apply_filters(rows, {"career_type": 2, "min_career_lv": 60})
        self.assertEqual([r["Jogador"] for r in selected], ["Alice"])
        result = evaluate(rows, {
            "operation": "list", "metric": "career_lv", "show_career": True,
            "filters": {"career_type": 2}, "limit": 10,
        }, "en")
        self.assertIn("Alice", result)
        self.assertIn("Caro", result)
        self.assertIn("Profession level", result)
        self.assertNotIn("Bob", result)

    def test_multilingual_field_labels_and_grouping(self):
        rows, _ = sanitize_csv(csv_bytes(
            'NWG;Night;1512;Alice;="1533176916001512";R4;Tipo 2;61;250000000;23/11/2026 15:44',
            'NWG;Night;1512;Bob;="1198363469001533";R3;Tipo 1;45;200000000;23/11/2026 15:44',
        ))
        for lang in ("pt", "en", "zh", "tr"):
            with self.subTest(language=lang):
                result = evaluate(rows, {
                    "operation": "group", "metric": "career_lv", "group_by": "profissao",
                    "filters": {},
                }, language=lang)
                self.assertIn("Tipo 1", result)
                self.assertIn("Tipo 2", result)

    def test_local_fallback_does_not_need_groq(self):
        count = local_fallback_plan("Quantos jogadores da profissão tipo 2?")
        self.assertEqual(count["operation"], "count")
        self.assertEqual(count["filters"]["career_type"], 2)
        top = local_fallback_plan("Quem tem maior nível de profissão?")
        self.assertEqual(top["operation"], "top")
        self.assertEqual(top["metric"], "career_lv")
        named = local_fallback_plan("Qual a profissão de Alice?")
        self.assertEqual(named["operation"], "list")
        self.assertEqual(named["filters"]["name_contains"], "Alice")
        self.assertTrue(named["show_career"])


if __name__ == "__main__":
    unittest.main()
