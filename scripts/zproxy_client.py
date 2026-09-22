#!/usr/bin/env python3
"""
Call WeChat through omni-pub zproxy (fixed egress IP), same path as Bevy omni-pub.

When wechat-publisher.yaml has zproxy.enabled, token/upload/draft go here
instead of api.weixin.qq.com from the cloud box (avoids 40164).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests

from config import _load_config_yaml, get_config

ZPROXY_TIMEOUT = 60


def get_zproxy_settings() -> Optional[Dict[str, Any]]:
    cfg = _load_config_yaml() or {}
    z = cfg.get("zproxy") or {}
    if not isinstance(z, dict) or not z.get("enabled"):
        return None
    server = str(z.get("server") or "").rstrip("/")
    api_key = str(z.get("api_key") or "").strip()
    header = str(z.get("wechat_app_id_header") or "DAUGHTER").strip()
    if not server or not api_key:
        raise RuntimeError("zproxy.enabled but server/api_key missing in wechat-publisher.yaml")
    return {"server": server, "api_key": api_key, "wechat_app_id_header": header}


def zproxy_enabled() -> bool:
    return get_zproxy_settings() is not None


def _headers(z: Dict[str, Any]) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {z['api_key']}",
        "X-Wechat-App-Id": z["wechat_app_id_header"],
    }


def verify_token_via_zproxy() -> Tuple[bool, str]:
    """
    Force zproxy to mint a WeChat token for the configured account by uploading
    a 1x1 PNG as content_image (does not consume permanent material quota).
    Returns (ok, message) — never returns the WeChat access_token.
    """
    z = get_zproxy_settings()
    if not z:
        return False, "zproxy not enabled"

    # Minimal valid PNG (1x1)
    import base64
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    files = {"file": ("zproxy-smoke.png", png, "image/png")}
    data = {"type": "content_image"}
    url = f"{z['server']}/v1/materials/upload"
    try:
        resp = requests.post(url, headers=_headers(z), files=files, data=data, timeout=ZPROXY_TIMEOUT)
    except requests.RequestException as e:
        return False, f"zproxy unreachable: {e}"

    try:
        body = resp.json()
    except Exception:
        return False, f"zproxy HTTP {resp.status_code}: non-JSON body"

    if resp.status_code == 200 and body.get("ok") and body.get("url"):
        return True, f"zproxy OK for header={z['wechat_app_id_header']} (content_image smoke)"

    err = body.get("error") or body
    return False, f"zproxy token/materials failed HTTP {resp.status_code}: {err}"


def upload_material_via_zproxy(image_path: Path, type_: str) -> Dict[str, Any]:
    """type_: thumb | content_image — matches omni-pub /v1/materials/upload."""
    z = get_zproxy_settings()
    if not z:
        raise RuntimeError("zproxy not enabled")
    if type_ not in ("thumb", "content_image"):
        raise ValueError(f"unsupported type {type_}")

    image_path = Path(image_path)
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }.get(image_path.suffix.lower(), "image/jpeg")

    with open(image_path, "rb") as f:
        files = {"file": (image_path.name, f, mime)}
        data = {"type": type_}
        resp = requests.post(
            f"{z['server']}/v1/materials/upload",
            headers=_headers(z),
            files=files,
            data=data,
            timeout=ZPROXY_TIMEOUT,
        )
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if resp.status_code != 200 or not body.get("ok"):
        raise RuntimeError(f"zproxy material upload failed HTTP {resp.status_code}: {body.get('error') or body or resp.text[:300]}")
    return body


def create_draft_via_zproxy(
    *,
    title: str,
    content: str,
    thumb_media_id: str,
    author: str = "",
    digest: str = "",
    content_source_url: str = "",
    update_existing_by_title: bool = False,
) -> Dict[str, Any]:
    z = get_zproxy_settings()
    if not z:
        raise RuntimeError("zproxy not enabled")
    payload = {
        "title": title,
        "content": content,
        "thumb_media_id": thumb_media_id,
        "author": author or None,
        "digest": digest or None,
        "content_source_url": content_source_url or None,
        "update_existing_by_title": update_existing_by_title,
    }
    # drop Nones
    payload = {k: v for k, v in payload.items() if v is not None}
    resp = requests.post(
        f"{z['server']}/v1/drafts",
        headers={**_headers(z), "Content-Type": "application/json"},
        json=payload,
        timeout=ZPROXY_TIMEOUT,
    )
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    if resp.status_code != 200 or not body.get("ok"):
        raise RuntimeError(f"zproxy draft failed HTTP {resp.status_code}: {body.get('error') or body or resp.text[:300]}")
    return body
