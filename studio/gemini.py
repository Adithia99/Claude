"""Thin REST client for the Gemini API: image generation and Veo image-to-video.

Auth: if GEMINI_API_KEY is set it is sent as x-goog-api-key. In the cloud
session the network proxy injects the key instead, so the variable can be empty.
"""
import base64
import mimetypes
import os
import time
from pathlib import Path

import requests

BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiError(RuntimeError):
    pass


def _headers():
    h = {"Content-Type": "application/json"}
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        h["x-goog-api-key"] = key
    return h


def _check(r):
    if r.status_code >= 400:
        raise GeminiError(f"{r.status_code} {r.request.method} {r.url}\n{r.text[:2000]}")
    return r.json()


def _inline(path):
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    data = base64.b64encode(Path(path).read_bytes()).decode()
    return mime, data


def list_models():
    out, token = [], None
    while True:
        params = {"pageSize": 200}
        if token:
            params["pageToken"] = token
        j = _check(requests.get(f"{BASE}/models", headers=_headers(), params=params, timeout=60))
        out += j.get("models", [])
        token = j.get("nextPageToken")
        if not token:
            return out


def generate_image(model, prompt, out_path, refs=(), aspect_ratio="9:16"):
    """Generate one image. `refs` are reference images (character sheets, photos)."""
    parts = []
    for ref in refs:
        mime, data = _inline(ref)
        parts.append({"inline_data": {"mime_type": mime, "data": data}})
    parts.append({"text": prompt})
    body = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": aspect_ratio},
        },
    }
    j = _check(requests.post(f"{BASE}/models/{model}:generateContent",
                             headers=_headers(), json=body, timeout=300))
    for cand in j.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            blob = part.get("inlineData") or part.get("inline_data")
            if blob and blob.get("data"):
                Path(out_path).parent.mkdir(parents=True, exist_ok=True)
                Path(out_path).write_bytes(base64.b64decode(blob["data"]))
                return out_path
    raise GeminiError(f"No image in response: {str(j)[:1500]}")


def generate_video(model, prompt, out_path, image=None, parameters=None, poll=10, timeout=900):
    """Veo text/image-to-video via predictLongRunning; blocks until the mp4 is saved."""
    inst = {"prompt": prompt}
    if image:
        mime, data = _inline(image)
        inst["image"] = {"bytesBase64Encoded": data, "mimeType": mime}
    body = {"instances": [inst], "parameters": parameters or {}}
    op = _check(requests.post(f"{BASE}/models/{model}:predictLongRunning",
                              headers=_headers(), json=body, timeout=300))
    name = op["name"]
    start = time.time()
    while not op.get("done"):
        if time.time() - start > timeout:
            raise GeminiError(f"Timed out waiting for {name}")
        time.sleep(poll)
        op = _check(requests.get(f"{BASE}/{name}", headers=_headers(), timeout=60))
    if "error" in op:
        raise GeminiError(f"Veo failed: {op['error']}")
    resp = op.get("response", {})
    samples = (resp.get("generateVideoResponse", {}).get("generatedSamples")
               or resp.get("generatedVideos") or [])
    if not samples:
        raise GeminiError(f"No video in response (maybe filtered): {str(resp)[:1500]}")
    video = samples[0].get("video", {})
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    if video.get("bytesBase64Encoded"):
        Path(out_path).write_bytes(base64.b64decode(video["bytesBase64Encoded"]))
    else:
        r = requests.get(video["uri"], headers=_headers(), timeout=300, allow_redirects=True)
        if r.status_code >= 400:
            raise GeminiError(f"Download failed {r.status_code}: {r.text[:500]}")
        Path(out_path).write_bytes(r.content)
    return out_path
