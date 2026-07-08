# Chainlit + DeepAgents Migration - Design

**Date:** 2026-07-08
**Status:** approved for implementation planning

## Problem

CapybaraAgent has accumulated custom runtime code for streaming, tool calls, chat history,
and agent orchestration. The code works, but too much low-level protocol behavior is
hand-written and hard to maintain.

## Goal

Move chat/session/tool orchestration to Chainlit and DeepAgents while preserving the
custom CapybaraAgent React design, local-first data posture, current features, and planned
surfaces.

## Non-goals

- Replacing the product UI with stock Chainlit UI.
- Shipping a cloud-first architecture.
- Dropping memory, MCP curation, local auth, model selection, artifacts, or planned tasks.

## Architecture

Chosen option: **FastAPI shell + mounted Chainlit**.

FastAPI remains as a thin domain/API shell. Chainlit is mounted under `/chainlit` and owns
chat session lifecycle, message streaming, steps, and thread persistence. FastAPI does not
preserve the UI design; the custom React shell does. FastAPI stays because it is the
cleanest host for memory, MCP, model settings, local profiles, and future task APIs during
the migration.

The frontend remains the existing Vite/React design shell. Its chat runtime adapter moves
from custom fetch/SSE parsing to Chainlit's React client. Existing Memory and MCP screens
continue to call the custom REST APIs.

DeepAgents replaces the pydantic-ai runtime. A small `DeepAgentRunner` receives user
messages, selected model, thread metadata, memory tools, and MCP tools, then streams text
and tool steps into Chainlit.

## Persistence

Chainlit stores threads/messages/steps. Capybara-owned tables store users, settings, facts,
MCP servers/tools, task definitions, provider credentials, and artifact metadata. Because
there are no real deployments, old Alembic revisions can be replaced by a new initial
schema after parity is reached.

## Design Preservation

The first viewport and navigational shell remain Capybara's custom UI. Chainlit is a
runtime and protocol dependency, not the visible design system.

## Migration Strategy

1. Prove Chainlit can be mounted beside the thin FastAPI domain shell and consumed by the
   custom React app.
2. Switch chat transport to Chainlit while keeping domain APIs stable.
3. Switch agent execution to DeepAgents.
4. Port memory and MCP tools to DeepAgents.
5. Reset persistence and remove old hand-written SSE/tool-call code.
6. Reassess whether FastAPI is still needed for any remaining domain APIs after parity.

## Risks

- Chainlit React client may not expose every thread-metadata operation needed by the
  custom UI. If so, add a small custom REST adapter rather than forking Chainlit.
- Python 3.14 may not be supported by Chainlit/DeepAgents dependency trees. Prefer a
  stable Python 3.12 or 3.13 target if resolution fails.
- Chainlit stock UI customization is insufficient for this product. Use the custom React
  client path.

## Success Criteria

- Existing chat, memory, MCP, auth, and model-selection flows work through the custom UI.
- Tool calls render via Chainlit steps instead of custom SSE `tool-call` parsing.
- Old chat SSE code and pydantic-ai-specific code are removed.
- Backend and frontend tests pass.
