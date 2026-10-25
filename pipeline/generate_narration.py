"""Generate the dashboard's natural voice recordings from its narration scripts.

    uv run --with edge-tts python pipeline/generate_narration.py

Recordings are generated once and served as static MP3 files. Site visitors do
not need access to a speech service. Re-run after editing the narration text,
then rebuild public/index.html. Existing matching recordings are reused.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re

import edge_tts

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "dashboard/template.html"
AUDIO = ROOT / "public/audio"


def read_constant(source, name):
    match = re.search(rf"const {name} = (\{{.*?\}});", source, re.S)
    if not match:
        raise ValueError(f"Missing {name} in dashboard/template.html")
    # These constants contain only literal strings; accept the existing JS keys.
    literal = re.sub(r"(?m)^(\s*)([A-Za-z_]\w*):", r'\1"\2":', match[1])
    return json.loads(literal)


async def generate(voice, rate):
    source = TEMPLATE.read_text()
    scripts = read_constant(source, "NARRATIONS")
    terms = read_constant(source, "SPOKEN_TERMS")
    term_pattern = re.compile(r"\b(?:" + "|".join(map(re.escape, terms)) + r")\b")
    AUDIO.mkdir(parents=True, exist_ok=True)
    sources, manifest = {}, {}
    for key, transcript in scripts.items():
        spoken = term_pattern.sub(lambda match: terms[match[0]], transcript)
        digest = hashlib.sha256(json.dumps([spoken, voice, rate]).encode()).hexdigest()[:12]
        target = AUDIO / f"{key}-{digest}.mp3"
        if not target.exists() or target.stat().st_size < 1000:
            temporary = target.with_suffix(".part")
            try:
                for attempt in range(3):
                    try:
                        await edge_tts.Communicate(spoken, voice, rate=rate).save(str(temporary))
                        if temporary.stat().st_size < 1000:
                            raise RuntimeError(f"Empty audio for {key}")
                        temporary.replace(target)
                        break
                    except Exception:
                        if attempt == 2:
                            raise
                        await asyncio.sleep(2 ** attempt)
            finally:
                temporary.unlink(missing_ok=True)
        sources[key] = "audio/" + target.name
        manifest[key] = {
            "src": sources[key],
            "transcript_sha256": hashlib.sha256(transcript.encode()).hexdigest(),
            "audio_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        }
        print(f"{key}: {target.stat().st_size / 1000:.0f} kB", flush=True)

    recordings = {"voice": voice, "rate": rate, "sources": sources}
    updated, count = re.subn(
        r"/\*__RECORDINGS_START__\*/.*?/\*__RECORDINGS_END__\*/",
        "/*__RECORDINGS_START__*/\nconst RECORDINGS = "
        + json.dumps(recordings, indent=2) + ";\n/*__RECORDINGS_END__*/",
        source, count=1, flags=re.S,
    )
    if count != 1:
        raise ValueError("Missing recordings marker in dashboard/template.html")
    TEMPLATE.write_text(updated)
    (AUDIO / "manifest.json").write_text(json.dumps({
        "voice": voice, "rate": rate, "recordings": manifest,
    }, indent=2) + "\n")
    print("Updated recordings and manifest. Rebuild public/index.html next.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--voice", default="en-IN-NeerjaNeural")
    parser.add_argument("--rate", default="-5%")
    args = parser.parse_args()
    asyncio.run(generate(args.voice, args.rate))
