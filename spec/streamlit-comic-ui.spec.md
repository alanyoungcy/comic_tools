# Streamlit Comic UI Spec

## Objective

Design a Streamlit interface for a single operator to generate educational comics from source text, review the generated pages, and work from the local project folder.

The UI should feel like a comic production desk, not a generic admin panel.

## Product framing

### Primary user

The primary user is the comic producer. They already understand the topic they want to teach and need a fast, guided way to turn source text into a multi-page comic.

### Core user jobs

- paste or write source material
- choose generation constraints
- launch the pipeline
- inspect page-by-page output
- identify failed pages quickly
- use the saved local project files

## Design direction

### Aesthetic

Use an editorial comic-studio look:

- background: warm off-white paper with faint halftone texture
- primary ink: near-black
- accent 1: vermilion red
- accent 2: muted cyan
- success: deep green
- warning: amber

The interface should borrow cues from a manga layout table and a print proofing workstation. It should feel authored and tactile, not like a template dashboard.

### Signature visual move

Use diagonal caption bars and framed content cards that resemble comic panels. Section headers should feel like issue labels, not plain form headings.

### Typography

- display: bold condensed grotesk or poster-style sans
- body: readable humanist sans
- metadata: monospace for run IDs, statuses, and filenames

## Layout

### Overall page structure

Use a wide desktop-first layout with a strong left rail and a larger right content stage.

#### Left rail

Persistent generation controls:

- source text input
- target page count
- tone/style controls
- language selector
- action buttons

#### Right stage

Dynamic output and run feedback:

- run status banner
- step progress strip
- result summary
- page gallery
- page detail inspector
- project file actions

On mobile, the left rail should collapse above the results stage in a single column.

## Information architecture

### Section 1: Header

Purpose:
Orient the user immediately.

Contents:

- product name: `ComicPublish Studio`
- one-line subtitle: generate teachable comics from raw text
- small environment badge for current backend status such as `API configured`

Behavior:

- remains compact
- should not consume excessive vertical space

### Section 2: Source Input Panel

Purpose:
Collect the teaching material and prompt controls.

Fields:

- source text textarea
- optional title override
- comic style preset
- desired page count or page-count guidance mode
- output language
- optional notes for narrator tone or character dynamics

Controls:

- `Generate Comic`
- `Reset`

Validation:

- source text required
- disable generate while a run is in progress

### Section 3: Run Status Panel

Purpose:
Explain what the system is doing now.

States:

- idle
- validating
- generating pages
- saving local files
- completed
- partial failure
- failed

UI elements:

- large status pill
- linear progress indicator
- short status log
- elapsed time
- run ID

The runner should write status snapshots frequently so the UI can update without fake demo states.

### Section 4: Result Summary Panel

Purpose:
Provide a fast completion overview.

Contents:

- series name
- total pages requested
- total pages returned
- success count
- failure count
- timestamp
- output bundle size if known

Display as a compact metrics strip with strong contrast and large numerals.

### Section 5: Page Gallery

Purpose:
Scan the output quickly.

Card content per page:

- thumbnail
- page number
- short excerpt
- success or failed badge

Interaction:

- clicking a card opens the page detail inspector
- failed cards are visually distinct and sortable to the front later

### Section 6: Page Detail Inspector

Purpose:
Support close review of one page.

Contents:

- full-size image
- page number
- Chinese content text
- generation notes
- file name
- image URL

Future controls:

- regenerate page
- edit prompt
- download single page

In phase 1, the controls may be read-only except for download.

### Section 7: Project Files Panel

Purpose:
Expose the saved local run outputs clearly.

Actions:

- download manifest JSON
- show local run folder path

The primary artifact is the local project folder. The UI should not advertise zip exports or clipboard actions that it does not actually perform.

## Interaction model

### Happy path

1. User pastes text.
2. User optionally tunes style and page count.
3. User clicks `Generate Comic`.
4. The UI locks the form and shows run progress.
5. The result summary appears.
6. The page gallery fills with returned pages.
7. The user inspects one or more pages.
8. The user uses the local project folder or downloads the manifest JSON.

### Partial failure path

1. Some pages succeed and some fail.
2. Summary shows partial failure state clearly.
3. Failed pages remain visible in the gallery.
4. Manifest and local project folder remain available if at least one page succeeded.
5. The failed state should not overwrite successful results.

### Hard failure path

1. The request fails before valid page output is returned.
2. The status panel becomes the dominant focus.
3. The error message explains whether it was validation, network, or backend parsing failure.
4. The user can retry without retyping the input.

## Content style

Keep labels operational and plain. Avoid overly playful copy in controls. Save the comic flavor for section framing and visual styling.

Examples:

- good: `Generate Comic`
- good: `Pages Returned`
- bad: `Summon Panels`
- bad: `Magic Happens Here`

## Accessibility

- maintain strong contrast on textured backgrounds
- ensure the status banner is readable by screen readers
- make all buttons keyboard accessible
- never encode status by color alone
- support reduced motion
- keep large textareas and image cards focus-visible

## Motion

Use minimal but purposeful motion:

- subtle panel fade-in on completed results
- progress-strip transition between stages
- gentle hover lift on page cards

Do not use heavy animation during long-running generation. The system should feel stable, not decorative.

## Streamlit-specific guidance

### Layout primitives

- use `st.columns` for the left rail and right stage on desktop
- use containers for section framing
- use `st.session_state` to preserve current run and selected page
- use `st.status` or equivalent for progress messaging
- use custom CSS to establish tokens, panel borders, texture, and typography

### State model

Session state should track:

- current form values
- current run status
- current run result payload
- selected page
- manifest path
- error message

### Rendering strategy

- render input controls first
- render state summary second
- render results only when available
- avoid rerender flicker by isolating the gallery and inspector containers

## Design tokens

```text
Color / Ink:        #161412
Color / Paper:      #f6f0e7
Color / Accent Red: #cf4c36
Color / Accent Cyan:#6ea7a3
Color / Success:    #2f6b45
Color / Warning:    #b7791f
Color / Border:     #2b2723
Radius / Panel:     18px
Shadow / Card:      0 10px 30px rgba(22,20,18,0.10)
Spacing base:       8px
```

## UI acceptance criteria

- The user can understand the workflow without seeing backend implementation details.
- Input, progress, results, and project files are visible in one page flow.
- Failed pages are obvious without blocking successful page review.
- The local project folder is prominent and unambiguous.
- The interface has a distinct comic-studio character rather than default Streamlit styling.

## Design handoff notes

If this spec is used to generate a UI design, the design should show:

- one full-page desktop view
- one mobile adaptation
- idle state
- in-progress state
- completed state with at least four page cards
- partial failure state with one failed card

The resulting design should prioritize workflow clarity first and visual identity second.
