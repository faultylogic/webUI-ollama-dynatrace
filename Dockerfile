FROM ghcr.io/open-webui/open-webui:main

RUN pip install traceloop-sdk opentelemetry-instrumentation-httpx "opentelemetry-instrumentation-aiohttp-client>=0.48b0"

COPY patch_main.py /tmp/patch_main.py
COPY patch_ollama.py /tmp/patch_ollama.py
RUN python /tmp/patch_main.py
RUN python /tmp/patch_ollama.py
