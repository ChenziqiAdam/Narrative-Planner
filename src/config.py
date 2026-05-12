import os

from dotenv import load_dotenv


_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SRC_DIR)

load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))


class Config:
    """Project configuration."""

    # API configuration
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY") or OPENAI_API_KEY
    MOONSHOT_BASE_URL = os.getenv("MOONSHOT_BASE_URL") or OPENAI_BASE_URL
    MODEL_NAME = os.getenv("MODEL_NAME", "moonshot-v1-8k")
    STRUCTURED_MODEL_NAME = os.getenv("STRUCTURED_MODEL_NAME", "moonshot-v1-8k")
    CHAT_MODEL_NAME = os.getenv("CHAT_MODEL_NAME", "moonshot-v1-8k")
    INTERVIEWER_MODEL_NAME = os.getenv("INTERVIEWER_MODEL_NAME") or CHAT_MODEL_NAME
    BASELINE_MODEL_NAME = os.getenv("BASELINE_MODEL_NAME") or INTERVIEWER_MODEL_NAME
    INTERVIEWEE_MODEL_NAME = os.getenv("INTERVIEWEE_MODEL_NAME") or CHAT_MODEL_NAME
    EXTRACTOR_MODEL_NAME = os.getenv("EXTRACTOR_MODEL_NAME") or STRUCTURED_MODEL_NAME
    STREAMING_MODEL_NAME = os.getenv("STREAMING_MODEL_NAME") or INTERVIEWER_MODEL_NAME
    CAMEL_MODEL_NAME = os.getenv("CAMEL_MODEL_NAME") or STRUCTURED_MODEL_NAME
    RELATION_LLM_MODEL_NAME = os.getenv("RELATION_LLM_MODEL_NAME") or STRUCTURED_MODEL_NAME
    ENABLE_RELATION_LLM_FALLBACK = os.getenv("ENABLE_RELATION_LLM_FALLBACK", "false").lower() in {
        "1", "true", "yes", "on",
    }

    # Automated interviewee simulation prompt controls.
    # The compare experiment can run many turns, so only recent dialogue should
    # be sent back to the simulated respondent on each call.
    INTERVIEWEE_HISTORY_MAX_TURNS = int(os.getenv("INTERVIEWEE_HISTORY_MAX_TURNS", "8"))
    INTERVIEWEE_HISTORY_MAX_CHARS = int(os.getenv("INTERVIEWEE_HISTORY_MAX_CHARS", "6000"))
    INTERVIEWEE_REPLY_MAX_TOKENS = int(os.getenv("INTERVIEWEE_REPLY_MAX_TOKENS", "900"))

    # Graph extraction prompt controls.  The full markdown prompt is useful for
    # development, but batch experiments need a compact extraction contract.
    GRAPH_EXTRACTION_COMPACT_PROMPT = os.getenv("GRAPH_EXTRACTION_COMPACT_PROMPT", "true").lower() in {
        "1", "true", "yes", "on",
    }
    GRAPH_EXTRACTION_CONTEXT_TURNS = int(os.getenv("GRAPH_EXTRACTION_CONTEXT_TURNS", "1"))
    GRAPH_EXTRACTION_MAX_TURN_CHARS = int(os.getenv("GRAPH_EXTRACTION_MAX_TURN_CHARS", "1200"))
    GRAPH_EXTRACTION_MAX_GRAPH_CONTEXT_CHARS = int(os.getenv("GRAPH_EXTRACTION_MAX_GRAPH_CONTEXT_CHARS", "1500"))
    GRAPH_EXTRACTION_MAX_OUTPUT_TOKENS = int(os.getenv("GRAPH_EXTRACTION_MAX_OUTPUT_TOKENS", "1200"))

    # App settings
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", 3))
    REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 30))

    # Paths
    PROJECT_ROOT = _PROJECT_ROOT
    PROMPTS_DIR = os.path.join(_SRC_DIR, "prompts")
    INTERVIEWEE_PROMPT_TEMPLATE = os.getenv(
        "INTERVIEWEE_PROMPT_TEMPLATE",
        os.path.join(PROMPTS_DIR, "roles", "elderly_system_prompt.md"),
    )
    DATA_DIR = "data"
    LOGS_DIR = "logs"

    # Neo4j graph database configuration
    NEO4J_ENABLED = os.getenv("NEO4J_ENABLED", "false").lower() in {
        "1", "true", "yes", "on"
    }
    NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
    NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

    # Embedding configuration
    EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "local")  # "local" | "openai"
    EMBEDDING_MODEL_LOCAL = os.getenv(
        "EMBEDDING_MODEL_LOCAL",
        "paraphrase-multilingual-MiniLM-L12-v2",
    )
    EMBEDDING_OPENAI_API_KEY = os.getenv("EMBEDDING_OPENAI_API_KEY") or OPENAI_API_KEY
    EMBEDDING_OPENAI_BASE_URL = os.getenv("EMBEDDING_OPENAI_BASE_URL") or OPENAI_BASE_URL
    EMBEDDING_OPENAI_MODEL = os.getenv("EMBEDDING_OPENAI_MODEL", "text-embedding-3-small")

    # Dynamic elder profile projection
    ENABLE_DYNAMIC_PROFILE_UPDATE = os.getenv("ENABLE_DYNAMIC_PROFILE_UPDATE", "true").lower() in {
        "1", "true", "yes", "on"
    }
    DYNAMIC_PROFILE_MIN_TURNS_BETWEEN_UPDATES = int(
        os.getenv("DYNAMIC_PROFILE_MIN_TURNS_BETWEEN_UPDATES", "3")
    )
    DYNAMIC_PROFILE_MAX_TURNS_BETWEEN_UPDATES = int(
        os.getenv("DYNAMIC_PROFILE_MAX_TURNS_BETWEEN_UPDATES", "5")
    )
    PROFILE_GUIDANCE_MAX_NOTES = int(os.getenv("PROFILE_GUIDANCE_MAX_NOTES", "4"))

    # Planner tool-calling controls.  These are intentionally small by default
    # so tool use can improve planning observability without doubling latency.
    PLANNER_TOOLS_ENABLED = os.getenv("PLANNER_TOOLS_ENABLED", "true").lower() in {
        "1", "true", "yes", "on"
    }
    PLANNER_MAX_TOOL_ROUNDS = int(os.getenv("PLANNER_MAX_TOOL_ROUNDS", "2"))
    PLANNER_MAX_TOOLS_PER_ROUND = int(os.getenv("PLANNER_MAX_TOOLS_PER_ROUND", "2"))

    # Legacy planner decision weights (used by pre-GraphRAG pipeline)
    PLANNER_NEW_INFO_WEIGHT = float(os.getenv("PLANNER_NEW_INFO_WEIGHT", "1.0"))
    PLANNER_MISSING_SLOT_WEIGHT = float(os.getenv("PLANNER_MISSING_SLOT_WEIGHT", "1.15"))
    PLANNER_THEME_COVERAGE_WEIGHT = float(os.getenv("PLANNER_THEME_COVERAGE_WEIGHT", "1.0"))
    PLANNER_EMOTION_ENERGY_WEIGHT = float(os.getenv("PLANNER_EMOTION_ENERGY_WEIGHT", "0.9"))
    PLANNER_MEMORY_STABILITY_WEIGHT = float(os.getenv("PLANNER_MEMORY_STABILITY_WEIGHT", "0.85"))
    PLANNER_CONFLICT_CLARIFICATION_WEIGHT = float(os.getenv("PLANNER_CONFLICT_CLARIFICATION_WEIGHT", "1.0"))
    PLANNER_INFORMATION_QUALITY_WEIGHT = float(os.getenv("PLANNER_INFORMATION_QUALITY_WEIGHT", "0.95"))
    PLANNER_LOW_GAIN_PENALTY = float(os.getenv("PLANNER_LOW_GAIN_PENALTY", "1.1"))
    PLANNER_REFLECTION_SLOT_WEIGHT = float(os.getenv("PLANNER_REFLECTION_SLOT_WEIGHT", "0.75"))
    PLANNER_FACTUAL_SLOT_WEIGHT = float(os.getenv("PLANNER_FACTUAL_SLOT_WEIGHT", "1.0"))

    # History compression — summarise old turns to stay within token limits
    SUMMARIZER_MODEL_NAME = os.getenv("SUMMARIZER_MODEL_NAME") or CHAT_MODEL_NAME
    HISTORY_COMPRESS_MAX_RECENT_TURNS = int(
        os.getenv("HISTORY_COMPRESS_MAX_RECENT_TURNS", "6")
    )
    HISTORY_COMPRESS_MAX_CHAR_THRESHOLD = int(
        os.getenv("HISTORY_COMPRESS_MAX_CHAR_THRESHOLD", "12000")
    )

    # Query optimization: delegate graph RAG retrieval to extraction agent
    # When enabled, the extraction agent performs memory queries instead of direct HybridRetriever calls
    QUERY_OPTIMIZATION_ENABLED = os.getenv("QUERY_OPTIMIZATION_ENABLED", "false").lower() in {
        "1", "true", "yes", "on"
    }

    @classmethod
    def get_api_key(cls):
        return getattr(cls, "OPENAI_API_KEY", None) or getattr(cls, "MOONSHOT_API_KEY", None)

    @classmethod
    def get_base_url(cls):
        return (
            os.getenv("OPENAI_BASE_URL")
            or os.getenv("MOONSHOT_BASE_URL")
            or getattr(cls, "OPENAI_BASE_URL", None)
            or getattr(cls, "MOONSHOT_BASE_URL", None)
            or "https://api.openai.com/v1"
        )

    @classmethod
    def get_openai_client_kwargs(cls):
        kwargs = {"api_key": cls.get_api_key()}
        base_url = cls.get_base_url()
        if base_url:
            kwargs["base_url"] = base_url
        return kwargs

    @classmethod
    def get_model_name(cls, role=None):
        role_key = (role or "").strip().lower()
        model_map = {
            "interviewer": cls.INTERVIEWER_MODEL_NAME,
            "baseline": cls.BASELINE_MODEL_NAME,
            "interviewee": cls.INTERVIEWEE_MODEL_NAME,
            "extractor": cls.EXTRACTOR_MODEL_NAME,
            "streaming": cls.STREAMING_MODEL_NAME,
            "camel": cls.CAMEL_MODEL_NAME,
            "structured": cls.STRUCTURED_MODEL_NAME,
            "chat": cls.CHAT_MODEL_NAME,
            "summarizer": cls.SUMMARIZER_MODEL_NAME,
        }
        return model_map.get(role_key, cls.MODEL_NAME)

    @classmethod
    def get_model_candidates(cls, role=None):
        role_key = (role or "").strip().lower()
        if role_key in {"extractor", "camel"}:
            candidates = [
                cls.get_model_name(role_key),
                cls.STRUCTURED_MODEL_NAME,
                cls.MODEL_NAME,
            ]
        elif role_key in {"interviewer", "streaming", "baseline", "interviewee", "summarizer"}:
            candidates = [
                cls.get_model_name(role_key),
                cls.CHAT_MODEL_NAME,
                cls.MODEL_NAME,
                cls.STRUCTURED_MODEL_NAME,
            ]
        else:
            candidates = [cls.get_model_name(role_key), cls.MODEL_NAME]

        unique_candidates = []
        for candidate in candidates:
            normalized = (candidate or "").strip()
            if normalized and normalized not in unique_candidates:
                unique_candidates.append(normalized)
        return unique_candidates


os.makedirs(Config.PROMPTS_DIR, exist_ok=True)
os.makedirs(Config.DATA_DIR, exist_ok=True)
os.makedirs(Config.LOGS_DIR, exist_ok=True)
