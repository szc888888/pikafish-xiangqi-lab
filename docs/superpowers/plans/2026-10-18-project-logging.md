# Project Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retain actionable, privacy-safe diagnostics for API, model, engine, frontend, and local service startup failures.

**Architecture:** Configure Python standard logging once and share named module loggers. Correlate browser API calls with FastAPI requests through `X-Request-ID`; retain process output separately from rotating API application logs. Emit event metadata only, excluding request bodies and board/chat/image content.

**Tech Stack:** Python 3.11+, FastAPI/Starlette, Python `logging.handlers.RotatingFileHandler`, Vue 3 + TypeScript, Vitest, PowerShell.

**Spec:** `docs/superpowers/specs/2026-10-18-project-logging-design.md`

## Global Constraints

- Keep Python dependencies unchanged; use the standard `logging` package.
- Never log API keys, authorization headers, prompts, chat history, model output, image bytes, recognized board contents, full FEN, full move history, or principal variations.
- Do not log request bodies, query strings, headers, IP addresses, or user agent by default.
- Log directories and files must be excluded from version control.
- Backend rotation target: 5 MiB per file and 3 backups.
- Do not add a log viewing endpoint, remote shipping, analytics, or per-move logging.
- The workspace has no `.git` directory; do not include commit steps or attempt commits.

---

## File Map

- Create `apps/api/app/logging_config.py` for idempotent logger configuration and safe exception classification helpers.
- Modify `apps/api/app/main.py` for startup/shutdown, request ID middleware, request completion, and API-level failure events.
- Modify `apps/api/app/llm.py` for provider operation timing and sanitized failure diagnostics.
- Modify `apps/api/app/engine.py` for Pikafish lifecycle, protocol, and search events.
- Modify `apps/web/src/lib/api.ts` for request IDs, response correlation, and payload-free failure diagnostics.
- Modify `apps/web/src/App.vue` only if necessary to surface request IDs in actionable error text without duplicating console logs.
- Modify `start.ps1` to create logs, redirect process output, cap retained launcher logs, and show a short log tail on startup failure.
- Modify `.gitignore` and `README.md` for log exclusion and retention/inspection instructions.
- Extend `apps/api/tests/test_coach_features.py`, `apps/api/tests/test_engine.py`, and `apps/api/tests/test_start_dev_script.py` for backend logging contracts.
- Extend `apps/web/src/lib/api.test.ts` for browser request correlation and redaction.

### Task 1: Backend Logging Configuration and HTTP Correlation

**Files:**
- Create: `apps/api/app/logging_config.py`
- Modify: `apps/api/app/main.py`
- Modify: `.gitignore`
- Test: `apps/api/tests/test_coach_features.py`

**Interfaces:**
- Produces `configure_logging(project_root: Path | None = None) -> None`, safe to call more than once.
- Produces `get_logger(name: str) -> logging.Logger` for application modules.
- Middleware accepts or generates a bounded safe `X-Request-ID`, returns it as a response header, and logs method, route template, status, duration, and ID.

- [ ] **Step 1: Add failing logger configuration tests**

Test that configuration installs console and rotating file handlers, writes under `<project_root>/logs/api.log`, rotates at 5 MiB with 3 backups, and can be called twice without adding duplicate handlers. Capture records and assert formatter includes timestamp, level, logger, event, and request ID fields.

- [ ] **Step 2: Run the targeted tests and confirm expected failures**

Run from `apps/api`: `python -m pytest tests/test_coach_features.py -k logging -q`

Expected: failures because `logging_config` and request logging are not implemented.

- [ ] **Step 3: Add the logging configuration module**

Use `logging.handlers.RotatingFileHandler` with UTF-8, `maxBytes=5 * 1024 * 1024`, and `backupCount=3`. Use a formatter with timestamp, level, logger name, and message. Create the `logs` directory only when configuring the application. Mark owned handlers so repeated calls update or reuse them and do not duplicate output.

- [ ] **Step 4: Add request correlation middleware and lifecycle events**

Configure logging before FastAPI initialization. Accept a request ID only when it matches a conservative 1-128 character `[A-Za-z0-9._-]` allowlist; otherwise generate a UUID. Add the ID to `request.state`, response `X-Request-ID`, and a context variable used by the formatter/filter. Log route template after routing when available, method, status, elapsed milliseconds, and ID. Log unexpected middleware exceptions with `logger.exception` and re-raise for existing framework handling. Log application startup/shutdown and engine readiness in lifespan.

- [ ] **Step 5: Verify the targeted backend tests**

Run: `python -m pytest tests/test_coach_features.py -k logging -q`

Expected: all new logging configuration and correlation tests pass.

### Task 2: Model Provider and Image Recognition Diagnostics

**Files:**
- Modify: `apps/api/app/llm.py`
- Test: `apps/api/tests/test_coach_features.py`

**Interfaces:**
- Consume `get_logger` and request ID context from Task 1.
- Provider operation logs use stable event names `llm.request.started`, `llm.request.succeeded`, and `llm.request.failed`, with `operation`, `model`, `provider_host`, `duration_ms`, `error_type`, `error_category`, and `http_status` where applicable.

- [ ] **Step 1: Add failing tests for provider failure classification**

For chat, assert HTTP 429, timeout, TLS verification, URL/network failure, malformed JSON, and invalid response shape each emit one failure record with the correct sanitized category. Assert the secret key, prompt text, response body, and URL path do not appear in captured records. Add one successful request test asserting operation, model, provider host, and duration are logged.

- [ ] **Step 2: Run the new provider logging tests and confirm expected failures**

Run from `apps/api`: `python -m pytest tests/test_coach_features.py -k provider_logging -q`

Expected: failure because operation events are absent.

- [ ] **Step 3: Add safe provider metadata and error classification**

Derive provider host with `urllib.parse.urlsplit(base_url).hostname`; never log the complete base URL. Classify exceptions into `http_error`, `timeout`, `tls_error`, `network_error`, `invalid_json`, `invalid_response`, or `unknown`. For `HTTPError`, log only status code and exception class, never response body or headers. Emit operation start and completion duration with `time.perf_counter()`.

- [ ] **Step 4: Apply diagnostics to chat, explanation, and vision paths**

Instrument each outbound request and response parsing stage. Preserve existing public messages and status behavior. Vision retry logs include retry count and validation category only; never log parsed matrix or image metadata beyond MIME type and byte count if needed.

- [ ] **Step 5: Run model tests**

Run: `python -m pytest tests/test_coach_features.py -q`

Expected: all existing behavior and new sanitized logging tests pass.

### Task 3: Pikafish Lifecycle and Search Diagnostics

**Files:**
- Modify: `apps/api/app/engine.py`
- Test: `apps/api/tests/test_engine.py`

**Interfaces:**
- Consume `get_logger` and request ID context from Task 1.
- Emit stable event names `engine.starting`, `engine.ready`, `engine.start_failed`, `engine.stopping`, `engine.stopped`, `engine.search.started`, `engine.search.completed`, and `engine.search.failed`.

- [ ] **Step 1: Add failing tests for startup and search logging**

Use the existing fake-process tests to capture log records for missing binary, successful UCI readiness, successful search, timeout, and illegal `bestmove`. Assert records contain phase, bounded search parameters, duration, and exception class where relevant, and never contain the supplied FEN or move sequence.

- [ ] **Step 2: Run engine logging tests and confirm expected failures**

Run from `apps/api`: `python -m pytest tests/test_engine.py -k logging -q`

Expected: failure because engine lifecycle events are absent.

- [ ] **Step 3: Add engine lifecycle events**

Log executable and NNUE paths, PID, and explicit `uci`/`isready` handshake phases. Log missing files, spawn errors, startup timeouts, unexpected exits, stop, and reset outcome. Keep full UCI output out of standard logs.

- [ ] **Step 4: Add bounded search outcome events**

Start a timer after the engine lock is acquired. Log `depth`, `movetime_ms`, `multipv`, `threads`, and `hash_mb` with duration and outcome. Do not include FEN, move history, PV, or raw `info` lines. Log timeout and illegal engine response with phase and safe exception metadata before raising the existing errors.

- [ ] **Step 5: Verify engine tests**

Run: `python -m pytest tests/test_engine.py -q`

Expected: all existing engine behavior and new logging assertions pass.

### Task 4: Frontend Request IDs and Failure Diagnostics

**Files:**
- Modify: `apps/web/src/lib/api.ts`
- Modify: `apps/web/src/App.vue` only if request ID is needed in displayed errors
- Test: `apps/web/src/lib/api.test.ts`

**Interfaces:**
- Every API request sends `X-Request-ID` generated by `crypto.randomUUID()` with a safe fallback.
- Errors may expose a `requestId` property while retaining the current message contract.
- Failure console diagnostics contain operation, request ID, status, and error category only.

- [ ] **Step 1: Add failing frontend request ID and redaction tests**

Mock `fetch` to assert request headers include an ID, response request ID is available on success/error, and failed requests call `console.error` without serializing request body or containing prompt/FEN strings. Verify successful calls do not log.

- [ ] **Step 2: Run the focused frontend tests and confirm expected failures**

Run from `apps/web`: `npm test -- --run src/lib/api.test.ts`

Expected: failures because request ID propagation and diagnostics are absent.

- [ ] **Step 3: Add correlation ID generation and error metadata**

Create one ID per request. Attach it to headers. Read the server `X-Request-ID` response header and prefer it for diagnostic context. Add a typed API error class that preserves the current human-readable message and carries `requestId`, HTTP status, and category.

- [ ] **Step 4: Log failures without request payloads**

At the shared request boundary log only operation path (static local API path), request ID, HTTP status when present, and sanitized category. Never log options, body, response body, or arbitrary error object. Keep health polling successes quiet.

- [ ] **Step 5: Verify frontend tests and typecheck**

Run: `npm test -- --run src/lib/api.test.ts` and `npm run build`.

Expected: targeted tests and TypeScript production build pass.

### Task 5: Windows Launcher Logs and Retention Documentation

**Files:**
- Modify: `start.ps1`
- Modify: `.gitignore`
- Modify: `README.md`
- Test: `apps/api/tests/test_start_dev_script.py`

**Interfaces:**
- Launcher creates `<project_root>/logs` and writes `api-process.log` and `web-process.log`.
- Startup timeout output identifies the corresponding log path and includes at most the last 40 lines.
- Launcher process logs use append mode with a bounded rollover policy.

- [ ] **Step 1: Determine a non-blocking bounded PowerShell capture pattern**

Check installed PowerShell version and supported `Start-Process` redirection behavior. Select a wrapper that redirects stdout/stderr and safely rolls over logs without interrupting API or Vite. Document the selected limits in the launcher comments and README.

- [ ] **Step 2: Add failing launcher contract tests**

Extend script text/dry-run tests to require logs directory setup, separate API/web output paths, rollover cap, and bounded tail output on startup failures. Ensure `-DryRun` creates no files and starts no processes.

- [ ] **Step 3: Run launcher tests and confirm expected failures**

Run from `apps/api`: `python -m pytest tests/test_start_dev_script.py -q`

Expected: tests fail because launcher logging is absent.

- [ ] **Step 4: Implement launcher capture and bounded retention**

Before starting services create `logs`. Redirect both stdout and stderr for each process to the corresponding process log. Use the selected safe rollover mechanism with a maximum current size of 5 MiB and 3 backups. Keep hidden-process behavior. On failed health wait, print the exact log path and `Get-Content -Tail 40` output. Do not print environment variables or `.env` contents.

- [ ] **Step 5: Document log locations and cleanup**

Add `logs/` to `.gitignore`. In README explain `api.log` versus process logs, rotation/retention, safe inspection commands, and that request payloads and secrets are excluded by design.

- [ ] **Step 6: Verify launcher tests and DryRun**

Run: `python -m pytest tests/test_start_dev_script.py -q` and `./start.ps1 -DryRun`.

Expected: tests pass and DryRun prints paths without creating logs or launching services.

### Task 6: Full Regression and Privacy Verification

**Files:**
- Test: `apps/api/tests/test_coach_features.py`
- Test: `apps/api/tests/test_engine.py`
- Test: `apps/api/tests/test_start_dev_script.py`
- Test: `apps/web/src/lib/api.test.ts`

- [ ] **Step 1: Run the complete backend suite**

Run from `apps/api`: `python -m pytest -q`.

Expected: all backend tests pass.

- [ ] **Step 2: Run the complete frontend suite**

Run from `apps/web`: `npm test -- --run`.

Expected: all frontend tests pass.

- [ ] **Step 3: Run production typecheck and build**

Run from `apps/web`: `npm run build`.

Expected: `vue-tsc --noEmit` and Vite production build succeed.

- [ ] **Step 4: Inspect representative generated logs**

Exercise one successful API health request, one successful model request, and a controlled provider/engine failure using test fakes. Inspect captured output and assert the configured API key, prompt sentinel, image bytes, FEN sentinel, and move-history sentinel do not occur. Confirm request IDs allow the browser failure record to be matched to its API request log.

- [ ] **Step 5: Review the final changed-file set**

Confirm only logging configuration, API/model/engine instrumentation, frontend diagnostics, launcher retention, README/ignore rules, and focused tests changed. Confirm no `.env`, image, board payload, user prompt, or generated log file is included in source changes.

---

## Self-Review

- Spec backend logging and request correlation: Task 1.
- Spec provider, vision, and privacy diagnostics: Task 2 and Task 6.
- Spec Pikafish lifecycle and bounded search events: Task 3.
- Spec browser-side request correlation and quiet successful polling: Task 4.
- Spec launcher capture, retention, failure tails, and docs: Task 5.
- Spec rotation, exclusions, regression coverage, and privacy inspection: Tasks 1, 5, and 6.
- No commit steps are present because the workspace is not a Git repository.
- No API key, user text, image, FEN, moves, or PV is included in logged event fields.
- Every implementation task specifies a failing test before production changes.
- Lifecycle coverage is mandatory: API startup/ready/shutdown; request start/completion/failure; model start/success/failure; image recognition attempts; engine start/ready/search/stop/reset; frontend request start/completion/failure; and launcher preparation/start/health/failure/completion.
