#!/usr/bin/env python3
"""Chibi video studio: script -> keyframes (Gemini) -> clips (Veo) -> Short + Long edits.

  python make.py models                       # list image/video models the key can use
  python make.py character me                 # build characters/me/sheet.png
  python make.py episode episodes/ep001.json  # images -> videos -> short
  python make.py long ep001 ep002 --out kompilasi01
  add --mock to any command to test the whole pipeline offline with placeholder visuals
"""
import argparse
import json
import sys
from pathlib import Path

from studio import assemble as A
from studio import gemini as G

ROOT = Path(__file__).resolve().parent
CFG = json.loads((ROOT / "config.json").read_text())
OUT = ROOT / "output"


def log(msg):
    print(f"» {msg}", flush=True)


# ---------- characters ----------

def load_char(name):
    path = ROOT / "characters" / name / "character.json"
    if not path.exists():
        sys.exit(f"Missing {path}")
    c = json.loads(path.read_text())
    c["dir"] = path.parent
    c["sheet_path"] = path.parent / c.get("sheet", "sheet.png")
    return c


def cmd_character(args):
    c = load_char(args.name)
    photos = sorted(p for p in (c["dir"] / "photos").glob("*")
                    if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}) \
        if (c["dir"] / "photos").exists() else []
    prompt = (
        f"{CFG['style']}. Character reference sheet on a plain light background: the same "
        f"character shown full body from front, three-quarter and back views, plus a row of "
        f"4 facial expressions (smug, shocked, crying-laughing, angry). Character: {c['desc']}. "
    )
    if photos:
        prompt += ("Base the face, hairstyle and skin tone on the person in the attached photos, "
                   "turned into an adorable chibi cartoon (keep it recognizable but stylized). ")
    out = c["sheet_path"]
    if out.exists() and not args.force:
        log(f"{out} already exists (use --force to regenerate)")
        return
    log(f"Generating character sheet for {args.name} ({len(photos)} photo refs)")
    if args.mock:
        A.mock_image(f"CHARACTER SHEET {args.name}: {c['desc']}", out, 1280, 720)
    else:
        G.generate_image(CFG["image_model"], prompt, out, refs=photos, aspect_ratio="16:9")
    log(f"Saved {out}")


# ---------- episodes ----------

def scene_image_prompt(ep, scene, chars):
    cast = " ".join(f"{c['name']}: {c['desc']}." for c in chars)
    return (f"{CFG['style']}. {ep.get('setting', '')} "
            f"Characters must match the attached reference sheets exactly. {cast} "
            f"Scene: {scene['image_prompt']}")


def scene_video_prompt(ep, scene):
    p = (f"Chibi 2D cartoon animation, smooth expressive motion, keep characters and art style "
         f"identical to the first frame. {scene['motion_prompt']}")
    if scene.get("audio"):
        p += f" Audio: {scene['audio']}"
    return p


def build_episode(ep_path, mock=False, only=None, redo=()):
    ep = json.loads(Path(ep_path).read_text())
    eid = ep["id"]
    d = OUT / eid
    (d / "frames").mkdir(parents=True, exist_ok=True)
    (d / "clips").mkdir(exist_ok=True)
    (d / "norm").mkdir(exist_ok=True)
    s = CFG["short"]

    # 1. keyframe images
    if only in (None, "images"):
        for sc in ep["scenes"]:
            if sc.get("clip"):
                continue
            img = d / "frames" / f"{sc['id']}.png"
            if img.exists() and sc["id"] not in redo:
                continue
            chars = [load_char(n) for n in sc.get("chars", [])]
            prompt = scene_image_prompt(ep, sc, chars)
            log(f"[{eid}] image {sc['id']}")
            if mock:
                A.mock_image(f"[{sc['id']}] {sc['image_prompt']}", img)
            else:
                refs = [c["sheet_path"] for c in chars if c["sheet_path"].exists()]
                G.generate_image(CFG["image_model"], prompt, img, refs=refs)

    # 2. video clips
    if only in (None, "videos"):
        for sc in ep["scenes"]:
            if sc.get("clip"):
                continue
            vid = d / "clips" / f"{sc['id']}.mp4"
            if vid.exists() and sc["id"] not in redo:
                continue
            img = d / "frames" / f"{sc['id']}.png"
            log(f"[{eid}] video {sc['id']}")
            if mock:
                A.mock_video(img, vid, sc.get("seconds", 8))
            else:
                params = dict(CFG["veo_parameters"])
                params["durationSeconds"] = sc.get("seconds", params.get("durationSeconds", 8))
                G.generate_video(CFG["video_model"], scene_video_prompt(ep, sc), vid,
                                 image=img, parameters=params)

    # 3. assemble the Short
    if only in (None, "assemble"):
        clips, events, t = [], [], 0.0
        for sc in ep["scenes"]:
            src = ROOT / sc["clip"] if sc.get("clip") else d / "clips" / f"{sc['id']}.mp4"
            if not src.exists():
                sys.exit(f"Missing clip {src}")
            n = d / "norm" / f"{sc['id']}.mp4"
            A.normalize(src, n, s["width"], s["height"], s["fps"],
                        flash=sc.get("interrupt", False), trim=sc.get("trim"))
            dur = A.probe(n)["duration"]
            for sub in sc.get("subs", []):
                start = t + sub.get("at", 0)
                end = min(start + sub.get("dur", 2.0), t + dur)
                events.append({"start": start, "end": end, "text": sub["text"],
                               "speaker": sub.get("speaker", "default")})
            clips.append(n)
            t += dur
        raw = A.concat(clips, d / f"{eid}_raw.mp4")
        ass = A.write_ass(events, d / f"{eid}.ass", s["width"], s["height"],
                          CFG["subtitle_font"], CFG["colors"])
        final = A.burn_subs(raw, ass, d / f"{eid}_short.mp4")
        (d / "upload.txt").write_text(
            f"{ep.get('title', eid)}\n\n{ep.get('caption', '')}\n\n"
            f"{' '.join(ep.get('hashtags', []))}\n\n"
            "Label: AI-generated content (centang 'AI-generated' / 'Altered or synthetic content' saat upload)\n",
            encoding="utf-8")
        log(f"[{eid}] Short ready: {final} ({t:.1f}s)")
        return final


def cmd_episode(args):
    for p in args.episodes:
        build_episode(p, mock=args.mock, only=args.only, redo=set(args.redo or []))


def cmd_long(args):
    s, L = CFG["short"], CFG["long"]
    d = OUT / "long" / args.out
    d.mkdir(parents=True, exist_ok=True)
    vert, land = [], []
    for i, eid in enumerate(args.ids):
        short = OUT / eid / f"{eid}_short.mp4"
        if not short.exists():
            sys.exit(f"Build {eid} first: python make.py episode episodes/{eid}.json")
        ep = json.loads((ROOT / "episodes" / f"{eid}.json").read_text())
        title = ep.get("title", eid)
        tv = A.title_card(f"#{i+1}  {title}", d / f"t{i}_v.mp4", s["width"], s["height"], s["fps"])
        tl = A.title_card(f"#{i+1}  {title}", d / f"t{i}_l.mp4", L["width"], L["height"], L["fps"])
        vert += [tv, short]
        land += [tl, A.to_landscape(short, d / f"{eid}_l.mp4", L["width"], L["height"], L["fps"])]
    if args.intro:
        intro = Path(args.intro)
        vert.insert(0, A.normalize(intro, d / "intro_v.mp4", s["width"], s["height"], s["fps"]))
        land.insert(0, A.normalize(intro, d / "intro_l.mp4", L["width"], L["height"], L["fps"]))
    v = A.concat(vert, d / f"{args.out}_tiktok_9x16.mp4")
    l = A.concat(land, d / f"{args.out}_youtube_16x9.mp4")
    log(f"Long vertical ({A.probe(v)['duration']:.0f}s): {v}")
    log(f"Long landscape ({A.probe(l)['duration']:.0f}s): {l}")


def cmd_models(_args):
    for m in G.list_models():
        methods = m.get("supportedGenerationMethods", [])
        name = m["name"].split("/")[-1]
        if "predictLongRunning" in methods or "image" in name or "veo" in name:
            print(f"{name:45s} {','.join(methods)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("models").set_defaults(fn=cmd_models)
    c = sub.add_parser("character")
    c.add_argument("name")
    c.add_argument("--force", action="store_true")
    c.add_argument("--mock", action="store_true")
    c.set_defaults(fn=cmd_character)
    e = sub.add_parser("episode")
    e.add_argument("episodes", nargs="+")
    e.add_argument("--mock", action="store_true")
    e.add_argument("--only", choices=["images", "videos", "assemble"])
    e.add_argument("--redo", nargs="*", help="scene ids to regenerate")
    e.set_defaults(fn=cmd_episode)
    lg = sub.add_parser("long")
    lg.add_argument("ids", nargs="+")
    lg.add_argument("--out", required=True)
    lg.add_argument("--intro", help="your own recorded intro clip (optional)")
    lg.add_argument("--mock", action="store_true")
    lg.set_defaults(fn=cmd_long)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
