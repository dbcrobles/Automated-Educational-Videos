# Phase 5 — Remove ElevenLabs; ingest the owner's real narration

## What exists going in
- **The hidden dependency:** `Backend/nodes/voice/node2_voice.py` does more
  than TTS. The ElevenLabs `/with-timestamps` call returns character alignment
  that becomes `assets/{id}/captions.json` (word list `[{word, start, end}]`)
  and `assets/{id}/timing.json` (scene boundaries). Node 3 and Node 4 consume
  those files. The timing/caption *formats* must survive; the TTS must not.
- Format references: `_chars_to_words()` and `_build_scene_timing()` in
  node2; consumers `load_captions_words()` / `load_scene_durations()` in
  `Backend/nodes/render_worker/node4_render_worker.py`.
- Beats carry `spoken_text` per beat (word counts give beat boundaries).

## What this phase must produce
1. **Delete ElevenLabs entirely** (owner's explicit decision — remove, don't
   disable): in `node2_voice.py` remove the API call, `ELEVENLABS_API_KEY`,
   `ELEVENLABS_USD_PER_CHAR`, `VOICE_POOL`, `select_voice`; in the dashboard
   remove `POPULAR_VOICES`/`VOICE_IDS_TO_NAMES` (~lines 15–27), the
   Settings-tab voice picker, `save_voice_name`, and the `reject_to_voiceover`
   button; in `accounts_config.json` remove `elevenlabs_voice_id`,
   `elevenlabs_voice_name`, `voice_mode`; update `README.md` (setup env list
   and architecture line). Keep `_chars_to_words`-style logic only where the
   new alignment path needs it. `grep -ri elevenlabs` must come back empty.
   The legacy short-form path now also requires uploaded narration — that is
   accepted; it fully retires TTS.
2. **Narration upload (dashboard):** on `Awaiting_Narration` cards, an
   `rx.upload` accepting one audio file (mp3/m4a/wav) — the owner reading the
   beats in order (the card should display each beat's `spoken_text` as the
   recording script). Save to `Backend/assets/{id}/narration.(ext)`, convert
   to `voiceover.mp3` with ffmpeg (`/opt/homebrew/bin/ffmpeg`, see node2 for
   subprocess patterns).
3. **Alignment worker:** `Backend/nodes/narration/node2b_narration.py`, `run()`
   polling `Awaiting_Narration` for videos whose narration file exists:
   - Transcribe with **faster-whisper** (add to `Backend/requirements.txt`;
     model `small`, `word_timestamps=True`, runs locally, $0).
   - Produce `captions.json` in the exact `[{word, start, end}]` format.
   - Produce `timing.json`: walk the aligned words against each beat's
     `spoken_text` word count (same approach as node2's
     `_build_scene_timing`); entry per beat `{scene_index, start, end,
     timing_source: 'narration_alignment'}`. Tolerate small transcription
     drift by scaling word counts proportionally when totals differ by <10%.
   - Update `beats.json` with each beat's actual `start`/`end`.
   - Status → `Pending_LongRender`. No API cost to log (local).
4. Register the worker in `main.py`.

## Contract
`captions.json` and `timing.json` keep their existing formats byte-compatible
with what node4 already parses.

## Verification
1. Upload a test recording → `captions.json` + `timing.json` appear, formats
   match node4's `load_captions_words`/`load_scene_durations` expectations.
2. Beat boundaries in `timing.json` land within ~1 s of section changes when
   read against the recording.
3. `grep -ri elevenlabs` across the repo returns nothing.