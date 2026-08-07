import os
import requests
from pyrogram import filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from L2RMUSIC import app
### ❖ ➥ 𝗕𝐖𝗙™🇮🇳

def upload_file(file_path):
    url = "https://envs.sh"
    try:
        with open(file_path, "rb") as f:
            files = {"file": f}
            # Custom User-Agent taaki server automated script na samjhe
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            response = requests.post(url, files=files, headers=headers)

        if response.status_code == 200:
            return True, response.text.strip()
        else:
            return False, f"ᴇʀʀᴏʀ: {response.status_code} - {response.text}"
    except Exception as e:
        return False, f"ᴇʀʀᴏʀ: {str(e)}"


@app.on_message(filters.command(["tgm", "tgt", "telegraph", "tl"]))
async def get_link_group(client, message):
    if not message.reply_to_message:
        return await message.reply_text(
            "Pʟᴇᴀsᴇ rᴇᴘʟʏ ᴛᴏ ᴀ ᴍᴇᴅɪᴀ ᴛᴏ ᴜᴘʟᴏᴀᴅ"
        )

    media = message.reply_to_message
    file_size = 0
    if media.photo:
        file_size = media.photo.file_size
    elif media.video:
        file_size = media.video.file_size
    elif media.audio:
        file_size = media.audio.file_size
    elif media.document:
        file_size = media.document.file_size

    if file_size > 200 * 1024 * 1024:
        return await message.reply_text("Pʟᴇᴀsᴇ pʀᴏᴠɪᴅᴇ ᴀ ᴍᴇᴅɪᴀ ғɪʟᴇ uɴᴅᴇʀ 200MB.")

    text = await message.reply("Pʀᴏᴄᴇssɪɴɢ...")
    local_path = None

    try:
        async def progress(current, total):
            try:
                await text.edit_text(f"📥 Dᴏᴡɴʟᴏᴀᴅɪɴɢ... {current * 100 / total:.1f}%")
            except Exception:
                pass

        local_path = await media.download(progress=progress)
        await text.edit_text("📤 Uᴘʟᴏᴀᴅɪɴɢ...")

        success, upload_path = upload_file(local_path)

        if success:
            await text.edit_text(
                f"⛩️ | [༄𝐿 2 𝙍.🖤🜲𝐊𝐈𝐍𝐆❦︎ 𝆺𝅥⃝🍷]({upload_path})",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "💌ʙω͠ғ™ ɪᴍᴀɢᴇs🦋",
                                url=upload_path,
                            )
                        ]
                    ]
                ),
            )
        else:
            await text.edit_text(
                f"ᴀɴ eʀʀᴏʀ oᴄᴄᴜʀʀᴇᴅ wʜɪʟᴇ uᴘʟᴏᴀᴅɪɴɢ ʏᴏᴜʀ fɪʟᴇ\n{upload_path}"
            )

    except Exception as e:
        await text.edit_text(f"❌ Fɪʟᴇ uᴘʟᴏᴀᴅ fᴀɪʟᴇᴅ\n\n<i>Rᴇᴀsᴏɴ: {e}</i>")
    
    finally:
        if local_path and os.path.exists(local_path):
            try:
                os.remove(local_path)
            except Exception:
                pass
