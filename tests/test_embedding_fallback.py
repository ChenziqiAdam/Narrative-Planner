import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _reset_embedding_singletons():
    import src.services.embedding_service as embedding_module

    embedding_module.EmbeddingService._instances.clear()
    embedding_module._default_service = None


class EmbeddingFallbackTest(unittest.TestCase):
    def setUp(self):
        _reset_embedding_singletons()

    def tearDown(self):
        _reset_embedding_singletons()

    def test_embedding_service_falls_back_when_local_model_load_fails(self):
        from src.config import Config
        from src.services.embedding_service import EmbeddingService

        with patch.object(Config, "EMBEDDING_PROVIDER", "local"):
            service = EmbeddingService()

            def fail_model_load():
                raise TypeError(
                    "Pooling.__init__() missing 1 required positional argument: "
                    "'word_embedding_dimension'"
                )

            with patch.object(service, "_ensure_model", fail_model_load):
                vectors = service.encode(["factory work", "family wedding"])

        self.assertEqual(len(vectors), 2)
        self.assertEqual(len(vectors[0]), service.get_dimension())
        self.assertTrue(service.get_status()["fallback_active"])
        self.assertIn("word_embedding_dimension", service.get_status()["fallback_reason"])

    def test_semantic_memory_search_falls_back_to_lexical_search(self):
        from src.config import Config
        from src.services.embedding_service import EmbeddingService
        from src.tools.elder_tools import ElderMemorySystem

        profile = {
            "elder_profile": {
                "life_memories_by_period": {
                    "period_1": {
                        "memory_events": [
                            {
                                "event_id": "mem_factory",
                                "event_name": "First factory shift",
                                "description": "I started work in the textile factory.",
                                "details": "The workshop was loud but memorable.",
                                "tags": ["factory", "work"],
                            },
                            {
                                "event_id": "mem_wedding",
                                "event_name": "Wedding day",
                                "description": "Family gathered for a small wedding.",
                                "details": "Neighbors came to celebrate.",
                                "tags": ["family"],
                            },
                        ]
                    }
                }
            }
        }

        def fail_model_load(self):
            raise TypeError(
                "Pooling.__init__() missing 1 required positional argument: "
                "'word_embedding_dimension'"
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "elder.json"
            path.write_text(json.dumps(profile), encoding="utf-8")

            with patch.object(Config, "EMBEDDING_PROVIDER", "local"), \
                patch.object(EmbeddingService, "_ensure_model", fail_model_load):
                memory_system = ElderMemorySystem(str(path))

                def fail_search(*args, **kwargs):
                    raise TypeError(
                        "Pooling.__init__() missing 1 required positional argument: "
                        "'word_embedding_dimension'"
                    )

                with patch.object(memory_system._vector_store, "search_by_text", fail_search):
                    results = memory_system.search_memories_by_semantic("factory work", top_k=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["memory_id"], "mem_factory")
        self.assertGreaterEqual(results[0]["similarity_score"], 0.0)
        self.assertLessEqual(results[0]["similarity_score"], 1.0)


if __name__ == "__main__":
    unittest.main()
