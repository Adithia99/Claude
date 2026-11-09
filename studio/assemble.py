"""ffmpeg helpers: normalize clips, concat, burn TikTok-style subtitles, 16:9 conversion."""
import json
import subprocess
from pathlib import Path


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("ffmpeg failed:\n" + " ".join(map(str, cmd)) + "\n" + p.stderr[-3000:])
    return p.stdout


def probe(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type",
               "-of", "json", str(path)])
    j = json.loads(out)
    return {
        "duration": float(j["format"]["duration"]),
        "has_audio": any(s["codec_type"] == "audio" for s in j.get("streams", [])),
    }


def normalize(src, dst, w, h, fps, flash=False, trim=None):
    """Scale/crop to WxH, fixed fps, always stereo 44.1k audio. Optional white flash in."""
    info = probe(src)
    vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps},setsar=1"
    if flash:
        vf += ",fade=t=in:st=0:d=0.25:color=white"
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(src)]
    if not info["has_audio"]:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-shortest"]
    if trim:
        cmd += ["-t", str(trim)]
    cmd += ["-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "44100", "-ac", "2", str(dst)]
    run(cmd)
    return dst


def concat(clips, dst):
    lst = Path(dst).with_suffix(".txt")
    lst.write_text("".join(f"file '{Path(c).resolve()}'\n" for c in clips))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c", "copy", str(dst)])
    lst.unlink()
    return dst


def _ts(t):
    h, rem = divmod(max(t, 0), 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def write_ass(events, dst, w, h, font, colors):
    """events: [{start, end, text, speaker}] -> big outlined captions, lower third."""
    size = int(h * 0.045) if h > w else int(h * 0.06)
    margin_v = int(h * 0.18) if h > w else int(h * 0.08)
    styles = []
    for name, col in colors.items():
        styles.append(f"Style: S_{name},{font},{size},{col},&H000000FF,&H00000000,&H64000000,"
                      f"-1,0,0,0,100,100,0,0,1,{max(3, size // 10)},2,2,40,40,{margin_v},1")
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {w}", f"PlayResY: {h}",
        "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        *styles, "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for e in events:
        style = e.get("speaker") if e.get("speaker") in colors else "default"
        text = e["text"].replace("{", "(").replace("}", ")").replace("\n", "\\N")
        # small pop-in: scale 80% -> 100% over 120ms
        text = r"{\fscx80\fscy80\t(0,120,\fscx100\fscy100)}" + text
        lines.append(f"Dialogue: 0,{_ts(e['start'])},{_ts(e['end'])},S_{style},,0,0,0,,{text}")
    Path(dst).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dst


def burn_subs(src, ass, dst):
    esc = str(Path(ass).resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", f"ass='{esc}'",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
         "-c:a", "copy", "-movflags", "+faststart", str(dst)])
    return dst


def to_landscape(src, dst, w, h, fps):
    """Vertical clip centered on a blurred, zoomed copy of itself (16:9)."""
    fc = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
          f"gblur=sigma=30,eq=brightness=-0.08[bg];"
          f"[0:v]scale=-2:{h}[fg];[bg][fg]overlay=(W-w)/2:0,fps={fps},setsar=1[v]")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-filter_complex", fc,
         "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "44100", "-ac", "2", str(dst)])
    return dst


def title_card(text, dst, w, h, fps, seconds=2.0, font="Inter"):
    """Plain title card used between episodes in the long compilation."""
    esc = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’")
    vf = (f"drawtext=font='{font}':text='{esc}':fontsize={int(h*0.08)}:fontcolor=white:"
          f"borderw=6:bordercolor=black:x=(w-tw)/2:y=(h-th)/2")
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x1b1b2f:s={w}x{h}:r={fps}",
         "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", str(seconds),
         "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "44100",
         "-ac", "2", str(dst)])
    return dst


def mock_image(text, dst, w=720, h=1280):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (w, h), (40, 44, 70))
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, w - 20, h - 20], outline=(255, 210, 0), width=6)
    y = 60
    for line in _wrap(text, 34)[:30]:
        d.text((50, y), line, fill=(255, 255, 255))
        y += 22
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    img.save(dst)
    return dst


def mock_video(image, dst, seconds, fps=24):
    run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(image),
         "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=44100", "-t", str(seconds),
         "-vf", f"zoompan=z='min(zoom+0.0015,1.15)':d={int(seconds*fps)}:s=720x1280:fps={fps}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-af", "volume=0.05",
         str(dst)])
    return dst


def _wrap(text, n):
    out, cur = [], ""
    for word in text.split():
        if len(cur) + len(word) + 1 > n:
            out.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    return out + [cur]
