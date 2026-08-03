import asyncio
import os
import re
from typing import Union
import yt_dlp
import aiohttp
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message
from py_yt import VideosSearch, Playlist
from motor.motor_asyncio import AsyncIOMotorClient

from L2RMUSIC import LOGGER, app 
from L2RMUSIC.utils.formatters import time_to_seconds

# --- CONFIG ---
PLAYLIST_ID = -1004441504296
MONGO_DB_URI = "mongodb+srv://BWFMUSIC:BWFMUSIC@cluster0.xwnup2l.mongodb.net/?retryWrites=true&w=majority"
SHRUTI_API_URL = "https://api.shrutibots.site"
SHRUTI_API_KEY = "ShrutiBotsvfxRF6Qt1ejYXnovI3TG"
DOWNLOAD_DIR = "downloads"

logger = LOGGER(__name__)

# Safely connect to MongoDB (won't crash if IP is not whitelisted)
try:
    _mongo_async_ = AsyncIOMotorClient(MONGO_DB_URI, serverSelectionTimeoutMS=3000)
    mongodb = _mongo_async_.L2RMUSIC  
    trackdb = mongodb.track_cache
except Exception as e:
    logger.error(f"MongoDB Connection Error: {e}")
    trackdb = None

# ==========================================
# STANDALONE FUNCTIONS (For song.py plugin)
# ==========================================
async def download_song(link: str) -> str:
    video_id = link.split("v=")[-1].split("&")[0] if "v=" in link else link.split("/")[-1]
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp3")
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0: return file_path
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{SHRUTI_API_URL}/download", params={"url": video_id, "type": "audio", "api_key": SHRUTI_API_KEY}, timeout=300) as resp:
                if resp.status == 200:
                    with open(file_path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(131072): f.write(chunk)
                    return file_path
    except Exception as e:
        logger.error(f"Song Download Error: {e}")
    return None

async def download_video(link: str) -> str:
    video_id = link.split("v=")[-1].split("&")[0] if "v=" in link else link.split("/")[-1]
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    file_path = os.path.join(DOWNLOAD_DIR, f"{video_id}.mp4")
    if os.path.exists(file_path) and os.path.getsize(file_path) > 0: return file_path
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{SHRUTI_API_URL}/download", params={"url": video_id, "type": "video", "api_key": SHRUTI_API_KEY}, timeout=600) as resp:
                if resp.status == 200:
                    with open(file_path, "wb") as f:
                        async for chunk in resp.content.iter_chunked(131072): f.write(chunk)
                    return file_path
    except Exception as e:
        logger.error(f"Video Download Error: {e}")
    return None


# ==========================================
# MAIN YOUTUBE API CLASS
# ==========================================
class YouTubeAPI:
    def __init__(self):
        self.base = "https://www.youtube.com/watch?v="
        self.regex = r"(?:youtube\.com|youtu\.be)"
        self.listbase = "https://youtube.com/playlist?list="

    def _find_file(self, vid_id):
        if not os.path.exists(DOWNLOAD_DIR): return None
        for ext in ["m4a", "mp4", "mp3", "webm"]:
            filepath = os.path.join(DOWNLOAD_DIR, f"{vid_id}.{ext}")
            if os.path.exists(filepath):
                if os.path.getsize(filepath) > 2048: return os.path.abspath(filepath)
                else:
                    try: os.remove(filepath)
                    except: pass
        return None

    async def _upload_to_cache(self, vid_id, file_path, title, is_video):
        if not trackdb or not os.path.exists(file_path): return
        try:
            db_id = f"{vid_id}_video" if is_video else vid_id
            exists = await asyncio.wait_for(trackdb.find_one({"vid_id": db_id}), timeout=2.0)
            if exists: return

            logger.info(f"📤 Uploading to Channel: {title}")
            cap = f"**Song:** {title}\n**ID:** `{vid_id}`\n**Saved by:** {app.me.mention}"
            
            msg = None
            if is_video: msg = await app.send_video(PLAYLIST_ID, file_path, caption=cap, supports_streaming=True)
            else: msg = await app.send_audio(PLAYLIST_ID, file_path, caption=cap, title=title)

            if msg:
                await trackdb.update_one({"vid_id": db_id}, {"$set": {"message_id": msg.id, "title": title, "type": "video" if is_video else "audio"}}, upsert=True)
                logger.info(f"✅ Upload Complete (Msg ID: {msg.id})")
        except Exception as e:
            logger.error(f"Cache Upload Error: {e}")

    async def download(self, link: str, mystic, video: Union[bool, str] = None, videoid: Union[bool, str] = None, songaudio: Union[bool, str] = None, songvideo: Union[bool, str] = None, format_id: Union[bool, str] = None, title: Union[bool, str] = None) -> str:
        if videoid: link = self.base + link
        if "&" in link: link = link.split("&")[0]
        vid_id = link.split('v=')[-1].split('&')[0] if "v=" in link else link.split('/')[-1]
        is_video = bool(video or songvideo)
        title = title or vid_id

        # 1. Local Cache Check
        local_path = self._find_file(vid_id)
        if local_path: return local_path, True

        # 2. Database Cache Check (With timeout so it never hangs)
        if trackdb:
            try:
                db_id = f"{vid_id}_video" if is_video else vid_id
                doc = await asyncio.wait_for(trackdb.find_one({"vid_id": db_id}), timeout=2.0)
                if doc and "message_id" in doc:
                    msg = await app.get_messages(PLAYLIST_ID, doc['message_id'])
                    if msg and not msg.empty:
                        media = msg.video or msg.audio or msg.document or msg.voice
                        if media:
                            temp_path = os.path.join(DOWNLOAD_DIR, f"{vid_id}.mp4")
                            file = await app.download_media(media.file_id, file_name=temp_path)
                            if file and os.path.getsize(file) > 2048:
                                return file, True
            except Exception as e:
                logger.error(f"DB Fetch Error: {e}")

        # 3. Shruti API Download
        ext = "mp4" if is_video else "mp3"
        type_str = "video" if is_video else "audio"
        file_path = os.path.join(DOWNLOAD_DIR, f"{vid_id}.{ext}")
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        
        try:
            logger.info(f"🛡️ Using API for {vid_id}")
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{SHRUTI_API_URL}/download", params={"url": vid_id, "type": type_str, "api_key": SHRUTI_API_KEY}, timeout=300) as resp:
                    if resp.status == 200:
                        with open(file_path, "wb") as f:
                            async for chunk in resp.content.iter_chunked(131072): f.write(chunk)
                        
                        if os.path.exists(file_path) and os.path.getsize(file_path) > 2048:
                            asyncio.create_task(self._upload_to_cache(vid_id, file_path, title, is_video))
                            return file_path, True
        except Exception as e:
            logger.error(f"API Download Failed: {e}")

        # 4. Ultimate Fallback (yt-dlp directly) if API fails
        try:
            logger.info(f"🔄 Using yt-dlp fallback for {vid_id}")
            opts = {
                'format': 'bestaudio/best' if not is_video else 'best',
                'outtmpl': os.path.join(DOWNLOAD_DIR, f"{vid_id}.%(ext)s"),
                'quiet': True,
                'no_warnings': True,
            }
            def _ytdl_download():
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(link, download=True)
                    return ydl.prepare_filename(info)
            
            loop = asyncio.get_event_loop()
            dl_path = await loop.run_in_executor(None, _ytdl_download)
            if dl_path and os.path.exists(dl_path):
                return dl_path, True
        except Exception as e:
            logger.error(f"yt-dlp fallback failed: {e}")

        return None, False

    # --- METADATA (Safe Try-Except) ---
    async def exists(self, link: str, videoid: Union[bool, str] = None):
        if videoid: link = self.base + link
        return bool(re.search(self.regex, link))

    async def url(self, message_1: Message) -> Union[str, None]:
        messages = [message_1]
        if message_1.reply_to_message: messages.append(message_1.reply_to_message)
        for message in messages:
            if message.entities:
                for entity in message.entities:
                    if entity.type == MessageEntityType.URL:
                        text = message.text or message.caption
                        return text[entity.offset: entity.offset + entity.length]
            elif message.caption_entities:
                for entity in message.caption_entities:
                    if entity.type == MessageEntityType.TEXT_LINK:
                        return entity.url
        return None

    async def details(self, link: str, videoid: Union[bool, str] = None):
        if videoid: link = self.base + link
        if "&" in link: link = link.split("&")[0]
        try:
            results = VideosSearch(link, limit=1)
            for result in (await results.next())["result"]:
                title = result["title"]
                duration_min = result["duration"]
                thumbnail = result["thumbnails"][0]["url"].split("?")[0]
                vidid = result["id"]
                duration_sec = int(time_to_seconds(duration_min)) if duration_min else 0
                return title, duration_min, duration_sec, thumbnail, vidid
        except: return "Unknown", "0:00", 0, "https://telegra.ph/file/default.jpg", ""

    async def title(self, link: str, videoid: Union[bool, str] = None):
        if videoid: link = self.base + link
        if "&" in link: link = link.split("&")[0]
        try:
            results = VideosSearch(link, limit=1)
            for result in (await results.next())["result"]: return result["title"]
        except: return "Unknown"

    async def duration(self, link: str, videoid: Union[bool, str] = None):
        if videoid: link = self.base + link
        if "&" in link: link = link.split("&")[0]
        try:
            results = VideosSearch(link, limit=1)
            for result in (await results.next())["result"]: return result["duration"]
        except: return "0:00"

    async def thumbnail(self, link: str, videoid: Union[bool, str] = None):
        if videoid: link = self.base + link
        if "&" in link: link = link.split("&")[0]
        try:
            results = VideosSearch(link, limit=1)
            for result in (await results.next())["result"]: return result["thumbnails"][0]["url"].split("?")[0]
        except: return "https://telegra.ph/file/default.jpg"

    async def playlist(self, link, limit, user_id, videoid: Union[bool, str] = None):
        if videoid: link = self.listbase + link
        if "&" in link: link = link.split("&")[0]
        try:
            plist = await Playlist.get(link)
            videos = plist.get("videos") or []
            ids = [data.get("id") for data in videos[:limit] if data.get("id")]
            return ids
        except: return []

    async def track(self, link: str, videoid: Union[bool, str] = None):
        if videoid: link = self.base + link
        if "&" in link: link = link.split("&")[0]
        try:
            results = VideosSearch(link, limit=1)
            for result in (await results.next())["result"]:
                title = result["title"]
                duration_min = result["duration"]
                vidid = result["id"]
                yturl = result["link"]
                thumbnail = result["thumbnails"][0]["url"].split("?")[0]
                return {"title": title, "link": yturl, "vidid": vidid, "duration_min": duration_min, "thumb": thumbnail}, vidid
        except: raise ValueError("Track not found")

    async def formats(self, link: str, videoid: Union[bool, str] = None):
        if videoid: link = self.base + link
        if "&" in link: link = link.split("&")[0]
        ytdl_opts = {"quiet": True, "no_warnings": True}
        try:
            def _get_formats():
                with yt_dlp.YoutubeDL(ytdl_opts) as ydl:
                    formats_available = []
                    r = ydl.extract_info(link, download=False)
                    for f in r.get("formats", []):
                        if "dash" not in str(f.get("format", "")).lower():
                            formats_available.append({"format": f.get("format"), "filesize": f.get("filesize"), "format_id": f.get("format_id"), "ext": f.get("ext"), "format_note": f.get("format_note"), "yturl": link})
                    return formats_available
            loop = asyncio.get_event_loop()
            res = await loop.run_in_executor(None, _get_formats)
            return res, link
        except: return [], link

    async def slider(self, link: str, query_type: int, videoid: Union[bool, str] = None):
        if videoid: link = self.base + link
        if "&" in link: link = link.split("&")[0]
        try:
            a = VideosSearch(link, limit=10)
            res = (await a.next()).get("result", [])
            result = res[query_type] if query_type < len(res) else res[0]
            return result["title"], result["duration"], result["thumbnails"][0]["url"].split("?")[0], result["id"]
        except: return "Unknown", "0:00", "https://telegra.ph/file/default.jpg", ""

YouTube = YouTubeAPI()
