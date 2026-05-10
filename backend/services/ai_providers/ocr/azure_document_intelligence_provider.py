"""
Azure Document Intelligence OCR Provider

Uses Azure AI Document Intelligence prebuilt OCR models to extract:
- line/word positions
- font family and font style (via styleFont add-on)
- font color
"""
import logging
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from PIL import Image
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class AzureDocumentIntelligenceOCRProvider:
    """Azure OCR provider for editable PPTX export."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        api_version: str = "2024-11-30",
        model_id: str = "prebuilt-read",
        max_poll_seconds: int = 60,
        poll_interval_seconds: float = 1.0,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.api_key = api_key
        self.api_version = api_version
        self.model_id = model_id
        self.max_poll_seconds = max_poll_seconds
        self.poll_interval_seconds = poll_interval_seconds

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=1, max=5),
        retry=retry_if_exception_type((requests.exceptions.RequestException, TimeoutError)),
        reraise=True,
    )
    def recognize(self, image_path: str) -> Dict[str, Any]:
        image_file = Path(image_path)
        if not image_file.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")

        with Image.open(image_path) as img:
            original_width, original_height = img.size

        result = self._analyze_document(image_file.read_bytes())
        analyze_result = result.get("analyzeResult", {})
        return self._normalize_result(
            analyze_result=analyze_result,
            image_size=(original_width, original_height),
        )

    def get_full_text(self, result: Dict[str, Any], separator: str = "\n") -> str:
        text_lines = result.get("text_lines", [])
        return separator.join(line.get("text", "") for line in text_lines)

    def _analyze_document(self, image_bytes: bytes) -> Dict[str, Any]:
        analyze_url = (
            f"{self.endpoint}/documentintelligence/documentModels/"
            f"{self.model_id}:analyze"
        )
        params = {
            "api-version": self.api_version,
            "features": "styleFont",
            "stringIndexType": "UnicodeCodePoint",
        }
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key,
            "Content-Type": "application/octet-stream",
        }

        response = requests.post(
            analyze_url,
            params=params,
            headers=headers,
            data=image_bytes,
            timeout=60,
        )
        response.raise_for_status()

        operation_location = response.headers.get("operation-location")
        if not operation_location:
            raise RuntimeError("Azure OCR response missing operation-location header")

        return self._poll_result(operation_location)

    def _poll_result(self, operation_location: str) -> Dict[str, Any]:
        headers = {"Ocp-Apim-Subscription-Key": self.api_key}
        deadline = time.time() + self.max_poll_seconds

        while time.time() < deadline:
            response = requests.get(operation_location, headers=headers, timeout=60)
            response.raise_for_status()
            payload = response.json()
            status = (payload.get("status") or "").lower()

            if status == "succeeded":
                return payload
            if status == "failed":
                message = self._extract_error_message(payload)
                raise RuntimeError(f"Azure OCR analyze failed: {message}")

            time.sleep(self.poll_interval_seconds)

        raise TimeoutError("Azure OCR analyze timed out")

    @staticmethod
    def _extract_error_message(payload: Dict[str, Any]) -> str:
        error = payload.get("error") or {}
        if isinstance(error, dict):
            return error.get("message") or error.get("code") or "unknown error"
        return str(error) or "unknown error"

    def _normalize_result(
        self,
        analyze_result: Dict[str, Any],
        image_size: Tuple[int, int],
    ) -> Dict[str, Any]:
        content = analyze_result.get("content", "")
        styles = analyze_result.get("styles", []) or []
        style_ranges = self._build_style_ranges(styles)

        pages = analyze_result.get("pages", []) or []
        normalized_pages = []
        all_lines: List[Dict[str, Any]] = []

        for page_index, page in enumerate(pages):
            page_width = page.get("width") or image_size[0]
            page_height = page.get("height") or image_size[1]
            unit = page.get("unit") or "pixel"
            scale_x = image_size[0] / page_width if page_width else 1.0
            scale_y = image_size[1] / page_height if page_height else 1.0

            normalized_lines = []
            for line_index, line in enumerate(page.get("lines", []) or []):
                polygon = line.get("polygon", [])
                bbox = self._polygon_to_bbox(polygon, scale_x, scale_y)
                line_spans = line.get("spans", []) or []
                line_words = []

                for word in page.get("words", []) or []:
                    word_polygon = word.get("polygon", [])
                    word_bbox = self._polygon_to_bbox(word_polygon, scale_x, scale_y)
                    if not self._bbox_overlaps(bbox, word_bbox):
                        continue

                    word_style = self._resolve_style(word.get("span"), style_ranges)
                    line_words.append({
                        "text": word.get("content", ""),
                        "bbox": word_bbox,
                        "confidence": word.get("confidence"),
                        "style": word_style,
                    })

                aggregate_style = self._aggregate_line_style(line_words, line_spans, style_ranges)
                line_text = line.get("content", "")
                line_data = {
                    "text": line_text,
                    "bbox": bbox,
                    "polygon": self._scale_polygon(polygon, scale_x, scale_y),
                    "page_index": page_index,
                    "line_index": line_index,
                    "unit": unit,
                    "words": line_words,
                    "style": aggregate_style,
                }
                normalized_lines.append(line_data)
                all_lines.append(line_data)

            normalized_pages.append({
                "page_index": page_index,
                "width": image_size[0],
                "height": image_size[1],
                "unit": unit,
                "lines": normalized_lines,
            })

        return {
            "content": content,
            "text_lines": all_lines,
            "pages": normalized_pages,
            "styles": styles,
            "image_size": image_size,
        }

    @staticmethod
    def _build_style_ranges(styles: List[Dict[str, Any]]) -> List[Tuple[int, int, Dict[str, Any]]]:
        ranges = []
        for style in styles:
            for span in style.get("spans", []) or []:
                offset = span.get("offset", 0)
                length = span.get("length", 0)
                ranges.append((offset, offset + length, style))
        return ranges

    @staticmethod
    def _resolve_style(span: Optional[Dict[str, Any]], style_ranges: List[Tuple[int, int, Dict[str, Any]]]) -> Dict[str, Any]:
        if not span:
            return {}
        start = span.get("offset", 0)
        end = start + span.get("length", 0)
        best_style: Dict[str, Any] = {}
        best_overlap = -1
        for range_start, range_end, style in style_ranges:
            overlap = max(0, min(end, range_end) - max(start, range_start))
            if overlap > best_overlap:
                best_overlap = overlap
                best_style = style
        return best_style

    def _aggregate_line_style(
        self,
        words: List[Dict[str, Any]],
        line_spans: List[Dict[str, Any]],
        style_ranges: List[Tuple[int, int, Dict[str, Any]]],
    ) -> Dict[str, Any]:
        style_candidates: List[Dict[str, Any]] = []
        for span in line_spans:
            style = self._resolve_style(span, style_ranges)
            if style:
                style_candidates.append(style)
        for word in words:
            if word.get("style"):
                style_candidates.append(word["style"])

        if not style_candidates:
            return {}

        font_family_counter: Counter[str] = Counter()
        color_counter: Counter[str] = Counter()
        font_weight_counter: Counter[str] = Counter()
        font_style_counter: Counter[str] = Counter()

        for style in style_candidates:
            family = style.get("similarFontFamily")
            if family:
                font_family_counter[family] += 1
            color = style.get("color")
            if color:
                color_counter[color.upper()] += 1
            weight = style.get("fontWeight")
            if weight:
                font_weight_counter[str(weight).lower()] += 1
            font_style = style.get("fontStyle")
            if font_style:
                font_style_counter[str(font_style).lower()] += 1

        return {
            "font_family": font_family_counter.most_common(1)[0][0] if font_family_counter else None,
            "font_color": color_counter.most_common(1)[0][0] if color_counter else None,
            "font_weight": font_weight_counter.most_common(1)[0][0] if font_weight_counter else None,
            "font_style": font_style_counter.most_common(1)[0][0] if font_style_counter else None,
        }

    @staticmethod
    def _polygon_to_bbox(polygon: List[float], scale_x: float, scale_y: float) -> List[int]:
        scaled = AzureDocumentIntelligenceOCRProvider._scale_polygon(polygon, scale_x, scale_y)
        if not scaled:
            return [0, 0, 0, 0]
        xs = [point["x"] for point in scaled]
        ys = [point["y"] for point in scaled]
        return [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]

    @staticmethod
    def _scale_polygon(polygon: List[float], scale_x: float, scale_y: float) -> List[Dict[str, int]]:
        if not polygon:
            return []
        points = []
        for idx in range(0, len(polygon), 2):
            try:
                x = int(round(float(polygon[idx]) * scale_x))
                y = int(round(float(polygon[idx + 1]) * scale_y))
            except (IndexError, TypeError, ValueError):
                continue
            points.append({"x": x, "y": y})
        return points

    @staticmethod
    def _bbox_overlaps(a: List[int], b: List[int]) -> bool:
        return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def create_azure_document_intelligence_provider(
    endpoint: Optional[str] = None,
    api_key: Optional[str] = None,
    api_version: Optional[str] = None,
    model_id: Optional[str] = None,
) -> Optional[AzureDocumentIntelligenceOCRProvider]:
    from config import Config

    if not endpoint or not api_key:
        try:
            from flask import current_app
            endpoint = endpoint or current_app.config.get("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
            api_key = api_key or current_app.config.get("AZURE_DOCUMENT_INTELLIGENCE_KEY")
            api_version = api_version or current_app.config.get("AZURE_DOCUMENT_INTELLIGENCE_API_VERSION")
            model_id = model_id or current_app.config.get("AZURE_DOCUMENT_INTELLIGENCE_MODEL_ID")
        except RuntimeError:
            pass

    endpoint = endpoint or Config.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT
    api_key = api_key or Config.AZURE_DOCUMENT_INTELLIGENCE_KEY
    api_version = api_version or Config.AZURE_DOCUMENT_INTELLIGENCE_API_VERSION
    model_id = model_id or Config.AZURE_DOCUMENT_INTELLIGENCE_MODEL_ID

    if not endpoint or not api_key:
        logger.warning("⚠️ 未配置 Azure Document Intelligence 凭证, 跳过 Azure OCR")
        return None

    return AzureDocumentIntelligenceOCRProvider(
        endpoint=endpoint,
        api_key=api_key,
        api_version=api_version,
        model_id=model_id,
    )
