"""Downloads Roblox assets (meshes, textures, models) into the asset library.

Since April 2025 Roblox only serves most asset files to authenticated
requests. Three ways are tried, in this order, falling through when one is
refused (e.g. an asset an API key isn't approved for):

1. Open Cloud API key (recommended by Roblox):
       GET https://apis.roblox.com/asset-delivery-api/v1/assetId/{id}
       header x-api-key   (scope: legacy-asset:manage)
2. Your .ROBLOSECURITY cookie (discouraged by Roblox, may stop working):
       GET https://assetdelivery.roblox.com/v1/assetId/{id}
       header Cookie: .ROBLOSECURITY=...
3. No login: the same endpoint without credentials. Works for Roblox-made
   assets (default body meshes, many built-in textures) only.

Each answers with JSON {"location": <CDN url>} (or {"errors": [...]}, even
with HTTP 200); the file is then fetched from the CDN.

Nothing here uses bpy, so it can be tested on its own. Credentials are only
ever sent to roblox.com hosts and never written to logs or error messages."""

import gzip
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor

OPEN_CLOUD = "https://apis.roblox.com/asset-delivery-api/v1/assetId/%s"
ASSET_DELIVERY = "https://assetdelivery.roblox.com/v1/assetId/%s"
USER_AGENT = "RBLX-Tools-Blender/0.3"

# Library sub-folders by file type
FOLDERS = {".mesh": "meshes", ".png": "textures", ".jpg": "textures", ".webp": "textures",
           ".gif": "textures", ".bmp": "textures", ".ktx": "textures", ".rbxm": "models",
           ".rbxmx": "models"}
LIBRARY_SUBFOLDERS = ("meshes", "textures", "models", "other")


class DownloadError(Exception):
    pass


class _Refused(Exception):
    """This method can't get the asset; try the next one."""


def sniff_extension(head):
    if head.startswith(b"\x89PNG"):
        return ".png"
    if head.startswith(b"\xff\xd8"):
        return ".jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    if head.startswith(b"GIF8"):
        return ".gif"
    if head.startswith(b"BM"):
        return ".bmp"
    if head.startswith(b"version "):
        return ".mesh"
    if head.startswith(b"<roblox!"):
        return ".rbxm"
    if head.lstrip().startswith(b"<roblox") or head.lstrip().startswith(b"<?xml"):
        return ".rbxmx"
    if head.startswith(b"\xabKTX"):
        return ".ktx"
    return ".bin"


def library_subfolder(ext):
    return FOLDERS.get(ext, "other")


def clean_cookie(value):
    """Accept the cookie with or without the '.ROBLOSECURITY=' prefix/quotes."""
    v = (value or "").strip().rstrip(";").strip().strip('"').strip("'").strip()
    if v.lower().startswith(".roblosecurity="):
        v = v.split("=", 1)[1]
    return v.strip().rstrip(";").strip().strip('"').strip("'").strip()


def _decompress(data, encoding):
    encoding = (encoding or "").lower()
    if encoding == "gzip" or data[:2] == b"\x1f\x8b":
        return gzip.decompress(data)
    if encoding == "deflate":
        return zlib.decompress(data)
    return data


def _http_get(url, headers, timeout):
    req = urllib.request.Request(url, headers=dict(headers, **{
        "User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return _decompress(resp.read(), resp.headers.get("Content-Encoding"))


def http_get_json(url, timeout=20, data=None):
    """Small helper for Roblox's public web APIs (users, avatar)."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json", "Accept-Encoding": "gzip"}
    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = _decompress(resp.read(), resp.headers.get("Content-Encoding"))
    except urllib.error.HTTPError as ex:
        raise DownloadError("%s returned HTTP %d" % (url.split("?")[0], ex.code))
    except (urllib.error.URLError, OSError) as ex:
        raise DownloadError("Could not reach %s: %s" % (url.split("/")[2], ex))
    return json.loads(raw.decode("utf-8"))


def _error_text(payload):
    errs = payload.get("errors") if isinstance(payload, dict) else None
    if isinstance(errs, list) and errs:
        e = errs[0] if isinstance(errs[0], dict) else {}
        code = e.get("code")
        msg = (e.get("message") or "").strip() or "error"
        return ("%s (%s)" % (msg, code)) if code not in (None, 0) else msg
    if isinstance(payload, dict) and payload.get("message"):
        return str(payload["message"])
    return "no download location"


class Downloader:
    """Downloads assets into `library_dir`/{meshes,textures,models,other}."""

    def __init__(self, library_dir, api_key="", cookie="", anonymous=True, timeout=30):
        self.library_dir = library_dir
        self.api_key = (api_key or "").strip()
        self.cookie = clean_cookie(cookie)
        self.anonymous = anonymous
        self.timeout = timeout
        self.errors = {}        # asset id -> message
        self.methods = {}       # asset id -> "API key" / "cookie" / "no login"
        self.disabled = set()   # methods whose credentials were rejected outright
        self.downloaded = 0
        self._lock = threading.Lock()

    # -- methods ---------------------------------------------------------
    def method_names(self):
        out = []
        if self.api_key:
            out.append("API key")
        if self.cookie:
            out.append("cookie")
        if self.anonymous:
            out.append("no login")
        return out

    def _request_location(self, method, aid):
        if method == "API key":
            url, headers = OPEN_CLOUD % aid, {"x-api-key": self.api_key}
        elif method == "cookie":
            url, headers = ASSET_DELIVERY % aid, {"Cookie": ".ROBLOSECURITY=" + self.cookie}
        else:
            url, headers = ASSET_DELIVERY % aid, {}
        headers["Accept"] = "application/json"
        for attempt in range(4):
            try:
                payload = json.loads(_http_get(url, headers, self.timeout).decode("utf-8"))
                break
            except urllib.error.HTTPError as ex:
                if ex.code == 429 and attempt < 3:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                try:
                    payload = json.loads(ex.read().decode("utf-8"))
                except Exception:
                    payload = {}
                text = _error_text(payload) if payload else "HTTP %d" % ex.code
                if ex.code == 401 or (ex.code == 403 and "authentication" in text.lower()):
                    if method != "no login":
                        with self._lock:
                            self.disabled.add(method)
                    raise _Refused("%s rejected: %s" % (method, text))
                raise _Refused("%s: HTTP %d %s" % (method, ex.code, text))
            except (urllib.error.URLError, OSError, ValueError) as ex:
                if attempt < 2:
                    time.sleep(1.0)
                    continue
                raise DownloadError("Network error: %s" % ex)
        else:
            raise _Refused("%s: rate limited (429)" % method)

        loc = payload.get("location") if isinstance(payload, dict) else None
        if not loc and isinstance(payload, dict) and payload.get("locations"):
            loc = payload["locations"][0].get("location")
        if not loc:
            errs = payload.get("errors") if isinstance(payload, dict) else None
            code = errs[0].get("code") if errs and isinstance(errs[0], dict) else None
            if code == 401 and method != "no login":
                # Credentials not accepted at all: stop trying them for this import
                with self._lock:
                    self.disabled.add(method)
            raise _Refused("%s: %s" % (method, _error_text(payload)))
        host = urllib.parse.urlparse(loc).hostname or ""
        if not (host == "roblox.com" or host.endswith(".roblox.com") or host.endswith(".rbxcdn.com")):
            raise _Refused("%s: unexpected download host %s" % (method, host))
        return loc

    # -- public ----------------------------------------------------------
    def fetch(self, aid):
        """Download asset `aid` into the library. Returns the file path or None."""
        aid = str(aid)
        with self._lock:
            if aid in self.errors:
                return None
        reasons = []
        for method in self.method_names():
            with self._lock:
                if method in self.disabled:
                    continue
            try:
                loc = self._request_location(method, aid)
                try:
                    data = _http_get(loc, {}, self.timeout)
                except (urllib.error.URLError, OSError) as ex:
                    raise _Refused("%s: download failed (%s)" % (method, ex))
                path = self._store(aid, data)
                with self._lock:
                    self.downloaded += 1
                    self.methods[aid] = method
                return path
            except _Refused as ex:
                reasons.append(str(ex))
            except DownloadError as ex:
                reasons.append(str(ex))
                break
        if not self.method_names():
            reasons.append("downloading is off")
        with self._lock:
            self.errors[aid] = "; ".join(reasons) or "no download method available"
        return None

    def _store(self, aid, data):
        ext = sniff_extension(data[:64])
        folder = os.path.join(self.library_dir, library_subfolder(ext))
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, aid + ext)
        tmp = path + ".part"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        return path

    def fetch_many(self, aids, workers=6, progress=None):
        aids = [str(a) for a in dict.fromkeys(aids)]
        results = {}
        if not aids:
            return results
        done = [0]

        def job(a):
            p = self.fetch(a)
            with self._lock:
                done[0] += 1
            return a, p

        with ThreadPoolExecutor(max_workers=workers) as ex:
            for a, p in ex.map(job, aids):
                results[a] = p
                if progress:
                    progress(done[0], len(aids))
        return results
