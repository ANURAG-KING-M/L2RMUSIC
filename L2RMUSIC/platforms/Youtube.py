import asyncio
import os
import re
import sys
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
# CONFIG (sab secrets Railway Variables se aayenge)
# ==========================================
PLAYLIST_ID = int(os.getenv("PLAYLIST_ID", "-1003616869403"))
MONGO_DB_URI = os.getenv("MONGO_DB_URI", "mongodb+srv://BWFMUSIC:BWFMUSIC@cluster0.xwnup2l.mongodb.net/?retryWrites=true&w=majority")
SHRUTI_API_URL = os.getenv("SHRUTI_API_URL", "https://api.shrutibots.site")
SHRUTI_API_KEY = os.getenv("SHRUTI_API_KEY", "ShrutiBotsvfxRF6Qt1ejYXnovI3TG")
DOWNLOAD_DIR = os.path.abspath(os.getenv("DOWNLOAD_DIR", "downloads"))
COOKIE_FILE = os.path.abspath(os.getenv("COOKIE_FILE", "cookies.txt"))
MIN_SIZE = 2048

logger = LOGGER(__name__)

# MongoDB
trackdb = None
if MONGO_DB_URI:
    try:
        _mongo_async_ = AsyncIOMotorClient(MONGO_DB_URI, serverSelectionTimeoutMS=5000)
        mongodb = _mongo_async_.L2RMUSIC
        trackdb = mongodb.track_cache
        logger.info("MongoDB connected successfully.")
    except Exception as e:
        logger.error(f"MongoDB Connection Error: {e}")
        trackdb = None
else:
    logger.warning("MONGO_DB_URI not set, Telegram cache disabled.")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


# ==========================================
# HELPERS
# ==========================================
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


def extract_video_id(link: str) -> Optional[str]:
    """Extract video ID from watch / youtu.be / shorts / live / embed links or a bare ID."""
    if not link:
        return None
    link = link.strip()
    if _ID_RE.match(link):
        return link
    m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", link)
    if m:
        return m.group(1)
    m = re.search(r"(?:youtu\.be/|/shorts/|/live/|/embed/|/v/)([A-Za-z0-9_-]{11})", link)
    if m:
        return m.group(1)
    return None


def _safe_name(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\n\r\t]', "", str(name)).strip()
    return name[:100] or "file"


def _cookie_opts() -> dict:
    if os.path.exists(COOKIE_FILE):
        return {"cookiefile": COOKIE_FILE}
    return {}


def _file_ok(path: Optional[str]) -> bool:
    return bool(path) and os.path.exists(path) and os.path.getsize(path) > MIN_SIZE


async def _shruti_fetch(video_id: str, is_video: bool) -> Optional[str]:
    """Download from Shruti API into DOWNLOAD_DIR. Returns absolute path or None."""
    if not SHRUTI_API_KEY:
        return None
    ext = "mp4" if is_video else "mp3"
    final_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.{ext}")
    tmp_path = final_path + ".part"
    params = {
        "url": video_id,
        "type": "video" if is_video else "audio",
        "api_key": SHRUTI_API_KEY,
    }
    try:
        timeout = aiohttp.ClientTimeout(total=600 if is_video else 300)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"{SHRUTI_API_URL}/download", params=params) as resp:
                if resp.status != 200:
                    logger.error(f"Shruti API returned {resp.status}")
                    return None
                with open(tmp_path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(131072):
                        f.write(chunk)
        if _file_ok(tmp_path):
            os.replace(tmp_path, final_path)
            return final_path
        logger.warning("Shruti file too small, removed.")
    except Exception as e:
        logger.error(f"Shruti download failed: {e}")
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
    return None


async def _ytdlp_fetch(link: str, vid_id: str, is_video: bool) -> Optional[str]:
    """yt-dlp fallback. Returns absolute path or None."""
    opts = {
        "format": "bestvideo[height<=720]+bestaudio/best[height<=720]/best" if is_video else "bestaudio/best",
        "outtmpl": os.path.join(DOWNLOAD_DIR, f"{vid_id}.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "geo_bypass": True,
        "nocheckcertificate": True,
        **_cookie_opts(),
    }
    if is_video:
        opts["merge_output_format"] = "mp4"

    def _run():
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(link, download=True)
            rd = info.get("requested_downloads")
            if rd and rd[0].get("filepath"):
                return rd[0]["filepath"]
            return ydl.prepare_filename(info)

    try:
        loop = asyncio.get_running_loop()
        path = await loop.run_in_executor(None, _run)
        if path:
            path = os.path.abspath(path)
        if _file_ok(path):
            return path
        # merge ke baad extension badal sakta hai, isliye folder me dhundo
        for ext in (["mp4", "mkv", "webm"] if is_video else ["m4a", "webm", "mp3", "opus"]):
            p = os.path.join(DOWNLOAD_DIR, f"{vid_id}.{ext}")
            if _file_ok(p):
                return p
    except Exception as e:
        logger.error(f"yt-dlp fallback failed: {e}")
    return None


# ==========================================
# STANDALONE FUNCTIONS (song.py plugin ke liye)
# ==========================================
async def download_song(link: str) -> Optional[str]:
    video_id = extract_video_id(link)
    if not video_id:
        return None
    path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")
    if _file_ok(path):
        return path
    path = await _shruti_fetch(video_id, False)
    if path:
        return path
    return await _ytdlp_fetch(f"https://www.youtube.com/watch?v={video_id}", video_id, False)


async def download_video(link: str) -> Optional[str]:
    video_id = extract_video_id(link)
    if not video_id:
        return None
    path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp4")
    if _file_ok(path):
        return path
    path = await _shruti_fetch(video_id, True)
    if path:
        return path
    return await _ytdlp_fetch(f"https://www.youtube.com/watch?v={video_id}", video_id, True)


# ==========================================
# MAIN YOUTUBE API CLASS
# ==========================================
class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.listbase = "https://youtube.com/playlist?list="

    def _find_file(self, vid_id: str, is_video: bool = False) -> Optional[str]:
        """Video ke liye sirf video files, audio ke liye sirf audio files."""
        exts = ["mp4", "mkv"] if is_video else ["mp3", "m4a", "opus", "webm"]
        for ext in exts:
            filepath = os.path.join(DOWNLOAD_DIR, f"{vid_id}.{ext}")
            if os.path.exists(filepath):
                if os.path.getsize(filepath) > MIN_SIZE:
                    return os.path.abspath(filepath)
                try:
                    os.remove(filepath)
                except Exception:
                    pass
        return None

    async def _upload_to_cache(self, vid_id: str, file_path: str, title: str, is_video: bool):
        if trackdb is None or not os.path.exists(file_path):
            return
        try:
            db_id = f"{vid_id}_video" if is_video else vid_id
            if await trackdb.find_one({"vid_id": db_id}):
                return

            logger.info(f"📤 Uploading to Channel: {title}")
            mention = app.me.mention if app.me else "Bot"
            cap = f"**Song:** {title}\n**ID:** `{vid_id}`\n**Saved by:** {mention}"
            try:
                if is_video:
                    msg = await app.send_video(PLAYLIST_ID, file_path, caption=cap, supports_streaming=True)
                else:
                    msg = await app.send_audio(PLAYLIST_ID, file_path, caption=cap, title=title)
            except Exception as send_err:
                logger.warning(f"Cannot send to channel (ID: {PLAYLIST_ID}): {send_err}")
                return

            if msg:
                await trackdb.update_one(
                    {"vid_id": db_id},
                    {"$set": {
                        "message_id": msg.id,
                        "title": title,
                        "type": "video" if is_video else "audio",
                    }},
                    upsert=True,
                )
                logger.info(f"✅ Upload Complete (Msg ID: {msg.id})")
        except Exception as e:
            logger.error(f"Cache Upload Error: {e}")

    async def video(self, link: str, videoid: Union[bool, str] = None):
        """Direct stream URL (yt-dlp -g). Returns (1, url) ya (0, error)."""
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        cmd = [
            sys.executable, "-m", "yt_dlp",
            "--no-warnings", "--no-playlist",
            "-g",
            "-f", "best[height<=?720][width<=?1280]/best",
        ]
        if os.path.exists(COOKIE_FILE):
            cmd += ["--cookies", COOKIE_FILE]
        cmd.append(link)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if stdout:
                return 1, stdout.decode().split("\n")[0]
            return 0, stderr.decode()
        except Exception as e:
            logger.error(f"video stream url error: {e}")
            return 0, str(e)

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
        """Returns (absolute_file_path, success)."""
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        vid_id = extract_video_id(link)
        if not vid_id:
            logger.error("Invalid YouTube link")
            return None, False
        link = self.base + vid_id

        # --- song.py: custom format download ---
        if songvideo or songaudio:
            fname = _safe_name(title or vid_id)
            if songvideo:
                opts = {
                    "format": f"{format_id}+bestaudio/best" if format_id else "bestvideo[height<=720]+bestaudio/best",
                    "outtmpl": os.path.join(DOWNLOAD_DIR, f"{fname}.%(ext)s"),
                    "merge_output_format": "mp4",
                    "quiet": True,
                    "no_warnings": True,
                    "noplaylist": True,
                    **_cookie_opts(),
                }
                final = os.path.join(DOWNLOAD_DIR, f"{fname}.mp4")
            else:
                opts = {
                    "format": f"{format_id}/bestaudio/best" if format_id else "bestaudio/best",
                    "outtmpl": os.path.join(DOWNLOAD_DIR, f"{fname}.%(ext)s"),
                    "quiet": True,
                    "no_warnings": True,
                    "noplaylist": True,
                    "postprocessors": [{
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }],
                    **_cookie_opts(),
                }
                final = os.path.join(DOWNLOAD_DIR, f"{fname}.mp3")

            def _song_dl():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    ydl.download([link])

            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, _song_dl)
                if _file_ok(final):
                    return final, True
            except Exception as e:
                logger.error(f"song download error: {e}")
            return None, False

        is_video = bool(video)

        # 1. Local cache
        local_path = self._find_file(vid_id, is_video)
        if local_path:
            logger.info(f"✅ Found local file: {local_path}")
            return local_path, True

        # 2. Telegram channel cache
        if trackdb is not None:
            try:
                db_id = f"{vid_id}_video" if is_video else vid_id
                doc = await asyncio.wait_for(trackdb.find_one({"vid_id": db_id}), timeout=5.0)
                if doc and "message_id" in doc:
                    try:
                        msg = await app.get_messages(PLAYLIST_ID, doc["message_id"])
                    except Exception as get_err:
                        logger.warning(f"Cache retrieval failed (channel {PLAYLIST_ID}): {get_err}")
                        msg = None
                    if msg and not msg.empty:
                        media = msg.video or msg.audio or msg.document or msg.voice
                        if media:
                            temp_path = os.path.join(DOWNLOAD_DIR, f"{vid_id}.{'mp4' if is_video else 'mp3'}")
                            file = await app.download_media(media.file_id, file_name=temp_path)
                            if file:
                                file = os.path.abspath(file)
                                if _file_ok(file):
                                    logger.info(f"✅ Downloaded from Telegram cache: {file}")
                                    return file, True
            except Exception as e:
                logger.error(f"DB Fetch Error: {e}")

        # 3. Shruti API
        logger.info(f"🛡️ Using Shruti API for {vid_id}")
        path = await _shruti_fetch(vid_id, is_video)
        if path:
            asyncio.create_task(self._upload_to_cache(vid_id, path, str(title or vid_id), is_video))
            logger.info(f"✅ Downloaded via Shruti API: {path}")
            return path, True

        # 4. yt-dlp fallback
        logger.info(f"🔄 Using yt-dlp fallback for {vid_id}")
        path = await _ytdlp_fetch(link, vid_id, is_video)
        if path:
            logger.info(f"✅ Downloaded via yt-dlp: {path}")
            asyncio.create_task(self._upload_to_cache(vid_id, path, str(title or vid_id), is_video))
            return path, True

        return None, False

    # --- Metadata ---
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
            for entities in (message.entities, message.caption_entities):
                if not entities:
                    continue
                for entity in entities:
                    if entity.type == MessageEntityType.URL:
                        return text[entity.offset: entity.offset + entity.length]
                    if entity.type == MessageEntityType.TEXT_LINK:
                        return entity.url
        return None

    async def details(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        try:
            results = VideosSearch(link, limit=1)
            for result in (await results.next())["result"]:
                title = result["title"]
                duration_min = result["duration"]
                thumbnail = result["thumbnails"][0]["url"].split("?")[0]
                vidid = result["id"]
                duration_sec = int(time_to_seconds(duration_min)) if duration_min else 0
                return title, duration_min, duration_sec, thumbnail, vidid
        except Exception as e:
            logger.error(f"details error: {e}")
        return "Unknown", "0:00", 0, "https://telegra.ph/file/default.jpg", ""

    async def title(self, link: str, videoid: Union[bool, str] = None) -> str:
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        try:
            results = VideosSearch(link, limit=1)
            for result in (await results.next())["result"]:
                return result["title"]
        except Exception as e:
            logger.error(f"title error: {e}")
        return "Unknown"

    async def duration(self, link: str, videoid: Union[bool, str] = None) -> str:
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        try:
            results = VideosSearch(link, limit=1)
            for result in (await results.next())["result"]:
                return result["duration"]
        except Exception as e:
            logger.error(f"duration error: {e}")
        return "0:00"

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None) -> str:
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        try:
            results = VideosSearch(link, limit=1)
            for result in (await results.next())["result"]:
                return result["thumbnails"][0]["url"].split("?")[0]
        except Exception as e:
            logger.error(f"thumbnail error: {e}")
        return "https://telegra.ph/file/default.jpg"

    async def playlist(self, link, limit, user_id, videoid: Union[bool, str] = None):
        if videoid:
            link = self.listbase + link
        if "&" in link:
            link = link.split("&")[0]
        try:
            plist = await Playlist.get(link)
            videos = plist.get("videos") or []
            return [data.get("id") for data in videos[:limit] if data.get("id")]
        except Exception as e:
            logger.error(f"playlist error: {e}")
            return []

    async def track(self, link: str, videoid: Union[bool, str] = None):
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        try:
            results = VideosSearch(link, limit=1)
            for result in (await results.next())["result"]:
                vidid = result["id"]
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
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        ytdl_opts = {"quiet": True, "no_warnings": True, **_cookie_opts()}

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
        if videoid:
            link = self.base + link
        if "&" in link:
            link = link.split("&")[0]
        try:
            a = VideosSearch(link, limit=10)
            res = (await a.next()).get("result", [])
            result = res[query_type] if query_type < len(res) else res[0]
            return result["title"], result["duration"], result["thumbnails"][0]["url"].split("?")[0], result["id"]
        except Exception as e:
            logger.error(f"slider error: {e}")
            return "Unknown", "0:00", "https://telegra.ph/file/default.jpg", ""


YouTube = YouTubeAPI()
