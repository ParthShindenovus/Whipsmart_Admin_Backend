import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from django.conf import settings
import logging

logger = logging.getLogger(__name__)


def _get_docs_base_dir() -> Path:
    """
    Return the base docs directory (project_root/docs).
    """
    base_dir = getattr(settings, "BASE_DIR", Path.cwd())
    return Path(base_dir) / "docs"


def _get_env_folder() -> str:
    """
    Return environment folder name based on DEBUG.
    """
    return "development" if getattr(settings, "DEBUG", False) else "production"


def get_pdf_path(filename: str) -> Path:
    """
    Resolve a PDF filename within the docs directory.
    """
    docs_dir = _get_docs_base_dir()
    pdf_path = docs_dir / filename
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found at path: {pdf_path}")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError("Only PDF files are supported for this endpoint.")
    return pdf_path


def extract_pdf_structure(pdf_path: Path) -> Dict[str, Any]:
    """
    Extract a structured representation from a PDF: file name, pages,
    headings (heuristic), paragraphs, and tables.
    Uses pdfplumber when available; falls back to PyPDF2 for plain text.
    """
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        logger.warning(
            "pdfplumber is not installed. Falling back to basic PyPDF2 text extraction. "
            "Install pdfplumber for better layout and table handling."
        )
        from knowledgebase.services.document_processor import extract_text_from_file

        text = extract_text_from_file(pdf_path, "pdf")
        # Simple fallback: one "page" with raw text
        return {
            "file_name": pdf_path.name,
            "pages": [
                {
                    "page_number": 1,
                    "headings": [],
                    "paragraphs": [p.strip() for p in text.split("\n\n") if p.strip()],
                    "tables": [],
                }
            ],
        }

    pages: List[Dict[str, Any]] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        for idx, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as e:  # pragma: no cover - very defensive
                logger.error(f"Error extracting text from page {idx} of {pdf_path}: {e}")
                text = ""

            # Extract lines and merge single-word lines (common PDF extraction issue)
            raw_lines = text.splitlines()
            merged_lines = []
            i = 0
            while i < len(raw_lines):
                line = raw_lines[i].strip()
                if not line:
                    merged_lines.append("")
                    i += 1
                    continue
                
                # Check if this is a single word/short fragment
                words = line.split()
                is_single_word = len(words) <= 2 and len(line) < 50
                
                # If single word, try to merge with next lines
                if is_single_word and i + 1 < len(raw_lines):
                    merged_parts = [line]
                    j = i + 1
                    # Merge consecutive single-word lines
                    while j < len(raw_lines):
                        next_line = raw_lines[j].strip()
                        if not next_line:
                            break
                        next_words = next_line.split()
                        next_is_single = len(next_words) <= 2 and len(next_line) < 50
                        if next_is_single:
                            merged_parts.append(next_line)
                            j += 1
                        else:
                            break
                    # Join merged parts
                    merged_line = " ".join(merged_parts)
                    merged_lines.append(merged_line)
                    i = j
                else:
                    merged_lines.append(line)
                    i += 1
            
            # Filter out empty lines but keep structure
            lines = [ln for ln in merged_lines if ln.strip()]

            # Improved heading detection: 
            # - Questions (ending with ?)
            # - Short lines (<= 100 chars)
            # - Title case or ALL CAPS
            # - Not ending with period (unless it's a question)
            # - Standalone lines (not part of paragraphs)
            headings: List[str] = []
            body_lines: List[str] = []
            
            for i, ln in enumerate(lines):
                ln_stripped = ln.strip()
                if not ln_stripped:
                    continue
                
                # Check if it's a question
                is_question = ln_stripped.endswith("?")
                
                # Check length
                is_short = len(ln_stripped) <= 100
                
                # Check if it's title case or mostly uppercase
                alpha = "".join(ch for ch in ln_stripped if ch.isalpha())
                if alpha:
                    upper_count = sum(1 for ch in alpha if ch.isupper())
                    upper_ratio = upper_count / len(alpha)
                    title_case = ln_stripped[0].isupper() if ln_stripped else False
                else:
                    upper_ratio = 0.0
                    title_case = False
                
                # Check if it doesn't end with period (unless it's a question)
                no_period_end = not ln_stripped.endswith(".") or is_question
                
                # Check if next line starts with lowercase (suggests it's a heading)
                next_is_body = False
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if next_line and next_line[0].islower():
                        next_is_body = True
                
                # Determine if it looks like a heading
                looks_like_heading = (
                    is_question or  # Questions are always headings
                    (is_short and no_period_end and (upper_ratio >= 0.5 or title_case)) or
                    (is_short and next_is_body and title_case)
                )
                
                if looks_like_heading:
                    headings.append(ln_stripped)
                else:
                    body_lines.append(ln)

            # Paragraph detection: merge body lines separated by blank lines
            # Handle case where PDF has each word on a separate line
            paragraphs: List[str] = []
            current_para: List[str] = []
            
            for i, ln in enumerate(body_lines):
                ln_cleaned = ln.strip()
                
                # Skip empty lines
                if not ln_cleaned:
                    if current_para:
                        # Join current paragraph and clean up
                        para_text = " ".join(current_para).strip()
                        para_text = " ".join(para_text.split())  # Normalize spaces
                        if para_text and len(para_text) > 2:  # Only add meaningful paragraphs
                            paragraphs.append(para_text)
                        current_para = []
                    continue
                
                # Clean up the line: remove excessive spaces
                ln_cleaned = " ".join(ln_cleaned.split())
                
                # Check if this is likely a single word/short fragment (common in PDF extraction)
                is_single_word = len(ln_cleaned.split()) <= 2 and len(ln_cleaned) < 50
                
                # Check if next line is also a single word (indicates word-by-word extraction)
                next_is_single_word = False
                if i + 1 < len(body_lines):
                    next_line = body_lines[i + 1].strip()
                    if next_line:
                        next_cleaned = " ".join(next_line.split())
                        next_is_single_word = len(next_cleaned.split()) <= 2 and len(next_cleaned) < 50
                
                # If current and next are single words, merge them into paragraph
                # Also merge if current line doesn't end with punctuation and next line doesn't start with capital
                should_merge = False
                if is_single_word:
                    # Always merge single words
                    should_merge = True
                elif current_para:
                    # Check if we should continue the paragraph
                    # Don't break if line doesn't end with sentence-ending punctuation
                    last_char = ln_cleaned[-1] if ln_cleaned else ""
                    if last_char not in ('.', '!', '?', ':'):
                        should_merge = True
                    # Also merge if next line starts with lowercase (continuation)
                    if next_is_single_word or (i + 1 < len(body_lines) and body_lines[i + 1].strip() and body_lines[i + 1].strip()[0].islower()):
                        should_merge = True
                
                if should_merge:
                    current_para.append(ln_cleaned)
                else:
                    # Save current paragraph if exists
                    if current_para:
                        para_text = " ".join(current_para).strip()
                        para_text = " ".join(para_text.split())
                        if para_text and len(para_text) > 2:
                            paragraphs.append(para_text)
                    # Start new paragraph
                    current_para = [ln_cleaned]
            
            # Save final paragraph
            if current_para:
                para_text = " ".join(current_para).strip()
                para_text = " ".join(para_text.split())
                if para_text and len(para_text) > 2:
                    paragraphs.append(para_text)

            # Table extraction
            tables_data: List[List[List[str]]] = []
            try:
                raw_tables = page.extract_tables() or []
                for tbl in raw_tables:
                    # Normalize to strings and strip spaces
                    norm_rows = [
                        [str(cell).strip() if cell is not None else "" for cell in row]
                        for row in tbl
                    ]
                    tables_data.append(norm_rows)
            except Exception as e:  # pragma: no cover - very defensive
                logger.error(f"Error extracting tables from page {idx} of {pdf_path}: {e}")

            pages.append(
                {
                    "page_number": idx,
                    "headings": headings,
                    "paragraphs": paragraphs,
                    "tables": tables_data,
                }
            )

    return {
        "file_name": pdf_path.name,
        "pages": pages,
    }


def _get_llm_client():
    """
    Get OpenAI/Azure OpenAI client for LLM operations.
    Returns (client, model_name) or (None, None) if not configured.
    """
    try:
        from openai import AzureOpenAI, OpenAI
        import os
        
        # Try Azure OpenAI first
        azure_key = getattr(settings, 'AZURE_OPENAI_API_KEY', None)
        azure_endpoint = getattr(settings, 'AZURE_OPENAI_ENDPOINT', None)
        azure_api_version = getattr(settings, 'AZURE_OPENAI_API_VERSION', '2024-02-15-preview')
        azure_deployment = getattr(settings, 'AZURE_OPENAI_DEPLOYMENT_NAME', 'gpt-4o')
        
        if azure_key and azure_endpoint:
            try:
                client = AzureOpenAI(
                    api_key=azure_key,
                    azure_endpoint=azure_endpoint,
                    api_version=azure_api_version
                )
                logger.info(f"Using Azure OpenAI for LLM structuring: {azure_deployment}")
                return client, azure_deployment
            except Exception as e:
                logger.warning(f"Failed to initialize Azure OpenAI: {e}")
        
        # Fallback to OpenAI
        openai_key = getattr(settings, 'OPENAI_API_KEY', None) or os.getenv('OPENAI_API_KEY')
        if openai_key:
            try:
                client = OpenAI(api_key=openai_key)
                model = 'gpt-4o-mini'  # Use cost-effective model for structuring
                logger.info("Using OpenAI for LLM structuring")
                return client, model
            except Exception as e:
                logger.warning(f"Failed to initialize OpenAI: {e}")
        
        logger.warning("No LLM service available for structuring. Will use basic formatting.")
        return None, None
    except ImportError:
        logger.warning("OpenAI library not available. Will use basic formatting.")
        return None, None


def chunk_text_by_context_window(text: str, max_chunk_size: int = 4000, overlap: int = 200) -> List[str]:
    """
    Chunk text into LLM context window-friendly sizes.
    Respects sentence boundaries and includes overlap for continuity.
    
    Args:
        text: Text to chunk
        max_chunk_size: Maximum characters per chunk (default: 4000 for LLM context)
        overlap: Characters to overlap between chunks (default: 200)
        
    Returns:
        List of text chunks
    """
    if not text or len(text.strip()) == 0:
        return []
    
    if len(text) <= max_chunk_size:
        return [text]
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + max_chunk_size
        
        if end >= len(text):
            # Last chunk
            chunks.append(text[start:].strip())
            break
        
        # Try to break at sentence boundary
        # Look for sentence endings within the last 500 chars
        lookback = min(500, max_chunk_size // 4)
        chunk_text = text[start:end]
        
        # Find last sentence ending
        last_period = chunk_text.rfind('. ')
        last_exclamation = chunk_text.rfind('! ')
        last_question = chunk_text.rfind('? ')
        last_newline = chunk_text.rfind('\n\n')
        
        # Use the latest sentence boundary found
        break_point = max(last_period, last_exclamation, last_question, last_newline)
        
        if break_point > max_chunk_size - lookback:
            # Good break point found
            end = start + break_point + 1
            chunks.append(text[start:end].strip())
            start = end - overlap  # Overlap for continuity
        else:
            # No good break point, break at word boundary
            last_space = chunk_text.rfind(' ')
            if last_space > max_chunk_size - lookback:
                end = start + last_space
                chunks.append(text[start:end].strip())
                start = end - overlap
            else:
                # Force break
                chunks.append(chunk_text.strip())
                start = end - overlap
    
    return [chunk for chunk in chunks if chunk.strip()]


def chunk_by_sections(structure: Dict[str, Any], max_chunk_size: int = 3000) -> List[Dict[str, Any]]:
    """
    Chunk PDF structure by sections/headings to avoid token limits.
    Groups pages by headings and creates chunks that respect section boundaries.
    
    Args:
        structure: Structured PDF data with pages
        max_chunk_size: Maximum characters per chunk (default: 3000)
        
    Returns:
        List of chunk dictionaries, each containing:
        - pages: List of page numbers in this chunk
        - headings: List of headings in this chunk
        - text: Combined text content
        - start_page: First page number
        - end_page: Last page number
    """
    chunks = []
    current_chunk = {
        "pages": [],
        "headings": [],
        "text": [],
        "start_page": None,
        "end_page": None
    }
    current_size = 0
    
    for page in structure.get("pages", []):
        page_num = page.get("page_number", 0)
        headings = page.get("headings", [])
        paragraphs = page.get("paragraphs", [])
        tables = page.get("tables", [])
        
        # Build text for this page
        page_text_parts = []
        if headings:
            page_text_parts.extend([f"## {h}" for h in headings])
        if paragraphs:
            page_text_parts.extend(paragraphs)
        if tables:
            for table in tables:
                table_text = "\n".join([" | ".join(row) for row in table])
                page_text_parts.append(f"Table:\n{table_text}")
        
        page_text = "\n\n".join(page_text_parts)
        page_size = len(page_text)
        
        # Check if adding this page would exceed max_chunk_size
        # If so, start a new chunk (unless current chunk is empty)
        if current_size > 0 and current_size + page_size > max_chunk_size:
            # Save current chunk
            current_chunk["text"] = "\n\n".join(current_chunk["text"])
            current_chunk["end_page"] = current_chunk["pages"][-1] if current_chunk["pages"] else None
            chunks.append(current_chunk)
            
            # Start new chunk
            current_chunk = {
                "pages": [page_num],
                "headings": headings.copy(),
                "text": [page_text],
                "start_page": page_num,
                "end_page": page_num
            }
            current_size = page_size
        else:
            # Add to current chunk
            if current_chunk["start_page"] is None:
                current_chunk["start_page"] = page_num
            current_chunk["pages"].append(page_num)
            current_chunk["end_page"] = page_num
            current_chunk["headings"].extend(headings)
            current_chunk["text"].append(page_text)
            current_size += page_size
    
    # Add final chunk
    if current_chunk["text"]:
        current_chunk["text"] = "\n\n".join(current_chunk["text"])
        chunks.append(current_chunk)
    
    logger.info(f"Chunked document into {len(chunks)} sections")
    return chunks


def structure_text_with_llm(raw_text: str, file_name: str, qa_format: bool = True, structure: Optional[Dict[str, Any]] = None, user_filename: Optional[str] = None, reference_url: Optional[str] = None) -> str:
    """
    Use LLM to structure and format extracted PDF text into a well-organized document.
    Can output in Q&A format (for RAG) or structured document format.
    
    Args:
        raw_text: Raw extracted text from PDF
        file_name: Name of the PDF file (uploaded filename)
        qa_format: If True, convert to Q&A format for RAG pipeline (default: True)
        structure: Optional structured PDF data with page information for metadata
        user_filename: User-provided filename for metadata (optional)
        reference_url: User-provided reference URL for metadata (optional)
        
    Returns:
        Structured and formatted text document in Q&A format or structured format
    """
    client, model = _get_llm_client()
    
    if not client or not model:
        # Fallback to basic formatting if LLM not available
        logger.warning("LLM not available, using basic formatting")
        return raw_text
    
    try:
        if qa_format:
            # Use user-provided filename and reference_url if provided
            metadata_filename = user_filename if user_filename else file_name
            metadata_reference_url = reference_url if reference_url else "N/A"
            
            # If structure is provided, chunk by sections to avoid token limits
            if structure and 'pages' in structure:
                chunks = chunk_by_sections(structure, max_chunk_size=3000)
                all_qa_pairs = []
                qa_counter = 1
                
                for chunk_idx, chunk in enumerate(chunks):
                    chunk_text = chunk["text"]
                    chunk_pages = chunk["pages"]
                    chunk_headings = chunk["headings"]
                    start_page = chunk["start_page"]
                    end_page = chunk["end_page"]
                    
                    logger.info(f"Processing chunk {chunk_idx + 1}/{len(chunks)} (pages {start_page}-{end_page})")
                    
                    # Process this chunk with LLM
                    chunk_qa = _process_chunk_with_llm(
                        chunk_text=chunk_text,
                        chunk_pages=chunk_pages,
                        chunk_headings=chunk_headings,
                        start_page=start_page,
                        end_page=end_page,
                        file_name=file_name,
                        metadata_filename=metadata_filename,
                        metadata_reference_url=metadata_reference_url,
                        qa_counter_start=qa_counter,
                        client=client,
                        model=model
                    )
                    
                    # Extract Q&A pairs and update counter
                    logger.info(f"LLM response length: {len(chunk_qa)} characters")
                    logger.debug(f"LLM response preview: {chunk_qa[:500]}")
                    qa_pairs = _extract_qa_pairs_from_response(chunk_qa, qa_counter)
                    logger.info(f"Extracted {len(qa_pairs)} Q&A pairs from chunk {chunk_idx + 1}")
                    
                    # If extraction failed or returned empty, use raw response
                    if not qa_pairs or all(not pair.strip() or len(pair.strip()) < 50 for pair in qa_pairs):
                        logger.warning(f"No valid Q&A pairs extracted from chunk {chunk_idx + 1}, using raw response")
                        # Add raw response as a single Q&A pair
                        if chunk_qa.strip():
                            raw_qa = f"===Q&A-{qa_counter:03d}===\n{chunk_qa.strip()}"
                            all_qa_pairs.append(raw_qa)
                            qa_counter += 1
                    else:
                        if qa_pairs:
                            logger.debug(f"First Q&A pair preview: {qa_pairs[0][:200]}")
                        all_qa_pairs.extend(qa_pairs)
                        qa_counter += len(qa_pairs)
                
                # Combine all Q&A pairs into final document
                final_text = "\n\n".join(all_qa_pairs)
                logger.info(f"Successfully structured text using LLM (chunked processing) for file: {file_name}")
                return final_text
            else:
                # Fallback to single processing if no structure provided
                return _process_single_chunk_with_llm(
                    raw_text=raw_text,
                    file_name=file_name,
                    metadata_filename=metadata_filename,
                    metadata_reference_url=metadata_reference_url,
                    client=client,
                    model=model
                )

        else:
            # Structured document format (non-Q&A)
            return _process_single_chunk_with_llm(
                raw_text=raw_text,
                file_name=file_name,
                metadata_filename=None,
                metadata_reference_url=None,
                client=client,
                model=model,
                qa_format=False
            )
        
    except Exception as e:
        logger.error(f"Error structuring text with LLM: {e}", exc_info=True)
        # Fallback to basic formatting
        return raw_text


def _process_chunk_with_llm(
    chunk_text: str,
    chunk_pages: List[int],
    chunk_headings: List[str],
    start_page: int,
    end_page: int,
    file_name: str,
    metadata_filename: str,
    metadata_reference_url: str,
    qa_counter_start: int,
    client,
    model: str
) -> str:
    """Process a single chunk with LLM and return Q&A pairs."""
    system_prompt = """You are an expert at converting document content into structured question-answer format for RAG (Retrieval-Augmented Generation) systems. Your task is to transform all content into labeled Q&A pairs with comprehensive metadata.

CRITICAL REQUIREMENTS:
1. Extract ALL information from the provided chunk and convert it into Q&A pairs
2. For every heading, section, or topic, create explicit questions
3. Convert implicit questions from headings (e.g., "How Does Novated Leasing Work?" becomes a question)
4. Create multiple questions from a single section if it contains multiple pieces of information
5. Format each Q&A pair with structured metadata in this EXACT format:

=== Q&A-[ID] ===
Q: [Question text]
A: [Answer text - include all relevant details, examples, numbers, tables, etc.]
METADATA:
- page: [page number from chunk pages, or range like "2-3"]
- filename: [User-provided filename]
- title: [Document title or main heading]
- section: [Section name or heading where this Q&A appears]
- description: [Brief description of the topic/context, 1-2 sentences]
- reference_url: [User-provided reference URL or "N/A"]
---

6. Preserve ALL information:
   - Numbers, percentages, dates, amounts
   - Tables (convert to readable format within answers)
   - Lists and bullet points
   - Contact information
   - URLs and links
   - All factual details

7. Create questions for:
   - Explicit questions found in the document
   - Headings (convert to "What is...", "How does...", "What are...", etc.)
   - Sections (create questions about the content)
   - Procedures and processes
   - Definitions and explanations
   - Features and benefits
   - Requirements and conditions
   - Options and choices

8. Make questions natural and searchable (as users would ask them)
9. Make answers comprehensive and self-contained (include all context needed)
10. Use section headings for the "section" metadata field
11. Create meaningful descriptions that summarize the Q&A context

Format: Use the exact structure shown above with === separators and METADATA section for each Q&A pair. Process ALL content in this chunk."""

    page_range = f"{start_page}-{end_page}" if start_page != end_page else str(start_page)
    section_info = ", ".join(chunk_headings[:5]) if chunk_headings else "General"
    
    user_prompt = f"""Convert the following document chunk (pages {page_range}) from PDF file "{file_name}" into structured Q&A format. Extract ALL information and create as many Q&A pairs as needed.

IMPORTANT:
- This is chunk of the document
- Start labeling Q&A pairs from Q&A-{qa_counter_start:03d}
- Use the EXACT format: === Q&A-[ID] === followed by Q:, A:, and METADATA: sections
- Create questions for EVERY section, heading, and piece of information
- Use page range "{page_range}" in metadata (or specific page if known)
- Use "{metadata_filename}" as the filename in all metadata sections
- Use "{metadata_reference_url}" as the reference_url in all metadata sections
- Section headings in this chunk: {section_info}
- Make answers comprehensive and include all details
- Process ALL content - do not skip anything

Document chunk (pages {page_range}):
{chunk_text}

Please provide the complete structured Q&A formatted output for this chunk with all information converted into labeled question-answer pairs."""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.3,
        max_tokens=8000  # Increased for comprehensive Q&A format
    )
    
    return response.choices[0].message.content


def _process_single_chunk_with_llm(
    raw_text: str,
    file_name: str,
    metadata_filename: Optional[str],
    metadata_reference_url: Optional[str],
    client,
    model: str,
    qa_format: bool = True
) -> str:
    """Process entire document as single chunk (fallback for non-chunked processing)."""
    if qa_format:
        system_prompt = """You are an expert at converting document content into structured question-answer format for RAG (Retrieval-Augmented Generation) systems. Your task is to transform all content into labeled Q&A pairs with comprehensive metadata.

CRITICAL REQUIREMENTS:
1. Extract ALL information from the document and convert it into Q&A pairs
2. Format each Q&A pair with structured metadata in this EXACT format:

=== Q&A-[ID] ===
Q: [Question text]
A: [Answer text - include all relevant details, examples, numbers, tables, etc.]
METADATA:
- page: [page number where this content appears, or "N/A" if unknown]
- filename: [User-provided filename or PDF filename]
- title: [Document title or main heading]
- section: [Section name or heading where this Q&A appears]
- description: [Brief description of the topic/context, 1-2 sentences]
- reference_url: [User-provided reference URL or "N/A"]
---

Format: Use the exact structure shown above with === separators and METADATA section for each Q&A pair."""

        metadata_filename_val = metadata_filename if metadata_filename else file_name
        metadata_reference_url_val = metadata_reference_url if metadata_reference_url else "N/A"
        
        user_prompt = f"""Convert the following extracted text from PDF file "{file_name}" into a comprehensive structured Q&A format suitable for RAG pipeline with metadata. Extract ALL information and create as many Q&A pairs as needed.

IMPORTANT:
- Use the EXACT format: === Q&A-[ID] === followed by Q:, A:, and METADATA: sections
- Label each Q&A pair sequentially: Q&A-001, Q&A-002, etc.
- Use "{metadata_filename_val}" as the filename in all metadata sections
- Use "{metadata_reference_url_val}" as the reference_url in all metadata sections
- Process ALL content - do not skip anything

Extracted text:
{raw_text}

Please provide the complete structured Q&A formatted document with all information converted into labeled question-answer pairs with comprehensive metadata."""
    else:
        # Structured document format
        system_prompt = """You are a document structuring expert. Your task is to take raw extracted text from a PDF and structure it into a well-organized, readable document with proper chunk-wise formatting.

Requirements:
1. Start with a clear document title/header including the file name
2. Identify and properly format all headings, subheadings, and questions
3. Organize content into logical sections and subsections (chunks)
4. Preserve all important information including:
   - Questions and their answers (mark questions clearly with "Q:" or as section headings)
   - Headings and subheadings (use proper hierarchy: # for main headings, ## for subsections)
   - Paragraphs with proper formatting
   - Tables (format them clearly with proper alignment)
   - Page numbers (if mentioned in the text)
   - File name (at the top)
5. Create a clear hierarchical structure with proper formatting:
   - Use markdown-style headings (# for main sections, ## for subsections)
   - Separate major sections with clear dividers (---)
   - Each logical chunk should be a self-contained section
6. Ensure questions are clearly marked and their answers follow immediately
7. Group related content together into logical chunks
8. Make the document easy to read and navigate
9. Preserve all factual information accurately
10. Format tables clearly with proper column alignment
11. Use consistent formatting throughout

Format the output as a clean, structured text document with clear chunk boundaries."""

        user_prompt = f"""Please structure the following extracted text from PDF file "{file_name}" into a well-organized document with proper headings, sections, chunk-wise formatting, and clear structure:

{raw_text}

Please provide the structured document with:
- Clear document title/header at the top (include file name)
- Properly formatted headings and subheadings (use # for main headings, ## for subsections)
- Questions clearly identified (mark with "Q:" or as section headings)
- Well-organized sections/chunks (each major topic should be a separate chunk)
- Clear separators between major sections (use ---)
- Tables formatted clearly
- All content preserved accurately
- Logical chunk-wise organization for easy reading and processing"""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.3,
        max_tokens=16000
    )
    
    return response.choices[0].message.content


def _renumber_qa_pairs(text: str, start_number: int) -> Tuple[str, int]:
    """
    Renumber Q&A pairs in text sequentially and return count.
    
    Args:
        text: Text containing Q&A pairs
        start_number: Starting Q&A number
        
    Returns:
        Tuple of (renumbered_text, count_of_qa_pairs)
    """
    import re
    
    # Extract all Q&A blocks with their content
    pattern = r'===+\s*Q&A-(\d+)\s*===+([\s\S]*?)(?===+\s*Q&A-|$)'
    matches = list(re.finditer(pattern, text))
    
    if not matches:
        return text, 0
    
    # Extract Q&A pairs and sort by original number
    qa_pairs = []
    for match in matches:
        original_num = int(match.group(1))
        content = match.group(2).strip()
        qa_pairs.append((original_num, content))
    
    # Sort by original number (ascending)
    qa_pairs.sort(key=lambda x: x[0])
    
    # Renumber sequentially
    current_number = start_number
    renumbered_pairs = []
    for _, content in qa_pairs:
        new_id = f"Q&A-{current_number:03d}"
        renumbered_pairs.append(f"==={new_id}===\n{content}")
        current_number += 1
    
    result_text = "\n\n".join(renumbered_pairs)
    return result_text, len(qa_pairs)


def _sort_and_renumber_all_qa_pairs(text: str) -> Tuple[str, int]:
    """
    Extract all Q&A pairs from combined text, sort them by number, and renumber sequentially.
    
    Args:
        text: Combined text with Q&A pairs
        
    Returns:
        Tuple of (sorted_and_renumbered_text, total_count)
    """
    import re
    
    # Extract all Q&A blocks
    pattern = r'===+\s*Q&A-(\d+)\s*===+([\s\S]*?)(?===+\s*Q&A-|$)'
    matches = list(re.finditer(pattern, text))
    
    if not matches:
        return text, 0
    
    # Extract Q&A pairs with their original numbers
    qa_pairs = []
    for match in matches:
        original_num = int(match.group(1))
        content = match.group(2).strip()
        qa_pairs.append((original_num, content))
    
    # Sort by original number (ascending)
    qa_pairs.sort(key=lambda x: x[0])
    
    # Renumber sequentially starting from 1
    renumbered_pairs = []
    for idx, (_, content) in enumerate(qa_pairs, start=1):
        new_id = f"Q&A-{idx:03d}"
        renumbered_pairs.append(f"==={new_id}===\n{content}")
    
    result_text = "\n\n".join(renumbered_pairs)
    return result_text, len(qa_pairs)


def _process_text_chunk_with_llm(
    text_chunk: str,
    chunk_index: int,
    total_chunks: int,
    file_name: str,
    user_filename: Optional[str],
    reference_url: Optional[str],
    qa_format: bool = True,
    qa_counter_start: int = 1
) -> str:
    """
    Process a single text chunk with LLM to create structured output.
    
    Args:
        text_chunk: Text chunk to process
        chunk_index: Index of this chunk (0-based)
        total_chunks: Total number of chunks
        file_name: PDF filename
        user_filename: User-provided filename for metadata
        reference_url: User-provided reference URL
        qa_format: Whether to use Q&A format
        
    Returns:
        Structured text output from LLM
    """
    client, model = _get_llm_client()
    
    if not client or not model:
        logger.warning("LLM not available, returning original chunk")
        return text_chunk
    
    metadata_filename = user_filename if user_filename else file_name
    metadata_reference_url = reference_url if reference_url else "N/A"
    
    try:
        if qa_format:
            system_prompt = """You are an expert at converting document content into structured question-answer format for RAG (Retrieval-Augmented Generation) systems. Your task is to transform all content into labeled Q&A pairs with comprehensive metadata.

CRITICAL REQUIREMENTS:
1. Extract ALL information from the provided text chunk and convert it into Q&A pairs
2. For every heading, section, or topic, create explicit questions
3. Convert implicit questions from headings (e.g., "How Does Novated Leasing Work?" becomes a question)
4. Create multiple questions from a single section if it contains multiple pieces of information
5. Format each Q&A pair with structured metadata in this EXACT format:

=== Q&A-[ID] ===
Q: [Question text]
A: [Answer text - include all relevant details, examples, numbers, tables, etc.]
METADATA:
- page: [page number if mentioned, or "N/A"]
- filename: [User-provided filename]
- title: [Document title or main heading]
- section: [Section name or heading where this Q&A appears]
- description: [Brief description of the topic/context, 1-2 sentences]
- reference_url: [User-provided reference URL or "N/A"]
---

6. Preserve ALL information:
   - Numbers, percentages, dates, amounts
   - Tables (convert to readable format within answers)
   - Lists and bullet points
   - Contact information
   - URLs and links
   - All factual details

7. Create questions for:
   - Explicit questions found in the document
   - Headings (convert to "What is...", "How does...", "What are...", etc.)
   - Sections (create questions about the content)
   - Procedures and processes
   - Definitions and explanations
   - Features and benefits
   - Requirements and conditions
   - Options and choices

8. Make questions natural and searchable (as users would ask them)
9. Make answers comprehensive and self-contained (include all context needed)
10. Use section headings for the "section" metadata field
11. Create meaningful descriptions that summarize the Q&A context

Format: Use the exact structure shown above with === separators and METADATA section for each Q&A pair. Process ALL content in this chunk."""

            user_prompt = f"""Convert the following text chunk (chunk {chunk_index + 1} of {total_chunks}) from PDF file "{file_name}" into structured Q&A format. Extract ALL information and create as many Q&A pairs as needed.

IMPORTANT:
- This is chunk {chunk_index + 1} of {total_chunks} from the document
- Start labeling Q&A pairs from Q&A-{qa_counter_start:03d}
- Use the EXACT format: === Q&A-[ID] === followed by Q:, A:, and METADATA: sections
- Create questions for EVERY section, heading, and piece of information
- Use "{metadata_filename}" as the filename in all metadata sections
- Use "{metadata_reference_url}" as the reference_url in all metadata sections
- Make answers comprehensive and include all details
- Process ALL content - do not skip anything
- Preserve tables, lists, and all structured data

Text chunk:
{text_chunk}

Please provide the complete structured Q&A formatted output for this chunk with all information converted into labeled question-answer pairs."""

        else:
            # Structured document format
            system_prompt = """You are a document structuring expert. Your task is to take raw extracted text and structure it into a well-organized, readable document with proper formatting.

Requirements:
1. Clean up and format the text properly
2. Identify and properly format all headings, subheadings, and questions
3. Organize content into logical sections
4. Preserve all important information including:
   - Questions and their answers
   - Headings and subheadings
   - Paragraphs with proper formatting
   - Tables (format them clearly)
   - Contact information
5. Remove excessive line breaks and spaces
6. Create proper paragraph spacing
7. Format tables clearly with proper alignment
8. Use consistent formatting throughout"""

            user_prompt = f"""Please structure and format the following text chunk (chunk {chunk_index + 1} of {total_chunks}) from PDF file "{file_name}":

{text_chunk}

Please provide a well-structured, properly formatted version with:
- Proper paragraph spacing
- Clear headings and subheadings
- Well-formatted tables
- No excessive line breaks or spaces
- All content preserved accurately"""

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.3,
            max_tokens=8000
        )
        
        structured_output = response.choices[0].message.content
        logger.info(f"Successfully processed chunk {chunk_index + 1}/{total_chunks} with LLM")
        return structured_output
        
    except Exception as e:
        logger.error(f"Error processing chunk {chunk_index + 1} with LLM: {e}", exc_info=True)
        # Return original chunk if LLM processing fails
        return text_chunk


def _extract_qa_pairs_from_response(response_text: str, qa_counter_start: int) -> List[str]:
    """Extract Q&A pairs from LLM response and return as list of formatted strings."""
    qa_pairs = []
    
    # Split by === separators, but keep them
    # Pattern: === Q&A-XXX === followed by content
    import re
    
    # Find all Q&A blocks using regex
    pattern = r'===+\s*Q&A-(\d+)\s*===+(.*?)(?===+\s*Q&A-|$)'
    matches = re.finditer(pattern, response_text, re.DOTALL)
    
    current_counter = qa_counter_start
    for match in matches:
        original_id = match.group(1)
        content = match.group(2).strip()
        
        # Only add if there's actual content (Q: and A:)
        if content and ("Q:" in content or "A:" in content):
            new_id = f"Q&A-{current_counter:03d}"
            qa_pair = f"==={new_id}===\n{content}"
            qa_pairs.append(qa_pair)
            current_counter += 1
    
    # Fallback: if regex didn't work, try simple split
    if not qa_pairs:
        blocks = response_text.split("===")
        current_counter = qa_counter_start
        
        for i, block in enumerate(blocks):
            block = block.strip()
            if not block:
                continue
            
            # Check if this block contains Q&A content
            if "Q:" in block or "A:" in block or block.startswith("Q&A-"):
                # Extract ID if present
                lines = block.split("\n")
                first_line = lines[0].strip() if lines else ""
                
                # Check if first line has Q&A-ID
                if "Q&A-" in first_line:
                    # Extract number from ID
                    import re
                    id_match = re.search(r'Q&A-(\d+)', first_line)
                    if id_match:
                        # Replace with sequential number
                        new_id = f"Q&A-{current_counter:03d}"
                        lines[0] = f"==={new_id}==="
                    else:
                        # Add header if missing
                        new_id = f"Q&A-{current_counter:03d}"
                        lines.insert(0, f"==={new_id}===")
                else:
                    # Add header if missing
                    new_id = f"Q&A-{current_counter:03d}"
                    lines.insert(0, f"==={new_id}===")
                
                qa_pair = "\n".join(lines)
                if qa_pair.strip() and ("Q:" in qa_pair or "A:" in qa_pair):
                    qa_pairs.append(qa_pair)
                    current_counter += 1
    
    logger.info(f"Extracted {len(qa_pairs)} Q&A pairs from LLM response")
    return qa_pairs


def render_structure_to_text(structure: Dict[str, Any], formatted: bool = True) -> str:
    """
    Render the structured PDF representation to a human-readable text format.
    
    Args:
        structure: Structured PDF data with pages
        formatted: If True, use formatted output with proper spacing and paragraphs
    """
    lines: List[str] = []

    file_name = structure.get("file_name", "")
    lines.append(f"FILE: {file_name}")
    lines.append("")

    for page in structure.get("pages", []):
        page_no = page.get("page_number")
        lines.append(f"PAGE {page_no}")
        lines.append("=" * (5 + len(str(page_no))))
        lines.append("")

        if formatted:
            # Formatted output with proper spacing
            headings = page.get("headings") or []
            paragraphs = page.get("paragraphs") or []
            tables = page.get("tables") or []
            
            # Clean and output headings as section headers
            for heading in headings:
                heading_cleaned = " ".join(heading.split())  # Remove excessive spaces
                if heading_cleaned.strip():
                    lines.append(f"\n## {heading_cleaned.strip()}\n")
            
            # Output paragraphs with proper spacing (already cleaned during extraction)
            for para in paragraphs:
                para_cleaned = para.strip()
                # Final cleanup: ensure no excessive spaces
                para_cleaned = " ".join(para_cleaned.split())
                if para_cleaned:
                    lines.append(f"{para_cleaned}\n")
            
            # Output tables with proper formatting
            for table in tables:
                if table:
                    lines.append("\n--- TABLE ---\n")
                    # Find max width for each column
                    if table:
                        max_cols = max(len(row) for row in table if row)
                        col_widths = [0] * max_cols
                        
                        for row in table:
                            for i, cell in enumerate(row):
                                if i < max_cols:
                                    col_widths[i] = max(col_widths[i], len(str(cell).strip()))
                        
                        # Format table rows
                        for row_idx, row in enumerate(table):
                            formatted_row = []
                            for i in range(max_cols):
                                cell = str(row[i]).strip() if i < len(row) else ""
                                # Pad cell to column width
                                formatted_row.append(cell.ljust(col_widths[i]))
                            lines.append(" | ".join(formatted_row))
                        
                        lines.append("\n")
        else:
            # Original format
            headings = page.get("headings") or []
            if headings:
                lines.append("Headings:")
                for h in headings:
                    lines.append(f"- {h}")
                lines.append("")

            paragraphs = page.get("paragraphs") or []
            if paragraphs:
                lines.append("Paragraphs:")
                for i, para in enumerate(paragraphs, start=1):
                    lines.append(f"[{i}] {para}")
                lines.append("")

            tables = page.get("tables") or []
            if tables:
                lines.append("Tables:")
                for t_idx, table in enumerate(tables, start=1):
                    lines.append(f"Table {t_idx}:")
                    for row in table:
                        lines.append(" | ".join(row))
                    lines.append("")

        lines.append("")  # extra space between pages

    return "\n".join(lines).rstrip() + "\n"


def parse_qa_structure(structured_text: str, file_name: str) -> List[Dict[str, Any]]:
    """
    Parse structured Q&A text into a list of dictionaries with metadata.
    Each dictionary contains question, answer, and all metadata fields.
    
    Args:
        structured_text: Structured Q&A text with metadata
        file_name: Name of the PDF file
        
    Returns:
        List of dictionaries, each containing:
        - question: Question text
        - answer: Answer text
        - page: Page number or "N/A"
        - filename: PDF filename
        - title: Document title
        - section: Section name
        - description: Brief description
        - reference_url: URL if mentioned, or "N/A"
    """
    import re
    qa_pairs = []
    
    # Use regex to find all Q&A blocks more reliably
    # Pattern matches: ===Q&A-XXX=== followed by content until next === or end
    pattern = r'===+\s*Q&A-(\d+)\s*===+([\s\S]*?)(?===+\s*Q&A-|$)'
    matches = re.finditer(pattern, structured_text)
    
    for match in matches:
        qa_id = match.group(1)
        block_content = match.group(2).strip()
        
        if not block_content:
            logger.warning(f"Empty Q&A block found for Q&A-{qa_id}")
            continue
        
        try:
            # Initialize metadata dict (no question_id)
            qa_dict = {
                "question": "",
                "answer": "",
                "page": "N/A",
                "filename": file_name,
                "title": "",
                "section": "",
                "description": "",
                "reference_url": "N/A"
            }
            
            # Parse Q&A and metadata from block content
            lines = block_content.split("\n")
            current_field = None
            question_lines = []
            answer_lines = []
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                if line.startswith("Q:"):
                    current_field = "question"
                    question_text = line[2:].strip()
                    if question_text:
                        question_lines.append(question_text)
                elif line.startswith("A:"):
                    current_field = "answer"
                    answer_text = line[2:].strip()
                    if answer_text:
                        answer_lines.append(answer_text)
                elif line.startswith("METADATA:"):
                    current_field = "metadata"
                elif line.startswith("- ") and current_field == "metadata":
                    # Parse metadata line
                    meta_line = line[2:].strip()
                    if ":" in meta_line:
                        key, value = meta_line.split(":", 1)
                        key = key.strip().lower()
                        value = value.strip()
                        
                        if key == "page":
                            qa_dict["page"] = value
                        elif key == "filename":
                            qa_dict["filename"] = value
                        elif key == "title":
                            qa_dict["title"] = value
                        elif key == "section":
                            qa_dict["section"] = value
                        elif key == "description":
                            qa_dict["description"] = value
                        elif key == "reference_url":
                            qa_dict["reference_url"] = value
                elif line == "---":  # Skip separator line
                    continue
                elif current_field == "question" and line:
                    # Continuation of question (multi-line)
                    question_lines.append(line)
                elif current_field == "answer" and line:
                    # Continuation of answer (multi-line)
                    answer_lines.append(line)
            
            # Join question and answer lines
            qa_dict["question"] = " ".join(question_lines).strip()
            qa_dict["answer"] = " ".join(answer_lines).strip()
            
            # Only add if we have both question and answer
            if qa_dict["question"] and qa_dict["answer"]:
                qa_pairs.append(qa_dict)
            else:
                logger.warning(f"Q&A-{qa_id} missing question or answer. Question: '{qa_dict['question'][:50]}...', Answer: '{qa_dict['answer'][:50]}...'")
        
        except Exception as e:
            logger.error(f"Error parsing Q&A block Q&A-{qa_id}: {e}", exc_info=True)
            continue
    
    logger.info(f"Parsed {len(qa_pairs)} Q&A pairs from structured text")
    return qa_pairs


def save_extracted_text_for_pdf(filename: str, use_llm: bool = True, qa_format: bool = True) -> Path:
    """
    High-level helper:
    - Locate the given PDF in docs/
    - Extract structured content
    - Optionally use LLM to structure and format the content (Q&A format for RAG by default)
    - Write a .txt file with the same base name in docs/extracted-docs/
    - Return the output path
    
    Args:
        filename: Name of PDF file in docs/ directory
        use_llm: Whether to use LLM for structuring (default: True)
        qa_format: If True, convert to Q&A format for RAG pipeline (default: True)
    """
    pdf_path = get_pdf_path(filename)

    structure = extract_pdf_structure(pdf_path)
    rendered = render_structure_to_text(structure)
    
    # Use LLM to structure and format the text if enabled
    if use_llm:
        format_type = "Q&A" if qa_format else "structured"
        logger.info(f"Structuring text with LLM ({format_type} format) for file: {filename}")
        rendered = structure_text_with_llm(rendered, filename, qa_format=qa_format, structure=structure)

    docs_dir = _get_docs_base_dir()
    output_dir = docs_dir / "extracted-docs" / _get_env_folder()
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / (pdf_path.stem + ".txt")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(rendered)

    logger.info(f"Saved extracted text for '{pdf_path}' to '{output_path}'")
    return output_path


def process_uploaded_pdf(uploaded_file, use_llm: bool = True, qa_format: bool = True, user_filename: Optional[str] = None, reference_url: Optional[str] = None, save_raw: bool = True) -> Dict[str, Path]:
    """
    Process an uploaded PDF file:
    - Extract structured content from the uploaded file
    - Optionally use LLM to structure and format the content (Q&A format for RAG by default)
    - Write a .txt file with the same base name in docs/extracted-docs/
    - Return the output path
    
    Args:
        uploaded_file: Django UploadedFile object
        use_llm: Whether to use LLM for structuring (default: True)
        qa_format: If True, convert to Q&A format for RAG pipeline (default: True)
        user_filename: User-provided filename for metadata (optional)
        reference_url: User-provided reference URL for metadata (optional)
        
    Returns:
        Path to the generated text file
    """
    import tempfile
    
    # Validate file extension
    file_name = uploaded_file.name
    if not file_name.lower().endswith('.pdf'):
        raise ValueError("Only PDF files are supported. Please upload a .pdf file.")
    
    # Save uploaded file to temporary location
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
        temp_path = Path(temp_file.name)
        for chunk in uploaded_file.chunks():
            temp_file.write(chunk)
    
    try:
        # Extract structure from temporary file
        logger.info(f"Extracting structure from PDF: {file_name}")
        structure = extract_pdf_structure(temp_path)
        
        # Create output directory
        docs_dir = _get_docs_base_dir()
        output_dir = docs_dir / "extracted-docs" / _get_env_folder()
        output_dir.mkdir(parents=True, exist_ok=True)
        
        base_filename = Path(file_name).stem
        result_paths = {}
        
        # Save raw extracted text with proper formatting (including tables)
        if save_raw:
            raw_rendered = render_structure_to_text(structure, formatted=True)
            raw_filename = f"{base_filename}_raw.txt"
            raw_output_path = output_dir / raw_filename
            
            with open(raw_output_path, "w", encoding="utf-8") as f:
                f.write(raw_rendered)
            
            logger.info(f"Saved raw extracted text for uploaded file '{file_name}' to '{raw_output_path}'")
            result_paths["raw_path"] = raw_output_path
        
        # Use LLM to structure and format the text if enabled
        if use_llm:
            format_type = "Q&A" if qa_format else "structured"
            logger.info(f"Structuring text with LLM ({format_type} format) for file: {file_name}")
            
            # Get cleaned raw text for LLM processing
            raw_text = render_structure_to_text(structure, formatted=True)
            
            # Chunk text by LLM context window and process each chunk
            if qa_format:
                # For Q&A format, use chunked processing
                text_chunks = chunk_text_by_context_window(raw_text, max_chunk_size=4000, overlap=200)
                logger.info(f"Split text into {len(text_chunks)} chunks for LLM processing")
                
                all_structured_chunks = []
                qa_counter = 1  # Sequential counter across all chunks
                
                for chunk_idx, text_chunk in enumerate(text_chunks):
                    logger.info(f"Processing chunk {chunk_idx + 1}/{len(text_chunks)} with LLM")
                    
                    # Process each chunk with LLM
                    structured_chunk = _process_text_chunk_with_llm(
                        text_chunk=text_chunk,
                        chunk_index=chunk_idx,
                        total_chunks=len(text_chunks),
                        file_name=file_name,
                        user_filename=user_filename,
                        reference_url=reference_url,
                        qa_format=qa_format,
                        qa_counter_start=qa_counter
                    )
                    
                    if structured_chunk:
                        # Renumber Q&A pairs sequentially and count them
                        renumbered_chunk, qa_count = _renumber_qa_pairs(structured_chunk, qa_counter)
                        all_structured_chunks.append(renumbered_chunk)
                        qa_counter += qa_count
                        logger.info(f"Chunk {chunk_idx + 1} generated {qa_count} Q&A pairs")
                
                # Combine all structured chunks and ensure proper ordering
                combined_text = "\n\n".join(all_structured_chunks)
                
                # Extract all Q&A pairs, sort them, and renumber sequentially
                rendered, total_qa_count = _sort_and_renumber_all_qa_pairs(combined_text)
                
                logger.info(f"Combined {len(all_structured_chunks)} structured chunks into final document with {total_qa_count} total Q&A pairs (sorted in ascending order)")
            else:
                # For non-Q&A format, use existing structure_text_with_llm
                rendered = render_structure_to_text(structure, formatted=False)
                rendered = structure_text_with_llm(rendered, file_name, qa_format=qa_format, structure=structure, user_filename=user_filename, reference_url=reference_url)
            
            # Generate processed output filename
            processed_filename = f"{base_filename}_qa.txt" if qa_format else f"{base_filename}_structured.txt"
            processed_output_path = output_dir / processed_filename
            
            # Write LLM-processed text to output file
            with open(processed_output_path, "w", encoding="utf-8") as f:
                f.write(rendered)
            
            logger.info(f"Saved LLM-processed text for uploaded file '{file_name}' to '{processed_output_path}'")
            result_paths["processed_path"] = processed_output_path
        else:
            logger.info(f"Skipping LLM structuring for file: {file_name}")
            # If no LLM, use raw as processed
            if save_raw:
                result_paths["processed_path"] = result_paths["raw_path"]
        
        # Return the main output path (processed if available, otherwise raw)
        main_path = result_paths.get("processed_path") or result_paths.get("raw_path")
        result_paths["output_path"] = main_path
        
        return result_paths
    finally:
        # Clean up temporary file
        try:
            if temp_path.exists():
                temp_path.unlink()
        except Exception as e:
            logger.warning(f"Error deleting temporary file {temp_path}: {e}")


