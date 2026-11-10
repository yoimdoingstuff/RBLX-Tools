"""Downloads Roblox assets through Roblox Open Cloud.

Since April 2025 Roblox only serves asset files to authenticated requests.
The supported way for tools is the Open Cloud Asset Delivery API with an API
key the user creates on create.roblox.com (scope: legacy-asset:manage):

    GET https://apis.roblox.com/asset-delivery-api/v1/assetId/{id}
        -> {"location": "https://...rbxcdn.com/..."}
    GET <location>  -> the file

Nothing here uses bpy, so it can be tested on its own."""

import gzip
import json
import os
import threading
import time
import urllib.error
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor

ENDPOINT = "https://apis.roblox.com/asset-delivery-api/v1/assetId/%s"
USER_AGENT = "RBLX-Tools-Blender/0.2"


class DownloadError(Exception):
    pass


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


class Downloader:
    def __init__(self, api_key, cache_dir, timeout=30):
        self.api_key = (api_key or "").strip()
        self.cache_dir = cache_dir
        self.timeout = timeout
        self.errors = {}        # asset id -> message
        self.fatal = None       # set when the key itself is rejected
        self.downloaded = 0
        self._lock = threading.Lock()

    def _meta(self, aid):
        url = ENDPOINT % aid
        for attempt in range(4):
            try:
                raw = _http_get(url, {"x-api-key": self.api_key, "Accept": "application/json"},
                                self.timeout)
                return json.loads(raw.decode("utf-8"))
            except urllib.error.HTTPError as ex:
                if ex.code == 429 and attempt < 3:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                if ex.code == 401:
                    raise DownloadError("API key was rejected (401). Check the key in the add-on "
                                        "preferences.", ) from None
                if ex.code == 403:
                    raise DownloadError("Not allowed (403): the API key needs the "
                                        "legacy-asset:manage permission, or the asset is private")
                if ex.code == 404:
                    raise DownloadError("Asset not found (404)")
                raise DownloadError("HTTP %d" % ex.code)
            except (urllib.error.URLError, OSError) as ex:
                if attempt < 2:
                    time.sleep(1.0)
                    continue
                raise DownloadError("Network error: %s" % ex)
        raise DownloadError("Rate limited by Roblox (429)")

    def fetch(self, aid):
        """Download asset `aid` into the cache. Returns the file path or None."""
        aid = str(aid)
        if not self.api_key or self.fatal:
            return None
        with self._lock:
            if aid in self.errors:
                return None
        try:
            meta = self._meta(aid)
            loc = meta.get("location")
            if not loc and meta.get("locations"):
                loc = meta["locations"][0].get("location")
            if not loc:
                err = meta.get("errors") or meta.get("message") or "no download location"
                raise DownloadError(str(err))
            try:
                data = _http_get(loc, {}, self.timeout)
            except (urllib.error.URLError, OSError) as ex:
                raise DownloadError("Download failed: %s" % ex)
            ext = sniff_extension(data[:64])
            os.makedirs(self.cache_dir, exist_ok=True)
            path = os.path.join(self.cache_dir, aid + ext)
            tmp = path + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
            with self._lock:
                self.downloaded += 1
            return path
        except DownloadError as ex:
            msg = str(ex)
            with self._lock:
                self.errors[aid] = msg
                if msg.startswith("API key was rejected"):
                    self.fatal = msg
            return None

    def fetch_many(self, aids, workers=6, progress=None):
        aids = [str(a) for a in dict.fromkeys(aids)]
        results = {}
        if not aids or not self.api_key:
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
