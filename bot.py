import disnake
from disnake.ext import commands
from disnake.ext.commands import has_permissions, CheckFailure
import os
import re
import time
import json
import random
from dotenv import load_dotenv

# Load biến môi trường từ .env
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Tạo bot với intents
intents = disnake.Intents.default()
intents.messages = True
intents.guilds = True
intents.members = True
intents.reactions = True  # Bật intents phản ứng

bot = commands.InteractionBot(intents=intents)

# Tạo một dictionary để lưu thời gian sử dụng lệnh của người dùng và số lần nhập sai
user_cooldowns = {}
user_wrong_attempts = {}

# Tạo các tệp cần thiết
DERANK_CHANNEL_FILE = 'derank_channel.json'
PARTYCODE_FILE = 'partycode.txt'
BLACKLIST_FILE = 'blacklist.txt'
SENT_MESSAGES_FILE = 'sent_messages.json'  # Tệp lưu tin nhắn đã gửi

# Đảm bảo tệp tồn tại
if not os.path.exists(PARTYCODE_FILE):
    open(PARTYCODE_FILE, 'w').close()

if not os.path.exists(BLACKLIST_FILE):
    open(BLACKLIST_FILE, 'w').close()

if not os.path.exists(SENT_MESSAGES_FILE):
    open(SENT_MESSAGES_FILE, 'w').close()  # Tạo tệp rỗng nếu chưa tồn tại

# Kiểm tra nếu user trong blacklist
def is_blacklisted(user_id):
    with open(BLACKLIST_FILE, 'r') as f:
        blacklisted_ids = f.read().splitlines()
    return str(user_id) in blacklisted_ids

# Thêm user vào blacklist
def add_to_blacklist(user_id):
    with open(BLACKLIST_FILE, 'a') as f:
        f.write(f'{user_id}\n')

# Đọc thông tin channel từ tệp JSON
def load_derank_channels():
    if os.path.exists(DERANK_CHANNEL_FILE):
        with open(DERANK_CHANNEL_FILE, 'r') as f:
            return json.load(f)
    return {}

# Ghi thông tin channel vào tệp JSON
def save_derank_channels(channels):
    with open(DERANK_CHANNEL_FILE, 'w') as f:
        json.dump(channels, f, indent=4)

# Tạo class View để chứa button
class PartyCodeView(disnake.ui.View):
    def __init__(self, author_id, party_code):
        super().__init__(timeout=None)  # Để view không bị timeout
        self.author_id = author_id
        self.party_code = party_code

    @disnake.ui.button(label="Hide Code & Full Slot", style=disnake.ButtonStyle.danger)
    async def hide_code(self, button: disnake.ui.Button, interaction: disnake.MessageInteraction):
        if interaction.author.id != self.author_id:
            await interaction.response.send_message("You are not authorized to use this button!", ephemeral=True)
            return

        # Để defer để tránh lỗi tương tác hết hạn
        await interaction.response.defer(ephemeral=True)

        if os.path.exists(SENT_MESSAGES_FILE):
            with open(SENT_MESSAGES_FILE, 'r') as f:
                sent_messages = json.load(f)
        else:
            await interaction.edit_original_response(content="No sent messages file found.")
            return  # Nếu tệp không tồn tại, dừng xử lý

        # Tìm tin nhắn đã phản ứng
        updated = False
        for msg in sent_messages:
            if msg['party_code'] == self.party_code:
                guild = bot.get_guild(int(msg['guild_id']))
                if guild:
                    channel = guild.get_channel(int(msg['channel_id']))
                    if channel:
                        try:
                            message = await channel.fetch_message(int(msg['message_id']))
                            if message.embeds:
                                embed = message.embeds[0]  # Lấy embed cũ
                                embed.set_field_at(0, name="> Party Code", value=f"> ||{self.party_code}||", inline=True)
                                embed.set_field_at(1, name="> Slot", value="> Full", inline=True)
                                await message.edit(embed=embed, view=None)  # Cập nhật tin nhắn và xóa button
                                updated = True
                        except disnake.NotFound:
                            print(f"Message with ID {msg['message_id']} not found.")
        
        # Xóa các tin nhắn đã cập nhật khỏi tệp JSON
        sent_messages = [msg for msg in sent_messages if msg['party_code'] != self.party_code]
        with open(SENT_MESSAGES_FILE, 'w') as f:
            json.dump(sent_messages, f, indent=4)

        if updated:
            await interaction.edit_original_response(content="The party code is now hidden and the slot is marked as full.")
        else:
            await interaction.edit_original_response(content="No messages found to update.")

from disnake.ext import commands
from disnake.ext.commands import has_permissions, CheckFailure

# Lệnh để thiết lập derank channel
@bot.slash_command(description="Set a channel where derank messages will be sent. Admin only.")
@has_permissions(administrator=True)
async def derank_channel(interaction: disnake.ApplicationCommandInteraction, channel: disnake.TextChannel):
    guild_id = str(interaction.guild.id)
    
    # Load dữ liệu từ tệp JSON
    derank_channels = load_derank_channels()

    # Chỉ lưu một channel duy nhất cho mỗi server
    derank_channels[guild_id] = channel.id

    # Lưu lại thông tin
    save_derank_channels(derank_channels)

    await interaction.response.send_message(f"Channel {channel.mention} has been set for derank messages!", ephemeral=True)

# Xử lý lỗi thiếu quyền
@derank_channel.error
async def derank_channel_error(interaction: disnake.ApplicationCommandInteraction, error):
    if isinstance(error, CheckFailure):
        await interaction.response.send_message("You do not have Administrator permissions to use this command.", ephemeral=True)

# Thêm biến user_cooldowns
user_cooldowns = {}

# Lệnh để gửi mã party và slot, chỉ dành cho role Deranker
@bot.slash_command(description="Send a party code to the derank channel.")
async def derank(interaction: disnake.ApplicationCommandInteraction, party_code: str, slot: str = None):
    user_id = interaction.author.id

    # Kiểm tra nếu user trong blacklist
    if is_blacklisted(user_id):
        await interaction.response.send_message("You are blacklisted from using this bot. If this was a mistake, please join https://discord.gg/sBp5nZMJWe for support.", ephemeral=True)
        return

    # Trì hoãn phản hồi
    await interaction.response.defer(ephemeral=True)

    current_time = time.time()
    # Kiểm tra nếu người dùng đã trong cooldown (2 phút)
    if user_id in user_cooldowns and current_time - user_cooldowns[user_id] < 120:
        await interaction.edit_original_response(content="You can only use this command every 2 minutes.")
        return

    # Cập nhật cooldown
    user_cooldowns[user_id] = current_time

    # Kiểm tra role Deranker
    deranker_role = disnake.utils.get(interaction.guild.roles, name="Deranker")
    if deranker_role not in interaction.author.roles:
        await interaction.edit_original_response(content="You don't have the Deranker role to use this command.")
        return

    # Kiểm tra độ dài và ký tự của party code (chỉ chấp nhận ký tự A-Z và 0-9, dài 6 ký tự)
    if not re.match(r'^[A-Z0-9]{6}$', party_code):
        if user_id not in user_wrong_attempts:
            user_wrong_attempts[user_id] = 0

        user_wrong_attempts[user_id] += 1

        if user_wrong_attempts[user_id] >= 3:
            add_to_blacklist(user_id)
            await interaction.edit_original_response(content="You have been blacklisted from using this bot due to multiple incorrect inputs.")
        else:
            attempts_remaining = 3 - user_wrong_attempts[user_id]
            await interaction.edit_original_response(content=f"Incorrect party code format! You have {attempts_remaining} attempts remaining before being blacklisted.")
        return

    # Kiểm tra slot chỉ chấp nhận 1 ký tự từ 1-9
    if slot is not None and not re.match(r'^[1-9]$', slot):
        await interaction.edit_original_response(content="Invalid slot! Slot must be a single character between 1 and 9.")
        return

    # Lưu party code vào tệp
    with open(PARTYCODE_FILE, 'a') as f:
        f.write(f'{user_id}: {party_code}\n')

    # Cập nhật cooldown
    user_cooldowns[user_id] = current_time

    # Nếu slot trống, đặt thành "slot không xác định"
    if slot is None:
        slot = "> Undetermined"
    else:
        slot = f"> {slot}"

    # Tạo màu ngẫu nhiên
    random_color = disnake.Color.from_rgb(random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))

    # Tạo embed để gửi thông báo
    embed = disnake.Embed(title="Derank Party Code", color=random_color)
    embed.add_field(name="> Party Code", value=f"> {party_code}", inline=True)  # Gửi mã không che
    embed.add_field(name="> Slot", value=slot, inline=True)

    # Thêm tên và avatar của server nơi người dùng sử dụng lệnh
    embed.add_field(name="Code sent from:", value=interaction.guild.name, inline=False)
    embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)

    # Thêm tên và avatar của người dùng
    embed.set_author(name=interaction.author.display_name, icon_url=interaction.author.avatar.url if interaction.author.avatar else None)

    # Lấy thông tin channel từ tệp JSON
    derank_channels = load_derank_channels()

    # Gửi tin nhắn đến tất cả các server có thiết lập derank channel
    sent_messages = []  # Lưu các tin nhắn đã gửi để có thể chỉnh sửa sau
    for guild_id, channel_id in derank_channels.items():
        guild = bot.get_guild(int(guild_id))
        if guild:
            # Tìm role Deranker cho từng guild
            deranker_role = disnake.utils.get(guild.roles, name="Deranker")
            if not deranker_role:
                continue  # Bỏ qua nếu không tìm thấy role

            channel = bot.get_channel(int(channel_id))
            if channel:
                view = PartyCodeView(author_id=user_id, party_code=party_code)  # Tạo view chứa button
                message = await channel.send(content=f"{deranker_role.mention}", embed=embed, view=view)
                sent_messages.append({
                    'guild_id': str(guild_id),
                    'channel_id': channel_id,
                    'message_id': message.id,
                    'party_code': party_code,
                    'slot': slot
                })

    # Lưu thông tin tin nhắn đã gửi
    with open(SENT_MESSAGES_FILE, 'w') as f:
        json.dump(sent_messages, f, indent=4)

    await interaction.edit_original_response(content="The party code has been sent to all derank channels.")

@bot.event
async def on_ready():
    print(f'We have logged in as {bot.user}')
    await bot.change_presence(activity=disnake.Game(name="VALORANT"))

# Chạy bot
bot.run(TOKEN)
