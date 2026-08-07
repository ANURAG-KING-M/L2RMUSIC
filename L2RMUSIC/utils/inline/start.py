From pyrogram.types import InlineKeyboardButton

Import config
from L2RMUSIC import app


Def start_panel(_):
    Buttons = [
        [
            InlineKeyboardButton(
                text=_["S_B_1"], url=f"https://t.me/{app.username}?startgroup=true"
            ),
            InlineKeyboardButton(text=_["S_B_2"], url=config.SUPPORT_CHAT),
        ],
    ]
    Return buttons


Def private_panel(_):
    Buttons = [
        [
            InlineKeyboardButton(
                text="🔎 ʜᴇʟᴩ 🔎",
                callback_data="settings_helper"
            )
        ],
        [
            InlineKeyboardButton(text="📨 sᴜᴘᴘᴏʀᴛ", url=config.SUPPORT_CHAT),
            InlineKeyboardButton(text="📨 ᴄʜᴀɴɴᴇʟ", url=config.SUPPORT_CHANNEL),
        ],
        [
            InlineKeyboardButton(
                text="⛩️ ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ ⛩️",
                url=f"https://t.me/{app.username}?startgroup=true"
            )
        ],
        [
            InlineKeyboardButton(text="🔥 ᴏᴡɴᴇʀ 🔥", user_id=config.OWNER_ID),
        ],
        [
            InlineKeyboardButton(text="🇮🇳 ʟᴀɴɢᴜᴀɢᴇ 🏳️‍🌈", callback_data="bot_info_data"),
        ],
    ]
    Return buttons
