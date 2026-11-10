---
name: clip
description: Turn a live stream, VOD or long video into finished vertical Shorts (9:16, hook, captions) with the local Clipper OS pipeline. Use whenever the user asks to clip a live/stream/VOD/video, make shorts/reels/tiktoks from a URL, find the most viral moments, or clip the best moments from a streamer — in any language, e.g. "clip this live: <URL>", "make the best 3 shorts from this stream", "find the most viral moments", "clip the best moments from X", "make shorts from this VOD", "faz clips desta live".
---

# Clip a live/VOD into finished Shorts

Run the local Clipper OS pipeline. It does everything: yt-dlp download → faster-whisper (local) →
Claude picks the most viral moments → FFmpeg cuts, reframes to 9:16, adds the hook and captions,
normalizes audio → `outputs/<vod-id>/clip-01.mp4 … clip-03.mp4` + `report.md`.
No paid services beyond the user's Claude Code. Nothing is uploaded or published.

Reply to the user in European Portuguese (pt-PT) unless they write in another language.

## Steps

1. **Get the URL.**
   - If the user gave a URL (YouTube, Twitch VOD, Kick, …) or a local video file, use it.
   - If they only named a streamer/channel, find their most recent VOD and **confirm it with the user
     before processing**:
     - Twitch: `<python> -m yt_dlp --flat-playlist -I 1:3 --print "%(title)s | %(url)s" "https://www.twitch.tv/<name>/videos?filter=archives"`
     - YouTube: `<python> -m yt_dlp --flat-playlist -I 1:3 --print "%(title)s | %(url)s" "https://www.youtube.com/@<name>/streams"`
   - One VOD per request. If they give several, ask which one first.

2. **Pick the Python of the project venv** (no activation needed):
   - Windows: `.venv/Scripts/python.exe` (Git Bash) or `.venv\Scripts\python.exe` (PowerShell)
   - Linux/macOS: `.venv/bin/python`
   - If `.venv` does not exist, stop and point the user to the installation section of `README.md`.

3. **Map the request to options** (defaults are good; only add what the user asked for):
   - number of shorts ("make 5 shorts") → `--clips 5` (default 3)
   - language of hooks/titles ("in English") → `--lang en` (default from `config.yaml`, pt-PT)
   - facecam on top + gameplay below → `--layout split`; person centred → `--layout crop`
     (default `blur` works for everything)
   - "redo the analysis" / "find different moments" → `--reanalyze`

4. **Run it in the background** — it can take from ~10 minutes to over an hour (download + local
   transcription of a long live). Use the Bash tool with `run_in_background: true`:

   ```
   <python> -m clipper auto "<URL>" [options]
   ```

   Tell the user it started and roughly what happens next. Don't poll in a tight loop; you are notified
   when it finishes. If the user asks, read the output so far and report the current step ([1/5] … [5/5]).

5. **When it finishes**, read `outputs/<vod-id>/report.md` (the folder is printed at the end) and reply with:
   - the full path of each `clip-NN.mp4`, its title, viral score and hook;
   - one line on **why** each moment was chosen;
   - a note for any clip marked ⚠ (below the quality threshold, included to complete the set);
   - that titles, descriptions, hashtags and thumbnail text are in `report.md`.

## Rules

- Never upload, publish or schedule anything.
- Do not use OpusClip in this flow. Only use `python -m clipper run … --provider compare` if the user
  explicitly asks to compare with OpusClip (it spends OpusClip credits and asks for confirmation).
- Don't re-run with `--reanalyze` or process extra VODs unless asked.
- If the error says the live is still running: tell the user to try again when the VOD is available.
- Other errors: show the last lines of the output and run `<python> -m clipper doctor`.
- Remind the user once to clip only creators who allow it, and to credit them (the description already does).
