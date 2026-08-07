from pyrogram import filters
from pyrogram.types import Message
from L2RMUSIC import app
from L2RMUSIC.core.call import Ashish
from L2RMUSIC.utils.database import is_active_chat

# DJ / Bass Boost Mode Command
@app.on_message(filters.command(["dj", "bassboost", "club"]))
async def dj_mode_handler(client, message: Message):
    chat_id = message.chat.id
    
    if not await is_active_chat(chat_id):
        return await message.reply_text("❌ Is waqt group mein koi bhi gaana nahi chal raha hai!")

    try:
        # Volume ko 200% karke DJ / Heavy sound feel dena
        await Ashish.change_volume(chat_id, 200)
        
        await message.reply_text(
            "🎛️ **DJ Mode Activated!**\n"
            "🔊 Gaane ko **High Volume & Club Bass** mein set kar diya gaya hai! Enjoy the party! 🎉"
        )
    except Exception as e:
        await message.reply_text(f"❌ Kuch error aa gaya: `{e}`")

# Normal Mode (Reset karne ke liye)
@app.on_message(filters.command(["normal", "offdj"]))
async def normal_mode_handler(client, message: Message):
    chat_id = message.chat.id
    
    if not await is_active_chat(chat_id):
        return await message.reply_text("❌ Koi gaana active nahi hai!")

    try:
        # Volume wapas normal (100%) par lana
        await Ashish.change_volume(chat_id, 100)
        await message.reply_text("🎧 Audio mode wapas **Normal Quality** par set kar diya gaya hai.")
    except Exception as e:
        await message.reply_text(f"❌ Error: `{e}`")
