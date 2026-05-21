# comicpublish

`comicpublish` is the local package behind AtSolution Comic Studio, a Streamlit production desk for turning source text into teachable comic pages and saving the result as local project files.

## What this first version does

- Provides an installable Python package and CLI
- Generates a comic outline, page prompts, and manifest files
- Saves generated pages, prompt records, page JSON files, and manifests in a local project folder
- Keeps the generation logic local and easy to extend with real model-backed skills later

## Quick start

```bash
python -m pip install -e . --no-build-isolation
comicpublish generate \
  --title "The Neon Alley Case" \
  --premise "A washed-up detective hunts a missing robot poet in a rain-drenched megacity." \
  --genre cyberpunk \
  --pages 4
```

Generated output goes into `build/` by default.

## Streamlit studio

The repo includes a Streamlit operator UI based on the editorial comic-desk design.

Before running the app, fill the workflow credentials in `.env`:

- `PLANNING_BASE_URL`, `PLANNING_API_KEY`, and `PLANNING_MODEL` for OpenAI-compatible chat completions
- `IMAGE_BASE_URL`, `IMAGE_API_KEY`, `IMAGE_MODEL`, and optional `IMAGE_SIZE` for OpenAI-compatible image generation. The default is `1248x1664`, a portrait comic page size whose width and height are both divisible by 16.
- `COMICPUBLISH_OUTPUT_DIR` for the local project output root

```bash
python -m pip install -e . --no-build-isolation
streamlit run streamlit_app.py
```

The app mirrors the useful parts of the n8n flow in Python: story concept generation, page planning, per-page prompt persistence, image generation, and local project file output. Supabase and zip export are no longer used. Completed runs are written into `build/projects/<project-slug>/<run-id>/`.

Generation runs execute in a background runner thread. The Streamlit stage polls runner snapshots so the status banner, logs, metrics, and gallery update while the workflow is still running. Each run also persists `analysis.md`, `storyboard.md`, and per-page prompt files in `prompts/` before image generation, so the comic build stays inspectable and reproducible.

Planning and image calls can be slow because the workflow waits for model responses and high-resolution page images. Page images are generated in parallel after all prompts are written; set `IMAGE_PARALLELISM=1`, `2`, or `3` to control concurrency. The default request timeout is `300` seconds per API call; reduce page count for faster runs or raise `REQUEST_TIMEOUT_SECONDS` if your image endpoint regularly needs more time.

The image generation list loads from local page JSON files. Each planned page is shown as queued, in progress, failed, or success, and each page can be regenerated independently from its saved prompt without rerunning planning.

Do not start it with `python streamlit_app.py`; that path now exits immediately with the correct instruction. Use `streamlit run streamlit_app.py`.

If you only want to run it without installing, use:

```bash
PYTHONPATH=src python -m comicpublish generate --title "Demo" --premise "A courier outruns a storm."
```

## Example output

```text
build/
  projects/
    how-mangroves-protect-a-coastline/
      CP-260520-104455/
        analysis.md
        storyboard.md
        manifest.json
        result.json
        pages/
          page-01.json
          mangrove_lessons_manga_1.png
        prompts/
          01-page-mangrove_lessons.md
```

## Next steps

- Add retry controls for failed individual pages
- Add optional PDF export for direct reading
