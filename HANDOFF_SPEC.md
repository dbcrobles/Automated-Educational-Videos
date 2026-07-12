# Implementation Spec — Simplified 5-Worker Pipeline

> **Source**: Fable 5 architecture audit of the full codebase (all 7 nodes, orchestrator, router, database layer, dashboard).
> **Executor**: GLM 5.2 / DeepSeek. Each section is independently executable and testable.
> **Scope note**: All former "suggested improvements" have been promoted into REQUIRED steps and folded into the node sections below. Nothing in this document is optional unless explicitly tagged `[PHASE 2]`.
> **Recommended execution order**: DB migrations → Node 1 merge → Node 2 voice sidecars → Node 3 hardening + cache → Remotion scaffold (test standalone) → Node 4 rewrite → Node 5 publisher changes → main.py + dashboard cleanup → delete dead code.

---

## 0. Global Architecture Decisions

**New state machine (single source of truth):**

```
Pending_Script → QA_Script (manual; skipped when auto_approve=1)
→ Pending_Voice → Pending_Assets → Pending_Render
→ QA_Final (manual; skipped when auto_approve=1) → Ready_To_Publish → Published
Any failure → Failed (error_message populated)
```

**Status renames / removals (must be migrated in DB AND dashboard):**

| Old | New |
|---|---|
| `Pending_QA` | removed → becomes `QA_Script` or `Pending_Voice` |
| `Pending_Voiceover` | `Pending_Voice` |
| `Pending_Compliance` | removed → render node goes straight to `QA_Final` |

**Night-mode rule:** Node 1 checks `auto_approve`: writes `Pending_Voice` instead of `QA_Script`. Node 4 checks `auto_approve`: writes `Ready_To_Publish` instead of `QA_Final`.

### 0.1 Per-video asset subfolders (NEW — cross-cutting)

All intermediates for a video live in `Backend/assets/{id}/`. The flat assets dir is already polluted with ~180 stale caption PNGs; this ends that.

| File | Producer | Consumer |
|---|---|---|
| `assets/{id}/voiceover.mp3` | Node 2 | Node 4 |
| `assets/{id}/timing.json` | Node 2 | Node 3 (optional), Node 4 |
| `assets/{id}/captions.json` | Node 2 | Node 4 |
| `assets/{id}/scene_{n}.mp4` | Node 3 | Node 4 (preprocessing) |
| `assets/{id}/prepped_scene_{n}.mp4` | Node 4 preprocess | Remotion |
| `assets/{id}/prepped_intro.mp4` | Node 4 preprocess | Remotion |
| `assets/{id}/comp.json` (Remotion props) | Node 4 | Remotion CLI |
| `assets/{id}/final.mp4` | Node 4 | Node 5 |

Shared (NOT per-video):
- `assets/cache/{hash}.mp4` — stock-clip cache (see Node 3)
- `assets/music/{mood}/*.mp3` — music library (see Node 4)
- `assets/intros/{account_id}/*.mp4` — human intros (unchanged)

**Legacy fallback rule (mandatory, applies to every node):** when reading an input, first check the new path (`assets/{id}/voiceover.mp3`), then the legacy flat path (`assets/voiceover_{id}.mp3`). This keeps videos 5–9 testable. Add one shared helper `asset_path(video_id, filename)` in `database.py` or a new `Backend/paths.py` (~10 lines) that resolves new-then-legacy.

### 0.2 API cost tracking (NEW — cross-cutting)

Every node that spends money logs an estimate. Minimal helper — add to `database.py`:

```python
def add_cost(video_id, usd):
    conn = get_connection()
    conn.execute(
        "UPDATE videos SET api_cost_estimate = COALESCE(api_cost_estimate, 0) + ? WHERE id = ?",
        (usd, video_id))
    conn.commit()
    conn.close()
```

Per-node rate constants (top of each file, adjust to real billing):

| Node | Constant | Default |
|---|---|---|
| Node 1 | `COST_RESEARCH_CALL` | `0.05` (pro-tier + search) |
| Node 1 | `COST_SCRIPT_CALL` | `0.01` (flash-tier JSON) |
| Node 2 | `ELEVENLABS_USD_PER_CHAR` | `0.00011` (multilingual_v2, creator tier) |
| Node 3 | `COST_VEO_GENERATION` | `0.40` per clip (stock fetches are free) |

Call `database.add_cost(video_id, estimate)` immediately after each successful paid call. The dashboard displays the running total (see Dashboard Changes).

---

## Node 1 — Script (absorbs Tech Director)

### Current Behavior
`node1_scripting.py` does 2 Gemini calls (search research → JSON storyboard), sets `Pending_QA`. `node2_tech_director.py` does a 3rd call (gemini-2.5-flash) that injects an intentional typo, splits narration into `audio_narration`/`caption_narration`, scores hook/retention, and auto-rejects on hook<6 or duration outside 65–105s.

### Problems
- 3 LLM calls where 2 suffice; the QA call is pure prompt-engineering that Pass 2 can do itself.
- Typo strategy adds the entire `audio_narration`/`caption_narration` split and `apply_typo_rule()` complexity downstream — being dropped.
- Auto-reject loops back to `Pending_Script` with no retry cap → can ping-pong forever burning API money.
- Duration gate uses fake pacing seconds (2/4/8); real duration comes from the voiceover now.
- `visual_search_query` prompts don't emphasize *motion* content.
- Pass 2 runs on a pro-tier model for what is a constrained JSON transform — ~10x overspend.

### Data Contract Changes
New Pydantic schema in `node1_scripting.py` (replaces both old schemas):

```python
class Hook(BaseModel):
    hook_type: str          # "question" | "statistic" | "controversy" | "promise"
    hook_text: str

class Scene(BaseModel):
    visual_search_query: str      # motion-oriented stock VIDEO query, 2-5 words
    narration: str                # single field — perfect spelling, spoken verbatim
    pacing_style: str             # "rapid" | "standard" | "slow_pan"
    transition_hint: str          # "whip_pan" | "zoom_punch" | "crossfade" | "dissolve" | "dip_to_black"
    hook: Optional[Hook] = None   # ONLY on scene 0 (publisher reads scenes[0].hook.hook_text)

class ScriptOutput(BaseModel):
    title: str
    word_count: int
    hook_score: float             # 0-10, self-assessed
    retention_estimate: float     # 0-100 (%)
    music_mood: str               # "tense" | "uplifting" | "mysterious" | "neutral"  (NEW)
    scenes: list[Scene]
    sources: list[str]
```

DB writes: `script` (full JSON), `script_sources`, `hook_score`, `retention_estimate`.

**Transition-hint constraint table (bake into the prompt):**

| pacing_style | allowed transition_hint | render duration |
|---|---|---|
| rapid | whip_pan, zoom_punch | 100–150 ms (4 frames @30fps) |
| standard | crossfade | 200–300 ms (8 frames) |
| slow_pan | dissolve, dip_to_black | 400–500 ms (14 frames) |

### Implementation Steps
1. **Keep Pass 1 unchanged** (research via `google_search` tool with the existing knowledge-only fallback). The 2-pass structure stays because tools + `response_schema` can't be combined in one Gemini call.
2. **Split the model constants** (REQUIRED, was a suggestion):
   ```python
   GEMINI_MODEL_RESEARCH   = "gemini-3.1-pro"      # Pass 1 — needs search grounding
   GEMINI_MODEL_STRUCTURED = "gemini-2.5-flash"    # Pass 2 — constrained JSON transform
   ```
   Pass 2 is a transform of already-retrieved research; flash-tier handles it at ~1/10 the cost. Keep both as swappable constants — never inline model strings.
3. **Rewrite Pass 2 prompt** to add:
   - Self-QA block: "Score your own hook 0–10 (`hook_score`) and estimate 3-second retention % (`retention_estimate`). Be harsh — a generic hook is a 4."
   - Stock-video query rule: "Every `visual_search_query` MUST describe *motion* (e.g. 'aerial city traffic night', 'hands typing keyboard closeup'), never a static scene. 2–5 literal words, no conversational filler."
   - `transition_hint` rule with the table above, plus: "no more than 2 consecutive scenes with the same pacing_style; use deliberate contrast patterns (rapid-rapid-slow_pan = tension/release)."
   - **Music mood rule (NEW):** "Choose one `music_mood` for the whole video that matches the emotional arc: 'tense', 'uplifting', 'mysterious', or 'neutral'."
   - Word-count gate: "Total narration must be 170–260 words (≈ 65–100 s at 2.6 words/sec). Report the true count in `word_count`."
   - Keep: CTA injection, hook object on scene 0, source citation, no-hallucination rule. Delete the typo rule — replace with "Perfect spelling everywhere."
4. **Post-generation validation in Python** (in `run()`, after parsing):
   - Recount words locally (`sum(len(s['narration'].split()) for s in scenes)`); if outside 160–280 OR `hook_score < 6` → increment `script_retry_count`; if `script_retry_count < 2` write `status='Pending_Script'` + `qa_feedback` explaining the rejection; else `status='Failed'`. This kills the infinite loop.
   - Validate `pacing_style`/`transition_hint`/`music_mood` against the enums; coerce invalid values to `standard`/`crossfade`/`neutral` (don't fail the video over one bad enum).
5. **Cost logging:** after Pass 1 success → `database.add_cost(video_id, COST_RESEARCH_CALL)`; after Pass 2 success → `add_cost(video_id, COST_SCRIPT_CALL)`.
6. **Success path:** `status = 'Pending_Voice' if video['auto_approve'] else 'QA_Script'`, write `hook_score`, `retention_estimate`, reset `script_retry_count=0`, clear `qa_feedback`.
7. **Delete** `Backend/nodes/tech_director/` entirely; remove its import + `node2_tech_director.run()` from `main.py`.

### Testing Plan
- No-API test: hardcode a canned `research_text`, monkeypatch `client.models.generate_content` to return a fixture JSON; assert schema validation, word-count gate, retry-counter logic, enum coercion (feed one bad `music_mood`).
- One live smoke test: insert a topic with `auto_approve=0`, run Node 1 once, verify `status='QA_Script'`, script parses against the new schema, and `api_cost_estimate ≈ 0.06`.

### Risk / Gotchas
- Self-scored `hook_score` will inflate (models grade their own work generously). Mitigation is prompt-side ("be harsh"); the manual QA gate is the real check.
- Existing videos 5–9 have scripts in the OLD schema (`audio_narration`, no `transition_hint`, no `music_mood`). Downstream nodes MUST fall back: `scene.get('narration') or scene.get('audio_narration')`, `scene.get('transition_hint', 'crossfade')`, `script.get('music_mood', 'neutral')`.
- Flash-tier Pass 2 may occasionally produce weaker prose than pro. If QA rejections spike, flip `GEMINI_MODEL_STRUCTURED` back — it's one constant.

---

## Node 2 — Voice (rename from Node 2b)

### Current Behavior
Single ElevenLabs `/with-timestamps` call on the concatenated narration, decodes character-level alignment into words, writes MP3 + a 4-word-chunk SRT (with typo remapping).

### Problems
- No per-scene timing is persisted — the render node currently *invents* durations from pacing enums, which is why clips loop (`-stream_loop -1`) and cut mid-sentence.
- SRT is a lossy format for word-level animated captions; Remotion wants JSON.
- `apply_typo_rule()` is dead weight once the typo strategy dies.

### Data Contract Changes
- **New file** `assets/{id}/timing.json`:
  ```json
  [{"scene_index": 0, "start": 0.0, "end": 4.23}, {"scene_index": 1, "start": 4.23, "end": 7.91}]
  ```
- **New file** `assets/{id}/captions.json`:
  ```json
  [{"word": "secret", "start": 0.0, "end": 0.31}]
  ```
- **Dropped:** SRT output, `generate_srt_text()`, `apply_typo_rule()`, `format_time_srt()`.
- DB: `voiceover_path` still written (now pointing into `assets/{id}/`); sidecars found by convention.

### Implementation Steps
1. Move/rename file to `Backend/nodes/voice/node2_voice.py`; poll status `'Pending_Voice'`.
2. **TTS input construction (critical for scene mapping):** build `narrations = [scene narration strings]` (with the legacy `audio_narration` fallback), then `full_text = " ".join(narrations)`. Keep `scene_word_counts = [len(n.split()) for n in narrations]`.
3. Keep the existing character→word grouping logic (lines 42–68 of the current file) — it already produces `[{word, start, end}]`. Write that list directly as `captions.json`.
4. **Per-scene timing:** because `full_text` is the exact string ElevenLabs aligned, the word list length equals `sum(scene_word_counts)`. Walk the word list, slicing `scene_word_counts[i]` words per scene: `start = first_word.start`, `end = last_word.end`. Assert total word count matches; if not (alignment merged something), fall back to proportional allocation by character count and log a warning — never crash.
5. Write both JSON files + MP3 into `assets/{id}/`. Success → `status='Pending_Assets'`.
6. **Cost logging:** `database.add_cost(video_id, len(full_text) * ELEVENLABS_USD_PER_CHAR)`.
7. **Model note:** `model_id` stays a constant. `eleven_multilingual_v2` ≈ 1 credit/char; `eleven_turbo_v2_5` is 0.5 credit/char with slightly flatter delivery — cost lever, don't switch silently.

### Testing Plan
- Zero-cost: save one real ElevenLabs response as `Backend/nodes/voice/fixtures/alignment_sample.json`; add a fixture-loading test path (`python3 node2_voice.py --fixture`) verifying: (a) word JSON monotonically increasing, (b) scene timing covers [0, audio_duration] with no gaps/overlaps > 50 ms, (c) `len(words) == sum(scene_word_counts)`, (d) cost estimate written.

### Risk / Gotchas
- ElevenLabs alignment characters include punctuation; the word-splitter must treat "—" and ellipses consistently with Python `.split()` or counts drift. The proportional fallback in step 4 is the safety net.
- Do NOT "normalize" text (e.g. expand "$1,000") before sending — alignment is over input text, so keeping the exact script text preserves the 1:1 word mapping.

---

## Node 3 — Assets (hardened + cache + dedup)

### Current Behavior
Confirmed: already hits the correct **video** endpoints — Pexels `https://api.pexels.com/videos/search` and Pixabay `https://pixabay.com/api/videos/`. Both return real motion footage. Tiered fetch → Veo fallback (max 3), then `validate_clip()`.

### Problems
- **Bug (fix is REQUIRED):** when `validate_clip()` fails, the file is deleted but the dead path is still appended to `downloaded_paths` (lines 221–225) and the video sails on to render, which silently drops the scene → audio/visual desync.
- `per_page=1` on Pexels: first result is often landscape-cropped or low quality.
- Pixabay has **no orientation parameter** — current code takes `hits[0]` blindly, usually landscape.
- 5-second request timeout is aggressive for video API responses.
- Clip duration is never checked against the scene's narration length.
- Same query across videos re-downloads the same footage (rate-limit + bandwidth waste).
- Two scenes in one video can resolve to identical footage — repeated b-roll is a retention killer.

### Data Contract Changes
- Still writes `video_path` = JSON array of local paths (now `assets/{id}/scene_{n}.mp4`), → `Pending_Render`.
- Reads `assets/{id}/timing.json` (if present) for per-scene minimum durations.
- **New shared cache dir** `assets/cache/`. Key function (~6 lines, include verbatim):
  ```python
  import hashlib
  def cache_path(query):
      h = hashlib.sha1(query.lower().strip().encode()).hexdigest()[:16]
      return os.path.join(ASSETS_DIR, 'cache', f'{h}.mp4')
  ```

### Implementation Steps
1. **`fetch_from_pexels(keyword, min_duration)`**: `per_page=5&orientation=portrait`. Rank candidates: (a) `video_files` entry with `width < height` natively, (b) `duration >= min_duration`, (c) highest resolution ≤ 1080×1920 (don't download 4K). Return a ranked list of `(source_id, url)` tuples, not just one URL.
2. **`fetch_from_pixabay(keyword, min_duration)`**: `per_page=10`. Filter `hits` where `videos.large.width < videos.large.height`; if none portrait, accept landscape (Node 4 crops anyway) but sort portrait-first, then `duration >= min_duration`, then resolution. Return ranked `(source_id, url)` list.
3. **Cache check first:** for each scene, compute `cache_path(query)`. If it exists AND its cache key hasn't been used by an earlier scene in *this* video → copy it to `assets/{id}/scene_{n}.mp4` and skip the APIs entirely.
4. **Duplicate-clip guard:** maintain `used_sources: set` per video containing every consumed `source_id` (Pexels video id / Pixabay id / cache hash). When ranking candidates, skip any whose `source_id ∈ used_sources`. Add the winner's id after each scene.
5. **Retry-through-candidates loop (fixes the ghost-path bug):** for each scene, iterate candidates (cache → Pexels list → Pixabay list → Veo); download → `validate_clip()` → on failure, delete the file and try the NEXT candidate. Only fail the scene when everything (incl. Veo, capped at 3/video) is exhausted. A path is appended to `downloaded_paths` ONLY after validation passes.
6. **Cache write-back:** after a stock clip passes validation, copy it into `cache_path(query)` (skip for Veo output — generated clips are topic-specific).
7. Load `timing.json` if present: `min_duration = end - start + 0.5s` padding (transition overlap). If missing (legacy), use pacing defaults (2/4/8).
8. Bump `requests` timeouts to 15 s (search) / 60 s (download).
9. **Cost logging:** `database.add_cost(video_id, COST_VEO_GENERATION)` per successful Veo generation. Stock fetches log nothing.
10. Keep `validate_clip()` as-is.

### Testing Plan
- Free: Pexels/Pixabay searches don't consume paid quota — run against a test row (`UPDATE videos SET status='Pending_Assets' WHERE id=5;`) and inspect: every file `ffprobe`-reports a video stream, `len(paths) == len(scenes)`, all paths exist, second run of the same video hits the cache (log line check).
- Bug regression: force `validate_clip` to return `False` once and confirm the loop advances to the next candidate — no ghost path.
- Dedup: craft a script where two scenes share one query; confirm two *different* source_ids are downloaded.

### Risk / Gotchas
- Pexels rate limit is 200 req/hr free tier — the cache directly protects this. Don't add per-candidate HEAD requests.
- Cache staleness is a non-issue (stock footage doesn't rot), but add a `MAX_CACHE_GB = 5` sweep: if the cache dir exceeds it, delete oldest-accessed files first (~10 lines, `os.path.getatime`).
- Veo cost is the wildcard in the $2.50 budget; candidates + cache should push Veo usage toward zero.

---

## Node 4 — Render (Remotion rewrite; absorbs Compliance + Intro + Ken Burns)

### Current Behavior
~380 lines of FFmpeg filter-graph assembly: fixed pacing durations with `-stream_loop -1 -shortest`, Pillow PNG caption overlays via concat demuxer (Homebrew FFmpeg lacks libfreetype/libass — hence the hundreds of `cap_*.png` files), an intro splice pass, then a separate node (Node 5 Compliance) doing another FFmpeg pass for the "AI-Assisted" overlay + IPTC metadata.

### Problems
- Clip duration is decoupled from narration → looping footage, cuts mid-word.
- No transitions, no word-level caption animation, no music. Output looks 2019.
- 3–4 full re-encodes per video (base → captions → intro → compliance) — slow and lossy.
- The caption PNG system litters assets/ with ~90 PNGs per video.
- The FFmpeg animated-crop "Ken Burns" tricks die with the filter graph and need a home.

### Data Contract Changes
- **New Remotion project** at `Backend/remotion/` (Node/React, isolated from Python).
- **New props file** `assets/{id}/comp.json` — the complete declarative video description:

```json
{
  "fps": 30, "width": 1080, "height": 1920,
  "durationInFrames": 2295,
  "intro": {"src": "5/prepped_intro.mp4", "durationInFrames": 150},
  "scenes": [
    {"src": "5/prepped_scene_0.mp4", "durationInFrames": 127, "sceneIndex": 0,
     "pacingStyle": "rapid", "transitionAfter": {"type": "whip_pan", "durationInFrames": 4}}
  ],
  "voiceoverSrc": "5/voiceover.mp3",
  "captions": [{"word": "secret", "startFrame": 0, "endFrame": 9}],
  "music": {"src": "music/uplifting/track_02.mp3", "volumeDb": -18, "fadeOutSec": 2},
  "compliance": {"text": "AI-Assisted", "fullDuration": false},
  "accentColor": "#FFD447"
}
```

  Notes: `intro` is optional (`null` when `use_human_intro=0` or no intro files exist). Caption/scene frames are relative to the START OF THE MAIN CONTENT, not the composition — the intro offset is applied once in React (see step A3). Python converts all seconds → frames at 30 fps; Remotion does zero timing math.
- `is_sponsored=1` → `compliance.text = "#ad | AI-Assisted"`, `fullDuration: true`.
- Node 4 writes `compliance_metadata` to DB (moved from Node 5).
- Status: `Pending_Render` → `QA_Final` (or `Ready_To_Publish` if `auto_approve`).

### Implementation Steps

**A. Remotion project scaffold (`Backend/remotion/`)** — one-time setup:

1. `package.json` with: `remotion`, `@remotion/cli`, `@remotion/transitions`, `react`, `react-dom`. Pin Remotion to one exact version — **all `@remotion/*` packages must match versions exactly** (known Remotion footgun).
2. `src/Root.tsx`: registers composition `ShortVideo` with `calculateMetadata` reading `durationInFrames`/fps/size from input props.
3. `src/ShortVideo.tsx`: top-level layout —
   - **Intro handling (NEW, replaces the FFmpeg splice):** if `props.intro` is set, render `<Sequence from={0} durationInFrames={intro.durationInFrames}><OffthreadVideo src={staticFile(intro.src)} /></Sequence>` — NOT muted (the human intro keeps its own audio). Then wrap ALL main content (TransitionSeries + voiceover `<Audio>` + `<Captions>`) in a single `<Sequence from={intro?.durationInFrames ?? 0}>`. Because everything shifts together inside one Sequence, no per-item frame math changes. Composition `durationInFrames = (intro?.durationInFrames ?? 0) + Σ scene durations`.
   - `<TransitionSeries>` of scenes: sequence *i* has `durationInFrames = scene_i.durationInFrames + transitionAfter_i.durationInFrames` (last scene: no transition). **Timeline math** (verify in a unit test): with this padding, scene *i* becomes fully visible at exactly `Σ scene_dur[0..i-1]` frames within the main Sequence — matching `timing.json`. Clips rendered with `<OffthreadVideo muted>`.
   - Transition mapping: `whip_pan` → `slide()` 4-frame linear; `zoom_punch` → custom presentation (incoming clip scales 1.15→1.0, opacity 0→1, over 4 frames — ~20 lines); `crossfade` → `fade()` 8 frames; `dissolve` → `fade()` 14 frames; `dip_to_black` → `fade()` through a black `<AbsoluteFill>` 14 frames.
   - **Ken Burns per scene (NEW):** wrap each clip in a scaling container:
     ```tsx
     const zoomAmt = { rapid: 0, standard: 0.04, slow_pan: 0.08 }[pacingStyle] ?? 0.04;
     const scale = interpolate(
       frame, [0, durationInFrames],
       sceneIndex % 2 === 0 ? [1, 1 + zoomAmt] : [1 + zoomAmt, 1]  // alternate in/out
     );
     // <AbsoluteFill style={{ transform: `scale(${scale})` }}>
     ```
   - `<Audio src={voiceoverSrc} />` at frame 0 *of the main Sequence*.
   - Music `<Audio loop>` spans the WHOLE composition (under the intro too) with volume curve:
     ```tsx
     const musicVolume = (f: number) => {
       const base = Math.pow(10, volumeDb / 20);              // -18 dB ≈ 0.126
       const fadeStart = totalFrames - fadeOutSec * fps;
       return f < fadeStart ? base
            : base * Math.max(0, (totalFrames - f) / (fadeOutSec * fps));
     };
     ```
4. `src/Captions.tsx`: groups the word array into pages (new page every 4 words OR when a word ends with `.!?`). Active page: rounded-rect pill (`background: rgba(0,0,0,0.55); border-radius: 24px; padding: 12px 28px`), positioned `bottom: 22%` centered; each word a `<span>` — white normally, `accentColor` + `scale(1.08)` while `currentFrame ∈ [word.startFrame, word.endFrame]`; page entrance = `spring()` scale 0.8→1 over ~5 frames. Font: **Montserrat Bold from a local TTF** in `remotion/public/fonts/` via `@font-face` (avoid `@remotion/google-fonts` — no network at render time).
5. `src/ComplianceOverlay.tsx`: small semi-transparent black box, bottom-left, white 28px text, shown composition frames `0..3*fps` (or all frames when `fullDuration`). Rendered at the composition root so it covers the intro too (disclosure must be visible from second 0).
6. All media referenced via `staticFile()` — Python must **symlink** referenced assets into `Backend/remotion/public/` before rendering (Remotion only serves from `public/`). Symlink the whole `assets/{id}/` folder as `public/{id}` plus `assets/music` as `public/music`.

**B. Rewrite `node4_render_worker.py`:**

1. `preprocess_clips(video)`: for each scene *i*, one FFmpeg call:
   ```
   ffmpeg -y -i assets/{id}/scene_{i}.mp4 -t {scene_dur + transition_dur + 0.2} \
     -vf "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30" \
     -an -c:v libx264 -preset veryfast -crf 20 -pix_fmt yuv420p assets/{id}/prepped_scene_{i}.mp4
   ```
   If the source is shorter than needed, add `-stream_loop -1` before `-i` (bounded by `-t`). Sequential, never parallel (18 GB constraint).
2. `preprocess_intro(video)` (NEW): if `use_human_intro` and `assets/intros/{account_id}/` has `.mp4` files, pick one with `random.Random(video_id).choice(...)`, preprocess with the same scale/crop/fps filter but KEEP AUDIO (`-c:a aac -ar 44100 -ac 2` instead of `-an`) → `assets/{id}/prepped_intro.mp4`. `ffprobe` its duration → `intro.durationInFrames = round(dur * 30)`. No intro → `intro: null`.
3. `build_props(video)`: load `timing.json` + `captions.json` + script scenes; convert to frames (`startFrame = round(start * 30)` — always from absolute seconds, never cumulative sums); resolve `transition_hint` → `{type, durationInFrames}` (default `crossfade`/8 for legacy scripts); **music selection by mood (NEW):** read `script.get('music_mood', 'neutral')`, list `assets/music/{mood}/*.mp3` (fall back to `assets/music/**/*.mp3` if the mood folder is empty), select with `random.Random(video_id).choice(...)` (deterministic → reproducible re-renders); write `assets/{id}/comp.json`. Create the `remotion/public/` symlinks.
4. `render(video)`: `subprocess.run(["npx", "remotion", "render", "ShortVideo", out_path, "--props", comp_json_path, "--concurrency", "2"], cwd=REMOTION_DIR)`. `--concurrency 2` caps Chrome-renderer memory. Capture stderr tail into the exception message like the current code does.
5. `stamp_metadata(out_path)`: single stream-copy pass (near-instant, no re-encode):
   ```
   ffmpeg -y -i rendered.mp4 -metadata comment="AI-Assisted | {GEMINI_MODEL_STRUCTURED}" \
     -metadata copyright="© 2026 {account_id}" -c copy assets/{id}/final.mp4
   ```
6. Write DB: `video_path=assets/{id}/final.mp4` (absolute), `compliance_metadata` (same JSON shape Node 5 wrote, with the real model string), `status = 'Ready_To_Publish' if auto_approve else 'QA_Final'`.
7. Cleanup: delete `prepped_*` files and `remotion/public/` symlinks after success. (Full intermediate cleanup happens post-publish — see Node 5.)
8. **Delete** `Backend/nodes/compliance/` AND the old intro-splice code path entirely (the Remotion intro replaces it); remove compliance from `main.py`.

### Testing Plan
- **Remotion in isolation, zero API cost:** hand-write a `comp_test.json` using 3 short clips from videos 5–9 intermediates + `voiceover_5.mp3` + one intro file; run `npx remotion studio` for interactive preview (captions, Ken Burns, transitions, intro — all visible live), then `npx remotion render`; check A/V sync at scene boundaries and that voiceover starts exactly when the intro ends.
- **Full node re-test:** `sqlite3 Backend/database/db.sqlite "UPDATE videos SET status='Pending_Render' WHERE id=5;"` — video 5 has NO `timing.json` (old pipeline). Required fallbacks: pacing-enum durations when timing JSON is absent; synthesize caption frames from the old SRT via a small `srt_to_captions_json()` shim (reuse the existing `parse_srt`). This keeps the "test with existing data" constraint satisfied.
- Timeline math unit check: 3-scene props file, assert scene *i* first-fully-visible frame == cumulative scene durations (+ intro offset when present).

### Risk / Gotchas
- First `npx remotion render` downloads a headless Chrome (~150 MB) — do it during setup, not the first pipeline run.
- Version-mismatched `@remotion/*` packages produce cryptic errors — pin exactly.
- `staticFile()` cannot read absolute paths outside `public/` — the symlink step is mandatory.
- OffthreadVideo memory scales with concurrency — if the machine swaps, drop `--concurrency` to 1.
- Ken Burns `scale()` on a 1080×1920 clip never reveals edges (scaling UP only) — no letterboxing risk. Do NOT scale below 1.0.
- Intro audio level vs. TTS level may mismatch — add `-af loudnorm` to the intro preprocess if intros sound quiet.

---

## Node 5 — Publish (per-platform captions + cleanup)

### Current Behavior
Polls `Ready_To_Publish`. Has per-platform caption logic (`generate_platform_caption`) but sends ONE arbitrary caption (`'tiktok'`, line 108) to WoopSocial for all platforms in a single multi-platform post. Desktop banking + Snapchat/X stubs.

### Problems
- The per-platform captions are generated but never used — YouTube gets TikTok hashtags.
- Intermediates for published videos live on disk forever (~50–200 MB each).

### Data Contract Changes
None to the DB schema. `generate_platform_caption` reads `scenes[0].hook.hook_text` — preserved by the new script schema.

### Implementation Steps
1. **Per-platform captions (NEW):** replace the single WoopSocial POST with one POST per enabled platform, each using `generate_platform_caption(video_record, platform)` as `text` and `platforms=[platform]`. Failure handling: attempt all; collect failures; if ANY fail, raise with a message listing which platforms succeeded (e.g. `"Published: youtube, instagram. FAILED: tiktok — <error>"`) so a manual retry doesn't blind-double-post. If ALL succeed → `Published`.
2. **Post-publish cleanup (NEW):** after status is set to `Published`, delete every intermediate for the video: everything in `assets/{id}/` EXCEPT `final.mp4`, plus any legacy flat files matching `voiceover_{id}.mp3`, `captions_{id}.*`, `timing_{id}.json`, `video_{id}_scene_*.mp4`, `raw_{id}.mp4`, `captioned_{id}.mp4`, `cap_{id}_*.png`, `comp*_{id}.*`, `compliant_{id}.mp4`, `spliced_{id}.mp4`. Wrap in try/except — cleanup failure must never mark the video Failed (log a warning only). The desktop Content Bank copy already happens before upload, so nothing user-facing is lost.
3. Keep the Snapchat/X stubs and desktop banking unchanged.
4. Optional cosmetic rename `node6_publisher.py` → `node5_publisher.py` (skip if minimizing churn).

### Testing Plan
- Dry-run: point `WOOPSOCIAL_API_KEY` at a dummy value and monkeypatch `requests.post` to record calls; assert one call per enabled platform with distinct captions; assert partial-failure message format.
- Cleanup: create dummy files matching every legacy pattern for a fake id, run cleanup, assert only `final.mp4` survives.

### Risk / Gotchas
- N platform posts = N uploads of the same file (~3× bandwidth). If WoopSocial supports media-id reuse or per-platform text in one call, prefer that — check their docs during implementation; the loop is the guaranteed-correct fallback.
- Partial publish leaves the video in `Failed` with a truthful error message — acceptable; the operator decides whether to re-post remaining platforms manually.

---

## Database Migrations

Extend the `migrations` list in `database.py` (existing idempotent ALTER-loop). **Important discovery:** the live DB has columns (`error_message`, `auto_approve`, `use_human_intro`, `post_yt`, `post_ig`, `post_tt`, `save_to_desktop`) that exist in *neither* `schema.sql` nor the migration list — a fresh DB would crash the dashboard's INSERT. Fix while here:

```python
migrations = [
    # ... existing 9 entries ...
    ("error_message", "TEXT"),
    ("auto_approve", "INTEGER DEFAULT 0"),
    ("use_human_intro", "INTEGER DEFAULT 0"),
    ("post_yt", "INTEGER DEFAULT 1"),
    ("post_ig", "INTEGER DEFAULT 1"),
    ("post_tt", "INTEGER DEFAULT 1"),
    ("save_to_desktop", "INTEGER DEFAULT 1"),
    ("script_retry_count", "INTEGER DEFAULT 0"),
    ("api_cost_estimate", "REAL DEFAULT 0"),
]
```

Plus a one-time status-value migration appended to `migrate()` (idempotent — safe to run every import):

```sql
UPDATE videos SET status='Pending_Voice'  WHERE status='Pending_Voiceover';
UPDATE videos SET status='QA_Script'      WHERE status='Pending_QA';
UPDATE videos SET status='Pending_Render' WHERE status='Pending_Compliance';
```

Also: add the `add_cost()` helper (Section 0.2) and update `schema.sql` so fresh installs contain all columns.

---

## Dashboard Changes (`Frontend/reflex_dashboard/reflex_dashboard.py`)

1. Delete `from router import ollama_router` and the `submit_feedback` method (the per-status rejection-note system already covers this path).
2. `PIPELINE_STAGES`, `STATUS_META`, `status_badge()`: remove `Pending_QA`; rename `Pending_Voiceover` → `Pending_Voice` (label "Voiceover…" can stay).
3. `approve_script()` and `reject_to_voiceover()`: write `'Pending_Voice'`.
4. `retry_video()` smart-retry: replace `'Pending_Voiceover'` string; update docstring stage list.
5. **Cost badge (NEW, required):** add `api_cost_estimate: float` to `VideoModel` and `load_videos()`; render a `rx.badge(f"💲{video.api_cost_estimate:.2f}", ...)` in the card header next to the hook/retention badges (only when > 0).
6. **Video preview (NEW, required):** in the `QA_Final` card, add `rx.video(src=...)` playing `final.mp4` so review doesn't require Finder. Note: Reflex serves static files from `Frontend/assets/` — the simplest path is a small state method that copies (or symlinks) `assets/{id}/final.mp4` to `Frontend/assets/preview_{id}.mp4` on card load, and `rx.video(src=f"/preview_{id}.mp4")`. Delete the preview file on approve/delete.

---

## New Dependencies

| Kind | Item |
|---|---|
| System | Node.js ≥ 18 (already on machine) |
| npm (in `Backend/remotion/`) | `remotion`, `@remotion/cli`, `@remotion/transitions` (exact same version), `react`, `react-dom` |
| Font | Montserrat-Bold.ttf → `Backend/remotion/public/fonts/` (Google Fonts, OFL license, one-time download) |
| Music | 5–10 CC0 MP3s → `Backend/assets/music/{tense,uplifting,mysterious,neutral}/` (Pixabay Audio / FreePD; ~60–120 s each; at least 1 track per mood folder) |
| Python | none added; `ollama` becomes removable |

---

## Files to Create / Modify / Delete

```
MODIFY  Backend/main.py                                     (drop node2 + node5 imports/calls)
MODIFY  Backend/database/database.py                        (migrations, status remap, add_cost helper, asset_path helper)
MODIFY  Backend/database/schema.sql                         (add all columns for fresh installs)
MODIFY  Backend/nodes/scripting/node1_scripting.py          (merged prompt, new schema incl. music_mood, retry gate, flash Pass 2, cost logging)
DELETE  Backend/nodes/tech_director/                        (entire folder)
CREATE  Backend/nodes/voice/node2_voice.py                  (from node2b_voiceover.py; timing+captions JSON, cost logging)
DELETE  Backend/nodes/voiceover/                            (after migration)
MODIFY  Backend/nodes/asset_fetcher/node3_asset_fetcher.py  (per_page=5, portrait ranking, retry-candidates bug fix, cache, dedup, Veo cost logging)
MODIFY  Backend/nodes/render_worker/node4_render_worker.py  (full rewrite: preprocess incl. intro → props → Remotion → metadata)
DELETE  Backend/nodes/compliance/                           (entire folder)
DELETE  Backend/router/                                     (entire folder)
MODIFY  Backend/nodes/publisher/node6_publisher.py          (per-platform posts, post-publish cleanup)
CREATE  Backend/remotion/package.json
CREATE  Backend/remotion/src/Root.tsx
CREATE  Backend/remotion/src/ShortVideo.tsx                 (incl. intro Sequence + Ken Burns + transitions + music)
CREATE  Backend/remotion/src/Captions.tsx
CREATE  Backend/remotion/src/ComplianceOverlay.tsx
CREATE  Backend/remotion/public/fonts/Montserrat-Bold.ttf
CREATE  Backend/assets/music/{tense,uplifting,mysterious,neutral}/  (+ tracks)
CREATE  Backend/assets/cache/                               (empty dir; populated at runtime)
MODIFY  Frontend/reflex_dashboard/reflex_dashboard.py       (status renames, drop ollama, cost badge, QA_Final video preview)
DELETE  Backend/assets/cap_*.png                            (~180 legacy caption PNGs — obsolete)
```

---

## Execution Sequencing Notes

Everything above is required; sequence it so each phase is shippable:

**Phase 1 — Python-only (no Remotion yet, pipeline keeps working end-to-end):**
1. DB migrations + `add_cost` + `asset_path` helpers.
2. Node 1 merge (schema, prompt, retry gate, flash Pass 2, cost logging) + delete tech_director.
3. Node 2 sidecars + cost logging.
4. Node 3 bug fix + candidates + cache + dedup + Veo cost logging.
5. Node 5 per-platform captions + cleanup.
6. Dashboard status renames + ollama removal + cost badge.
   *(The OLD Node 4 FFmpeg renderer still runs during Phase 1 — it ignores the new sidecars but nothing breaks, because pacing-enum fallbacks remain.)*

**Phase 2 — Remotion:**
7. Scaffold `Backend/remotion/`, verify standalone with `npx remotion studio` + a hand-written `comp_test.json` (zero API cost).
8. Rewrite Node 4 (preprocess → props → render → metadata; intro + Ken Burns + music + compliance inside Remotion) + delete compliance node.
9. QA_Final video preview in dashboard.
10. Re-render video 5 end-to-end via the legacy fallbacks; then one fresh video through the whole new pipeline with `auto_approve=0`, checking `api_cost_estimate` lands well under $2.50 (target: <$1 with flash Pass 2 + cached stock).

**Deliberately deferred (do NOT build now):** nothing. All former suggestions are folded in above.