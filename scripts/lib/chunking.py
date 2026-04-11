from __future__ import annotations

from pathlib import Path


def load_chunk_input(source_dir: Path) -> tuple[str, list[Path], str]:
    transcript_files = sorted((source_dir / "transcript").glob("*.md"))
    if transcript_files:
        texts = [path.read_text(encoding="utf-8").strip() for path in transcript_files]
        return "\n\n".join(texts), transcript_files, "transcript"

    extracted_files = sorted((source_dir / "extracted").glob("*.txt"))
    if extracted_files:
        texts = [path.read_text(encoding="utf-8").strip() for path in extracted_files]
        return "\n\n".join(texts), extracted_files, "extracted"

    raise ValueError(
        f"{source_dir}: no chunk input found. Expected transcript/*.md or extracted/*.txt"
    )


def chunk_text(text: str, chunk_size: int = 1200, chunk_unit: str = "chars") -> list[str]:
    normalized = text.strip()
    if not normalized:
        return []

    if chunk_unit == "paragraphs":
        paragraphs = [part.strip() for part in normalized.split("\n\n") if part.strip()]
        chunks: list[str] = []
        current: list[str] = []
        current_len = 0
        for paragraph in paragraphs:
            next_len = current_len + len(paragraph)
            if current and next_len > chunk_size:
                chunks.append("\n\n".join(current))
                current = [paragraph]
                current_len = len(paragraph)
            else:
                current.append(paragraph)
                current_len = next_len
        if current:
            chunks.append("\n\n".join(current))
        return chunks

    if chunk_unit == "chars":
        return [
            normalized[index : index + chunk_size].strip()
            for index in range(0, len(normalized), chunk_size)
            if normalized[index : index + chunk_size].strip()
        ]

    raise ValueError(f"unsupported chunk_unit: {chunk_unit}")


def write_chunks(source_dir: Path, chunks: list[str]) -> list[Path]:
    chunks_dir = source_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for idx, chunk in enumerate(chunks, start=1):
        path = chunks_dir / f"{idx:04d}.md"
        path.write_text(chunk + "\n", encoding="utf-8")
        written.append(path)
    return written
