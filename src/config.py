import os

from dotenv import load_dotenv


_SRC_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SRC_DIR)

# Always load the project-local .env so the config is stable no matter
# which working directory or launcher is used to start the app.
load_dotenv(os.path.join(_PROJECT_ROOT, ".env"))


class Config:
    """Project configuration."""

    # API configuration
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

    # Keep Moonshot-compatible settings working even when the project only
    # configures the generic OpenAI-compatible variables.
    MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY") or OPENAI_API_KEY
    MOONSHOT_BASE_URL = os.getenv("MOONSHOT_BASE_URL") or OPENAI_BASE_URL
    MODEL_NAME = os.getenv("MODEL_NAME", "moonshot-v1-8k")
    STRUCTURED_MODEL_NAME = os.getenv("STRUCTURED_MODEL_NAME", "moonshot-v1-8k")
    CHAT_MODEL_NAME = os.getenv("CHAT_MODEL_NAME", "kimi-latest")
    PLANNER_MODEL_NAME = os.getenv("PLANNER_MODEL_NAME") or STRUCTURED_MODEL_NAME
    INTERVIEWER_MODEL_NAME = os.getenv("INTERVIEWER_MODEL_NAME") or CHAT_MODEL_NAME
    BASELINE_MODEL_NAME = os.getenv("BASELINE_MODEL_NAME") or INTERVIEWER_MODEL_NAME
    EXTRACTOR_MODEL_NAME = os.getenv("EXTRACTOR_MODEL_NAME") or STRUCTURED_MODEL_NAME
    INTERVIEWEE_MODEL_NAME = os.getenv("INTERVIEWEE_MODEL_NAME") or CHAT_MODEL_NAME
    STREAMING_MODEL_NAME = os.getenv("STREAMING_MODEL_NAME") or INTERVIEWER_MODEL_NAME
    CAMEL_MODEL_NAME = os.getenv("CAMEL_MODEL_NAME") or STRUCTURED_MODEL_NAME
    RELATION_LLM_MODEL_NAME = os.getenv("RELATION_LLM_MODEL_NAME") or STRUCTURED_MODEL_NAME
    ENABLE_RELATION_LLM_FALLBACK = os.getenv("ENABLE_RELATION_LLM_FALLBACK", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    # App settings
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", 3))
    REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 30))

    # Paths
    PROJECT_ROOT = _PROJECT_ROOT
    PROMPTS_DIR = os.path.join(_SRC_DIR, "prompts")
    DATA_DIR = "data"
    LOGS_DIR = "logs"

    # Optional prompt overrides
    INTERVIEWEE_PROMPT_TEMPLATE = os.getenv(
        "INTERVIEWEE_PROMPT_TEMPLATE",
        None,
    )
    LIFE_GENERATOR_SYSTEM_PROMPT = os.getenv(
        "LIFE_GENERATOR_SYSTEM_PROMPT",
        None,
    )
    INTERVIEWER_SYSTEM_PROMPT = os.getenv(
        "INTERVIEWER_SYSTEM_PROMPT",
        "prompts/interviewer_system_prompt.md",
    )

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
            "planner": cls.PLANNER_MODEL_NAME,
            "interviewer": cls.INTERVIEWER_MODEL_NAME,
            "baseline": cls.BASELINE_MODEL_NAME,
            "extractor": cls.EXTRACTOR_MODEL_NAME,
            "interviewee": cls.INTERVIEWEE_MODEL_NAME,
            "streaming": cls.STREAMING_MODEL_NAME,
            "camel": cls.CAMEL_MODEL_NAME,
            "structured": cls.STRUCTURED_MODEL_NAME,
            "chat": cls.CHAT_MODEL_NAME,
        }
        return model_map.get(role_key, cls.MODEL_NAME)

    @classmethod
    def get_model_candidates(cls, role=None):
        role_key = (role or "").strip().lower()
        if role_key in {"planner", "extractor", "camel"}:
            candidates = [
                cls.get_model_name(role_key),
                cls.STRUCTURED_MODEL_NAME,
                cls.MODEL_NAME,
            ]
        elif role_key in {"interviewer", "baseline", "interviewee", "streaming"}:
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
