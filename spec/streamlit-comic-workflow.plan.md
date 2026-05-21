# Streamlit Comic Workflow Plan

## Goal

Build a Streamlit application that lets a user enter source text, configure comic-generation options, launch a run against an existing n8n workflow, review generated pages, and download the comic as a packaged artifact.

The Streamlit app should be the operator-facing workflow UI. n8n should remain the automation and model-orchestration layer.

## Inputs From Current State

The existing n8n flow already does the core generation pipeline:

1. Accepts text input from chat
2. Generates a story concept
3. Expands the concept into page-by-page content
4. Generates one image per page
5. Uploads page images to Supabase Storage
6. Aggregates results into a final response

That is enough to avoid rebuilding generation logic in Python immediately. The Streamlit app should integrate with this workflow first, then add local packaging, editing, and download features.

## Recommended Architecture

### Chosen approach

Use Streamlit as a thin orchestration and review layer over n8n, with a small Python service layer inside this repo that:

- validates user input
- calls n8n
- normalizes the returned data
- assembles a downloadable comic bundle locally
- stores lightweight run metadata for session history

### Why this approach

- It preserves the value of the n8n workflow you already built.
- It avoids reimplementing prompt chains in Python too early.
- It gives the UI a stable internal contract even if the n8n nodes change later.
- It creates a clean seam for replacing n8n in the future if needed.

### Alternatives considered

1. Directly call models from Streamlit.
This gives maximum control, but it discards your existing automation and increases implementation scope immediately.

2. Call the current n8n chat workflow exactly as-is.
This is fastest, but the current output is optimized for chat display, not structured UI rendering or progress tracking.

3. Add a small Python API backend in front of Streamlit and n8n.
This is viable later if multi-user auth, persistent jobs, or background workers become necessary, but it is unnecessary for phase 1.

## Product Scope

### Phase 1

Deliver a usable single-user Streamlit app that can:

- accept source text and prompt controls
- submit a run to n8n
- show run status
- display generated pages and page text
- save a local run folder
- generate a zip file for download

### Phase 2

Add operator controls and quality-of-life features:

- regenerate a single page
- edit page prompts before regeneration
- keep run history across sessions
- export Markdown manifest and reading HTML

### Phase 3

Add production workflow features:

- async job queue
- page approval state
- multiple visual style presets
- PDF export
- authentication and multi-user separation

## Required n8n Adjustments

The current workflow is strong as a generation prototype, but Streamlit needs a more structured contract.

### Minimum changes for UI integration

1. Replace or supplement `chatTrigger` with a webhook-friendly entrypoint.
The Streamlit app should submit JSON, not depend on a chat session surface.

2. Return structured JSON, not only formatted Markdown.
The UI needs:
- `series_name`
- `total_pages`
- `pages`
- `page_num`
- `content`
- `image_url`
- `status`
- `errors`

3. Separate machine output from presentation output.
Keep the human-readable formatted chat response if useful, but produce a raw JSON payload in parallel.

4. Add stable run metadata.
Each invocation should return or generate:
- `run_id`
- `created_at`
- `input_summary`
- `workflow_version`

5. Decide synchronous vs asynchronous execution.
For phase 1, synchronous execution is acceptable if page counts stay small.
For anything longer-running, introduce async status polling.

### Recommended n8n response shape

```json
{
  "run_id": "20260519_001",
  "series_name": "understanding_cash_flow",
  "topic": "现金流基础",
  "total_pages": 5,
  "status": "completed",
  "pages": [
    {
      "page_num": 1,
      "content": "中文页面内容",
      "image_url": "https://.../page_1.png",
      "upload_success": true
    }
  ],
  "errors": []
}
```

## Python Project Design

### Proposed package structure

```text
src/comicpublish/
  app.py
  config.py
  models.py
  n8n_client.py
  orchestrator.py
  packaging.py
  storage.py
  ui/
    sections.py
    theme.py
```

### Responsibilities

- `app.py`
  Streamlit entrypoint and page composition.

- `config.py`
  Environment variables, defaults, API endpoints, timeout settings.

- `models.py`
  Typed data models for request payloads, page results, run results, and export manifests.

- `n8n_client.py`
  Handles HTTP requests to the n8n webhook and response normalization.

- `orchestrator.py`
  Coordinates validation, submission, retry behavior, error handling, and local persistence.

- `packaging.py`
  Creates run folders, manifest files, optional HTML summary, and zip downloads.

- `storage.py`
  Saves local metadata and optionally caches remote image assets into the run bundle.

- `ui/sections.py`
  Reusable Streamlit rendering functions for input form, progress state, gallery, and downloads.

## Data Flow

1. User enters source text in Streamlit.
2. User chooses options such as audience, page count target, comic style, and output language.
3. Streamlit validates the form.
4. Streamlit sends a normalized request to `orchestrator.py`.
5. The orchestrator calls n8n through `n8n_client.py`.
6. n8n runs concept, pagination, image generation, and upload.
7. The orchestrator receives the result payload.
8. The app downloads or references remote images and writes a local bundle.
9. The bundle includes manifest JSON, source text, page metadata, image references, and a zip file.
10. Streamlit renders the completed run and exposes download buttons.

## Local Artifact Contract

Each completed run should create a folder like:

```text
build/runs/<run_id>/
  input.json
  result.json
  manifest.json
  pages/
    page-01.json
    page-01.png
    page-02.json
  export/
    <series_name>.zip
```

This makes the workflow auditable and keeps Streamlit from being the only place where output exists.

## Streamlit Screen Model

### Single-page app with three working zones

1. Input rail
For source text, controls, and launch actions.

2. Run monitor
For status, page count, progress, errors, and logs.

3. Output review
For page gallery, page text, download actions, and regenerate actions later.

This should remain a single-page workflow in phase 1. Tabs are fine inside the output area, but not as the primary navigation model.

## Error Handling

### User-facing errors

- missing source text
- n8n endpoint unavailable
- invalid JSON returned by n8n
- page generation partial failure
- image upload success mismatch
- empty image URLs

### System behavior

- fail fast on invalid configuration
- show clear retry controls for network failures
- preserve partial results when some pages fail
- write raw response snapshots for debugging
- never discard generated page metadata because one image failed

## Config and Secrets

Use environment variables for:

- `N8N_WEBHOOK_URL`
- `N8N_API_KEY` if needed
- `SUPABASE_PUBLIC_BASE_URL` if the UI reconstructs URLs
- `COMICPUBLISH_OUTPUT_DIR`
- `REQUEST_TIMEOUT_SECONDS`

Do not hardcode credentials in Streamlit code or UI forms.

## Testing Strategy

### Unit tests

- request payload building
- response parsing
- run folder creation
- zip packaging
- error normalization

### Integration tests

- mock n8n success response
- mock malformed response
- partial page success response

### Manual acceptance checks

- launch a run from Streamlit
- confirm generated pages render in the UI
- confirm zip download works
- confirm local run folder is created
- confirm error state is readable

## Risks

### Current workflow contract risk

Your current n8n workflow returns a chat-oriented response. That is fragile for UI parsing. This is the first place to tighten.

### Long-running request risk

If multi-page image generation runs too long, a synchronous Streamlit request may feel frozen. If this happens, move to async job status early.

### Text-in-image quality risk

The current image prompt expects Chinese dialogue rendered inside the generated image. This is often inconsistent with image models. You may need a later phase that separates art generation from text balloon overlay for reliable readability.

## Recommended Implementation Order

1. Define the normalized request and response schemas in Python.
2. Adjust n8n to expose a structured webhook response.
3. Implement `n8n_client.py` and mock-driven tests.
4. Build the Streamlit input form and result rendering.
5. Add local bundle packaging and zip downloads.
6. Add partial-failure handling and debug snapshots.
7. Add page-level regeneration workflow.

## Acceptance Criteria For Phase 1

- A user can paste text into Streamlit and start a run.
- The app calls n8n without manual intervention.
- The completed result shows all returned pages with image URLs and page descriptions.
- The run is saved locally with machine-readable metadata.
- The user can download a zip artifact for the generated comic.
- Failures are visible without inspecting server logs.

## Recommendation

Start with a strict phase 1 boundary:

- Streamlit handles input, orchestration, review, and download.
- n8n handles story and image generation.
- Supabase remains the remote image host.

That gives you a working product fastest, while keeping the door open for later prompt editing, page regeneration, and a better final reading format.

