import asyncio
from pyrogram import Client, errors
from pyrogram.enums import ChatMemberStatus, ParseMode

import config

from ..logging import LOGGER


class Ashish(Client):
    def __init__(self):
        LOGGER(__name__).info("Starting Bot...")
        super().__init__(
            name="L2RMUSIC",
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            bot_token=config.BOT_TOKEN,
            in_memory=True,
            parse_mode=ParseMode.HTML,
            max_concurrent_transmissions=7,
        )

    async def start(self):
        LOGGER(__name__).info("Attempting to connect to Telegram...")

        # ----- Login with retry on FloodWait -----
        while True:
            try:
                await super().start()
                break  # success
            except errors.FloodWait as e:
                wait_time = e.value
                LOGGER(__name__).warning(
                    f"⚠️ Telegram FloodWait during login. Waiting {wait_time}s..."
                )
                await asyncio.sleep(wait_time)
            except (ValueError, errors.AuthKeyUnregistered, errors.BotMethodInvalid, errors.BadRequest) as ex:
                LOGGER(__name__).error(
                    f"❌ Fatal Login Error! Check BOT_TOKEN, API_ID, API_HASH.\n  Reason: {type(ex).__name__} - {ex}"
                )
                exit(1)
            except Exception as ex:
                LOGGER(__name__).error(f"Unexpected login error: {type(ex).__name__} - {ex}")
                exit(1)

        # ----- Set bot identity -----
        self.id = self.me.id
        self.name = self.me.first_name + (" " + self.me.last_name if self.me.last_name else "")
        self.username = self.me.username
        self.mention = self.me.mention

        # ----- Normalize LOGGER_ID (handle missing -100) -----
        logger_id = getattr(config, "LOGGER_ID", None)
        if logger_id is None:
            LOGGER(__name__).error("❌ LOGGER_ID is not set in config.")
            exit(1)

        # Convert to int if it's a string
        if isinstance(logger_id, str):
            try:
                logger_id = int(logger_id)
            except ValueError:
                LOGGER(__name__).error("❌ LOGGER_ID must be an integer.")
                exit(1)

        # Store normalized ID
        self.logger_id = await self._normalize_chat_id(logger_id)
        if self.logger_id is None:
            LOGGER(__name__).error("❌ Failed to resolve LOGGER_ID. Please check the ID.")
            exit(1)

        # ----- Send startup message (with retry on FloodWait) -----
        while True:
            try:
                await self.send_message(
                    chat_id=self.logger_id,
                    text=(
                        f"<u><b>» {self.mention} ʙᴏᴛ sᴛᴀʀᴛᴇᴅ :</b></u>\n\n"
                        f"ɪᴅ : <code>{self.id}</code>\n"
                        f"ɴᴀᴍᴇ : {self.name}\n"
                        f"ᴜsᴇʀɴᴀᴍᴇ : @{self.username}"
                    ),
                )
                break  # success
            except errors.FloodWait as e:
                wait_time = e.value
                LOGGER(__name__).warning(
                    f"⚠️ FloodWait while sending startup message. Waiting {wait_time}s..."
                )
                await asyncio.sleep(wait_time)
            except (errors.ChannelInvalid, errors.PeerIdInvalid) as ex:
                LOGGER(__name__).error(
                    "❌ Bot cannot access the log group/channel. "
                    "Make sure the bot is added to the group and has send permissions."
                )
                exit(1)
            except ValueError as ex:
                # This may happen if ID is still invalid (shouldn't after normalization, but just in case)
                LOGGER(__name__).error(
                    f"❌ Invalid chat ID: {self.logger_id}. Ensure it's a valid supergroup ID (negative with -100 prefix)."
                )
                exit(1)
            except Exception as ex:
                LOGGER(__name__).error(
                    f"❌ Failed to send startup message: {type(ex).__name__} - {ex}"
                )
                exit(1)

        # ----- Check admin status in log channel -----
        try:
            member = await self.get_chat_member(self.logger_id, self.id)
            if member.status != ChatMemberStatus.ADMINISTRATOR:
                LOGGER(__name__).error(
                    "❌ Bot is not an admin in the log group/channel. Please promote it."
                )
                exit(1)
        except Exception as ex:
            LOGGER(__name__).error(
                f"❌ Failed to check admin status: {type(ex).__name__} - {ex}"
            )
            exit(1)

        LOGGER(__name__).info(f"✅ Music Bot Started as {self.name}")

    async def stop(self):
        LOGGER(__name__).info("Stopping Bot...")
        await super().stop()

    # ----- Helper to normalize chat ID (handle missing -100) -----
    async def _normalize_chat_id(self, chat_id: int):
        """
        Tries to resolve the chat ID. If the provided ID is positive and fails
        with ValueError, it attempts to use the negative version (for supergroups).
        Returns the working ID or None if all attempts fail.
        """
        # First, try the ID as-is (works for users, groups, and supergroups with -100)
        try:
            # A simple test: get chat info to see if it's valid
            await self.get_chat(chat_id)
            return chat_id
        except ValueError:
            # If ValueError occurs, it might be a supergroup missing -100
            if chat_id > 0:
                negative_id = -chat_id  # This will be -100... for supergroups
                LOGGER(__name__).info(
                    f"🔁 Positive ID {chat_id} failed. Trying negative version: {negative_id}"
                )
                try:
                    await self.get_chat(negative_id)
                    return negative_id
                except Exception:
                    pass  # fall through
            # If still fails, try adding -100 explicitly (though -chat_id is the same for numbers > 0)
            # Actually, for a supergroup ID like 1002111675614, -1002111675614 is correct.
            # If that fails, it's truly invalid.
            LOGGER(__name__).error(f"❌ Invalid chat ID: {chat_id} (and negative variant also failed).")
            return None
        except Exception as e:
            # Some other error (e.g., permission denied) - we'll consider it invalid
            LOGGER(__name__).error(f"❌ Chat ID {chat_id} is not accessible: {type(e).__name__} - {e}")
            return None
