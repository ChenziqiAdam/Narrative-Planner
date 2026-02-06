"""
Build RAG System for User Simulator (Refactored Version)
Flexible script to process any markdown memoir files
"""

import os
import sys
import argparse
from typing import Optional
from config import RAGConfig, DEFAULT_CONFIG
from rag_module import MarkdownParser, TextChunker, TwoLayerRAG
from character_profile import CharacterProfileGenerator


def build_rag_system(config: RAGConfig) -> tuple:
    """
    Build complete RAG system from memoir files

    Args:
        config: RAGConfig object with all settings

    Returns:
        Tuple of (rag, profile)
    """
    print("=" * 60)
    print(f"Building RAG System: {config.project_name}")
    print("=" * 60)

    # Step 1: Initialize parser
    print("\n[Step 1] Initializing parser...")
    parser = MarkdownParser(config.markdown)
    print("✓ Parser initialized")

    # Step 2: Parse structured memoir
    print("\n[Step 2] Parsing structured memoir...")
    if not os.path.exists(config.structured_memoir_path):
        print(f"✗ Error: File not found - {config.structured_memoir_path}")
        sys.exit(1)

    chapters = parser.parse_structured_memoir(config.structured_memoir_path)
    print(f"✓ Extracted {len(chapters)} chapters")

    # Print chapter titles
    if chapters:
        print("\nChapters found:")
        for i, chapter in enumerate(chapters[:10], 1):  # Show first 10
            print(f"  {i}. {chapter.title} ({len(chapter.content)} chars)")
        if len(chapters) > 10:
            print(f"  ... and {len(chapters) - 10} more")

    # Step 3: Parse interview transcript (optional)
    qa_pairs = []
    if config.interview_transcript_path and os.path.exists(config.interview_transcript_path):
        print("\n[Step 3] Parsing interview transcript...")
        qa_pairs = parser.parse_interview_transcript(config.interview_transcript_path)
        print(f"✓ Extracted {len(qa_pairs)} Q&A pairs")
    else:
        print("\n[Step 3] Skipping interview transcript (not provided)")

    # Step 4: Generate chapter summaries
    print("\n[Step 4] Generating chapter summaries...")
    for chapter in chapters:
        if chapter.content:
            summary_len = config.profile.summary_length
            chapter.summary = f"{chapter.content[:summary_len]}..."
        else:
            chapter.summary = chapter.title
    print(f"✓ Generated summaries for {len(chapters)} chapters")

    # Step 5: Create text chunks
    print("\n[Step 5] Creating text chunks...")
    chunker = TextChunker(config.chunking)
    chunks = chunker.create_chunks_from_chapters(chapters)
    print(f"✓ Created {len(chunks)} text chunks")

    # Step 6: Initialize RAG system
    print("\n[Step 6] Initializing RAG system...")
    print(f"Loading embedding model: {config.embedding.model_name}")
    print("(This may take a while on first run...)")
    rag = TwoLayerRAG(config)
    print("✓ Embedding model loaded")

    # Add chapters and chunks
    rag.add_chapters(chapters)
    rag.add_chunks(chunks)
    print("✓ Added chapters and chunks to RAG system")

    # Step 7: Build FAISS indices
    print("\n[Step 7] Building FAISS indices...")
    print("Building chapter index (Layer 1)...")
    rag.build_chapter_index()

    print("Building chunk index (Layer 2)...")
    rag.build_chunk_index()

    # Step 8: Save indices
    print(f"\n[Step 8] Saving indices to {config.output_dir}...")
    rag.save_index()

    # Step 9: Generate character profile
    print("\n[Step 9] Generating character profile...")
    profile_generator = CharacterProfileGenerator()
    profile = profile_generator.generate_profile(chapters, qa_pairs)

    # Update profile with config character info
    profile['basic_info'].update(config.character_info)

    profile_path = os.path.join(config.output_dir, "character_profile.json")
    profile_generator.save_profile(profile, profile_path)
    print(f"✓ Character profile saved to {profile_path}")

    # Step 10: Generate system prompt
    print("\n[Step 10] Generating system prompt for User Simulator...")
    system_prompt = profile_generator.generate_system_prompt(profile)
    prompt_path = os.path.join(config.output_dir, "system_prompt.txt")
    with open(prompt_path, 'w', encoding='utf-8') as f:
        f.write(system_prompt)
    print(f"✓ System prompt saved to {prompt_path}")

    # Step 11: Save configuration
    print("\n[Step 11] Saving configuration...")
    config_path = os.path.join(config.output_dir, "config.json")
    config.save(config_path)
    print(f"✓ Configuration saved to {config_path}")

    # Step 12: Test retrieval
    print("\n[Step 12] Testing retrieval...")
    if chapters:
        # Generate test queries based on first few chapter titles
        test_queries = [
            chapters[0].title if len(chapters) > 0 else "测试查询",
        ]

        # Add more specific queries if we have content
        if len(chapters) > 1:
            test_queries.append(f"关于{chapters[1].title}")

        for query in test_queries[:2]:  # Test first 2 queries
            print(f"\n测试查询: {query}")
            try:
                results = rag.retrieve(query, top_k=2)
                print(f"返回 {len(results)} 条结果:")
                for i, result in enumerate(results, 1):
                    text_preview = result['text'][:80].replace('\n', ' ')
                    print(f"  {i}. [{result['chapter']}] {text_preview}...")
                    print(f"     相似度分数: {result['similarity_score']:.4f}")
            except Exception as e:
                print(f"  ✗ Retrieval test failed: {e}")

    print("\n" + "=" * 60)
    print("RAG System Built Successfully!")
    print("=" * 60)
    print(f"\nProject: {config.project_name}")
    print(f"Output directory: {config.output_dir}")
    print(f"\nFiles created:")
    print(f"  - chapter_index.faiss")
    print(f"  - chunk_index.faiss")
    print(f"  - metadata.json")
    print(f"  - character_profile.json")
    print(f"  - system_prompt.txt")
    print(f"  - config.json")

    print(f"\nStatistics:")
    print(f"  Chapters: {len(chapters)}")
    print(f"  Chunks: {len(chunks)}")
    print(f"  Q&A pairs: {len(qa_pairs)}")

    return rag, profile


def main():
    """Main entry point with command line arguments"""
    parser = argparse.ArgumentParser(
        description="Build RAG system for memoir interview simulation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Use default configuration (Chinese memoir)
  python build_rag.py

  # Specify custom memoir file
  python build_rag.py --memoir my_memoir.md --output ./my_rag_data

  # Full customization
  python build_rag.py \\
    --memoir memoir.md \\
    --transcript interview.md \\
    --output ./output \\
    --project "My Memoir" \\
    --chunk-size 600 \\
    --overlap 100 \\
    --name "John Doe"
        """
    )

    parser.add_argument(
        '--memoir',
        type=str,
        default=None,
        help='Path to structured memoir markdown file'
    )

    parser.add_argument(
        '--transcript',
        type=str,
        default=None,
        help='Path to interview transcript markdown file (optional)'
    )

    parser.add_argument(
        '--output',
        type=str,
        default=None,
        help='Output directory for RAG data'
    )

    parser.add_argument(
        '--project',
        type=str,
        default=None,
        help='Project name'
    )

    parser.add_argument(
        '--chunk-size',
        type=int,
        default=500,
        help='Maximum characters per chunk (default: 500)'
    )

    parser.add_argument(
        '--overlap',
        type=int,
        default=50,
        help='Overlap characters between chunks (default: 50)'
    )

    parser.add_argument(
        '--name',
        type=str,
        default=None,
        help='Character name for profile'
    )

    parser.add_argument(
        '--config',
        type=str,
        default=None,
        help='Path to config JSON file (overrides other arguments)'
    )

    args = parser.parse_args()

    # Load or create configuration
    if args.config and os.path.exists(args.config):
        print(f"Loading configuration from {args.config}")
        config = RAGConfig.load(args.config)
    else:
        # Start with default config
        config = DEFAULT_CONFIG

        # Override with command line arguments
        if args.memoir:
            config.structured_memoir_path = args.memoir
        if args.transcript:
            config.interview_transcript_path = args.transcript
        if args.output:
            config.output_dir = args.output
        if args.project:
            config.project_name = args.project
        if args.chunk_size != 500:
            config.chunking.max_chars = args.chunk_size
        if args.overlap != 50:
            config.chunking.overlap_chars = args.overlap
        if args.name:
            config.character_info['name'] = args.name

    # Validate paths
    if not os.path.exists(config.structured_memoir_path):
        print(f"Error: Memoir file not found - {config.structured_memoir_path}")
        print("\nUsage: python build_rag.py --memoir <path_to_memoir.md>")
        sys.exit(1)

    # Build RAG system
    try:
        rag, profile = build_rag_system(config)
        print("\n✓ All done! RAG system is ready for use.")

    except Exception as e:
        print(f"\n✗ Error building RAG system: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
