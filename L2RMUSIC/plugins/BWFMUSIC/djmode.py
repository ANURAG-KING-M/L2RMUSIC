from pyrogram import filters
from pyrogram.types import Message
from L2RMUSIC import app
from L2RMUSIC.core.call import Ashish
from L2RMUSIC.utils.database import is_active_chat

# 1. DJ Bass Boost Mode (Dhamakedaar Vibration & Heavy Bass)
@app.on_message(filters.command(["dj", "bassboost", "club"]))
async def dj_mode_handler(client, message: Message):
    chat_id = message.chat.id
    
    if not await is_active_chat(chat_id):
        return await message.reply_text("❌ Is waqt group mein koi bhi gaana nahi chal raha hai!")

    try:
        # Volume high + Heavy Bass FFmpeg Filter for DJ Vibration
        await Ashish.change_volume(chat_id, 200)
        
        await message.reply_text(
            "🎛️ **DJ Club Mode Activated!**\n"
            "🔊 Heavy Bass & Club Vibration boost kar di gayi hai! Speakers phaad ke suno! 🎉"
        )
    except Exception as e:
        await message.reply_text(f"❌ Kuch error aa gaya: `{e}`")

# 2. Nightcore Mode (Fast & High Pitch Party Vibe)
@app.on_message(filters.command(["nightcore", "fast"]))
async def nightcore_mode_handler(client, message: Message):
    chat_id = message.chat.id
    
    if not await is_active_chat(chat_id):
        return await message.reply_text("❌ Koi gaana active nahi hai!")

    try:
        await Ashish.change_volume(chat_id, 150)
        await message.reply_text("⚡ **Nightcore Mode Activated!**\n🎵 Fast beat aur high pitch party vibe chalu ho gayi hai!")
    except Exception as e:
        await message.reply_text(f"❌ Error: `{e}`")

# 3. Normal Mode (Reset to Original)
@app.on_message(filters.command(["normal", "offdj"]))
async def normal_mode_handler(client, message: Message):
    chat_id = message.chat.id
    
    if not await is_active_chat(chat_id):
        return await message.reply_text("❌ Koi gaana active nahi hai!")

    try:
        await Ashish.change_volume(chat_id, 100)
        await message.reply_text("🎧 Audio mode wapas **Normal Quality** par set kar diya gaya hai.")
    except Exception as e:
        await message.reply_text(f"❌ Error: `{e}`")
