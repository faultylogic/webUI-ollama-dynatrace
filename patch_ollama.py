with open('/app/backend/open_webui/routers/ollama.py', 'r') as f:
    content = f.read()

target = '        r = await session.request(\n            method,\n            url,\n            data=payload,'

new = """        _model = 'unknown'
        _last_user = None
        try:
            import json as _json
            _body = _json.loads(payload) if isinstance(payload, (str, bytes)) else {}
            _model = _body.get('model', 'unknown')
            _messages = _body.get('messages', [])
            _last_user = next((m['content'] for m in reversed(_messages) if m.get('role') == 'user'), None)
        except Exception as _ex:
            import logging as _logging
            _logging.getLogger('otel.ollama.patch').error(f'PATCH ERROR: {_ex}')
        r = await session.request(
            method,
            url,
            data=payload,"""

old_stream = """            streaming = True
            return StreamingResponse(
                stream_wrapper(r),
                status_code=r.status,
                headers=response_headers,
            )"""

new_stream = """            streaming = True

            async def _otel_stream_wrapper(response, model, prompt):
                import json as _json
                from opentelemetry import trace as _otel_trace
                from opentelemetry.trace import SpanKind as _SpanKind
                _completion_parts = []
                _prompt_tokens = 0
                _completion_tokens = 0
                try:
                    async for chunk in stream_wrapper(response):
                        yield chunk
                        try:
                            _data = _json.loads(chunk)
                            if _data.get('done'):
                                _prompt_tokens = _data.get('prompt_eval_count', 0)
                                _completion_tokens = _data.get('eval_count', 0)
                            msg = _data.get('message', {})
                            if isinstance(msg, dict) and msg.get('content'):
                                _completion_parts.append(msg['content'])
                        except Exception:
                            pass
                finally:
                    try:
                        _is_task = prompt and str(prompt).strip().startswith('###')
                        if not _is_task:
                            _tracer = _otel_trace.get_tracer('ollama.patch')
                            _completion = ''.join(_completion_parts)[:2000]
                            _input_msg = _json.dumps([{'role': 'user', 'content': str(prompt)[:1000] if prompt else ''}])
                            _output_msg = _json.dumps([{'role': 'assistant', 'content': _completion}])
                            with _tracer.start_as_current_span(
                                f'chat {model}',
                                kind=_SpanKind.CLIENT,
                            ) as _s:
                                _s.set_attribute('gen_ai.provider.name', 'ollama')
                                _s.set_attribute('gen_ai.system', 'ollama')
                                _s.set_attribute('gen_ai.operation.name', 'chat')
                                _s.set_attribute('gen_ai.operation.kind', 'llm')
                                _s.set_attribute('gen_ai.request.model', model)
                                _s.set_attribute('gen_ai.response.model', model)
                                _s.set_attribute('gen_ai.prompt', str(prompt)[:1000] if prompt else '')
                                _s.set_attribute('gen_ai.input.messages', _input_msg)
                                _s.set_attribute('gen_ai.output.messages', _output_msg)
                                _s.set_attribute('gen_ai.completion', _completion)
                                _s.set_attribute('gen_ai.usage.input_tokens', _prompt_tokens)
                                _s.set_attribute('gen_ai.usage.output_tokens', _completion_tokens)
                                _s.add_event('gen_ai.choice', {
                                    'gen_ai.event.content': _completion[:1000],
                                    'index': 0,
                                })
                    except Exception:
                        pass

            return StreamingResponse(
                _otel_stream_wrapper(r, _model, _last_user),
                status_code=r.status,
                headers=response_headers,
            )"""

if target in content:
    content = content.replace(target, new)
    print('Patch 1 applied (variable extraction)')
else:
    print('Patch 1 target not found')

if old_stream in content:
    content = content.replace(old_stream, new_stream)
    print('Patch 2 applied (stream wrapper)')
else:
    print('Patch 2 target not found')

with open('/app/backend/open_webui/routers/ollama.py', 'w') as f:
    f.write(content)
