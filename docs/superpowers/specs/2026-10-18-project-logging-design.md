# Project Logging Design

## Goal

Make operational failures across the local Xiangqi application diagnosable from retained logs while keeping credentials, user conversations, uploaded images, and sensitive board data out of logs.

## Current State

- FastAPI has no application logging policy or request correlation middleware.
- OpenAI-compatible chat failures are converted to generic messages; their underlying exception details are not retained.
- Pikafish startup errors are held in memory, while UCI startup and analysis lifecycle events are not logged.
- `start.ps1` launches API and Vite as hidden processes without redirecting stdout or stderr to retained files.
- The frontend reports request errors to the current view but has no persistent diagnostic record or correlation ID.
- The workspace currently has no `.git` directory, so this specification cannot be committed here.

## Design

### Backend logging

Use Python's standard `logging` package with one application logging configuration shared by API, LLM, and engine modules. Emit timestamped structured records to console and a project-local `logs/api.log` file using size-based rotation with bounded backups. Configure the application logger explicitly and avoid duplicating Uvicorn access records.

Add HTTP middleware that accepts a valid caller-provided request ID or creates one, returns it in the response header, and records method, route template, status code, elapsed milliseconds, and request ID. Do not record query strings, request bodies, headers, IP addresses, or user agent by default. Log uncaught request exceptions with stack traces and return the existing safe API error behavior.

Use stable event names and levels:

- `INFO`: process startup/shutdown, service readiness, request completion, engine lifecycle, and successful external model operation with duration.
- `WARNING`: expected provider failures, rejected input that reaches an application boundary, engine restart, and recoverable timeout.
- `ERROR`: unexpected exceptions, failed startup, engine protocol failures, and model transport/protocol failures that make a feature unavailable.

### Model and image recognition diagnostics

For chat, plan explanation, and vision calls, log operation name, configured model identifier, provider host only, elapsed time, and outcome. On failure, retain the exception class and a sanitized reason category. For HTTP errors, log status code without response body. Distinguish timeout, TLS verification, DNS/connectivity, non-success HTTP, malformed JSON, and response schema failures. Do not log API keys, authorization headers, complete URLs containing credentials or query strings, prompts, chat history, model output, image bytes, or recognized board contents.

The client-facing response stays concise and safe. Where current public errors already include a useful upstream status, preserve that behavior. No new endpoint exposing log contents is introduced.

### Pikafish diagnostics

Log executable and NNUE paths at startup, process ID when available, UCI handshake milestones, readiness, shutdown, and restart outcome. Record search duration and bounded parameters (`depth`, `movetime_ms`, `multipv`, `threads`, `hash_mb`) with outcome. Do not log full FEN, full move history, principal variations, or every UCI `info` line at normal log levels. Record sanitized protocol failure details, timeout, unexpected process exit, and illegal engine output with enough context to identify the phase.

### Frontend diagnostics

Generate or propagate a request ID for API calls and include it in error messages or a compact diagnostic context available in the UI. Log request start, completion, and failure to the browser console with operation, request ID, HTTP status when available, duration, and a sanitized error category. Successful routine polling remains quiet in the browser console unless explicitly debug-enabled. Do not log request payloads, user prompts, chat messages, uploaded images, FEN, or move history.

### Service launcher

Create the project `logs` directory when starting services. Log launcher lifecycle events for log-directory preparation, each process start, health-check success, service reuse, startup failure, and launcher completion. Redirect API stdout/stderr to `logs/api-process.log` and Vite stdout/stderr to `logs/web-process.log`, using append mode and a documented manual cleanup policy. Preserve the current hidden-process behavior and health wait checks. Startup failures must print the relevant log file path and tail a bounded number of recent lines without dumping environment variables.

### Retention and privacy

Keep application logs out of version control. Use bounded backend rotation (initial target: 5 MiB per file and 3 backups). Launcher process logs should also be bounded; if PowerShell redirection cannot rotate safely for a long-running process, use a small wrapper or scheduled rollover that does not interrupt the service. Document retention and cleanup. Log directories must not contain `.env` or user uploads.

## Scope

Included: Python API and domain-service operations, model provider calls, image recognition service calls, Pikafish process/search lifecycle, browser-side request failures, and the Windows launcher.

Excluded: analytics or user behavior tracking, persistent request-body/audit logging, remote log shipping, a log-viewing API/UI, changing user-facing error semantics except where needed to include a request ID, and logging every ordinary chess move or board state.

## Validation

- Unit tests verify logging configuration, request IDs and response headers, request completion fields, and exception handling.
- Model tests verify timeout, TLS, HTTP status, malformed response, and schema failures are logged with operation metadata and without secrets or payloads.
- Engine tests verify startup, handshake, timeout, protocol failure, and search completion events without board content.
- Launcher tests verify log directory creation, stdout/stderr redirection, health wait behavior, and useful failure output.
- Frontend tests verify failed requests carry correlation IDs and diagnostic logging omits payloads; successful health polling does not create noisy logs.
- Run all backend tests, all frontend tests, and the production build.
- Inspect representative captured logs and assert that configured API key, prompt text, image data, FEN, and move sequences are absent.

## Open Implementation Detail

The precise Windows process log rollover mechanism must be selected during implementation after checking what PowerShell and the installed runtime support. It must cap retained disk use and must not require exposing or rewriting service configuration.
