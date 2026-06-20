from __future__ import annotations

import re
import statistics
from typing import Dict, List, Tuple

import fitz  # PyMuPDF

class NoHeadingsDetectedError(Exception):
    pass

class PDFParser:
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.doc = fitz.open(pdf_path)
        self.toc = self.doc.get_toc(simple=False)
        self.sections = self._build_section_map()

    def _build_section_map(self) -> Dict[int, List[Tuple[float, str]]]:
        section_map = {}
        
        # 1. Try ToC
        if self.toc:
            for item in self.toc:
                level = item[0]
                title = item[1]
                page_num = item[2] - 1
                dest = item[3]
                y_coord = 0.0
                if isinstance(dest, dict) and 'to' in dest:
                    point = dest['to']
                    if hasattr(point, 'y'):
                        y_coord = point.y
                if page_num not in section_map:
                    section_map[page_num] = []
                section_map[page_num].append((y_coord, title))
                
        # 2. Fallback
        if not self.toc or len(self.toc) < 2:
            fallback_map = self._fallback_heading_detection()
            if fallback_map:
                section_map = fallback_map

        if not section_map:
            raise NoHeadingsDetectedError("Could not detect any structured headings or ToC.")
            
        for page in section_map:
            section_map[page].sort(key=lambda x: x[0])
            
        return section_map

    def _fallback_heading_detection(self) -> Dict[int, List[Tuple[float, str]]]:
        section_map = {}
        
        # Determine median font size to find "larger" text
        sizes = []
        for page_num in range(min(5, len(self.doc))): # sample first few pages
            page = self.doc[page_num]
            blocks = page.get_text("dict").get("blocks", [])
            for b in blocks:
                if "lines" not in b: continue
                for l in b["lines"]:
                    for s in l.get("spans", []):
                        if s["text"].strip():
                            sizes.append(s["size"])
        
        if not sizes:
            return {}
            
        median_size = statistics.median(sizes)
        
        # Common section heading patterns e.g. "1. Introduction", "II. Methods", "Abstract"
        heading_pattern = re.compile(r"^(Abstract|Introduction|Methods|Results|Discussion|Conclusion|References|Acknowledgements?|Appendix|(\d+(\.\d+)*\.?\s+[A-Z].+)|([I|V|X]+\.?\s+[A-Z].+))$", re.IGNORECASE)

        for page_num in range(len(self.doc)):
            page = self.doc[page_num]
            blocks = page.get_text("dict").get("blocks", [])
            for b in blocks:
                if "lines" not in b: continue
                for l in b["lines"]:
                    for s in l.get("spans", []):
                        text = s["text"].strip()
                        size = s["size"]
                        flags = s["flags"]
                        
                        is_bold = flags & 2**4
                        
                        # Heading logic: significantly larger than median OR (bold and slightly larger/equal and matches pattern)
                        if (size > median_size * 1.1) or (is_bold and size >= median_size):
                            if heading_pattern.match(text) or text.isupper():
                                # Avoid very long "headings" which are likely just bold text
                                if 3 < len(text) < 100:
                                    y_coord = s["origin"][1]
                                    if page_num not in section_map:
                                        section_map[page_num] = []
                                    section_map[page_num].append((y_coord, text))
                                    
        return section_map

    def get_section_for_annotation(self, page_index: int, position) -> str:
        y_coord = 0.0
        if isinstance(position, dict):
            rects = position.get("rects") or []
            if rects:
                y_coord = min(r[1] for r in rects if len(r) >= 2)
        current_page = page_index
        while current_page >= 0:
            if current_page in self.sections and self.sections[current_page]:
                candidate_sections = self.sections[current_page]
                if current_page == page_index:
                    valid_sections = [s for s in candidate_sections if s[0] <= y_coord + 20]
                    if valid_sections:
                        return valid_sections[-1][1]
                    return candidate_sections[0][1]
                else:
                    return candidate_sections[-1][1]
            current_page -= 1
        return "General Notes"

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        try:
            parser = PDFParser(sys.argv[1])
            print("Detected Sections:")
            for p, secs in sorted(parser.sections.items()):
                print(f"Page {p}:")
                for y, title in secs:
                    print(f"  @y={y:.1f}: {title}")
        except NoHeadingsDetectedError as e:
            print(f"Error: {e}")
