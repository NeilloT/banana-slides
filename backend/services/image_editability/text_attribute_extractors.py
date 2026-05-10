"""
文字属性提取器 - 从文字区域图像中提取文字的视觉属性

包含：
- TextStyleResult: 文字样式数据结构
- TextAttributeExtractor: 提取器抽象接口
- CaptionModelTextAttributeExtractor: 基于Caption Model的默认实现
- TextAttributeExtractorRegistry: 提取器注册表
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional, Tuple, Union
from PIL import Image
from services.prompts import get_text_attribute_extraction_prompt

logger = logging.getLogger(__name__)


def hex_to_rgb(hex_color: str) -> Tuple[int, int, int]:
    """
    将十六进制颜色转换为 RGB 元组。

    支持 `#RRGGBB`、`RRGGBB` 和 `#RGB` 简写格式。
    """
    hex_color = hex_color.lstrip('#')

    if len(hex_color) == 3:
        hex_color = ''.join(c * 2 for c in hex_color)

    if len(hex_color) != 6:
        return (0, 0, 0)

    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return (r, g, b)
    except ValueError:
        return (0, 0, 0)


@dataclass
class ColoredSegment:
    """
    带颜色的文字片段
    
    用于表示一段文字及其颜色，支持 LaTeX 公式
    """
    text: str  # 文字内容（如果是公式则为 LaTeX 格式）
    color_rgb: Tuple[int, int, int] = (0, 0, 0)  # RGB颜色 (0-255)
    is_latex: bool = False  # 是否为 LaTeX 公式
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {
            'text': self.text,
            'color': f"#{self.color_rgb[0]:02x}{self.color_rgb[1]:02x}{self.color_rgb[2]:02x}"
        }
        if self.is_latex:
            result['is_latex'] = True
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ColoredSegment':
        """从字典创建实例"""
        text = data.get('text', '')
        color = data.get('color', '#000000')
        is_latex = bool(data.get('is_latex', False))
        
        # 解析颜色
        if isinstance(color, str):
            color_rgb = hex_to_rgb(color)
        else:
            color_rgb = (0, 0, 0)
        return cls(text=text, color_rgb=color_rgb, is_latex=is_latex)


@dataclass
class TextStyleResult:
    """
    文字样式数据结构
    
    包含从文字区域图像中提取的视觉属性
    
    Note:
        字体大小不在此处提取，因为传入的是裁剪后的子图，无法准确估算。
        字体大小应由 PPTXBuilder.calculate_font_size 根据bbox计算。
    """
    # 字体颜色 RGB (0-255) - 默认颜色，用于整体颜色或兜底
    font_color_rgb: Tuple[int, int, int] = (0, 0, 0)
    
    # 带颜色的文字片段列表 - 支持一行文字多种颜色
    # 如果有值，渲染时优先使用这个，文字内容也以这里的为准
    colored_segments: List[ColoredSegment] = field(default_factory=list)
    
    # 是否粗体
    is_bold: bool = False
    
    # 是否斜体
    is_italic: bool = False
    
    # 是否有下划线
    is_underline: bool = False

    # 字体名称（如果可以识别）
    font_family: Optional[str] = None
    
    # 文字对齐方式 - 可选 ('left', 'center', 'right', 'justify')
    text_alignment: Optional[str] = None
    
    # 置信度 (0.0-1.0)
    confidence: float = 1.0
    
    # 额外的元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        # 将 tuple 转换为 list 以便 JSON 序列化
        result['font_color_rgb'] = list(self.font_color_rgb)
        # 转换 colored_segments
        result['colored_segments'] = [seg.to_dict() if isinstance(seg, ColoredSegment) else seg for seg in self.colored_segments]
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TextStyleResult':
        """从字典创建实例"""
        if 'font_color_rgb' in data and isinstance(data['font_color_rgb'], list):
            data['font_color_rgb'] = tuple(data['font_color_rgb'])
        # 转换 colored_segments
        if 'colored_segments' in data:
            data['colored_segments'] = [
                ColoredSegment.from_dict(seg) if isinstance(seg, dict) else seg 
                for seg in data['colored_segments']
            ]
        return cls(**data)
    
    def get_hex_color(self) -> str:
        """获取十六进制颜色值（默认颜色）"""
        r, g, b = self.font_color_rgb
        return f"#{r:02x}{g:02x}{b:02x}"
    
    def get_full_text(self) -> str:
        """获取完整的文字内容（从 colored_segments 拼接）"""
        if self.colored_segments:
            return ''.join(seg.text for seg in self.colored_segments)
        return ""
    
    def has_multi_color(self) -> bool:
        """是否有多种颜色"""
        if not self.colored_segments or len(self.colored_segments) <= 1:
            return False
        colors = set(seg.color_rgb for seg in self.colored_segments)
        return len(colors) > 1


class TextAttributeExtractor(ABC):
    """
    文字属性提取器抽象接口
    
    用于从文字区域图像中提取文字的视觉属性，支持接入多种实现：
    - CaptionModelTextAttributeExtractor: 使用视觉语言模型（如Gemini）分析图像
    - 未来可扩展：基于传统CV的方法、专用OCR模型等
    """
    
    @abstractmethod
    def extract(
        self,
        image: Union[str, Image.Image],
        text_content: Optional[str] = None,
        **kwargs
    ) -> TextStyleResult:
        """
        从文字区域图像中提取文字样式属性
        
        Args:
            image: 文字区域的图像，可以是文件路径或PIL Image对象
            text_content: 文字内容（可选，某些实现可能用于辅助识别）
            **kwargs: 其他由具体实现自定义的参数
        
        Returns:
            TextStyleResult对象，包含提取的文字样式属性
        """
        pass
    
    @abstractmethod
    def supports_batch(self) -> bool:
        """
        是否支持批量处理
        
        Returns:
            如果支持批量处理返回True
        """
        pass
    
    def extract_batch(
        self,
        items: List[Tuple[Union[str, Image.Image], Optional[str]]],
        **kwargs
    ) -> List[TextStyleResult]:
        """
        批量提取文字样式属性
        
        默认实现：逐个调用extract方法
        子类可以覆盖此方法以实现更高效的批量处理
        
        Args:
            items: 列表，每个元素是 (image, text_content) 元组
            **kwargs: 其他参数
        
        Returns:
            TextStyleResult列表
        """
        results = []
        for image, text_content in items:
            try:
                result = self.extract(image, text_content, **kwargs)
                results.append(result)
            except Exception as e:
                logger.error(f"批量提取文字属性失败: {e}")
                # 返回默认结果
                results.append(TextStyleResult(confidence=0.0))
        return results


class CaptionModelTextAttributeExtractor(TextAttributeExtractor):
    """
    基于Caption Model（视觉语言模型）的文字属性提取器
    
    使用视觉语言模型（如Gemini）分析文字区域图像，
    通过生成JSON的方式获取字体颜色、是否粗体、是否斜体等属性。
    """
    @staticmethod
    def build_prompt(text_content: Optional[str] = None) -> str:
        """
        构建合并后的prompt
        如果text_content存在则插入提示，否则省略
        """
        if text_content:
            content_hint = f'图片中的文字内容是: "{text_content}"'
        else:
            content_hint = ""
        return get_text_attribute_extraction_prompt(content_hint=content_hint)
    
    def __init__(self, ai_service, prompt_template: Optional[str] = None):
        """
        初始化Caption Model文字属性提取器
        
        Args:
            ai_service: AIService实例（需要支持generate_json方法和图片输入）
            prompt_template: 自定义的prompt模板（可选），必须使用 {content_hint} 作为占位符
        """
        self.ai_service = ai_service
        self.prompt_template = prompt_template
    
    def supports_batch(self) -> bool:
        """当前实现不支持批量处理"""
        return False
    
    def extract(
        self,
        image: Union[str, Image.Image],
        text_content: Optional[str] = None,
        **kwargs
    ) -> TextStyleResult:
        """
        使用Caption Model提取文字样式属性
        
        Args:
            image: 文字区域的图像
            text_content: 文字内容（可选，用于辅助识别）
            **kwargs: 
                - thinking_budget: int, 思考预算，默认500
        
        Returns:
            TextStyleResult对象
        """
        thinking_budget = kwargs.get('thinking_budget', 500)
        
        try:
            # 准备图片
            if isinstance(image, str):
                pil_image = Image.open(image)
            else:
                pil_image = image
            
            # 构建prompt
            # 统一使用 content_hint 格式
            if text_content:
                content_hint = f'图片中的文字内容是: "{text_content}"'
            else:
                content_hint = ""
            
            if self.prompt_template:
                # 自定义模板必须使用 {content_hint} 占位符
                prompt = self.prompt_template.format(content_hint=content_hint)
            else:
                prompt = get_text_attribute_extraction_prompt(content_hint=content_hint)
            
            # 调用AI服务（需要支持图片输入的generate_json）
            # 这里假设text_provider支持带图片的generate方法
            result_json = self._call_vision_model(pil_image, prompt, thinking_budget)
            
            # 解析结果
            return self._parse_result(result_json)
        
        except Exception as e:
            logger.error(f"CaptionModelTextAttributeExtractor提取失败: {e}", exc_info=True)
            return TextStyleResult(confidence=0.0, metadata={'error': str(e)})
    
    def _call_vision_model(self, image: Image.Image, prompt: str, thinking_budget: int) -> Dict[str, Any]:
        """
        调用视觉语言模型，使用 ai_service.generate_json_with_image（带重试机制）
        
        Args:
            image: PIL Image对象
            prompt: 提示词
            thinking_budget: 思考预算
        
        Returns:
            解析后的JSON结果
        """
        import tempfile
        import os
        
        # 保存临时图片文件
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
            tmp_path = tmp_file.name
            image.save(tmp_path)
        
        try:
            # 使用 ai_service.generate_json_with_image（带重试机制）
            result = self.ai_service.generate_json_with_image(
                prompt=prompt,
                image_path=tmp_path,
                thinking_budget=thinking_budget
            )
            return result if isinstance(result, dict) else {}

        except ValueError as e:
            if "不支持图片输入" in str(e):
                raise RuntimeError(f"当前图片样式提取模型不支持图片输入: {e}") from e
            raise RuntimeError(f"视觉模型返回内容无法解析: {e}") from e

        except Exception as e:
            raise RuntimeError(f"调用视觉模型提取文本样式失败: {e}") from e
        
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    
    def _parse_result(self, result_json: Dict[str, Any]) -> TextStyleResult:
        """
        解析AI返回的JSON结果
        
        Args:
            result_json: AI返回的JSON字典，支持两种格式：
                - 新格式：包含 colored_segments 数组（文字-颜色对）
                - 旧格式：包含 font_color 单一颜色
        
        Returns:
            TextStyleResult对象
        """
        if not result_json:
            return TextStyleResult(
                confidence=0.0,
                metadata={'error': '视觉模型未返回可解析的样式结果'}
            )
        
        try:
            # 解析 colored_segments（新格式：支持一行多颜色）
            colored_segments = []
            segments_data = result_json.get('colored_segments', [])
            
            if segments_data and isinstance(segments_data, list):
                for seg in segments_data:
                    if isinstance(seg, dict):
                        colored_segments.append(ColoredSegment.from_dict(seg))
            
            # 计算默认颜色（从 segments 取第一个，或用旧格式的 font_color）
            if colored_segments:
                font_color_rgb = colored_segments[0].color_rgb
            else:
                # 兼容旧格式
                font_color_hex = result_json.get('font_color', '#000000')
                if isinstance(font_color_hex, str):
                    font_color_rgb = hex_to_rgb(font_color_hex)
                else:
                    font_color_rgb = (0, 0, 0)
            
            # 解析布尔值
            is_bold = bool(result_json.get('is_bold', False))
            is_italic = bool(result_json.get('is_italic', False))
            is_underline = bool(result_json.get('is_underline', False))
            
            # 解析文字对齐方式
            text_alignment = result_json.get('text_alignment')
            if text_alignment not in ('left', 'center', 'right', 'justify', None):
                text_alignment = None
            
            return TextStyleResult(
                font_color_rgb=font_color_rgb,
                colored_segments=colored_segments,
                is_bold=is_bold,
                is_italic=is_italic,
                is_underline=is_underline,
                text_alignment=text_alignment,
                font_family=result_json.get('font_family'),
                confidence=0.9,  # 模型返回的结果给予较高置信度
                metadata={'source': 'caption_model', 'raw_response': result_json}
            )
        
        except Exception as e:
            logger.error(f"解析结果失败: {e}")
            return TextStyleResult(confidence=0.0, metadata={'error': str(e)})
    
    def extract_batch_with_full_image(
        self,
        full_image: Union[str, Image.Image],
        text_elements: List[Dict[str, Any]],
        **kwargs
    ) -> Dict[str, TextStyleResult]:
        """
        【新逻辑】使用全图一次性提取所有文本元素的样式属性
        
        优势：模型可以看到全局上下文，提高分析准确性
        
        Args:
            full_image: 完整的页面图片，可以是文件路径或PIL Image对象
            text_elements: 文本元素列表，每个元素包含：
                - element_id: 元素唯一标识
                - bbox: 边界框 [x0, y0, x1, y1]
                - content: 文字内容
            **kwargs:
                - thinking_budget: int, 思考预算，默认1000
        
        Returns:
            字典，key为element_id，value为TextStyleResult
        """
        import json
        import tempfile
        from services.prompts import get_batch_text_attribute_extraction_prompt
        
        thinking_budget = kwargs.get('thinking_budget', 1000)
        
        if not text_elements:
            return {}
        
        try:
            # 准备图片
            if isinstance(full_image, str):
                pil_image = Image.open(full_image)
                tmp_path = full_image  # 如果已经是路径，直接使用
                need_cleanup = False
            else:
                pil_image = full_image
                # 保存临时图片文件
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
                    tmp_path = tmp_file.name
                    pil_image.save(tmp_path)
                need_cleanup = True
            
            # 构建文本元素的 JSON 描述
            elements_for_prompt = []
            for elem in text_elements:
                elements_for_prompt.append({
                    'element_id': elem['element_id'],
                    'bbox': elem['bbox'],
                    'content': elem['content']
                })
            
            text_elements_json = json.dumps(elements_for_prompt, ensure_ascii=False, indent=2)
            
            # 构建 prompt
            prompt = get_batch_text_attribute_extraction_prompt(text_elements_json)
            
            # 调用 ai_service.generate_json_with_image（带重试机制）
            try:
                result = self.ai_service.generate_json_with_image(
                    prompt=prompt,
                    image_path=tmp_path,
                    thinking_budget=thinking_budget
                )
                
                # 确保结果是列表
                if isinstance(result, list):
                    result_list = result
                elif isinstance(result, dict):
                    # 如果返回的是字典，尝试获取列表
                    result_list = result.get('results', [result])
                else:
                    result_list = []
                
                # 解析结果
                return self._parse_batch_result(result_list, text_elements)

            except ValueError as e:
                if "不支持图片输入" in str(e):
                    raise RuntimeError(f"当前图片样式提取模型不支持图片输入: {e}") from e
                raise RuntimeError(f"视觉模型返回内容无法解析: {e}") from e

            except Exception as e:
                raise RuntimeError(f"批量调用视觉模型提取文本样式失败: {e}") from e
                
            finally:
                if need_cleanup:
                    import os
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
        
        except Exception as e:
            logger.error(f"批量提取文字属性失败: {e}", exc_info=True)
            raise
    
    def _parse_batch_result(
        self,
        result_list: List[Dict[str, Any]],
        original_elements: List[Dict[str, Any]]
    ) -> Dict[str, TextStyleResult]:
        """
        解析批量提取的 AI 返回结果
        
        Args:
            result_list: AI 返回的 JSON 列表，每个元素包含样式属性
            original_elements: 原始输入的元素列表，用于匹配 element_id
        
        Returns:
            字典，key 为 element_id，value 为 TextStyleResult
        """
        results = {}
        
        # 创建 element_id 到原始元素的映射，用于回退
        original_map = {elem['element_id']: elem for elem in original_elements}
        
        for item in result_list:
            try:
                element_id = item.get('element_id')
                if not element_id:
                    continue
                
                # 解析颜色（十六进制格式）
                font_color_hex = item.get('font_color', '#000000')
                if isinstance(font_color_hex, str):
                    font_color_rgb = hex_to_rgb(font_color_hex)
                else:
                    font_color_rgb = (0, 0, 0)
                
                # 解析布尔值
                is_bold = bool(item.get('is_bold', False))
                is_italic = bool(item.get('is_italic', False))
                is_underline = bool(item.get('is_underline', False))
                
                # 解析文字对齐方式
                text_alignment = item.get('text_alignment')
                if text_alignment not in ('left', 'center', 'right', 'justify', None):
                    text_alignment = None
                
                results[element_id] = TextStyleResult(
                    font_color_rgb=font_color_rgb,
                    is_bold=is_bold,
                    is_italic=is_italic,
                    is_underline=is_underline,
                    text_alignment=text_alignment,
                    font_family=item.get('font_family'),
                    confidence=0.9,
                    metadata={'source': 'batch_caption_model', 'raw_response': item}
                )
                
            except Exception as e:
                logger.warning(f"解析元素 {item.get('element_id', 'unknown')} 的样式失败: {e}")
                continue
        
        logger.info(f"批量解析完成: 成功 {len(results)}/{len(original_elements)} 个元素")
        return results


class AzureOCRTextAttributeExtractor(TextAttributeExtractor):
    """
    基于 Azure OCR 的文字样式提取器

    Azure Document Intelligence 可以直接返回字体、颜色、粗细等属性，
    因此导出时优先走单次全图识别，避免逐个裁剪重复调用外部 OCR。
    """

    prefer_full_image_extraction = True

    def __init__(self, ocr_provider):
        self._ocr_provider = ocr_provider

    def supports_batch(self) -> bool:
        return True

    def extract(
        self,
        image: Union[str, Image.Image],
        text_content: Optional[str] = None,
        **kwargs
    ) -> TextStyleResult:
        image_path, need_cleanup = self._ensure_image_path(image)
        try:
            result = self._ocr_provider.recognize(image_path)
            return self._build_text_style(
                matched_lines=result.get('text_lines', []),
                text_content=text_content,
            )
        except Exception as e:
            logger.error(f"Azure OCR 单图样式提取失败: {e}", exc_info=True)
            return TextStyleResult(confidence=0.0, metadata={'error': str(e)})
        finally:
            self._cleanup_temp_path(image_path, need_cleanup)

    def extract_batch_with_full_image(
        self,
        full_image: Union[str, Image.Image],
        text_elements: List[Dict[str, Any]],
        **kwargs
    ) -> Dict[str, TextStyleResult]:
        image_path, need_cleanup = self._ensure_image_path(full_image)
        try:
            result = self._ocr_provider.recognize(image_path)
            ocr_lines = result.get('text_lines', [])
            styles = {}
            for element in text_elements:
                matched_lines = self._match_lines_to_element(element, ocr_lines)
                if matched_lines:
                    styles[element['element_id']] = self._build_text_style(
                        matched_lines=matched_lines,
                        text_content=element.get('content'),
                        element_bbox=element.get('bbox'),
                    )
            return styles
        except Exception as e:
            logger.error(f"Azure OCR 批量样式提取失败: {e}", exc_info=True)
            raise RuntimeError(f"Azure OCR 批量样式提取失败: {e}") from e
        finally:
            self._cleanup_temp_path(image_path, need_cleanup)

    def _match_lines_to_element(
        self,
        element: Dict[str, Any],
        ocr_lines: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        element_bbox = element.get('bbox', [0, 0, 0, 0])
        target_text = self._normalize_text(element.get('content', ''))
        matches = []

        for line in ocr_lines:
            line_bbox = line.get('bbox', [0, 0, 0, 0])
            overlap_ratio = self._intersection_ratio(element_bbox, line_bbox)
            if self._bbox_center_inside(line_bbox, element_bbox):
                overlap_ratio = max(overlap_ratio, 0.45)

            line_text = self._normalize_text(line.get('text', ''))
            text_score = 0.0
            if target_text and line_text:
                if target_text in line_text:
                    text_score = 1.0
                elif line_text in target_text:
                    text_score = 0.8

            score = overlap_ratio + text_score
            if score >= 0.45:
                matches.append((score, line))

        matches.sort(
            key=lambda item: (
                item[1].get('bbox', [0, 0, 0, 0])[1],
                item[1].get('bbox', [0, 0, 0, 0])[0]
            )
        )
        return [line for _, line in matches]

    def _build_text_style(
        self,
        matched_lines: List[Dict[str, Any]],
        text_content: Optional[str] = None,
        element_bbox: Optional[List[int]] = None,
    ) -> TextStyleResult:
        if not matched_lines:
            return TextStyleResult(confidence=0.0, metadata={'error': 'Azure OCR 未返回匹配文本'})

        font_families: Dict[str, int] = {}
        font_colors: Dict[str, int] = {}
        bold_hits = 0
        italic_hits = 0

        for line in matched_lines:
            style = line.get('style', {}) or {}
            font_family = style.get('font_family')
            if font_family:
                font_families[font_family] = font_families.get(font_family, 0) + 1
            font_color = style.get('font_color')
            if font_color:
                font_colors[font_color] = font_colors.get(font_color, 0) + 1
            font_weight = str(style.get('font_weight') or '').lower()
            if font_weight in {'bold', 'bolder', 'semibold', '600', '700', '800', '900'}:
                bold_hits += 1
            font_style = str(style.get('font_style') or '').lower()
            if font_style == 'italic':
                italic_hits += 1

        dominant_family = max(font_families, key=font_families.get) if font_families else None
        dominant_color = max(font_colors, key=font_colors.get) if font_colors else '#000000'

        return TextStyleResult(
            font_color_rgb=hex_to_rgb(dominant_color),
            is_bold=bold_hits > 0,
            is_italic=italic_hits > 0,
            is_underline=False,
            text_alignment=self._infer_alignment(element_bbox, matched_lines),
            font_family=dominant_family,
            confidence=0.95,
            metadata={
                'source': 'azure_ocr',
                'matched_line_count': len(matched_lines),
                'text_content': text_content,
            }
        )

    @staticmethod
    def _infer_alignment(
        element_bbox: Optional[List[int]],
        matched_lines: List[Dict[str, Any]]
    ) -> Optional[str]:
        if not element_bbox or not matched_lines:
            return None

        left_gaps = []
        right_gaps = []
        centers = []
        element_width = max(1, element_bbox[2] - element_bbox[0])

        for line in matched_lines:
            bbox = line.get('bbox', [0, 0, 0, 0])
            left_gaps.append(max(0, bbox[0] - element_bbox[0]))
            right_gaps.append(max(0, element_bbox[2] - bbox[2]))
            centers.append((bbox[0] + bbox[2]) / 2)

        avg_left = sum(left_gaps) / len(left_gaps)
        avg_right = sum(right_gaps) / len(right_gaps)
        avg_center = sum(centers) / len(centers)
        element_center = (element_bbox[0] + element_bbox[2]) / 2

        if abs(avg_center - element_center) <= element_width * 0.08 and abs(avg_left - avg_right) <= element_width * 0.12:
            return 'center'
        if avg_right < element_width * 0.08 and avg_left > element_width * 0.2:
            return 'right'
        return 'left'

    @staticmethod
    def _ensure_image_path(image: Union[str, Image.Image]) -> Tuple[str, bool]:
        import tempfile

        if isinstance(image, str):
            return image, False

        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp_file:
            tmp_path = tmp_file.name
            image.save(tmp_path)
        return tmp_path, True

    @staticmethod
    def _cleanup_temp_path(path: str, should_cleanup: bool) -> None:
        import os

        if should_cleanup and os.path.exists(path):
            os.remove(path)

    @staticmethod
    def _normalize_text(text: str) -> str:
        return ''.join(text.split()).lower()

    @staticmethod
    def _intersection_ratio(a: List[int], b: List[int]) -> float:
        x0 = max(a[0], b[0])
        y0 = max(a[1], b[1])
        x1 = min(a[2], b[2])
        y1 = min(a[3], b[3])
        if x1 <= x0 or y1 <= y0:
            return 0.0
        inter = (x1 - x0) * (y1 - y0)
        b_area = max(1, (b[2] - b[0]) * (b[3] - b[1]))
        return inter / b_area

    @staticmethod
    def _bbox_center_inside(inner: List[int], outer: List[int]) -> bool:
        center_x = (inner[0] + inner[2]) / 2
        center_y = (inner[1] + inner[3]) / 2
        return outer[0] <= center_x <= outer[2] and outer[1] <= center_y <= outer[3]


class TextAttributeExtractorRegistry:
    """
    文字属性提取器注册表
    
    管理不同元素类型应该使用哪个文字属性提取器：
    - 普通文本 → CaptionModelTextAttributeExtractor
    - 标题文本 → 可使用不同配置的提取器
    - 其他类型 → 默认提取器
    
    使用方式：
        >>> registry = TextAttributeExtractorRegistry()
        >>> registry.register('text', caption_extractor)
        >>> registry.register('title', title_extractor)
        >>> registry.register_default(caption_extractor)
        >>> 
        >>> extractor = registry.get_extractor('text')
        >>> extractor = registry.get_extractor('unknown_type')  # 返回默认提取器
    """
    
    # 预定义的元素类型分组
    TEXT_TYPES = {'text', 'title', 'paragraph', 'heading', 'header', 'footer', 'list'}
    TABLE_TEXT_TYPES = {'table_cell'}
    
    def __init__(self):
        """初始化注册表"""
        self._type_mapping: Dict[str, TextAttributeExtractor] = {}
        self._default_extractor: Optional[TextAttributeExtractor] = None
    
    def register(self, element_type: str, extractor: TextAttributeExtractor) -> 'TextAttributeExtractorRegistry':
        """
        注册元素类型到提取器的映射
        
        Args:
            element_type: 元素类型（如 'text', 'title' 等）
            extractor: 对应的提取器实例
        
        Returns:
            self，支持链式调用
        """
        self._type_mapping[element_type] = extractor
        logger.debug(f"注册文字属性提取器: {element_type} -> {extractor.__class__.__name__}")
        return self
    
    def register_types(self, element_types: List[str], extractor: TextAttributeExtractor) -> 'TextAttributeExtractorRegistry':
        """
        批量注册多个元素类型到同一个提取器
        
        Args:
            element_types: 元素类型列表
            extractor: 对应的提取器实例
        
        Returns:
            self，支持链式调用
        """
        for t in element_types:
            self.register(t, extractor)
        return self
    
    def register_default(self, extractor: TextAttributeExtractor) -> 'TextAttributeExtractorRegistry':
        """
        注册默认提取器（当没有特定类型映射时使用）
        
        Args:
            extractor: 默认提取器实例
        
        Returns:
            self，支持链式调用
        """
        self._default_extractor = extractor
        logger.debug(f"注册默认文字属性提取器: {extractor.__class__.__name__}")
        return self
    
    def get_extractor(self, element_type: Optional[str]) -> Optional[TextAttributeExtractor]:
        """
        根据元素类型获取对应的提取器
        
        Args:
            element_type: 元素类型，None表示使用默认提取器
        
        Returns:
            对应的提取器，如果没有注册则返回默认提取器
        """
        if element_type is None:
            return self._default_extractor
        
        # 先查找精确匹配
        if element_type in self._type_mapping:
            return self._type_mapping[element_type]
        
        # 返回默认提取器
        return self._default_extractor
    
    def get_all_extractors(self) -> List[TextAttributeExtractor]:
        """
        获取所有已注册的提取器（去重）
        
        Returns:
            提取器列表
        """
        extractors = list(set(self._type_mapping.values()))
        if self._default_extractor and self._default_extractor not in extractors:
            extractors.append(self._default_extractor)
        return extractors
    
    @classmethod
    def create_default(
        cls,
        caption_extractor: Optional[TextAttributeExtractor] = None
    ) -> 'TextAttributeExtractorRegistry':
        """
        创建默认配置的注册表
        
        默认配置：
        - 所有文本类型 → CaptionModelTextAttributeExtractor
        - 其他类型 → 默认提取器
        
        Args:
            caption_extractor: Caption Model提取器实例
        
        Returns:
            配置好的注册表实例
        """
        registry = cls()
        
        if not caption_extractor:
            logger.warning("创建TextAttributeExtractorRegistry时未提供任何extractor")
            return registry
        
        # 设置默认提取器
        registry.register_default(caption_extractor)
        
        # 所有文本类型使用相同的提取器
        registry.register_types(list(cls.TEXT_TYPES), caption_extractor)
        registry.register_types(list(cls.TABLE_TEXT_TYPES), caption_extractor)
        
        logger.info(f"创建默认TextAttributeExtractorRegistry: "
                   f"默认提取器->{caption_extractor.__class__.__name__}")
        
        return registry
