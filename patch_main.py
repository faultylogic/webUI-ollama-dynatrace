with open('/app/backend/open_webui/main.py', 'r') as f:
    content = f.read()

injection = """
    try:
        from traceloop.sdk import Traceloop
        from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor
        import os

        Traceloop.init(
            app_name=os.getenv('OTEL_SERVICE_NAME', 'open-webui'),
            api_endpoint=os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT', '').replace('/v1/traces', ''),
            headers={
                'Authorization': os.getenv('OTEL_EXPORTER_OTLP_HEADERS', '').replace('Authorization=', '')
            },
            disable_batch=False,
        )

        def request_hook(span, params):
            if span and span.is_recording():
                url = str(params.url) if hasattr(params, 'url') else ''
                if 'ollama' in url or '11434' in url:
                    span.set_attribute('llm.system', 'ollama')
                    span.set_attribute('server.address', 'ollama')

        AioHttpClientInstrumentor().instrument(request_hook=request_hook)

    except Exception as e:
        print(f'Traceloop init failed: {e}')
"""

content = content.replace(
    '    setup_opentelemetry(app=app, db_engine=engine)',
    '    setup_opentelemetry(app=app, db_engine=engine)' + injection
)

with open('/app/backend/open_webui/main.py', 'w') as f:
    f.write(content)

print('Patched main.py successfully')
print('_patched_init count:', content.count('_patched_init'))
print('AioHttpClientInstrumentor count:', content.count('AioHttpClientInstrumentor'))
