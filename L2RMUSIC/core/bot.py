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

        # ---------- LOGIN WITH RETRY ON FLOODWAIT ----------
        while True:
            try:
                await super().start()
                break
            except errors.FloodWait as e:
                wait_time = e.value
                LOGGER(__name__).warning(
                    f"⚠️ FloodWait during login. Waiting {wait_time}s..."
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

        # ---------- SET BOT IDENTITY ----------
        self.id = self.me.id
        self.name = self.me.first_name + (" " + self.me.last_name if self.me.last_name else "")
        self.username = self.me.username
        self.mention = self.me.mention

        # ---------- NORMALIZE LOGGER_ID ----------
        logger_id_raw = getattr(config, "LOGGER_ID", None)
        if logger_id_raw is None:
            LOGGER(__name__).error("❌ LOGGER_ID is not set in config.")
            exit(1)

        # Convert to int if string
        try:
            logger_id_raw = int(logger_id_raw)
        except (ValueError, TypeError):
            LOGGER(__name__).error(f"❌ LOGGER_ID must be an integer, got {logger_id_raw}")
            exit(1)

        # Try to resolve the correct chat ID
        resolved_id = await self._resolve_chat_id(logger_id_raw)
        if resolved_id is None:
            LOGGER(__name__).error(
                f"❌ Could not resolve LOGGER_ID: {logger_id_raw}. "
                "Make sure the bot is added to the group/channel and the ID is correct."
            )
            exit(1)

        self.logger_id = resolved_id
        LOGGER(__name__).info(f"✅ Log channel resolved to: {self.logger_id}")

        # ---------- SEND STARTUP MESSAGE (WITH RETRY) ----------
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
                LOGGER(__name__).info("✅ Startup message sent successfully.")
                break
            except errors.FloodWait as e:
                wait_time = e.value
                LOGGER(__name__).warning(
                    f"⚠️ FloodWait while sending startup message. Waiting {wait_time}s..."
                )
                await asyncio.sleep(wait_time)
            except (errors.ChannelInvalid, errors.PeerIdInvalid) as ex:
                LOGGER(__name__).error(
                    "❌ Bot cannot access the log group/channel. "
                    "Ensure the bot is added and has permission to send messages."
                )
                exit(1)
            except ValueError as ex:
                # This should not happen after resolution, but just in case
                LOGGER(__name__).error(
                    f"❌ Invalid chat ID after resolution: {self.logger_id} - {ex}"
                )
                exit(1)
            except Exception as ex:
                LOGGER(__name__).error(
                    f"❌ Failed to send startup message: {type(ex).__name__} - {ex}"
                )
                exit(1)

        # ---------- CHECK ADMIN STATUS ----------
        try:
            member = await self.get_chat_member(self.logger_id, self.id)
            if member.status != ChatMemberStatus.ADMINISTRATOR:
                LOGGER(__name__).error(
                    "❌ Bot is not an admin in the log group/channel. Please promote it."
                )
                exit(1)
            LOGGER(__name__).info("✅ Bot is admin in log channel.")
        except Exception as ex:
            LOGGER(__name__).error(
                f"❌ Failed to check admin status: {type(ex).__name__} - {ex}"
            )
            exit(1)

        LOGGER(__name__).info(f"✅ Music Bot Started as {self.name}")

    async def stop(self):
        LOGGER(__name__).info("Stopping Bot...")
        await super().stop()

    # ---------- HELPER TO RESOLVE CHAT ID ----------
    async def _resolve_chat_id(self, chat_id: int):
        """
        Tries to validate the chat ID. If the ID is positive and fails,
        it automatically tries the negative version (for supergroups).
        Returns the working ID or None if both fail.
        """
        # First, try the ID as given
        try:
            await self.get_chat(chat_id)
            return chat_id  # valid
        except ValueError:
            # If ValueError (invalid peer), try negative variant for supergroups
            if chat_id > 0:
                negative_id = -chat_id
                LOGGER(__name__).info(
                    f"🔁 Positive ID {chat_id} failed. Trying negative: {negative_id}"
                )
                try:
                    await self.get_chat(negative_id)
                    return negative_id
                except Exception:
                    pass  # fall through
            # If we reach here, both failed
            LOGGER(__name__).error(f"❌ Both {chat_id} and negative variant are invalid.")
            return None
        except Exception as e:
            # Some other error (permission, network, etc.)
            LOGGER(__name__).error(
                f"❌ Error accessing chat {chat_id}: {type(e).__name__} - {e}"
            )
            return None
