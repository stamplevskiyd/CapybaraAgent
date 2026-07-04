# System status & configuration endpoint — deferred concept

**Date captured:** 2026-07-04
**Status:** Deferred / backlog — **do not implement now.** Slated for a later slice.
**Type:** Feature concept (backend + frontend + first background-task infra)

## Idea

The frontend polls the backend **infrequently** (a low-frequency status poll, not a
hot loop) for the current system status and configuration. The response drives
several UI affordances:

1. **Current version** — the running app version, surfaced in the UI.
2. **Update availability** — is a newer version out? A background task
   (**Celery**) periodically fetches the list of tags/releases from GitHub and
   caches it; the status response compares the current version against the latest
   and flags when an update exists. GitHub is *not* called on the request path —
   only the cached result is read.
3. **Default-config warning** — warn the user when their configuration equals the
   shipped defaults or is missing (e.g. still running on the committed
   `.env.defaults` values — dev `JWT_SECRET`, `POSTGRES_PASSWORD=capybara`, etc.).
   This hooks directly into the two-level `.env` design
   (`2026-07-04-config-env-layering-design.md`): detect "still on defaults".
4. **Onboarding / tutorial** — show an onboarding menu when **no user is
   registered yet** (fresh install) or for newly registered users.

## Why it's deferred

- Introduces the **first background-task subsystem** (Celery + a broker, likely
  Redis) — called out in the product vision (`CLAUDE.md` → "background tasks on a
  cron schedule") but not part of the current backend slices.
- Touches the frontend, which is its own upcoming slice.
- Depends on the config-layering work landing first (for the default-config
  check).

## Rough shape (to be designed later, not binding)

- Endpoint e.g. `GET /system/status` returning: `version`, update info
  (`latest_version`, `update_available`), config warnings (`using_default_config`
  and which keys), and onboarding flags (`needs_onboarding`, `no_users_yet`).
- Likely **unauthenticated or partially public**: the "no user registered yet"
  case must work *before* anyone can log in — so at least the onboarding/version
  parts can't sit behind auth. Auth boundary to be decided at design time.
- Version source: derive from package metadata / `pyproject.toml`, single source.
- GitHub tag fetch: Celery beat (scheduled) task → cache (Redis/DB) with a TTL;
  status reads cache only. Handle GitHub rate limits / offline gracefully
  (local-first app may have no network).

## Open questions for the future design phase

- Auth model for the endpoint (fully public vs. mixed public/authenticated fields).
- Where update-check state and the cached tag list live (Redis vs. a DB table).
- Poll interval and whether the backend hints a interval to the frontend.
- How "config equals default" is detected precisely (compare against
  `.env.defaults` values? a checksum? per-key flags?) without leaking secrets.
- Onboarding state: purely derived (no users → onboard) vs. a persisted
  per-user "completed onboarding" flag.
- Broker/infra choice and how it fits docker-compose (adds a Redis service).

## References

- Config layering: `docs/superpowers/specs/2026-07-04-config-env-layering-design.md`
- Product vision (background tasks, memory, MCP): `CLAUDE.md`, `design_handoff_capybaraagent/README.md`
