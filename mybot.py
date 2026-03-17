import discord
from discord.ext import commands
import asyncio
import re
import os   # ← NEW LINE

# ────────────────────────────────────────────────
TOKEN = os.getenv("TOKEN")   # ← Railway will give this
OWNER_ID = 1023959373204176927
# ────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# This will hold the channel you selected
bot.selected_channel = None

# Timer task for auto-disconnect
bot.inactivity_task = None

INACTIVITY_WARNING_MINUTES = 10
INACTIVITY_FINAL_WAIT_SECONDS = 60

# ──── Helper: Clean channel name for matching ─────
def clean_channel_name(name: str) -> str:
    cleaned = re.sub(r'^[\s›│→\-\|\#🎮🗣️📢🔊📌🔞🔥⚡⭐]+', '', name.strip())
    cleaned = re.sub(r'[\s›│→\-\|\#]+', ' ', cleaned).strip().lower()
    return cleaned

async def resolve_mentions(guild, text):
    words = text.split()
    new_words = []

    for word in words:
        if word.startswith('@'):
            name = word[1:].lower()

            if name in ['everyone', 'here']:
                new_words.append(f'@{name}')
                continue

            found_user = None
            for member in guild.members:
                if member.name.lower() == name or member.display_name.lower() == name:
                    found_user = member
                    break

            if found_user:
                new_words.append(found_user.mention)
                continue

            found_role = None
            for role in guild.roles:
                if role.name.lower() == name:
                    found_role = role
                    break

            if found_role:
                new_words.append(found_role.mention)
                continue

        new_words.append(word)

    return ' '.join(new_words)

async def start_inactivity_timer():
    if bot.inactivity_task:
        bot.inactivity_task.cancel()

    async def timer():
        try:
            await asyncio.sleep(INACTIVITY_WARNING_MINUTES * 60)
            owner = bot.get_user(OWNER_ID)
            if owner and bot.selected_channel:
                await owner.send(
                    f"⚠️ No activity from you for {INACTIVITY_WARNING_MINUTES} minutes.\n"
                    f"Auto-disconnecting in {INACTIVITY_FINAL_WAIT_SECONDS} seconds..."
                )

            await asyncio.sleep(INACTIVITY_FINAL_WAIT_SECONDS)

            if bot.selected_channel:
                old_channel_name = bot.selected_channel.name
                bot.selected_channel = None
                if owner:
                    await owner.send(
                        f"🛑 Auto-disconnected from #{old_channel_name} due to inactivity."
                    )
        except asyncio.CancelledError:
            pass

    bot.inactivity_task = asyncio.create_task(timer())

@bot.event
async def on_ready():
    print(f"🚀 Bot is awake and ready for remote control!")
    print(f"Logged in as {bot.user}")
    bot.selected_channel = None
    bot.inactivity_task = None

@bot.event
async def on_message(message):
    await bot.process_commands(message)

    if message.author.bot:
        return

    # Reset inactivity timer on ANY message from owner in DM
    if isinstance(message.channel, discord.DMChannel) and message.author.id == OWNER_ID:
        if bot.selected_channel:
            await start_inactivity_timer()

    # ====================== DM CONTROL (only you) ======================
    if isinstance(message.channel, discord.DMChannel) and message.author.id == OWNER_ID:
        content = message.content.strip()
        lower = content.lower()

        # Reply to message via link (unchanged from previous)
        if re.match(r'^https?://discord\.com/channels/\d+/\d+/\d+$', content):
            try:
                parts = content.split('/')
                if len(parts) < 6:
                    await message.channel.send("Invalid message link format.")
                    return

                guild_id = int(parts[-3])
                channel_id = int(parts[-2])
                msg_id = int(parts[-1])

                guild = bot.get_guild(guild_id)
                if not guild:
                    await message.channel.send("Bot not in that server / can't access guild.")
                    return

                channel = guild.get_channel(channel_id)
                if not channel or not isinstance(channel, discord.TextChannel):
                    await message.channel.send("Invalid channel or not a text channel.")
                    return

                target_msg = await channel.fetch_message(msg_id)
                if not target_msg:
                    await message.channel.send("Couldn't find that message (maybe deleted or no access).")
                    return

                await message.channel.send(
                    f"Found message by {target_msg.author.display_name}: {target_msg.content[:100]}...\n"
                    f"Reply with what you want to say (next message will be sent as reply to it)."
                )

                def check(reply):
                    return reply.author.id == OWNER_ID and reply.channel.id == message.channel.id

                reply_msg = await bot.wait_for('message', check=check, timeout=120.0)

                resolved_reply = await resolve_mentions(guild, reply_msg.content)
                sent_reply = await target_msg.reply(resolved_reply)

                await message.channel.send(f"✅ Replied: {sent_reply.jump_url}")
            except asyncio.TimeoutError:
                await message.channel.send("No reply received in 2 minutes. Cancelled.")
            except discord.NotFound:
                await message.channel.send("Message not found (deleted or inaccessible).")
            except discord.Forbidden:
                await message.channel.send("Bot lacks permission to read/send in that channel.")
            except Exception as e:
                await message.channel.send(f"Error: {str(e)}")
            return

        # SELECT channel (unchanged)
        if lower.startswith("select "):
            query = lower[7:].strip()
            if not query:
                await message.channel.send("Please provide a channel name after `select`.")
                return

            matches = []
            for guild in bot.guilds:
                for ch in guild.text_channels:
                    clean_name = clean_channel_name(ch.name)
                    if query in clean_name:
                        matches.append(ch)

            if not matches:
                await message.channel.send(f"No channels found matching '{query}' 😔")
                return

            if len(matches) == 1:
                bot.selected_channel = matches[0]
                await message.channel.send(f"✅ **#{matches[0].name}** selected automatically!\n"
                                           f"Now just type anything (text + images/GIFs) — I will send it automatically.\n"
                                           f"Type `stop` to quit.")
                await start_inactivity_timer()
                return

            # Multiple matches disambiguation (unchanged)
            by_category = {}
            for ch in matches:
                cat_name = ch.category.name if ch.category else "No Category"
                if cat_name not in by_category:
                    by_category[cat_name] = []
                by_category[cat_name].append(ch)

            response = "Multiple channels match. Please reply with the number:\n\n"

            if len(by_category) > 1:
                num = 1
                for cat, chans in by_category.items():
                    response += f"**{cat}**\n"
                    for ch in chans:
                        response += f"{num}. #{ch.name}\n"
                        num += 1
            else:
                chans = matches
                num = 1
                for ch in chans:
                    response += f"{num}. #{ch.name} → {ch.jump_url}\n"
                    num += 1

            response += "\nReply with just the number (e.g. `1` or `2`) to select."

            await message.channel.send(response)

            def check(m):
                return (m.author.id == OWNER_ID and
                        m.channel.id == message.channel.id and
                        m.content.strip().isdigit())

            try:
                reply = await bot.wait_for('message', check=check, timeout=60.0)
                choice = int(reply.content.strip()) - 1

                if 0 <= choice < len(matches):
                    bot.selected_channel = matches[choice]
                    await message.channel.send(f"✅ **#{bot.selected_channel.name}** selected!\n"
                                               f"Now just type anything (text + images/GIFs) — I will send it automatically.\n"
                                               f"Type `stop` to quit.")
                    await start_inactivity_timer()
                else:
                    await message.channel.send("Invalid number. Selection cancelled.")
            except asyncio.TimeoutError:
                await message.channel.send("No reply received. Selection cancelled.")
            except:
                await message.channel.send("Something went wrong. Selection cancelled.")
            return

        # STOP / DESELECT (unchanged)
        elif lower in ["stop", "deselect", "quit", "exit"]:
            if bot.selected_channel:
                await message.channel.send(f"🛑 Mode stopped. #{bot.selected_channel.name} deselected.")
                bot.selected_channel = None
                if bot.inactivity_task:
                    bot.inactivity_task.cancel()
                    bot.inactivity_task = None
            else:
                await message.channel.send("Nothing to stop — no channel selected.")

        # HELP (updated with attachments note)
        elif lower == "help":
            await message.channel.send(
                "**Remote Control Mode Commands:**\n"
                "`select name` → start auto mode (fuzzy match, handles ›│ etc.)\n"
                "`stop` / `deselect` → stop auto mode\n"
                "`status` → show info\n"
                "`shutdown` → turn bot off\n"
                "Paste a message link[](https://discord.com/channels/...) → reply to that message\n\n"
                "Attachments: send images/GIFs/files in DM → bot forwards to selected channel\n"
                "Incoming attachments from channel → shown with URLs in your DM\n"
                f"Auto-disconnect after {INACTIVITY_WARNING_MINUTES} min no messages\n"
                "Mentions: type @username, @role or @everyone — bot converts them"
            )

        # STATUS (unchanged)
        elif lower == "status":
            ch = bot.selected_channel.name if bot.selected_channel else "None"
            await message.channel.send(f"Status: Online\nSelected channel: #{ch}\nOwner: You! ❤️")

        # SHUTDOWN (unchanged)
        elif lower == "shutdown":
            await message.channel.send("Shutting down... Bye! 👋")
            bot.selected_channel = None
            if bot.inactivity_task:
                bot.inactivity_task.cancel()
            await bot.close()

                # AUTO FORWARD (text + attachments from DM → channel)
        elif bot.selected_channel:
            try:
                resolved_content = await resolve_mentions(bot.selected_channel.guild, content) if content else None

                files = []
                for att in message.attachments:
                    # Use proxy_url to avoid full download + encoding issues
                    # This tells Discord to proxy the file from your upload
                    file_obj = await att.to_file(spoiler=att.is_spoiler())
                    files.append(file_obj)

                if resolved_content or files:
                    await bot.selected_channel.send(
                        content=resolved_content,
                        files=files if files else None
                    )
                    # Optional feedback
                    # await message.channel.send(f"✅ Sent ({len(files)} attachment(s))")
                else:
                    await message.channel.send("Nothing to send (empty + no attachments).")
            except discord.HTTPException as e:
                await message.channel.send(f"Send failed (size limit? rate limit?): {str(e)}")
            except Exception as e:
                await message.channel.send(f"Unexpected error: {str(e)}")

        # Nothing selected + random text
        else:
            await message.channel.send("No channel selected yet!\n"
                                       "Type `select channelname` to start.\n"
                                       "Paste a message link to reply to old messages.\n"
                                       "Type `help` for all commands.")

    # ====================== MIRROR MESSAGES FROM SELECTED CHANNEL ======================
    if (bot.selected_channel and 
        message.channel.id == bot.selected_channel.id and 
        message.author != bot.user):

        author_str = message.author.display_name
        text = message.content or "(no text)"

        if (message.reference and 
            message.reference.resolved and 
            message.reference.resolved.author == bot.user):
            prefix = f"{author_str} replied: "
        elif bot.user in message.mentions:
            prefix = f"{author_str} mentioned: "
        else:
            prefix = f"{author_str}: "

        mirror_text = prefix + text

        # Add attachments info (URLs so you can click/view them)
        if message.attachments:
            att_lines = []
            for att in message.attachments:
                if att.content_type and 'image' in att.content_type:
                    att_lines.append(f"Image/GIF: {att.url}")
                else:
                    att_lines.append(f"File: {att.filename} → {att.url}")
            mirror_text += "\n" + "\n".join(att_lines)

        owner_user = bot.get_user(OWNER_ID)
        if owner_user:
            try:
                await owner_user.send(mirror_text)
            except:
                pass  # silent fail if DM closed

@bot.command()
async def hello(ctx):
    await ctx.send("Hello from the remote-controlled bot! 😄")

bot.run(TOKEN)