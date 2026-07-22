from __future__ import annotations

import re
import statistics
from typing import Dict, List, Optional, Tuple

import fitz


class NoHeadingsDetectedError(Exception):
    pass


class PDFParser:
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.doc = fitz.open(pdf_path)
        self.toc = self.doc.get_toc(simple=False)
        self.column_boundaries: Dict[int, Optional[float]] = {}
        self.sections = self._build_section_map()

    def _page_height(self, page_num: int) -> float:
        if 0 <= page_num < len(self.doc):
            return float(self.doc[page_num].rect.height)
        return 0.0

    def _toc_y_to_page_y(self, page_num: int, y_coord: float) -> float:
        """Convert TOC destinations into the same top-origin coordinates used
        by extracted text blocks and Zotero annotation rectangles.
        """
        page_height = self._page_height(page_num)
        if page_height <= 0:
            return y_coord
        return max(0.0, min(page_height, page_height - y_coord))

    def _detect_columns(self, page) -> Optional[float]:
        """Analyze text blocks on a page to detect two-column layout.

        Uses block centers instead of left edges so pages whose right column
        starts near the page midpoint are still detected correctly. Full-width
        captions and running headers are ignored because they often span both
        columns and would otherwise drown out the signal.
        """
        blocks = page.get_text("dict").get("blocks", [])
        if not blocks:
            return None

        page_width = page.rect.width
        page_height = page.rect.height
        mid = page_width / 2
        margin_band = page_height * 0.08
        column_blocks = []

        for block in blocks:
            if "bbox" not in block or "lines" not in block:
                continue
            text = " ".join(
                span["text"]
                for line in block["lines"]
                for span in line.get("spans", [])
            ).strip()
            if not text:
                continue

            x0, y0, x1, y1 = block["bbox"]
            width = x1 - x0
            center_x = (x0 + x1) / 2

            # Running headers, page numbers, and full-width captions are common
            # on article pages and should not influence column detection.
            if y1 < margin_band or y0 > page_height - margin_band:
                continue
            if width >= page_width * 0.75:
                continue

            column_blocks.append((x0, x1, center_x))

        if len(column_blocks) < 4:
            return None

        separation = page_width * 0.10
        left_blocks = [block for block in column_blocks if block[2] < mid - separation]
        right_blocks = [block for block in column_blocks if block[2] > mid + separation]
        substantial_blocks = [
            block
            for block in column_blocks
            if (block[1] - block[0]) >= page_width * 0.20
        ]
        substantial_left = [block for block in substantial_blocks if block[2] < mid - separation]
        substantial_right = [block for block in substantial_blocks if block[2] > mid + separation]

        has_balanced_columns = (
            len(left_blocks) >= 2
            and len(right_blocks) >= 2
        )
        has_merged_column_blocks = (
            len(substantial_left) >= 1
            and len(substantial_right) >= 1
            and len(substantial_blocks) >= 3
        )

        if has_balanced_columns or has_merged_column_blocks:
            left_edge = statistics.median(block[1] for block in left_blocks)
            right_edge = min(block[0] for block in right_blocks)

            if right_edge - left_edge >= page_width * 0.02:
                return (left_edge + right_edge) / 2

        return None

    def _build_section_map(self) -> Dict[int, List[Tuple[float, float, str]]]:
        section_map = {}

        if self.toc:
            for item in self.toc:
                title = item[1]
                page_num = item[2] - 1
                dest = item[3]
                y_coord = 0.0
                x_coord = 0.0
                if isinstance(dest, dict) and "to" in dest:
                    point = dest["to"]
                    if hasattr(point, "y"):
                        y_coord = point.y
                        x_coord = getattr(point, "x", 0.0)
                    elif isinstance(point, (list, tuple)) and len(point) >= 2:
                        y_coord = point[1]
                        x_coord = point[0]
                elif isinstance(dest, dict) and "dest" in dest:
                    # Parse /FitR left top right bottom or /XYZ left top zoom
                    dest_str = dest["dest"]
                    if isinstance(dest_str, str):
                        parts = dest_str.split()
                        if len(parts) >= 3 and parts[0] in ("/FitR", "/XYZ"):
                            try:
                                y_coord = float(parts[2])  # top y-coordinate
                                x_coord = float(parts[1])  # left x-coordinate
                            except ValueError:
                                pass
                y_coord = self._toc_y_to_page_y(page_num, y_coord)
                section_map.setdefault(page_num, []).append((y_coord, x_coord, title))

        if not self.toc or len(self.toc) < 2:
            fallback_map = self._fallback_heading_detection()
            if fallback_map:
                section_map = fallback_map

        if not section_map:
            raise NoHeadingsDetectedError("Could not detect any structured headings or ToC.")

        for page in section_map:
            section_map[page].sort(key=lambda item: item[0])

        # Detect columns for each page that has headings
        for page_num in section_map:
            if page_num < len(self.doc):
                page = self.doc[page_num]
                self.column_boundaries[page_num] = self._detect_columns(page)

        return section_map

    def get_heading_positions(self) -> list[tuple[int, float, str, int]]:
        """Find actual heading positions by searching for heading text on pages.

        Returns list of (page_index, y_top, title, toc_index) sorted in reading order.
        Uses fitz text search for precise positions instead of TOC destination coords.
        Falls back to TOC coordinates when text search fails.
        """
        positions = []
        seen_titles = set()

        for toc_index, item in enumerate(self.toc):
            title = item[1].strip()
            toc_page = item[2] - 1  # Convert to 0-indexed

            if title in seen_titles:
                continue
            seen_titles.add(title)

            found = False

            # Try searching for the heading text on the previous, TOC, and next page
            for page_offset in (-1, 0, 1):
                search_page = toc_page + page_offset
                if search_page < 0 or search_page >= len(self.doc):
                    continue
                page = self.doc[search_page]

                # Try full title first
                hits = page.search_for(title)
                if not hits and page_offset >= 0:
                    # On TOC page and next page only: try without leading section
                    # numbers (e.g., "2.3 " prefix). Avoid on previous page because
                    # trimmed keywords often match body text there.
                    trimmed = re.sub(r'^[\dIVXivx]+[.)\s]+\s*', '', title).strip()
                    if trimmed and len(trimmed) >= 4:
                        hits = page.search_for(trimmed)

                if hits:
                    # Use the first hit - headings appear before body text
                    rect = hits[0]
                    positions.append((search_page, rect.y0, title, toc_index))
                    found = True
                    break

            if not found:
                # Fallback: use TOC destination coordinates
                dest = item[3]
                y_coord = 0.0
                if isinstance(dest, dict) and "to" in dest:
                    point = dest["to"]
                    if hasattr(point, "y"):
                        y_coord = point.y
                    elif isinstance(point, (list, tuple)) and len(point) >= 2:
                        y_coord = point[1]
                y_coord = self._toc_y_to_page_y(toc_page, y_coord)
                positions.append((toc_page, y_coord, title, toc_index))

        positions.sort(key=lambda x: (x[0], x[3], x[1]))
        return positions

    def _detect_headings_by_font(self) -> list[tuple[int, float, float, str, int]]:
        """Detect headings across all pages using font family analysis.
        
        Scans every page for text blocks whose font differs from the dominant
        body-text font.  Matched headings are paired with TOC entries by
        proximity so the caller can use TOC order as a tiebreaker.
        
        Returns list of (page_index, x_left, y_top, title, toc_index) tuples.
        Returns empty list if font-based detection finds nothing useful.
        """
        if not self.toc or len(self.toc) < 2:
            return []
        
        # --- Step 1: Collect font statistics from ALL pages ---
        font_char_counts: dict[str, int] = {}
        for page in self.doc:
            for block in page.get_text("dict").get("blocks", []):
                if "lines" not in block:
                    continue
                for line in block["lines"]:
                    for span in line.get("spans", []):
                        text = span["text"].strip()
                        if text:
                            font = span.get("font", "")
                            font_char_counts[font] = font_char_counts.get(font, 0) + len(text)
        
        if not font_char_counts:
            return []
        
        # Body fonts = top 2 most common fonts by character count
        sorted_fonts = sorted(font_char_counts.items(), key=lambda x: -x[1])
        body_fonts = {f for f, _ in sorted_fonts[:2]}
        
        # --- Step 2: Scan all pages for heading blocks (non-body-font text) ---
        raw_headings: list[tuple[int, float, float, str]] = []  # (page, x0, y0, text)
        
        for page_num in range(len(self.doc)):
            page = self.doc[page_num]
            page_height = page.rect.height
            page_width = page.rect.width
            margin_band = page_height * 0.08
            
            for block in page.get_text("dict").get("blocks", []):
                if "lines" not in block or "bbox" not in block:
                    continue
                
                x0, y0, x1, y1 = block["bbox"]
                block_text = " ".join(
                    span["text"]
                    for line in block["lines"]
                    for span in line.get("spans", [])
                ).strip()
                
                if not block_text or len(block_text) > 150:
                    continue
                
                # Skip margin regions (running headers, page numbers)
                if y1 < margin_band or y0 > page_height - margin_band:
                    continue
                
                # Skip very narrow blocks (unlikely to be headings)
                if (x1 - x0) < 20:
                    continue
                
                # Check if block uses a non-body font
                is_heading_font = False
                for line in block["lines"]:
                    for span in line.get("spans", []):
                        if span["text"].strip() and span.get("font", "") not in body_fonts:
                            is_heading_font = True
                            break
                    if is_heading_font:
                        break
                
                if not is_heading_font:
                    continue
                
                # Skip blocks that span full width (likely captions or headers, not section headings)
                if (x1 - x0) >= page_width * 0.85:
                    continue
                
                raw_headings.append((page_num, x0, y0, block_text))
        
        if not raw_headings:
            return []
        
        # --- Step 3: Match detected headings to TOC entries ---
        # Build TOC lookup: stripped_title -> (toc_index, title, toc_page)
        toc_lookup: dict[str, tuple[int, str, int]] = {}
        seen = set()
        for toc_idx, item in enumerate(self.toc):
            title = item[1].strip()
            toc_page = item[2] - 1
            if title in seen:
                continue
            seen.add(title)
            
            # Full title
            toc_lookup[title.lower()] = (toc_idx, title, toc_page)
            # Without section number prefix (e.g., "2.3. Mock Observations" -> "Mock Observations")
            trimmed = re.sub(r'^[\dIVXivx]+[.)\s]+\s*', '', title).strip()
            if trimmed and trimmed.lower() != title.lower():
                toc_lookup[trimmed.lower()] = (toc_idx, title, toc_page)
        
        results: list[tuple[int, float, float, str, int]] = []
        matched_toc_indices: set[int] = set()
        
        for page_num, x0, y0, text in raw_headings:
            text_lower = text.lower().strip()
            
            # Direct match
            match = toc_lookup.get(text_lower)
            
            # Fuzzy match: check if any TOC title is contained in the detected text or vice versa
            if not match:
                for key, (toc_idx, title, toc_page) in toc_lookup.items():
                    if (key in text_lower or text_lower in key) and len(min(key, text_lower)) >= 4:
                        match = (toc_idx, title, toc_page)
                        break
            
            if match:
                toc_idx, title, toc_page = match
                # Only accept if on the TOC page or adjacent page (±1)
                if abs(page_num - toc_page) <= 1:
                    results.append((page_num, x0, y0, title, toc_idx))
                    matched_toc_indices.add(toc_idx)
        
        # Add unmatched TOC entries using text search fallback
        seen_titles = set()
        for toc_idx, item in enumerate(self.toc):
            title = item[1].strip()
            toc_page = item[2] - 1
            
            if toc_idx in matched_toc_indices or title in seen_titles:
                continue
            seen_titles.add(title)
            
            # Text search fallback (same logic as get_heading_positions)
            found = False
            for page_offset in (-1, 0, 1):
                search_page = toc_page + page_offset
                if search_page < 0 or search_page >= len(self.doc):
                    continue
                page = self.doc[search_page]
                hits = page.search_for(title)
                if not hits and page_offset >= 0:
                    trimmed = re.sub(r'^[\dIVXivx]+[.)\s]+\s*', '', title).strip()
                    if trimmed and len(trimmed) >= 4:
                        hits = page.search_for(trimmed)
                if hits:
                    rect = hits[0]
                    results.append((search_page, rect.x0, rect.y0, title, toc_idx))
                    found = True
                    break
            
            if not found:
                # Last resort: TOC destination coords
                dest = item[3]
                y_coord = 0.0
                x_coord = 0.0
                if isinstance(dest, dict) and "to" in dest:
                    point = dest["to"]
                    if hasattr(point, "y"):
                        y_coord = point.y
                        x_coord = getattr(point, "x", 0.0)
                    elif isinstance(point, (list, tuple)) and len(point) >= 2:
                        y_coord = point[1]
                        x_coord = point[0]
                y_coord = self._toc_y_to_page_y(toc_page, y_coord)
                results.append((toc_page, x_coord, y_coord, title, toc_idx))
        
        # Ensure column boundaries exist for all pages with headings
        heading_pages = {r[0] for r in results}
        for pn in heading_pages:
            if pn not in self.column_boundaries and pn < len(self.doc):
                self.column_boundaries[pn] = self._detect_columns(self.doc[pn])
        
        results.sort(key=lambda x: (x[0], x[4], x[2]))
        return results

    def _fallback_heading_detection(self) -> Dict[int, List[Tuple[float, float, str]]]:
        section_map = {}
        sizes = []
        for page_num in range(min(5, len(self.doc))):
            page = self.doc[page_num]
            blocks = page.get_text("dict").get("blocks", [])
            for block in blocks:
                if "lines" not in block:
                    continue
                for line in block["lines"]:
                    for span in line.get("spans", []):
                        if span["text"].strip():
                            sizes.append(span["size"])

        if not sizes:
            return {}

        median_size = statistics.median(sizes)
        heading_pattern = re.compile(
            r"^(Abstract|Introduction|Methods|Results|Discussion|Conclusion|References|Acknowledgements?|Appendix|(\d+(\.\d+)*\.?\s+[A-Z].+)|([I|V|X]+\.?\s+[A-Z].+))$",
            re.IGNORECASE,
        )

        for page_num in range(len(self.doc)):
            page = self.doc[page_num]
            blocks = page.get_text("dict").get("blocks", [])
            for block in blocks:
                if "lines" not in block:
                    continue
                for line in block["lines"]:
                    for span in line.get("spans", []):
                        text = span["text"].strip()
                        size = span["size"]
                        flags = span["flags"]
                        is_bold = flags & 2**4
                        if (size > median_size * 1.1) or (is_bold and size >= median_size):
                            if (heading_pattern.match(text) or text.isupper()) and 3 < len(text) < 100:
                                y_coord = span["origin"][1]
                                x_coord = span["origin"][0]
                                section_map.setdefault(page_num, []).append((y_coord, x_coord, text))

        return section_map

    def get_section_for_annotation(self, page_index: int, position) -> str:
        """Assign an annotation to the nearest preceding heading.

        Coordinate system: headings and annotations both use top-origin page
        coordinates where smaller y-values are closer to the top of the page
        and therefore earlier in reading order.

        For two-column pages, headings and annotations are matched by column
        first. Full-width headings (which start at the left margin) are
        classified as left-column; right-column annotations fall through to
        them via the left-column fallback, preserving correct reading order.
        """
        # Extract both x and y coordinates from annotation position
        y_coord = 0.0
        x_coord = 0.0
        if isinstance(position, dict):
            rects = position.get("rects") or []
            if rects:
                y_coord = min(rect[1] for rect in rects if len(rect) >= 2)
                x_coord = min(rect[0] for rect in rects if len(rect) >= 1)

        # Determine which column the annotation is in
        mid = self.column_boundaries.get(page_index)
        if mid is None:
            annotation_column = 0  # Single column
        else:
            annotation_column = 0 if x_coord < mid else 1

        current_page = page_index
        while current_page >= 0:
            if current_page in self.sections and self.sections[current_page]:
                candidate_sections = self.sections[current_page]
                page_mid = self.column_boundaries.get(current_page)

                if current_page == page_index:
                    # Helper to determine whether a heading is in the same
                    # column as the annotation
                    def _in_same_column(heading_x: float) -> bool:
                        if page_mid is None:
                            return True
                        heading_col = 0 if heading_x < page_mid else 1
                        return heading_col == annotation_column

                    # First pass: headings in the SAME column, above the annotation
                    same_col = [s for s in candidate_sections if _in_same_column(s[1])]
                    preceding = [s for s in same_col if s[0] <= y_coord + 20]
                    if preceding:
                        # Ascending sort (top-to-bottom); last element is the
                        # nearest heading above the annotation.
                        return preceding[-1][2]

                    # Second pass: only if annotation is in right column (1).
                    # Check left-column headings — these come before the right
                    # column in reading order. Return the bottom-most left
                    # heading, which is the last item in top-to-bottom order.
                    if annotation_column == 1 and page_mid is not None:
                        left_headings = [s for s in candidate_sections if s[1] < page_mid]
                        if left_headings:
                            return left_headings[-1][2]

                    # No suitable heading on current page; fall through to
                    # previous pages below.

                else:
                    # Previous page: return the last heading in reading order.
                    if page_mid is not None:
                        # Two-column page: prefer right-column headings,
                        # taking the bottom-most one.
                        right_col = [s for s in candidate_sections if s[1] >= page_mid]
                        if right_col:
                            return right_col[-1][2]
                        # No right-column headings; fall back to left column.
                        left_col = [s for s in candidate_sections if s[1] < page_mid]
                        if left_col:
                            return left_col[-1][2]
                    else:
                        # Single-column page: bottom-most heading.
                        return candidate_sections[-1][2]

            current_page -= 1

        # Final fallback when no heading was found on any preceding page.
        return "Abstract"
