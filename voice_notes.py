"""
voice_notes.py - the channels' voice notes, turned into English text so they can be read like any other post.

Runs after every 30-minute save (.github/workflows/telegram.yml). For each saved post marked as a voice
note ("voice" in telegram_posts.csv) that has no transcript yet, newest first, it reads the post's own
Telegram page for the audio link, downloads the .ogg file and translates the speech into English with
Whisper small, an open-source speech model (run with sherpa-onnx; the model files come from the sherpa-onnx
releases on GitHub and are cached between runs). Both channels speak mostly Hindi, so the speech is
translated, not just written down. A run stops starting new ones after 8 minutes; the rest wait for the
next run.

Transcripts go to data/<channel>/voice_notes.csv (id, posted_at, transcribed_at, seconds, model, text),
which is only ever added to and only written by this job. A machine transcript can mishear a number:
Claude takes a level from one only when it's clear, and says so in the call's note.

Run by hand: python voice_notes.py            (transcribe what's waiting)
             python voice_notes.py --pending  (just count it)
"""

import html
import io
import os
import re
import shutil
import sys
import tarfile
import time
import urllib.request

import pandas as pd

import berlin_calls as bc
import channels

MODEL = "sherpa-onnx-whisper-small"
MODEL_URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/{MODEL}.tar.bz2"
MODEL_DIR = os.path.join("models", MODEL)
FILES = ("small-encoder.int8.onnx", "small-decoder.int8.onnx", "small-tokens.txt")
MODEL_NAME = "Whisper small, translated to English"
COLS = ["id", "posted_at", "transcribed_at", "seconds", "model", "text"]
MAX_PER_RUN = 20          # at most this many a run, newest first; older ones wait for the next runs
BUDGET = 8 * 60           # seconds: no new voice note is started after this, so the run ends inside its timeout
MAX_AUDIO = 15 * 60       # seconds: a longer voice note is transcribed for its first 15 minutes only
CHUNK = 28                # seconds: Whisper reads at most 30 seconds at a time
RATE = 16000
AUDIO = re.compile(r'<audio[^>]*class="tgme_widget_message_voice[^"]*"[^>]*src="([^"]+)"')


def path(ch):
    return os.path.join(ch["folder"], "voice_notes.csv")


def read(p):
    return pd.read_csv(p, dtype=str, keep_default_na=False) if os.path.exists(p) else pd.DataFrame(columns=COLS)


def pending(ch):
    """Saved voice-note posts of this channel without a transcript, oldest first."""
    posts = bc.read_posts(channels.posts_path(ch))
    if not len(posts):
        return []
    posts = posts.drop_duplicates("id", keep="first")
    done = set(read(path(ch))["id"].astype(str))
    voice = posts[(posts["media"] == "voice") & (posts["id"].astype(int) >= int(ch["start_id"]))]
    return [r for _, r in voice.sort_values("posted_at").iterrows() if r["id"] not in done]


def get(url, timeout=60, tries=3):
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=bc.HEADERS), timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # GitHub's release downloads sometimes time out once
            last = exc
            time.sleep(5 * (i + 1))
    raise last


def audio_link(handle, pid, fetch_text=None):
    """(audio URL, page found): the voice note's .ogg link from the post's own page."""
    page = (fetch_text or (lambda u: get(u, 30).decode("utf-8", "replace")))(
        f"https://t.me/{handle}/{pid}?embed=1&mode=tme")
    m = AUDIO.search(page)
    return (html.unescape(m.group(1)) if m else None), f'data-post="{handle}/{pid}"' in page


def decode(data):
    """Any audio file's bytes -> 16 kHz mono float samples (PyAV, which bundles FFmpeg)."""
    import av
    import numpy as np
    parts = []
    with av.open(io.BytesIO(data)) as box:
        resampler = av.AudioResampler(format="flt", layout="mono", rate=RATE)
        for frame in box.decode(audio=0):
            parts += [f.to_ndarray().reshape(-1) for f in resampler.resample(frame)]
        parts += [f.to_ndarray().reshape(-1) for f in resampler.resample(None)]
    return np.concatenate(parts).astype("float32") if parts else np.zeros(0, dtype="float32")


def ensure_model(folder=MODEL_DIR, fetch=None):
    """The three model files in folder, downloading them once if they aren't cached there. They're
    unpacked into a side folder and moved into place only when all three are complete, so a run cut
    off halfway never leaves (or caches) a broken model."""
    if all(os.path.isfile(os.path.join(folder, f)) and os.path.getsize(os.path.join(folder, f)) for f in FILES):
        return folder
    data = (fetch or (lambda u: get(u, 600)))(MODEL_URL)
    part = folder + ".part"
    shutil.rmtree(part, ignore_errors=True)
    os.makedirs(part)
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:bz2") as tar:
            for member in tar:
                name = os.path.basename(member.name)
                if name in FILES and member.isfile():         # only these, flat: nothing else is unpacked
                    with tar.extractfile(member) as src, open(os.path.join(part, name), "wb") as dst:
                        shutil.copyfileobj(src, dst)
        missing = [f for f in FILES if not os.path.isfile(os.path.join(part, f))]
        if missing:
            raise RuntimeError(f"model archive lacked {missing}")
    except BaseException:
        shutil.rmtree(part, ignore_errors=True)
        raise
    shutil.rmtree(folder, ignore_errors=True)
    os.replace(part, folder)
    return folder


def recognizer(folder):
    import sherpa_onnx
    return sherpa_onnx.OfflineRecognizer.from_whisper(
        encoder=os.path.join(folder, FILES[0]), decoder=os.path.join(folder, FILES[1]),
        tokens=os.path.join(folder, FILES[2]), language="hi", task="translate", num_threads=os.cpu_count() or 2)


def transcribe(rec, samples):
    texts = []
    for i in range(0, len(samples), CHUNK * RATE):
        stream = rec.create_stream()
        stream.accept_waveform(RATE, samples[i:i + CHUNK * RATE])
        rec.decode_stream(stream)
        if stream.result.text.strip():
            texts.append(stream.result.text.strip())
    return " ".join(texts)


def run(fetch_text=None, fetch_audio=None, rec=None, limit=MAX_PER_RUN, budget=BUDGET):
    """Transcribe waiting voice notes, newest first (the nightly review needs the new ones).
    Returns how many rows were added."""
    todo = sorted(((ch, r) for ch in channels.CHANNELS.values() for r in pending(ch)),
                  key=lambda t: t[1]["posted_at"], reverse=True)
    if not todo:
        print("No new voice notes.")
        return 0
    added, tried, started = 0, 0, time.monotonic()
    for ch, r in todo[:limit]:
        if tried and time.monotonic() - started > budget:     # the first one always starts
            break
        tried += 1
        name = f"{ch['name']} #{r['id']}"
        try:
            url, found = audio_link(ch["handle"], r["id"], fetch_text)
            deleted = os.path.exists(channels.deleted_path(ch)) and r["id"] in set(read(channels.deleted_path(ch))["id"])
            if not url:
                if found or deleted:                          # no audio there any more: don't try again
                    text, seconds = ("(deleted before it could be transcribed)" if deleted else
                                     "(no voice note on the post's page)"), 0
                else:
                    print(f"{name}: page not readable now; trying again next run")
                    continue
            else:
                rec = rec or recognizer(ensure_model())
                samples = decode((fetch_audio or (lambda u: get(u, 60)))(url))
                seconds = round(len(samples) / RATE)
                text = transcribe(rec, samples[:MAX_AUDIO * RATE]) or "(no speech recognised)"
                if seconds > MAX_AUDIO:
                    mmss = lambda s: f"{s // 60}:{s % 60:02d}"
                    text += f" [only the first {mmss(MAX_AUDIO)} of {mmss(seconds)} was transcribed]"
        except Exception as exc:  # Telegram or the model unreachable: it waits for the next run
            print(f"{name}: not transcribed ({exc})")
            continue
        bc.append(path(ch), COLS, [{"id": r["id"], "posted_at": r["posted_at"],
                                    "transcribed_at": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    "seconds": seconds, "model": MODEL_NAME, "text": text}])
        added += 1
        print(f"{name}: {seconds}s -> {text[:120]}")
    left = len(todo) - added
    print(f"Transcribed {added} voice notes" + (f"; {left} wait for the next run" if left else ""))
    return added


if __name__ == "__main__":
    if "--pending" in sys.argv:
        print(sum(len(pending(ch)) for ch in channels.CHANNELS.values()))
    else:
        run()
