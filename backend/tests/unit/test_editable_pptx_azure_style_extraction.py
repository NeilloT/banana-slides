from pathlib import Path

from services.export_service import ExportService
from services.image_editability.text_attribute_extractors import TextStyleResult


class FullImageAzureStyleExtractor:
    prefer_full_image_extraction = True

    def extract_batch_with_full_image(self, full_image, text_elements, **kwargs):
        return {
            text_elements[0]['element_id']: TextStyleResult(
                font_color_rgb=(17, 34, 51),
                is_bold=True,
                is_italic=True,
                font_family='Aptos',
                confidence=0.95,
            )
        }


class EditableImageStub:
    class BBox:
        def __init__(self):
            self.x0 = 0
            self.y0 = 0
            self.x1 = 100
            self.y1 = 40

    class Element:
        def __init__(self, image_path: str):
            self.element_type = "text"
            self.element_id = "text_0"
            self.content = "hello"
            self.image_path = image_path
            self.bbox = EditableImageStub.BBox()
            self.bbox_global = self.bbox
            self.children = []

    def __init__(self, image_path: str):
        self.image_path = image_path
        self.elements = [EditableImageStub.Element(image_path)]


def test_hybrid_style_extraction_prefers_single_pass_full_image_results(tmp_path):
    image_path = Path(tmp_path) / "text.png"
    image_path.write_bytes(b"png")
    editable_images = [EditableImageStub(str(image_path))]

    results, failures = ExportService._batch_extract_text_styles_hybrid(
        editable_images=editable_images,
        text_attribute_extractor=FullImageAzureStyleExtractor(),
        max_workers=2,
        fail_fast=False,
    )

    assert failures == []
    assert results["text_0"].font_family == "Aptos"
    assert results["text_0"].is_bold is True
