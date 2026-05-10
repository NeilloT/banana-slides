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


def test_azure_provider_prefers_spans_over_bbox_overlap():
    provider = AzureDocumentIntelligenceOCRProvider(
        endpoint='https://example.cognitiveservices.azure.com',
        api_key='test-key',
    )

    analyze_result = {
        'content': 'Span Match',
        'pages': [
            {
                'width': 1000,
                'height': 500,
                'unit': 'pixel',
                'words': [
                    {
                        'content': 'Span',
                        'confidence': 0.99,
                        'polygon': [700, 100, 820, 100, 820, 160, 700, 160],
                        'span': {'offset': 0, 'length': 4},
                    },
                ],
                'lines': [
                    {
                        'content': 'Span Match',
                        'polygon': [100, 100, 260, 100, 260, 160, 100, 160],
                        'spans': [{'offset': 0, 'length': 10}],
                    }
                ],
            }
        ],
    }

    normalized = provider._normalize_result(analyze_result=analyze_result, image_size=(1000, 500))

    line = normalized['text_lines'][0]
    assert [word['text'] for word in line['words']] == ['Span']


def test_poll_result_rejects_unknown_status():
    provider = AzureDocumentIntelligenceOCRProvider(
        endpoint='https://example.cognitiveservices.azure.com',
        api_key='test-key',
    )

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {'status': 'queued'}

    class FakeSession:
        def get(self, *_args, **_kwargs):
            return FakeResponse()

    try:
        provider._poll_result(FakeSession(), 'https://example.com/operations/1')
        assert False, 'Expected RuntimeError for unknown Azure OCR status'
    except RuntimeError as exc:
        assert 'unexpected status' in str(exc)


def test_analyze_document_reuses_single_session(monkeypatch):
    provider = AzureDocumentIntelligenceOCRProvider(
        endpoint='https://example.cognitiveservices.azure.com',
        api_key='test-key',
    )

    captured = {}

    class FakeResponse:
        headers = {'operation-location': 'https://example.com/operations/1'}

        def raise_for_status(self):
            return None

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, *_args, **_kwargs):
            return FakeResponse()

    def fake_poll_result(session, operation_location):
        captured['session'] = session
        captured['operation_location'] = operation_location
        return {'status': 'succeeded'}

    monkeypatch.setattr(
        'services.ai_providers.ocr.azure_document_intelligence_provider.requests.Session',
        FakeSession,
    )
    monkeypatch.setattr(provider, '_poll_result', fake_poll_result)

    result = provider._analyze_document(b'fake-image')

    assert result == {'status': 'succeeded'}
    assert isinstance(captured['session'], FakeSession)
    assert captured['session'].headers['Ocp-Apim-Subscription-Key'] == 'test-key'
    assert captured['operation_location'] == 'https://example.com/operations/1'
