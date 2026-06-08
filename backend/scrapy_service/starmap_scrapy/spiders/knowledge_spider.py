"""
Knowledge Spider for StarMap 408 exam platform.

Parses PDF textbooks into structured knowledge points.
Supports Wangdao/Tianqin 408 exam prep books.
"""

import hashlib
import logging
import re
from pathlib import Path

import scrapy

from starmap_scrapy.items import KnowledgePointItem

logger = logging.getLogger(__name__)

# Common chapter heading patterns in 408 textbooks
CHAPTER_PATTERNS = [
    re.compile(r"^第\s*(\d+|[一二三四五六七八九十百]+)\s*章\s*(.*)$"),
    re.compile(r"^(\d+)\s+(.+)$"),  # "1 绪论"
    re.compile(r"^(\d+\.\d*)\s+(.+)$"),  # "1.1 概述"
]

# Section heading patterns
SECTION_PATTERNS = [
    re.compile(r"^(\d+\.\d+)\s+(.+)$"),  # "1.1 数据结构的基本概念"
    re.compile(r"^(\d+\.\d+\.\d+)\s+(.+)$"),  # "1.1.1 基本概念"
]


class KnowledgeSpider(scrapy.Spider):
    """
    Spider for parsing PDF textbooks into knowledge points.

    Usage:
        scrapy crawl knowledge \\
            -a pdf_path=/path/to/book.pdf \\
            -a subject_id=subj_ds \\
            -a source="王道2025/数据结构"
    """

    name = "knowledge"

    # Task context
    task_id = None
    pdf_path = None
    subject_id = None
    chapter_id = None
    source = None

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if "task_id" in kwargs:
            self.task_id = kwargs["task_id"]
        if "pdf_path" in kwargs:
            self.pdf_path = kwargs["pdf_path"]
        if "subject_id" in kwargs:
            self.subject_id = kwargs["subject_id"]
        if "chapter_id" in kwargs:
            self.chapter_id = kwargs["chapter_id"]
        if "source" in kwargs:
            self.source = kwargs["source"]

    def start_requests(self):
        """Parse PDF and yield knowledge point items."""
        if not self.pdf_path:
            logger.error("No pdf_path provided")
            return

        pdf_file = Path(self.pdf_path)
        if not pdf_file.exists():
            logger.error(f"PDF file not found: {self.pdf_path}")
            return

        if not self.subject_id:
            logger.error("No subject_id provided")
            return

        logger.info(f"Starting PDF parsing: {self.pdf_path}")

        try:
            import pdfplumber
        except ImportError:
            logger.error("pdfplumber not installed. Run: pip install pdfplumber")
            return

        pages_text = []
        with pdfplumber.open(str(pdf_file)) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text:
                    pages_text.append({
                        "page_num": i + 1,
                        "text": text.strip()
                    })

        logger.info(f"Extracted {len(pages_text)} pages from PDF")

        # Split into sections and yield knowledge points
        sections = self._split_into_sections(pages_text)
        logger.info(f"Found {len(sections)} sections")

        for section in sections:
            yield self._create_knowledge_point(section)

    def _split_into_sections(self, pages_text):
        """
        Split extracted text into logical sections based on headings.

        Returns list of dicts: {title, content, page_start, page_end, level}
        """
        sections = []
        current_section = None
        buffer = []

        for page in pages_text:
            lines = page["text"].split("\n")
            for line in lines:
                line = line.strip()
                if not line:
                    continue

                # Check if this line is a heading
                heading_info = self._detect_heading(line)

                if heading_info:
                    # Save previous section
                    if current_section and buffer:
                        current_section["content"] = "\n".join(buffer).strip()
                        if len(current_section["content"]) > 50:  # Skip tiny sections
                            sections.append(current_section)

                    # Start new section
                    current_section = {
                        "title": heading_info["title"],
                        "level": heading_info["level"],
                        "page_start": page["page_num"],
                        "page_end": page["page_num"],
                        "content": ""
                    }
                    buffer = []
                else:
                    buffer.append(line)
                    if current_section:
                        current_section["page_end"] = page["page_num"]

        # Don't forget the last section
        if current_section and buffer:
            current_section["content"] = "\n".join(buffer).strip()
            if len(current_section["content"]) > 50:
                sections.append(current_section)

        # If no sections found, treat entire PDF as one section
        if not sections and pages_text:
            all_text = "\n".join(p["text"] for p in pages_text)
            sections.append({
                "title": "全文",
                "level": 0,
                "page_start": 1,
                "page_end": len(pages_text),
                "content": all_text.strip()
            })

        return sections

    def _detect_heading(self, line):
        """
        Detect if a line is a chapter/section heading.

        Returns {title, level} or None.
        """
        # Skip very long lines (unlikely to be headings)
        if len(line) > 80:
            return None

        # Chapter patterns (level 1)
        for pattern in CHAPTER_PATTERNS:
            match = pattern.match(line)
            if match:
                return {"title": line.strip(), "level": 1}

        # Section patterns (level 2-3)
        for pattern in SECTION_PATTERNS:
            match = pattern.match(line)
            if match:
                depth = len(match.group(1).split("."))
                return {"title": line.strip(), "level": depth}

        return None

    def _generate_id(self, prefix, content):
        """Generate deterministic ID from content."""
        hash_str = hashlib.md5(content.encode("utf-8")).hexdigest()[:12]
        return f"{prefix}_{hash_str}"

    def _split_content_into_chunks(self, content, max_chars=2000):
        """Split long content into manageable chunks."""
        if len(content) <= max_chars:
            return [content]

        chunks = []
        paragraphs = content.split("\n\n")
        current_chunk = []

        for para in paragraphs:
            if len("\n\n".join(current_chunk)) + len(para) > max_chars:
                if current_chunk:
                    chunks.append("\n\n".join(current_chunk))
                    current_chunk = []
            current_chunk.append(para)

        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        return chunks

    def _create_knowledge_point(self, section):
        """Create a KnowledgePointItem from a section."""
        content = section["content"]
        chunks = self._split_content_into_chunks(content)

        # Use first chunk as main content, or combine if small enough
        main_content = chunks[0] if len(chunks) == 1 else "\n\n".join(chunks[:3])

        point_id = self._generate_id("kp", f"{self.subject_id}:{section['title']}:{main_content[:200]}")

        # Extract key points from content
        key_points = self._extract_key_points(content)

        # Estimate difficulty based on content complexity
        difficulty = self._estimate_difficulty(content)

        return KnowledgePointItem(
            id=point_id,
            chapter_id=self.chapter_id,
            subject_id=self.subject_id,
            title=section["title"],
            content=main_content[:5000],  # Limit content length
            difficulty=difficulty,
            exam_frequency="medium",  # Default, can be refined by LLM
            tags=self._extract_tags(content),
            key_points=key_points,
            related_point_ids=[],
            source=self.source,
            source_page=f"p{section['page_start']}-{section['page_end']}",
            crawl_task_id=self.task_id,
            status="active",
        )

    def _extract_key_points(self, content):
        """Extract key points from content."""
        key_points = []
        lines = content.split("\n")

        for line in lines:
            line = line.strip()
            # Look for bullet points, numbered lists, or emphasized text
            if re.match(r"^[\-•·]\s+", line):
                key_points.append(re.sub(r"^[\-•·]\s+", "", line))
            elif re.match(r"^\d+[.、）)]\s+", line):
                key_points.append(re.sub(r"^\d+[.、）)]\s+", "", line))
            elif line.startswith("**") and line.endswith("**"):
                key_points.append(line.strip("*").strip())

        return key_points[:10]  # Limit to 10 key points

    def _estimate_difficulty(self, content):
        """Estimate difficulty based on content complexity."""
        # Simple heuristic based on content length and technical terms
        technical_terms = [
            "算法", "复杂度", "时间复杂度", "空间复杂度", "递归",
            "证明", "定理", "推导", "公式", "运算",
            "二叉树", "图论", "排序", "查找", "哈希",
            "进程", "线程", "死锁", "内存", "虚拟",
            "协议", "路由", "TCP", "UDP", "HTTP"
        ]

        term_count = sum(1 for term in technical_terms if term in content)

        if term_count >= 5 or len(content) > 3000:
            return "hard"
        elif term_count >= 2 or len(content) > 1500:
            return "medium"
        else:
            return "easy"

    def _extract_tags(self, content):
        """Extract relevant tags from content."""
        tags = []
        tag_keywords = {
            "重点": ["重点", "重要", "核心", "关键"],
            "常考": ["常考", "高频", "考试", "真题"],
            "难点": ["难点", "易错", "易混淆"],
            "算法": ["算法", "伪代码", "流程图"],
            "概念": ["定义", "概念", "含义"],
        }

        for tag, keywords in tag_keywords.items():
            if any(kw in content for kw in keywords):
                tags.append(tag)

        return tags
