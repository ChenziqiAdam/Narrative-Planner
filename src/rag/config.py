"""
Configuration file for RAG system
Allows flexible configuration for different memoir projects
"""

import os
from dataclasses import dataclass, field
from typing import List, Dict, Optional


@dataclass
class MarkdownConfig:
    """Configuration for markdown parsing"""
    # Header patterns for chapter detection
    chapter_patterns: List[str] = field(default_factory=lambda: [
        r'^#{1,3}\s+',  # Markdown headers (# ## ###)
    ])

    # Speaker patterns for interview transcript
    speaker_patterns: Dict[str, str] = field(default_factory=lambda: {
        'interviewer': r'^(采访者|访谈者|Interviewer)[:：]',
        'interviewee': r'^(受访老人|受访者|Interviewee)[:：]',
    })

    # Text encoding
    encoding: str = 'utf-8'

    # Skip patterns (lines to ignore)
    skip_patterns: List[str] = field(default_factory=lambda: [
        r'^\s*$',  # Empty lines
    ])


@dataclass
class ChunkingConfig:
    """Configuration for text chunking"""
    # Maximum characters per chunk
    max_chars: int = 500

    # Overlap between chunks
    overlap_chars: int = 50

    # Sentence delimiters
    sentence_delimiters: List[str] = field(default_factory=lambda: [
        '。', '！', '？', '\n', '.', '!', '?'
    ])

    # Minimum chunk size
    min_chunk_size: int = 50


@dataclass
class EmbeddingConfig:
    """Configuration for embedding model"""
    # Model name from sentence-transformers
    model_name: str = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'

    # Device for model inference
    device: str = 'cpu'  # or 'cuda' for GPU

    # Batch size for encoding
    batch_size: int = 32

    # Vector dimension (auto-detected from model)
    vector_dim: Optional[int] = None


@dataclass
class RetrievalConfig:
    """Configuration for retrieval"""
    # Layer 1: Number of chapters to retrieve
    layer1_top_k: int = 2

    # Layer 2: Number of chunks to retrieve
    layer2_top_k: int = 3

    # FAISS index type
    index_type: str = 'flat'  # 'flat' or 'ivf' for large scale

    # Similarity metric
    similarity_metric: str = 'l2'  # 'l2' or 'cosine'


@dataclass
class ProfileConfig:
    """Configuration for character profile generation"""
    # Whether to use LLM for profile generation
    use_llm: bool = False

    # LLM model for profile generation (if use_llm=True)
    llm_model: Optional[str] = None

    # Whether to generate summary for chapters
    generate_summary: bool = True

    # Summary method: 'truncate' or 'llm'
    summary_method: str = 'truncate'

    # Summary length (for truncate method)
    summary_length: int = 200


@dataclass
class RAGConfig:
    """Main configuration for RAG system"""
    # Project name
    project_name: str = "memoir_rag"

    # Input files
    structured_memoir_path: str = "./回忆录参考成文.md"
    interview_transcript_path: Optional[str] = "./回忆录访谈稿.md"

    # Output directory
    output_dir: str = "./rag_data"

    # Sub-configurations
    markdown: MarkdownConfig = field(default_factory=MarkdownConfig)
    chunking: ChunkingConfig = field(default_factory=ChunkingConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    profile: ProfileConfig = field(default_factory=ProfileConfig)

    # Character information (can be customized)
    character_info: Dict = field(default_factory=lambda: {
        'name': '未知',
        'role': '受访者',
        'purpose': '记录人生经历',
        'audience': '后代',
    })

    def __post_init__(self):
        """Validate configuration"""
        if not os.path.exists(self.structured_memoir_path):
            print(f"Warning: structured_memoir_path does not exist: {self.structured_memoir_path}")

        if self.interview_transcript_path and not os.path.exists(self.interview_transcript_path):
            print(f"Warning: interview_transcript_path does not exist: {self.interview_transcript_path}")

        # Create output directory if not exists
        os.makedirs(self.output_dir, exist_ok=True)

    @classmethod
    def from_dict(cls, config_dict: Dict) -> 'RAGConfig':
        """Create config from dictionary"""
        return cls(**config_dict)

    def to_dict(self) -> Dict:
        """Convert config to dictionary"""
        return {
            'project_name': self.project_name,
            'structured_memoir_path': self.structured_memoir_path,
            'interview_transcript_path': self.interview_transcript_path,
            'output_dir': self.output_dir,
            'character_info': self.character_info,
        }

    def save(self, filepath: str):
        """Save configuration to JSON file"""
        import json
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, filepath: str) -> 'RAGConfig':
        """Load configuration from JSON file"""
        import json
        with open(filepath, 'r', encoding='utf-8') as f:
            config_dict = json.load(f)
        return cls.from_dict(config_dict)


# Default configuration
DEFAULT_CONFIG = RAGConfig()


# Example: English memoir configuration
ENGLISH_MEMOIR_CONFIG = RAGConfig(
    project_name="english_memoir",
    structured_memoir_path="./memoir_english.md",
    interview_transcript_path="./interview_english.md",
    output_dir="./rag_data_english",
    markdown=MarkdownConfig(
        speaker_patterns={
            'interviewer': r'^(Interviewer|Q)[:：]',
            'interviewee': r'^(Interviewee|A|Respondent)[:：]',
        }
    ),
    chunking=ChunkingConfig(
        max_chars=600,  # English typically needs more chars
        overlap_chars= 100,
        sentence_delimiters=['.', '!', '?', '\n'],
    ),
    character_info={
        'name': 'Unknown',
        'role': 'Interviewee',
        'purpose': 'Record life story',
        'audience': 'Descendants',
    }
)


if __name__ == "__main__":
    # Test configuration
    config = DEFAULT_CONFIG
    print("Default Configuration:")
    print(f"  Project: {config.project_name}")
    print(f"  Memoir: {config.structured_memoir_path}")
    print(f"  Transcript: {config.interview_transcript_path}")
    print(f"  Output: {config.output_dir}")
    print(f"  Chunk size: {config.chunking.max_chars}")
    print(f"  Embedding model: {config.embedding.model_name}")
    print(f"  Layer 1 top-k: {config.retrieval.layer1_top_k}")
    print(f"  Layer 2 top-k: {config.retrieval.layer2_top_k}")
