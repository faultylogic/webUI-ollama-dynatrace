# open-webui-dynatrace

A custom Docker image that adds full AI observability to [Open WebUI](https://github.com/open-webui/open-webui) by integrating Traceloop OpenLLMetry and OpenTelemetry, with traces, metrics, logs, and LLM-specific telemetry exported to Dynatrace.

## What this adds

Out of the box, Open WebUI has basic OpenTelemetry support but it defaults to gRPC and lacks LLM-specific semantic attributes. This image patches Open WebUI at build time to:

- Switch OTLP export from gRPC to HTTP/protobuf (required for Dynatrace)
- Initialize [Traceloop](https://www.traceloop.com/openllmetry) for OpenLLMetry instrumentation
- Instrument aiohttp for outbound HTTP tracing to Ollama
- Capture LLM-specific `gen_ai.*` span attributes on every chat request, including prompt, completion, model, and token counts
- Filter out internal Open WebUI background tasks from the AI Observability prompts stream
- Export all telemetry to Dynatrace AI Observability

### Span attributes captured

| Attribute | Description |
|---|---|
| `gen_ai.provider.name` | Always `ollama` |
| `gen_ai.operation.name` | Always `chat` |
| `gen_ai.request.model` | The model used (e.g. `llama3.2:latest`) |
| `gen_ai.response.model` | The model that responded |
| `gen_ai.input.messages` | JSON array of the user prompt |
| `gen_ai.output.messages` | JSON array of the assistant response |
| `gen_ai.prompt` | Raw user prompt text (up to 1000 chars) |
| `gen_ai.completion` | Raw assistant response text (up to 2000 chars) |
| `gen_ai.usage.input_tokens` | Prompt token count from Ollama |
| `gen_ai.usage.output_tokens` | Completion token count from Ollama |

---

## Architecture

```
Browser → Open WebUI (patched) → Ollama
                ↓
         Dynatrace OTLP
     (traces, metrics, logs)
```

The image is built on top of `ghcr.io/open-webui/open-webui:main` with two Python patch scripts applied at build time:

- **`patch_main.py`** — injects Traceloop init and aiohttp instrumentation into Open WebUI's startup
- **`patch_ollama.py`** — wraps the Ollama streaming response to capture LLM semantic attributes

---

## Prerequisites

- Docker and Docker Compose
- A Dynatrace environment with OTLP ingestion enabled
- A Dynatrace API token with `openTelemetryTrace.ingest`, `metrics.ingest`, and `logs.ingest` scopes
- Ollama running (included in the compose file)

---

## Deployment

### Nvidia GPU (Windows/Linux)

```yaml
services:
  ollama:
    volumes:
      - ollama_data:/root/.ollama
    container_name: ollama
    pull_policy: always
    tty: true
    restart: unless-stopped
    image: ollama/ollama:latest
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]

  open-webui:
    image: faultylogic/open-webui-dynatrace:latest
    container_name: open-webui
    ports:
      - "3000:8080"
    volumes:
      - open-webui_data:/app/backend/data
    environment:
      - 'OLLAMA_BASE_URL=http://ollama:11434'
      - ENABLE_OTEL=true
      - ENABLE_OTEL_TRACES=true
      - ENABLE_OTEL_METRICS=true
      - ENABLE_OTEL_LOGS=true
      - OTEL_EXPORTER_OTLP_ENDPOINT=https://<YOUR_ENV>.live.dynatrace.com/api/v2/otlp/v1/traces
      - OTEL_METRICS_EXPORTER_OTLP_ENDPOINT=https://<YOUR_ENV>.live.dynatrace.com/api/v2/otlp/v1/metrics
      - OTEL_LOGS_EXPORTER_OTLP_ENDPOINT=https://<YOUR_ENV>.live.dynatrace.com/api/v2/otlp/v1/logs
      - OTEL_OTLP_SPAN_EXPORTER=http
      - OTEL_METRICS_OTLP_SPAN_EXPORTER=http
      - OTEL_LOGS_OTLP_SPAN_EXPORTER=http
      - OTEL_EXPORTER_OTLP_HEADERS=Authorization=Api-Token <YOUR_DT_API_TOKEN>
      - OTEL_SERVICE_NAME=open-webui
    restart: unless-stopped
    depends_on:
      - ollama

volumes:
  ollama_data:
  open-webui_data:
```

### Apple Silicon (M-series Mac)

Same as above but remove the `deploy` block from the `ollama` service — Ollama handles Metal GPU acceleration automatically on M-series with no extra configuration.

### Running

```bash
docker compose up -d
```

Open WebUI will be available at `http://localhost:3000`.

---

## Environment variables

| Variable | Description |
|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Dynatrace OTLP traces endpoint (`/api/v2/otlp/v1/traces`) |
| `OTEL_METRICS_EXPORTER_OTLP_ENDPOINT` | Dynatrace OTLP metrics endpoint (`/api/v2/otlp/v1/metrics`) |
| `OTEL_LOGS_EXPORTER_OTLP_ENDPOINT` | Dynatrace OTLP logs endpoint (`/api/v2/otlp/v1/logs`) |
| `OTEL_EXPORTER_OTLP_HEADERS` | `Authorization=Api-Token <YOUR_DT_API_TOKEN>` |
| `OTEL_SERVICE_NAME` | Service name shown in Dynatrace (default: `open-webui`) |
| `OTEL_OTLP_SPAN_EXPORTER` | Must be `http` (not `grpc`) |
| `OTEL_METRICS_OTLP_SPAN_EXPORTER` | Must be `http` |
| `OTEL_LOGS_OTLP_SPAN_EXPORTER` | Must be `http` |
| `ENABLE_OTEL` | Enable OTEL (`true`) |
| `ENABLE_OTEL_TRACES` | Enable trace export (`true`) |
| `ENABLE_OTEL_METRICS` | Enable metrics export (`true`) |
| `ENABLE_OTEL_LOGS` | Enable log export (`true`) |

---

## Validating in Dynatrace

After sending a chat message, use these DQL queries in Dynatrace Notebooks to validate:

**Confirm spans are arriving:**
```dql
fetch spans
| filter service.name == "open-webui"
| filter isNotNull(`gen_ai.provider.name`)
| fields start_time, span.name, `gen_ai.request.model`, `gen_ai.prompt`, `gen_ai.completion`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`
| sort start_time desc
| limit 20
```

**Ollama inference latency:**
```dql
fetch spans
| filter service.name == "open-webui"
| filter http.url == "http://ollama:11434/api/chat"
| filter http.method == "POST"
| summarize avg_duration = avg(duration), requests = count(), by: bin(start_time, 1h)
| sort start_time desc
```

**Token usage over time:**
```dql
fetch spans
| filter service.name == "open-webui"
| filter isNotNull(`gen_ai.usage.output_tokens`)
| summarize total_input = sum(toLong(`gen_ai.usage.input_tokens`)), total_output = sum(toLong(`gen_ai.usage.output_tokens`)), by: bin(start_time, 1h)
| sort start_time desc
```

The **AI Observability** app in Dynatrace will show prompts, completions, token counts, and latency in the Prompts stream once data is flowing.

---

## Building from source

If you want to build and push the image yourself:

```bash
git clone <this-repo>
cd <this-repo>
docker build -t <your-dockerhub-username>/open-webui-dynatrace:latest .
docker push <your-dockerhub-username>/open-webui-dynatrace:latest
```

### Project structure

```
.
├── Dockerfile          # Extends open-webui:main, installs deps, runs patches
├── docker-compose.yml  # Compose file for open-webui + ollama
├── patch_main.py       # Patches Open WebUI startup with Traceloop + aiohttp instrumentation
└── patch_ollama.py     # Patches Ollama router to capture gen_ai.* span attributes
```

---

## Known limitations

- **Ollama native OTEL** — Ollama does not yet have native OpenTelemetry support. Inference-side metrics (GPU utilization, queue depth) are not available. This will improve when Ollama ships native OTEL.
- **Token counts** — Token counts are parsed from Ollama's streaming response final chunk (`prompt_eval_count` and `eval_count`). If Ollama changes its response format these may stop populating.
- **Non-streaming requests** — The patch only wraps streaming responses. Non-streaming Ollama calls (rare in Open WebUI) will not have `gen_ai.completion` or token attributes.
- **Image updates** — When `ghcr.io/open-webui/open-webui:main` updates, the patch target strings may shift. Rebuild with `--no-cache` if patches stop applying after an upstream update.

---

## Docker Hub

```
faultylogic/open-webui-dynatrace:latest
```

[https://hub.docker.com/r/faultylogic/open-webui-dynatrace](https://hub.docker.com/r/faultylogic/open-webui-dynatrace)
