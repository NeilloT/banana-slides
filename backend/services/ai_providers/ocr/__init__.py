"""OCR相关的AI Provider"""

import logging

from services.ai_providers.ocr.baidu_table_ocr_provider import (
    BaiduTableOCRProvider,
    create_baidu_table_ocr_provider
)
from services.ai_providers.ocr.baidu_accurate_ocr_provider import (
    BaiduAccurateOCRProvider,
    create_baidu_accurate_ocr_provider
)
from services.ai_providers.ocr.azure_document_intelligence_provider import (
    AzureDocumentIntelligenceOCRProvider,
    create_azure_document_intelligence_provider,
)

logger = logging.getLogger(__name__)


def create_text_ocr_provider(provider_name=None):
    """Create the configured text OCR provider for editable PPTX export."""
    from config import Config

    requested_provider = provider_name.lower() if provider_name else None

    if provider_name is None:
        try:
            from flask import current_app
            provider_name = current_app.config.get('OCR_PROVIDER')
        except RuntimeError:
            provider_name = None

    provider_name = (provider_name or Config.OCR_PROVIDER or 'baidu').lower()

    if provider_name == 'azure':
        provider = create_azure_document_intelligence_provider()
        if provider:
            return provider
        if requested_provider == 'azure':
            return None
        logger.warning("Azure OCR 不可用，回退到百度高精度 OCR")

    return create_baidu_accurate_ocr_provider()

__all__ = [
    'BaiduTableOCRProvider',
    'create_baidu_table_ocr_provider',
    'BaiduAccurateOCRProvider',
    'create_baidu_accurate_ocr_provider',
    'AzureDocumentIntelligenceOCRProvider',
    'create_azure_document_intelligence_provider',
    'create_text_ocr_provider',
]
