# Persistent Data and User Lifecycle Design

## Goal

Make user accounts, games, move records, review results, exports, deletion, backups, and privacy handling suitable for a production deployment while preserving the existing Xiangqi rule boundary.

The database target is PostgreSQL using the configured SQLAlchemy URL:

```text
postgresql+psycopg://postgres:123456@192.168.1.4:5432/chess
```

The password in this URL is a development credential and must be rotated before production. Production must use a secret store and a dedicated database role with only the required privileges.

## Decisions

### Authentication

Use a third-party OpenID Connect provider. The application uses the Authorization Code flow with PKCE.

- The provider is configurable through issuer URL, client ID, client secret, redirect URI, and allowed audience.
- The backend validates issuer, audience, signature, expiration, `state`, `nonce`, and PKCE verifier before creating a local session.
- The stable external identity is `(issuer, subject)`. Email, nickname, and avatar are profile attributes and are not identity keys.
- The application stores no password and does not accept a client-supplied `user_id` for ownership decisions.
- The backend creates or finds a local user from the verified OIDC identity and puts the local user ID in the server-side auth context.
- Use an opaque, rotating session cookie with `HttpOnly`, `Secure`, and an appropriate `SameSite` value. Do not put access or refresh tokens in browser local storage.
- Logout clears the local session. Provider logout is optional and configured separately because providers differ.

If direct WeChat login is required later, treat it as a separate provider adapter. WeChat website login is commonly OAuth2 rather than OIDC; it must not be labeled OIDC unless the selected service exposes a standards-compliant OIDC issuer. The business tables remain unchanged because they reference the local user ID.

When no complete OIDC configuration is present, the application offers local email/password registration and login as a fallback. Passwords are hashed with Argon2id and never stored in plaintext. Local credentials use a separate `local_credentials` table keyed to the same local user. This fallback requires email verification, password reset, and production mail delivery before it is advertised as a fully verified account system.

### Ownership and consistency

The authoritative game history is `initial_fen` plus the ordered move list. Current board, side to move, and status are cached projections that must be checked against a replay.

Every game mutation runs in one database transaction and must:

1. Lock or version-check the game.
2. Replay all moves from `initial_fen` with the shared Python rule module.
3. Validate FEN, side to move, legal moves, self-check, flying generals, repetition, perpetual check, and perpetual chase.
4. Compare the replayed position with the submitted projection.
5. Insert the move and update the projection atomically.

Use an integer `version` for optimistic concurrency. A stale version returns `409` and cannot overwrite another tab's move.

### Review immutability

A review stores a snapshot of the starting FEN and complete move sequence. It must remain reproducible if the live game is later edited. Engine metadata, parameters, rule stop reason, and per-ply findings are stored with that review. A review must never invent a centipawn loss for a mate or an unavailable comparison.

## Data model

All tables use UUID primary keys, UTC timestamps, and foreign keys. Business data is scoped by `users.id`.

### `users`

- `id`
- `display_name`, `avatar_url` (nullable profile fields)
- `status`: `active`, `deletion_pending`, `deleted`
- `created_at`, `updated_at`, `deleted_at`

No password, provider token, or raw authentication response is stored.

### `user_identities`

- `id`, `user_id`
- `issuer`, `subject`
- `email`, `email_verified` (optional provider claims, refreshed on login)
- `created_at`, `last_login_at`
- unique constraint on `(issuer, subject)`

Provider access and refresh tokens are not persisted. If a future integration requires one, encrypt it with a managed key and give it a separate retention policy.

### `local_credentials`

- `id`, `user_id`
- normalized lowercase `email` with a unique constraint
- Argon2 password hash
- email verification state
- failed login count and temporary lock time
- creation and last-login timestamps

Email login returns the same server-side session shape as OIDC. Error responses do not reveal whether an email account exists. A production rollout must add verification and password-reset email workflows before treating the address as verified.

### `privacy_consents`

- `id`, `user_id`
- `policy_type`: `privacy`, `terms`
- `policy_version`
- `accepted_at`, `withdrawn_at`
- unique active consent per user and policy type

The login/signup completion path records the exact policy version accepted. Policy withdrawal blocks new optional processing while retaining the minimum records needed to complete deletion or meet legal obligations.

### `games`

- `id`, `user_id`
- `name`
- `initial_fen`
- `current_fen`, `red_to_move`, `status`
- `version`
- `created_at`, `updated_at`, `deleted_at`

`status` distinguishes at least `active`, `finished`, `abandoned`, and `deleted`. FEN and position fields are validated at the API boundary and again in the transaction.

### `game_moves`

- `id`, `game_id`
- `ply` (one-based)
- `side`: `red` or `black`
- `uci`
- `notation_zh`
- `before_fen`, `after_fen`
- `created_at`
- unique constraint on `(game_id, ply)`

The move row records both FEN snapshots for auditability and fast display, but replay remains the correctness check.

### `reviews`

- `id`, `game_id`, `user_id`
- `game_version`
- `initial_fen_snapshot`
- `moves_snapshot` (validated JSON array)
- `history_hash`
- `engine_name`, `engine_version`, `nnue_version`
- `parameters` (validated JSON)
- `status`: `queued`, `running`, `complete`, `stopped_rule_violation`, `failed`
- `summary`, `error_code`, `created_at`, `completed_at`

The hash is calculated from a canonical representation of the starting FEN and ordered UCI moves. It is used to detect accidental snapshot changes, not as a replacement for replay validation.

### `review_items`

- `id`, `review_id`, `ply`, `side`
- `move`, `best_move`
- `before_score`, `after_score`, `loss_cp`
- `mate_value` where applicable
- `grade`: `good`, `inaccuracy`, `mistake`, `blunder`, `unknown`
- `pv` (validated JSON array)
- `rule_stop_kind`, `rule_stop_message`
- unique constraint on `(review_id, ply)`

Scores carry an explicit perspective and type. Mate values are never converted to ordinary centipawns.

### `data_requests`

- `id`, `user_id`
- `type`: `export` or `delete`
- `status`: `queued`, `running`, `ready`, `completed`, `failed`, `cancelled`, `expired`
- `requested_at`, `started_at`, `completed_at`, `expires_at`
- `artifact_key` (opaque storage key, nullable)
- `error_code`

An export artifact is stored outside PostgreSQL in encrypted storage and is available through a short-lived, authorized download endpoint.

### Deletion tracking

Use a separate internal deletion ledger, such as `deletion_tombstones`, containing the user ID, deletion request time, purge completion time, and backup purge watermark. This prevents a restored backup from reactivating a user who completed deletion.

## API shape

### Authentication

- `GET /auth/oidc/start`
- `GET /auth/oidc/callback`
- `POST /auth/logout`
- `GET /api/me`

OIDC callback errors are generic to the browser and detailed only in redacted server logs. All state-changing API routes require the server session and CSRF protection where cookie authentication is used.

### Games and moves

- `GET /api/games`
- `POST /api/games`
- `GET /api/games/{id}`
- `POST /api/games/{id}/moves`
- `PATCH /api/games/{id}`
- `DELETE /api/games/{id}`

Each write accepts `expected_version`. The server derives `user_id` from the verified session, validates ownership, replays the complete history, and returns the new version.

### Reviews

- `POST /api/games/{id}/reviews`
- `GET /api/reviews/{id}`
- `GET /api/games/{id}/reviews`

Review creation copies the validated game history into the review snapshot before asynchronous engine work begins. A failed engine job leaves a failed review record with a safe error code.

### Export and account deletion

- `POST /api/me/exports`
- `GET /api/me/exports/{id}`
- `GET /api/me/exports/{id}/download`
- `POST /api/me/deletion`
- `POST /api/me/deletion/cancel` during the recovery window

Exports are asynchronous ZIP files with a versioned `manifest.json`, authoritative JSON game data, move records, review snapshots/results, and a human-readable PGN-like Xiangqi text file when available. Download authorization checks both the session user and request status.

Deletion immediately marks the account `deletion_pending`, revokes sessions, blocks new writes, and starts a seven-day recovery window. After the window, a worker deletes identities, consents where legally permitted, games, moves, reviews, review items, exports, and profile data in batches. The deletion ledger is retained only as required to prevent backup resurrection and to satisfy legal audit needs.

## Backup and recovery

- Daily encrypted PostgreSQL full backup.
- WAL archiving and point-in-time recovery where the hosting setup supports it.
- At least 30 days of backup retention, with the exact period documented in the privacy policy.
- Backups stored on a separate host or account with encryption and restricted access.
- Monthly restore drill into an isolated environment, followed by migration checks and replay checks for representative games.
- After restore, replay the deletion ledger and tombstones before serving traffic. Users past the purge point must not reappear.
- Record backup success, size, age, WAL lag, restore result, and failed-job alerts. Do not put database credentials or user board data in ordinary application logs.

Recovery objectives for launch must be set explicitly: target RPO of 15 minutes with WAL, target RTO of 2 hours for a single-region restore. These are operational targets, not guarantees until tested on the production-sized database.

## Privacy and data handling

The privacy policy and in-product data handling page must state:

- OIDC provider, identity claims collected, and why they are needed.
- User profile, games, move history, reviews, and export artifacts collected and processed.
- That uploaded board images are transient and are not persisted by the application.
- Whether coach prompts or external model providers receive board state or user text; default behavior is no long-term chat retention.
- Retention for active data, exports, logs, and backups.
- Export, deletion, consent withdrawal, and recovery-window behavior.
- Backup retention and the fact that deletion is applied to restored backups through the deletion ledger.
- Contact address, controller/operator identity, effective date, and policy version.

Do not log OIDC tokens, authorization headers, raw claims, prompts, images, FEN, or full move histories. Redacted audit events may record user ID, operation, result, and request ID where needed for security and support.

## Rollout order

1. Add SQLAlchemy models, Alembic, connection pooling, and startup migration checks.
2. Add provider-agnostic OIDC configuration, callback validation, session middleware, CSRF protection, and `/api/me`.
3. Add users and identity mapping, then migrate game persistence from browser-only storage.
4. Add transactional move writes with replay and optimistic locking.
5. Add immutable review snapshots and asynchronous review persistence.
6. Add export worker and download authorization.
7. Add deletion workflow, tombstones, and purge worker.
8. Add scheduled backup, restore drill, deletion replay, and operational alerts.
9. Add privacy policy UI, consent recording, and account controls.

At each step, retain a compatibility path for old local-storage games: import them through the same FEN and move replay validator, and reject or quarantine records that cannot be reconstructed.

## Acceptance criteria

- A verified OIDC identity can create one local user and cannot create duplicates for the same `(issuer, subject)`.
- An unverified or malformed callback cannot create a session.
- A game, every move, current FEN, side to move, and version are committed atomically.
- Invalid moves, self-check, flying generals, repetition, perpetual check, and perpetual chase are rejected without partial writes.
- A stale game version returns `409` and leaves the stored game unchanged.
- A review can be reconstructed from its stored snapshot after the live game changes.
- Exported JSON can be imported after replay validation.
- Deletion blocks new writes immediately, supports the documented recovery window, and remains effective after backup restore.
- Backup restore drills meet the declared RPO/RTO targets or produce an actionable incident.
- Backend tests, frontend tests, and the production build pass before release.

## Open implementation choices

- Select the OIDC provider and configure its allowed redirect URIs, scopes, and logout behavior.
- Decide whether production sessions use a PostgreSQL/Redis session store or signed encrypted cookies; server-side sessions are preferred when revocation and deletion must be immediate.
- Select object storage and key-management service for exports and backups.
- Confirm the legal retention period, recovery window, operator contact, and applicable jurisdiction before publishing the privacy policy.
