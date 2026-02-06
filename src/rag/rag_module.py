"""
RAG Module for User Simulator (Refactored Version)
Flexible, configurable two-layer FAISS index for memoir retrieval
"""

import re
import json
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
from config import RAGConfig, MarkdownConfig, ChunkingConfig


@dataclass
class Chapter:
    """Represents a chapter in the memoir"""
    title: str
    content: str
    summary: str = ""
    start_line: int = 0
    end_line: int = 0
    metadata: Dict = None


@dataclass
class TextChunk:
    """Represents a text chunk for detailed retrieval"""
    text: str
    chapter_title: str
    chunk_id: int
    metadata: Dict = None


class MarkdownParser:
    """Parse markdown memoir files and extract chapter structure"""

    def __init__(self, config: MarkdownConfig = None):
        """
        Initialize parser with configuration

        Args:
            config: MarkdownConfig object, uses default if None
        """
        self.config = config or MarkdownConfig()

    def parse_structured_memoir(self, file_path: str) -> List[Chapter]:
        """
        Parse structured memoir file
        Extract chapters based on markdown headers

        Args:
            file_path: Path to markdown file

        Returns:
            List of Chapter objects
        """
        with open(file_path, 'r', encoding=self.config.encoding) as f:
            lines = f.readlines()

        chapters = []
        current_chapter = None
        current_content = []

        for i, line in enumerate(lines):
            # Check if line is a chapter header
            is_header = False
            for pattern in self.config.chapter_patterns:
                if re.match(pattern, line):
                    is_header = True
                    break

            if is_header:
                # Save previous chapter
                if current_chapter:
                    current_chapter.content = ''.join(current_content).strip()
                    current_chapter.end_line = i - 1
                    chapters.append(current_chapter)

                # Start new chapter
                title = re.sub(r'^#{1,6}\s+', '', line).strip()
                current_chapter = Chapter(
                    title=title,
                    content="",
                    start_line=i,
                    metadata={'source': file_path}
                )
                current_content = []
            elif current_chapter:
                # Skip empty lines if configured
                skip = False
                for pattern in self.config.skip_patterns:
                    if re.match(pattern, line):
                        skip = True
                        break
                if not skip:
                    current_content.append(line)

        # Add last chapter
        if current_chapter:
            current_chapter.content = ''.join(current_content).strip()
            current_chapter.end_line = len(lines) - 1
            chapters.append(current_chapter)

        return chapters

    def parse_interview_transcript(self, file_path: str) -> List[Dict]:
        """
        Parse interview transcript
        Extract Q&A pairs

        Args:
            file_path: Path to transcript file

        Returns:
            List of Q&A dictionaries
        """
        with open(file_path, 'r', encoding=self.config.encoding) as f:
            lines = f.readlines()

        qa_pairs = []
        current_speaker = None
        current_text = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check for speaker pattern
            speaker_found = None
            matched_text = None

            for speaker_type, pattern in self.config.speaker_patterns.items():
                match = re.match(pattern, line)
                if match:
                    speaker_found = speaker_type
                    # Extract text after the speaker prefix
                    matched_text = re.sub(pattern, '', line).strip()
                    break

            if speaker_found:
                # Save previous entry
                if current_speaker and current_text:
                    qa_pairs.append({
                        'speaker': current_speaker,
                        'text': ' '.join(current_text).strip()
                    })

                current_speaker = speaker_found
                current_text = [matched_text] if matched_text else []
            elif current_speaker:
                current_text.append(line)

        # Add last entry
        if current_speaker and current_text:
            qa_pairs.append({
                'speaker': current_speaker,
                'text': ' '.join(current_text).strip()
            })

        return qa_pairs

    def parse_generic_text(self, file_path: str, split_by_paragraphs: bool = True) -> List[Chapter]:
        """
        Parse generic markdown/text file without specific structure
        Useful for plain text memoirs

        Args:
            file_path: Path to file
            split_by_paragraphs: If True, split by blank lines; otherwise treat as one chapter

        Returns:
            List of Chapter objects
        """
        with open(file_path, 'r', encoding=self.config.encoding) as f:
            content = f.read()

        if not split_by_paragraphs:
            # Treat entire file as one chapter
            return [Chapter(
                title=f"Document: {file_path}",
                content=content.strip(),
                metadata={'source': file_path}
            )]

        # Split by paragraphs (double newlines)
        paragraphs = re.split(r'\n\s*\n', content)
        chapters = []

        for i, para in enumerate(paragraphs):
            para = para.strip()
            if para:
                # Use first line or first N chars as title
                title = para.split('\n')[0][:50] + "..." if len(para) > 50 else para[:50]
                chapters.append(Chapter(
                    title=f"Section {i+1}: {title}",
                    content=para,
                    metadata={'source': file_path, 'section': i+1}
                ))

        return chapters


class TextChunker:
    """Chunk text into smaller pieces for detailed retrieval"""

    def __init__(self, config: ChunkingConfig = None):
        """
        Initialize chunker with configuration

        Args:
            config: ChunkingConfig object, uses default if None
        """
        self.config = config or ChunkingConfig()

    def chunk_by_sentences(self, text: str) -> List[str]:
        """
        Chunk text by sentences with overlap

        Args:
            text: Input text

        Returns:
            List of text chunks
        """
        # Build regex pattern for sentence delimiters
        delimiters = '|'.join([re.escape(d) for d in self.config.sentence_delimiters])
        pattern = f'([{delimiters}])'

        # Split by delimiters but keep them
        sentences = re.split(pattern, text)
        sentences = [''.join(sentences[i:i+2]) for i in range(0, len(sentences)-1, 2)]
        if len(sentences) % 2 == 1:
            sentences.append(sentences[-1])

        chunks = []
        current_chunk = []
        current_length = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            sentence_len = len(sentence)

            if current_length + sentence_len > self.config.max_chars and current_chunk:
                # Save current chunk
                chunk_text = ''.join(current_chunk)
                if len(chunk_text) >= self.config.min_chunk_size:
                    chunks.append(chunk_text)

                # Start new chunk with overlap
                overlap_text = ''.join(current_chunk)[-self.config.overlap_chars:] if self.config.overlap_chars > 0 else ""
                current_chunk = [overlap_text, sentence]
                current_length = len(overlap_text) + sentence_len
            else:
                current_chunk.append(sentence)
                current_length += sentence_len

        # Add last chunk
        if current_chunk:
            chunk_text = ''.join(current_chunk)
            if len(chunk_text) >= self.config.min_chunk_size:
                chunks.append(chunk_text)

        return chunks

    def create_chunks_from_chapters(self, chapters: List[Chapter]) -> List[TextChunk]:
        """
        Create text chunks from chapters

        Args:
            chapters: List of Chapter objects

        Returns:
            List of TextChunk objects
        """
        all_chunks = []
        chunk_id = 0

        for chapter in chapters:
            if not chapter.content:
                continue

            chunks = self.chunk_by_sentences(chapter.content)

            for chunk_text in chunks:
                all_chunks.append(TextChunk(
                    text=chunk_text,
                    chapter_title=chapter.title,
                    chunk_id=chunk_id,
                    metadata={
                        'chapter': chapter.title,
                        'source': chapter.metadata.get('source') if chapter.metadata else None
                    }
                ))
                chunk_id += 1

        return all_chunks


class TwoLayerRAG:
    """
    Two-layer RAG system:
    Layer 1: Chapter-level retrieval using summaries
    Layer 2: Detailed chunk-level retrieval within relevant chapters
    """

    def __init__(self, config: RAGConfig = None):
        """
        Initialize RAG system with configuration

        Args:
            config: RAGConfig object, uses default if None
        """
        from config import DEFAULT_CONFIG
        self.config = config or DEFAULT_CONFIG

        # Initialize embedding model
        self.model = SentenceTransformer(
            self.config.embedding.model_name,
            device=self.config.embedding.device
        )

        self.chapters: List[Chapter] = []
        self.chunks: List[TextChunk] = []

        # Layer 1: Chapter summaries
        self.chapter_index: Optional[faiss.IndexFlatL2] = None
        self.chapter_embeddings: Optional[np.ndarray] = None

        # Layer 2: Detailed chunks
        self.chunk_index: Optional[faiss.IndexFlatL2] = None
        self.chunk_embeddings: Optional[np.ndarray] = None

    def add_chapters(self, chapters: List[Chapter]):
        """Add chapters to the RAG system"""
        self.chapters = chapters

    def add_chunks(self, chunks: List[TextChunk]):
        """Add text chunks to the RAG system"""
        self.chunks = chunks

    def generate_chapter_summaries(self, llm_summary_fn=None):
        """
        Generate summaries for each chapter

        Args:
            llm_summary_fn: Optional LLM function for summary generation
        """
        for chapter in self.chapters:
            if llm_summary_fn and self.config.profile.use_llm:
                chapter.summary = llm_summary_fn(chapter.content, chapter.title)
            else:
                # Simple summary: first N characters
                summary_len = self.config.profile.summary_length
                chapter.summary = f"{chapter.title}: {chapter.content[:summary_len]}..."

    def build_chapter_index(self):
        """Build FAISS index for chapter summaries (Layer 1)"""
        if not self.chapters:
            raise ValueError("No chapters added. Call add_chapters() first.")

        # Generate embeddings for chapter summaries
        summary_texts = [f"{ch.title} {ch.summary}" for ch in self.chapters]
        self.chapter_embeddings = self.model.encode(
            summary_texts,
            convert_to_numpy=True,
            batch_size=self.config.embedding.batch_size
        )

        # Build FAISS index
        dimension = self.chapter_embeddings.shape[1]
        self.chapter_index = faiss.IndexFlatL2(dimension)
        self.chapter_index.add(self.chapter_embeddings.astype('float32'))

        print(f"✓ Built chapter index with {len(self.chapters)} chapters, dimension {dimension}")

    def build_chunk_index(self):
        """Build FAISS index for text chunks (Layer 2)"""
        if not self.chunks:
            raise ValueError("No chunks added. Call add_chunks() first.")

        # Generate embeddings for chunks
        chunk_texts = [chunk.text for chunk in self.chunks]
        self.chunk_embeddings = self.model.encode(
            chunk_texts,
            convert_to_numpy=True,
            batch_size=self.config.embedding.batch_size
        )

        # Build FAISS index
        dimension = self.chunk_embeddings.shape[1]
        self.chunk_index = faiss.IndexFlatL2(dimension)
        self.chunk_index.add(self.chunk_embeddings.astype('float32'))

        print(f"✓ Built chunk index with {len(self.chunks)} chunks, dimension {dimension}")

    def search_chapters(self, query: str, top_k: int = None) -> List[Tuple[Chapter, float]]:
        """
        Search for relevant chapters (Layer 1)

        Args:
            query: Search query
            top_k: Number of results, uses config if None

        Returns:
            List of (Chapter, similarity_score) tuples
        """
        if self.chapter_index is None:
            raise ValueError("Chapter index not built. Call build_chapter_index() first.")

        if top_k is None:
            top_k = self.config.retrieval.layer1_top_k

        # Encode query
        query_embedding = self.model.encode([query], convert_to_numpy=True).astype('float32')

        # Search
        distances, indices = self.chapter_index.search(query_embedding, top_k)

        results = []
        for idx, dist in zip(indices[0], distances[0]):
            if idx < len(self.chapters):
                results.append((self.chapters[idx], float(dist)))

        return results

    def search_chunks(self, query: str, top_k: int = None,
                     chapter_filter: Optional[List[str]] = None) -> List[Tuple[TextChunk, float]]:
        """
        Search for relevant text chunks (Layer 2)

        Args:
            query: Search query
            top_k: Number of results, uses config if None
            chapter_filter: Optional list of chapter titles to restrict search

        Returns:
            List of (TextChunk, similarity_score) tuples
        """
        if self.chunk_index is None:
            raise ValueError("Chunk index not built. Call build_chunk_index() first.")

        if top_k is None:
            top_k = self.config.retrieval.layer2_top_k

        # Filter chunks by chapter if specified
        if chapter_filter:
            filtered_chunks = [c for c in self.chunks if c.chapter_title in chapter_filter]
            if not filtered_chunks:
                return []

            # Build temporary index for filtered chunks
            filtered_texts = [c.text for c in filtered_chunks]
            filtered_embeddings = self.model.encode(
                filtered_texts,
                convert_to_numpy=True,
                batch_size=self.config.embedding.batch_size
            )

            temp_index = faiss.IndexFlatL2(filtered_embeddings.shape[1])
            temp_index.add(filtered_embeddings.astype('float32'))

            # Search
            query_embedding = self.model.encode([query], convert_to_numpy=True).astype('float32')
            distances, indices = temp_index.search(query_embedding, min(top_k, len(filtered_chunks)))

            results = []
            for idx, dist in zip(indices[0], distances[0]):
                if idx < len(filtered_chunks):
                    results.append((filtered_chunks[idx], float(dist)))

            return results
        else:
            # Search all chunks
            query_embedding = self.model.encode([query], convert_to_numpy=True).astype('float32')
            distances, indices = self.chunk_index.search(query_embedding, top_k)

            results = []
            for idx, dist in zip(indices[0], distances[0]):
                if idx < len(self.chunks):
                    results.append((self.chunks[idx], float(dist)))

            return results

    def retrieve(self, query: str, top_k: int = None) -> List[Dict]:
        """
        Two-layer retrieval:
        1. Find top relevant chapters
        2. Search within those chapters for detailed chunks
        3. Return top-k results

        Args:
            query: Search query
            top_k: Number of final results

        Returns:
            List of result dictionaries
        """
        if top_k is None:
            top_k = self.config.retrieval.layer2_top_k

        # Layer 1: Find relevant chapters
        relevant_chapters = self.search_chapters(query)
        chapter_titles = [ch.title for ch, _ in relevant_chapters]

        # Layer 2: Search chunks within relevant chapters
        chunk_results = self.search_chunks(query, top_k=top_k, chapter_filter=chapter_titles)

        # Format results
        results = []
        for chunk, score in chunk_results:
            results.append({
                'text': chunk.text,
                'chapter': chunk.chapter_title,
                'similarity_score': score,
                'metadata': chunk.metadata
            })

        return results

    def save_index(self, index_dir: str = None):
        """Save FAISS indices and metadata to disk"""
        import os

        if index_dir is None:
            index_dir = self.config.output_dir

        os.makedirs(index_dir, exist_ok=True)

        # Save FAISS indices
        if self.chapter_index:
            faiss.write_index(self.chapter_index, f"{index_dir}/chapter_index.faiss")
        if self.chunk_index:
            faiss.write_index(self.chunk_index, f"{index_dir}/chunk_index.faiss")

        # Save metadata
        metadata = {
            'config': self.config.to_dict(),
            'chapters': [
                {
                    'title': ch.title,
                    'summary': ch.summary,
                    'content': ch.content,
                    'start_line': ch.start_line,
                    'end_line': ch.end_line,
                    'metadata': ch.metadata
                } for ch in self.chapters
            ],
            'chunks': [
                {
                    'text': chunk.text,
                    'chapter_title': chunk.chapter_title,
                    'chunk_id': chunk.chunk_id,
                    'metadata': chunk.metadata
                } for chunk in self.chunks
            ]
        }

        with open(f"{index_dir}/metadata.json", 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)

        print(f"✓ Saved RAG system to {index_dir}")

    def load_index(self, index_dir: str = None):
        """Load FAISS indices and metadata from disk"""
        if index_dir is None:
            index_dir = self.config.output_dir

        # Load FAISS indices
        self.chapter_index = faiss.read_index(f"{index_dir}/chapter_index.faiss")
        self.chunk_index = faiss.read_index(f"{index_dir}/chunk_index.faiss")

        # Load metadata
        with open(f"{index_dir}/metadata.json", 'r', encoding='utf-8') as f:
            metadata = json.load(f)

        self.chapters = [
            Chapter(
                title=ch['title'],
                summary=ch['summary'],
                content=ch['content'],
                start_line=ch['start_line'],
                end_line=ch['end_line'],
                metadata=ch.get('metadata')
            ) for ch in metadata['chapters']
        ]

        self.chunks = [
            TextChunk(
                text=chunk['text'],
                chapter_title=chunk['chapter_title'],
                chunk_id=chunk['chunk_id'],
                metadata=chunk.get('metadata')
            ) for chunk in metadata['chunks']
        ]

        print(f"✓ Loaded RAG system from {index_dir}")


if __name__ == "__main__":
    # Example usage
    from config import DEFAULT_CONFIG

    print("RAG Module V2 - Configurable and Flexible")
    print(f"Config: {DEFAULT_CONFIG.project_name}")
