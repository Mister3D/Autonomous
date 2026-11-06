# LLM settings (Pi models.json)

**Status**: in place  
**Key files**: `autonomous/services/setup_config.py`, `autonomous/services/chat_attachments.py`, `frontend/src/components/LlmSettings.vue`  
**Last updated**: 2026-11-06 (providers vs models split in Settings UI)

## User behaviour

- Settings → **LLM**: edit OpenAI-compatible providers written to `~/.pi/agent/models.json` (Pi schema).
- Two clear blocks:
  1. **Providers** — add / edit API endpoints (id, URL, key). Save without needing a model.
  2. **Models** — choose a **provider**, then a **model** id (fetch from `/v1/models` or type it), set limits, save.
- Existing models are listed flat with a provider badge; each card has its own Save / Remove.
- Links to Pi docs for `/login` and advanced cases: [models](https://pi.dev/docs/latest/models), [models configuration](https://pi.dev/docs/latest/models-configuration).
- No global “max vision images” control in the UI: set it **per model**. Code fallback is still `guard.max_images_per_prompt` default **2** when the model has no `inputLimits.images.maxPerRequest` (also updated when a provider returns “at most N”).

## Implementation

- Source of truth for config: Pi `models.json` (`name`, `input`, `inputLimits.images.maxPerRequest`, `contextWindow`, `maxTokens`).
- `PUT /setup/llm`:
  - no `models` / `model` → update provider credentials only (keep existing models, or create empty);
  - `models: [...]` → full list replace for that provider (may be `[]`);
  - `model` → upsert one model on that provider.
- Writes are **merge-safe**: unknown fields (`cost`, `reasoning`, `compat`, resize profiles…) are kept.
- Autonomous **overlay**: `max_images_per_prompt(bot=…)` reads the bot’s model ref from Pi JSON and truncates vision prompts; if the provider returns “at most N images”, the limit is written back into that model entry (`remember_model_image_limit`) and the guard fallback is updated.

## Pitfalls / non-regressions

- Do not store a second parallel LLM catalog in SQLite.
- Do not drop unknown keys when saving a model.
- Do not require a model when saving provider credentials alone.
- Built-in providers via Pi `/login` stay outside this editor (custom OpenAI-compat only).

## Quick check

```bash
pytest tests/test_llm_models_limits.py tests/test_setup_models.py -q
```
