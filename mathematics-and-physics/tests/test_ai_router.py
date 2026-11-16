import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_router import classify_task, candidates, PROVIDERS, RouterError, route_chat

class RouterTests(unittest.TestCase):
    def test_domains(self):
        self.assertEqual(classify_task("اكتب كود Python"), "software")
        self.assertEqual(classify_task("احسب مقاومة دائرة إلكترونية"), "electronics")
        self.assertEqual(classify_task("قانون نيوتن في الفيزياء"), "physics")
        self.assertEqual(classify_task("حل معادلة تكامل"), "mathematics")

    def test_unknown_provider(self):
        with self.assertRaises(ValueError):
            candidates("software", "not-a-provider")

    def test_only_configured(self):
        env = {p.key_env: "" for p in PROVIDERS.values()}
        env.update({p.model_env: "" for p in PROVIDERS.values()})
        with patch.dict(os.environ, env):
            self.assertEqual(candidates("software"), [])

    def test_preferred_order(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "test", "GROQ_MODEL": "model",
                                     "OPENROUTER_API_KEY": "test"}):
            self.assertEqual(candidates("software", "groq")[0], "groq")

if __name__ == "__main__":
    unittest.main()
