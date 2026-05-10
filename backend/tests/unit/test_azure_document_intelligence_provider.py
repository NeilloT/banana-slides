from services.ai_providers.ocr.azure_document_intelligence_provider import (
    AzureDocumentIntelligenceOCRProvider,
)


def test_azure_provider_normalizes_lines_and_styles():
    provider = AzureDocumentIntelligenceOCRProvider(
        endpoint='https://example.cognitiveservices.azure.com',
        api_key='test-key',
    )

    analyze_result = {
        'content': 'Hello Azure',
        'styles': [
            {
                'similarFontFamily': 'Aptos',
                'fontStyle': 'italic',
                'fontWeight': 'bold',
                'color': '#112233',
                'spans': [{'offset': 0, 'length': 11}],
            }
        ],
        'pages': [
            {
                'width': 1000,
                'height': 500,
                'unit': 'pixel',
                'words': [
                    {
                        'content': 'Hello',
                        'confidence': 0.99,
                        'polygon': [100, 100, 300, 100, 300, 160, 100, 160],
                        'span': {'offset': 0, 'length': 5},
                    },
                    {
                        'content': 'Azure',
                        'confidence': 0.98,
                        'polygon': [320, 100, 580, 100, 580, 160, 320, 160],
                        'span': {'offset': 6, 'length': 5},
                    },
                ],
                'lines': [
                    {
                        'content': 'Hello Azure',
                        'polygon': [100, 100, 580, 100, 580, 160, 100, 160],
                        'spans': [{'offset': 0, 'length': 11}],
                    }
                ],
            }
        ],
    }

    normalized = provider._normalize_result(analyze_result=analyze_result, image_size=(1000, 500))

    assert normalized['image_size'] == (1000, 500)
    assert len(normalized['text_lines']) == 1
    line = normalized['text_lines'][0]
    assert line['text'] == 'Hello Azure'
    assert line['bbox'] == [100, 100, 580, 160]
    assert line['style']['font_family'] == 'Aptos'
    assert line['style']['font_color'] == '#112233'
    assert line['style']['font_weight'] == 'bold'
    assert line['style']['font_style'] == 'italic'
