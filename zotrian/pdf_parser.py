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
            right_edge = statistics.median(block[0] for block in right_blocks)

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
