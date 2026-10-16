import asyncio
import os
import re
from typing import Union, Optional, Tuple

import aiohttp
import yt_dlp
from motor.motor_asyncio import AsyncIOMotorClient
from py_yt import VideosSearch, Playlist
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message

from L2RMUSIC import LOGGER, app
from L2RMUSIC.utils.formatters import time_to_seconds

# ==========================================
# CONFIG  (secrets sirf environment se lo!)
# ==========================================
PLAYLIST_ID = int(os.getenv("PLAYLIST_ID", "-1003616869403"))
MONGO_DB_URI = os.getenv("MONGO_DB_URI", "mongodb+srv://BWFMUSIC:BWFMUSIC@cluster0.xwnup2l.mongodb.net/?retryWrites=true&w=majority")
SHRUTI_API_URL = os.getenv("SHRUTI_API_URL", "https://api.shrutibots.site")
SHRUTI_API_KEY = os.getenv("SHRUTI_API_KEY", "ShrutiBots7EhoL3cMjnYD3VEhQDIA")
DOWNLOAD_DIR = os.getenv("DOWNLOAD_DIR", "downloads")
COOKIES_FILE = os.getenv("COOKIES_FILE", "cookies.txt")
# True = pehle channel cache check karo (fast), phir API/yt-dlp
CACHE_FIRST = os.getenv("CACHE_FIRST", "False").lower() == "true"

MIN_SIZE = 2048
DEFAULT_THUMB = "https://telegra.ph/file/default.jpg"

logger = LOGGER(__name__)

# ==========================================
# MONGODB
# ==========================================
trackdb = None
if MONGO_DB_URI:
    try:
        _mongo_async_ = AsyncIOMotorClient(MONGO_DB_URI, serverSelectionTimeoutMS=5000)
        trackdb = _mongo_async_.L2RMUSIC.track_cache
        logger.info("MongoDB client created.")
    except Exception as e:
        logger.error(f"MongoDB Connection Error: {e}")
else:
    logger.warning("MONGO_DB_URI not set - DB cache disabled.")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ==========================================
# INTERNAL STATE
# ==========================================
_locks: dict = {}            # per-video download lock
_uploaded: set = set()       # db_ids already in channel (memory)
_preloading: set = set()     # videos currently preloading
_tasks: set = set()          # keep task refs so they aren't GC'd
_channel_ready = False

VIDEO_ID_RE = re.compile(
    r"(?:v=|youtu\.be/|shorts/|embed/|live/)([0-9A-Za-z_-]{11})"
)


def _spawn(coro):
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


def extract_video_id(link: str) -> Optional[str]:
    """Extract video ID from various YouTube URL formats (or a bare ID)."""
    if not link:
        return None
    link = link.strip()
    m = VIDEO_ID_RE.search(link)
    if m:
        return m.group(1)
    if re.fullmatch(r"[0-9A-Za-z_-]{11}", link):
        return link
    return None


def _ok(path: Optional[str]) -> bool:
    return bool(path) and os.path.exists(path) and os.path.getsize(path) > MIN_SIZE


def _safe_remove(path: str):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass


async def _ensure_channel() -> bool:
    """Resolve the cache channel once so Pyrogram knows the peer."""
    global _channel_ready
    if _channel_ready:
        return True
    try:
        await app.get_chat(PLAYLIST_ID)
        _channel_ready = True
    except Exception as e:
        logger.warning(
            f"Cache channel {PLAYLIST_ID} not accessible "
            f"(bot ko channel mein admin banao): {e}"
        )
    return _channel_ready


# ==========================================
# DOWNLOAD SOURCES
# ==========================================
async def _api_download(vid_id: str, is_video: bool) -> Optional[str]:
    """Source 1: Shruti API."""
    if not SHRUTI_API_KEY:
        return None
    ext = "mp4" if is_video else "mp3"
    file_path = os.path.join(DOWNLOAD_DIR, f"{vid_id}.{ext}")
    timeout = aiohttp.ClientTimeout(total=600 if is_video else 300)
    try:
        logger.info(f"🛡️ Shruti API: {vid_id}")
        async with aiohttp.ClientSession(timeout=timeout) as session:
            params = {
                "url": vid_id,
                "type": "video" if is_video else "audio",
                "api_key": SHRUTI_API_KEY,
            }
            async with session.get(f"{SHRUTI_API_URL}/download", params=params) as resp:
                if resp.status != 200:
                    logger.error(f"Shruti API returned {resp.status}")
                    return None
                with open(file_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(131072):
                        f.write(chunk)
        if _ok(file_path):
            return file_path
        _safe_remove(file_path)
        logger.warning("API file too small, removed.")
    except Exception as e:
        logger.error(f"API Download Failed: {e}")
        _safe_remove(file_path)
    return None


async def _ytdlp_download(vid_id: str, is_video: bool) -> Optional[str]:
    """Source 2: yt-dlp (cookies agar cookies.txt maujood ho)."""
    link = f"https://www.youtube.com/watch?v={vid_id}"
    opts = {
        "format": (
            "best[height<=720][ext=mp4]/best[ext=mp4]/best"
            if is_video
            else "bestaudio[ext=m4a]/bestaudio/best"
        ),
        "outtmpl": os.path.join(DOWNLOAD_DIR, f"{vid_id}.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "geo_bypass": True,
    }
    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE

    def _run():
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(link, download=True)
            return ydl.prepare_filename(info)

    try:
        logger.info(f"🔄 yt-dlp: {vid_id}")
        loop = asyncio.get_running_loop()
        path = await loop.run_in_executor(None, _run)
        if _ok(path):
            return path
    except Exception as e:
        logger.error(f"yt-dlp failed: {e}")
    return None


async def _channel_fetch(vid_id: str, is_video: bool) -> Optional[str]:
    """Source 3: pehle se channel mein saved file."""
    if not await _ensure_channel():
        return None

    msg = None
    db_id = f"{vid_id}_video" if is_video else vid_id

    # a) DB se message id
    if trackdb is not None:
        try:
            doc = await asyncio.wait_for(trackdb.find_one({"vid_id": db_id}), timeout=5.0)
            if doc and doc.get("message_id"):
                msg = await app.get_messages(PLAYLIST_ID, doc["message_id"])
        except Exception as e:
            logger.warning(f"Cache DB lookup failed: {e}")

    # b) DB mein na ho to channel mein caption (ID) se search
    if (not msg or msg.empty):
        try:
            async for m in app.search_messages(PLAYLIST_ID, query=vid_id, limit=5):
                if m.video if is_video else (m.audio or m.document or m.voice):
                    msg = m
                    break
        except Exception as e:
            logger.debug(f"Channel search unavailable: {e}")

    if not msg or msg.empty:
        return None

    media = msg.video or msg.audio or msg.document or msg.voice
    if not media:
        return None

    target = os.path.join(DOWNLOAD_DIR, f"{vid_id}.{'mp4' if is_video else 'mp3'}")
    try:
        file = await app.download_media(msg, file_name=target)
        if _ok(file):
            logger.info(f"✅ Telegram cache se mila: {file}")
            _uploaded.add(db_id)
            return file
    except Exception as e:
        logger.error(f"Channel download failed: {e}")
    return None


# ==========================================
# CHANNEL UPLOAD (auto-cache)
# ==========================================
async def _fetch_title(vid_id: str) -> str:
    try:
        res = VideosSearch(f"https://www.youtube.com/watch?v={vid_id}", limit=1)
        for r in (await res.next())["result"]:
            return r["title"]
    except Exception:
        pass
    return vid_id


async def _upload_to_cache(vid_id: str, file_path: str, title: Optional[str], is_video: bool):
    """Channel mein upload karo + DB mein message id save karo."""
    db_id = f"{vid_id}_video" if is_video else vid_id
    if db_id in _uploaded or not _ok(file_path):
        return
    if not await _ensure_channel():
        return
    try:
        if trackdb is not None:
            if await trackdb.find_one({"vid_id": db_id}):
                _uploaded.add(db_id)
                return

        if not title or title == vid_id:
            title = await _fetch_title(vid_id)

        logger.info(f"📤 Uploading to channel: {title}")
        mention = app.me.mention if getattr(app, "me", None) else "Bot"
        cap = f"**Song:** {title}\n**ID:** `{vid_id}`\n**Saved by:** {mention}"

        try:
            if is_video:
                msg = await app.send_video(PLAYLIST_ID, file_path, caption=cap, supports_streaming=True)
            else:
                msg = await app.send_audio(PLAYLIST_ID, file_path, caption=cap, title=title)
        except Exception as first_err:
            logger.warning(f"send media failed ({first_err}), trying as document")
            try:
                msg = await app.send_document(PLAYLIST_ID, file_path, caption=cap)
            except Exception as send_err:
                logger.warning(f"Cannot send to channel {PLAYLIST_ID}: {send_err}")
                return

        _uploaded.add(db_id)
        if msg and trackdb is not None:
            await trackdb.update_one(
                {"vid_id": db_id},
                {"$set": {
                    "message_id": msg.id,
                    "title": title,
                    "type": "video" if is_video else "audio",
                }},
                upsert=True,
            )
        logger.info(f"✅ Channel upload done (Msg ID: {getattr(msg, 'id', '?')})")
    except Exception as e:
        logger.error(f"Cache Upload Error: {e}")


# ==========================================
# CORE FETCH LOGIC
# ==========================================
async def fetch_media(vid_id: str, is_video: bool = False, title: Optional[str] = None) -> Optional[str]:
    """
    local -> (channel if CACHE_FIRST) -> API -> yt-dlp(cookies) -> channel
    Successful download hamesha channel mein bhi save hota hai.
    """
    key = f"{vid_id}_{'v' if is_video else 'a'}"
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        # 1. Local
        path = _find_file_static(vid_id, is_video)
        if path:
            _spawn(_upload_to_cache(vid_id, path, title, is_video))
            return path

        # 2. Channel first (optional)
        if CACHE_FIRST:
            path = await _channel_fetch(vid_id, is_video)
            if path:
                return path

        # 3. API
        path = await _api_download(vid_id, is_video)
        # 4. yt-dlp + cookies
        if not path:
            path = await _ytdlp_download(vid_id, is_video)

        if path:
            _spawn(_upload_to_cache(vid_id, path, title, is_video))
            return path

        # 5. Last resort: channel
        if not CACHE_FIRST:
            path = await _channel_fetch(vid_id, is_video)
            if path:
                return path

        logger.error(f"All sources failed for {vid_id}")
        return None


def _find_file_static(vid_id: str, is_video: bool = False) -> Optional[str]:
    if not os.path.exists(DOWNLOAD_DIR):
        return None
    first = "mp4" if is_video else "mp3"
    exts = [first] + [e for e in ("m4a", "webm", "mp3", "mp4") if e != first]
    # video ke liye audio-only file na uthao aur vice versa
    if is_video:
        exts = ["mp4", "webm"]
    for ext in exts:
        p = os.path.join(DOWNLOAD_DIR, f"{vid_id}.{ext}")
        if os.path.exists(p):
            if os.path.getsize(p) > MIN_SIZE:
                return os.path.abspath(p)
            _safe_remove(p)
    return None


async def _preload(vid_id: str):
    """Background mein song channel mein save karo (audio)."""
    if not vid_id or vid_id in _uploaded or vid_id in _preloading:
        return
    _preloading.add(vid_id)
    try:
        if trackdb is not None:
            try:
                if await trackdb.find_one({"vid_id": vid_id}):
                    _uploaded.add(vid_id)
                    return
            except Exception:
                pass
        await fetch_media(vid_id, False)
    except Exception as e:
        logger.error(f"Preload error: {e}")
    finally:
        _preloading.discard(vid_id)


def schedule_preload(vid_id: str):
    if vid_id:
        _spawn(_preload(vid_id))


# ==========================================
# STANDALONE FUNCTIONS (song.py plugin ke liye)
# ==========================================
async def download_song(link: str) -> Optional[str]:
    vid = extract_video_id(link)
    return await fetch_media(vid, False) if vid else None


async def download_video(link: str) -> Optional[str]:
    vid = extract_video_id(link)
    return await fetch_media(vid, True) if vid else None


# ==========================================
# MAIN YOUTUBE API CLASS
# ==========================================
class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.listbase = "https://youtube.com/playlist?list="
        self.valid_exts = ["m4a", "mp4", "mp3", "webm"]

    def _find_file(self, vid_id: str, is_video: bool = False) -> Optional[str]:
        return _find_file_static(vid_id, is_video)

    def _clean(self, link: str, videoid=None, base=None) -> str:
        if videoid:
            link = (base or self.base) + link
        if "&" in link:
            link = link.split("&")[0]
        return link

    async def download(
        self,
        link: str,
        mystic,
        video: Union[bool, str] = None,
        videoid: Union[bool, str] = None,
        songaudio: Union[bool, str] = None,
        songvideo: Union[bool, str] = None,
        format_id: Union[bool, str] = None,
        title: Union[bool, str] = None,
    ) -> Tuple[Optional[str], bool]:
        """Returns (file_path, success)."""
        link = self._clean(link, videoid)
        vid_id = extract_video_id(link)
        if not vid_id:
            logger.error("Invalid YouTube link")
            return None, False

        is_video = bool(video or songvideo)
        path = await fetch_media(vid_id, is_video, title if isinstance(title, str) else None)
        return (path, True) if path else (None, False)

    # ---------- Metadata ----------
    async def exists(self, link: str, videoid: Union[bool, str] = None) -> bool:
        if videoid:
            link = self.base + link
        return bool(re.search(self.regex, link))

    async def url(self, message_1: Message) -> Optional[str]:
        messages = [message_1]
        if message_1.reply_to_message:
            messages.append(message_1.reply_to_message)
        for message in messages:
            text = message.text or message.caption or ""
            for ent_list in (message.entities, message.caption_entities):
                for entity in ent_list or []:
                    if entity.type == MessageEntityType.URL:
                        return text[entity.offset: entity.offset + entity.length]
                    if entity.type == MessageEntityType.TEXT_LINK:
                        return entity.url
        return None

    async def details(self, link: str, videoid: Union[bool, str] = None):
        link = self._clean(link, videoid)
        try:
            results = VideosSearch(link, limit=1)
            for result in (await results.next())["result"]:
                title = result["title"]
                duration_min = result["duration"]
                thumbnail = result["thumbnails"][0]["url"].split("?")[0]
                vidid = result["id"]
                duration_sec = int(time_to_seconds(duration_min)) if duration_min else 0
                schedule_preload(vidid)  # channel mein pehle se save
                return title, duration_min, duration_sec, thumbnail, vidid
        except Exception as e:
            logger.error(f"details error: {e}")
        return "Unknown", "0:00", 0, DEFAULT_THUMB, ""

    async def title(self, link: str, videoid: Union[bool, str] = None) -> str:
        link = self._clean(link, videoid)
        try:
            results = VideosSearch(link, limit=1)
            for result in (await results.next())["result"]:
                return result["title"]
        except Exception as e:
            logger.error(f"title error: {e}")
        return "Unknown"

    async def duration(self, link: str, videoid: Union[bool, str] = None) -> str:
        link = self._clean(link, videoid)
        try:
            results = VideosSearch(link, limit=1)
            for result in (await results.next())["result"]:
                return result["duration"]
        except Exception as e:
            logger.error(f"duration error: {e}")
        return "0:00"

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None) -> str:
        link = self._clean(link, videoid)
        try:
            results = VideosSearch(link, limit=1)
            for result in (await results.next())["result"]:
                return result["thumbnails"][0]["url"].split("?")[0]
        except Exception as e:
            logger.error(f"thumbnail error: {e}")
        return DEFAULT_THUMB

    async def playlist(self, link, limit, user_id, videoid: Union[bool, str] = None):
        link = self._clean(link, videoid, self.listbase)
        try:
            plist = await Playlist.get(link)
            videos = plist.get("videos") or []
            ids = [d.get("id") for d in videos[:limit] if d.get("id")]
            for vid in ids:
                schedule_preload(vid)
            return ids
        except Exception as e:
            logger.error(f"playlist error: {e}")
            return []

    async def track(self, link: str, videoid: Union[bool, str] = None):
        link = self._clean(link, videoid)
        try:
            results = VideosSearch(link, limit=1)
            for result in (await results.next())["result"]:
                vidid = result["id"]
                schedule_preload(vidid)  # channel mein pehle se save
                return {
                    "title": result["title"],
                    "link": result["link"],
                    "vidid": vidid,
                    "duration_min": result["duration"],
                    "thumb": result["thumbnails"][0]["url"].split("?")[0],
                }, vidid
        except Exception as e:
            logger.error(f"track error: {e}")
        raise ValueError("Track not found")

    async def formats(self, link: str, videoid: Union[bool, str] = None):
        link = self._clean(link, videoid)
        ytdl_opts = {"quiet": True, "no_warnings": True}
        if COOKIES_FILE and os.path.exists(COOKIES_FILE):
            ytdl_opts["cookiefile"] = COOKIES_FILE

        def _get_formats():
            with yt_dlp.YoutubeDL(ytdl_opts) as ydl:
                out = []
                r = ydl.extract_info(link, download=False)
                for f in r.get("formats", []):
                    if "dash" not in str(f.get("format", "")).lower():
                        out.append({
                            "format": f.get("format"),
                            "filesize": f.get("filesize"),
                            "format_id": f.get("format_id"),
                            "ext": f.get("ext"),
                            "format_note": f.get("format_note"),
                            "yturl": link,
                        })
                return out

        try:
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(None, _get_formats)
            return res, link
        except Exception as e:
            logger.error(f"formats error: {e}")
            return [], link

    async def slider(self, link: str, query_type: int, videoid: Union[bool, str] = None):
        link = self._clean(link, videoid)
        try:
            a = VideosSearch(link, limit=10)
            res = (await a.next()).get("result", [])
            result = res[query_type] if query_type < len(res) else res[0]
            return (
                result["title"],
                result["duration"],
                result["thumbnails"][0]["url"].split("?")[0],
                result["id"],
            )
        except Exception as e:
            logger.error(f"slider error: {e}")
            return "Unknown", "0:00", DEFAULT_THUMB, ""


# Global instance
YouTube = YouTubeAPI()
