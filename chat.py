import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
from google import genai
from google.genai import types # Make sure types is imported for specific exceptions
import datetime
import pytz
import json
from collections import deque, defaultdict # Added for new features

# 設定 Google Gemini API 金鑰，並建立 SDK 用戶端
GEMINI_API_KEY = ""  # 請替換成你的 API Key
client_genai = genai.Client(api_key=GEMINI_API_KEY)

# 請替換為實際的開發者 
OWNER_ID = 1142777874760351785

flag = {""}
how_cogs_use = {
    ""
}

# 將 how_cogs_use 轉換為字串
how_cogs_use_str = "\n".join([f"{key}: {value}" for key, value in how_cogs_use.items()])

# 系統提示：針對開發者的版本
SPECIAL_ROLE_PROMPT_DEV = (
    
)

# 系統提示：針對非開發者的版本
SPECIAL_ROLE_PROMPT_NONDEV = (
 )

# 早安與晚安問候訊息範本
MORNING_GREETING = 
EVENING_GREETING = 

# --- 新增功能區塊：使用者記憶管理 ---
USER_MEMORY_FILE = "user_memories.json"
MAX_USER_HISTORY_MESSAGES_STORED = 50  # Max messages stored per user in JSON
MAX_USER_HISTORY_FOR_PROMPT = 5   # Max user messages to include in prompt
MAX_CHANNEL_CONTEXT_MESSAGES = 15 # Max channel messages for short-term context

class UserMemoryManager:
    def __init__(self):
        self.user_memories = self._load_memories()

    def _load_memories(self):
        try:
            with open(USER_MEMORY_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    return defaultdict(list)
                # Ensure data is in the expected format (str_user_id: list_of_messages)
                return defaultdict(list, {
                    str(k): [dict(msg) for msg in v if isinstance(msg, dict)]
                    for k, v in data.items() if isinstance(v, list)
                })
        except (FileNotFoundError, json.JSONDecodeError):
            return defaultdict(list)

    def _save_memories(self):
        try:
            with open(USER_MEMORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.user_memories, f, ensure_ascii=False, indent=4)
        except IOError as e:
            print(f"Error saving user memories: {e}")

    def add_message(self, user_id: int, content: str, location_info: dict):
        user_id_str = str(user_id)
        
        message_entry = {
            "timestamp": datetime.datetime.now(pytz.utc).isoformat(),
            "content": content,
            "location": location_info
        }
        
        if user_id_str not in self.user_memories:
            self.user_memories[user_id_str] = []
            
        self.user_memories[user_id_str].append(message_entry)
        self.user_memories[user_id_str] = self.user_memories[user_id_str][-MAX_USER_HISTORY_MESSAGES_STORED:]
        self._save_memories()

    def get_user_history(self, user_id: int, max_messages: int = MAX_USER_HISTORY_FOR_PROMPT) -> list:
        user_id_str = str(user_id)
        return self.user_memories.get(user_id_str, [])[-max_messages:]

    def clear_user_memory(self, user_id: int) -> bool:
        user_id_str = str(user_id)
        if user_id_str in self.user_memories:
            del self.user_memories[user_id_str]
            self._save_memories()
            return True
        return False
# --- 結束使用者記憶管理功能區塊 ---

class GeminiChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.active_channels = {}
        self.chat_sessions = {}
        self.greeting_status = {"morning": False, "evening": False}
        self.timezone = pytz.timezone('Asia/Taipei')
        self.creator_dm_channel = None
        
        # 新增：初始化使用者記憶管理器和頻道上下文儲存
        self.user_memory_manager = UserMemoryManager()
        self.channel_contexts = defaultdict(lambda: deque(maxlen=MAX_CHANNEL_CONTEXT_MESSAGES))
        
        self.greeting_task.start()

    def cog_unload(self):
        self.greeting_task.cancel()

    @tasks.loop(minutes=5)
    async def greeting_task(self):
        await self.bot.wait_until_ready()
        now = datetime.datetime.now(self.timezone)
        current_hour = now.hour
        
        if self.creator_dm_channel is None:
            try:
                creator = await self.bot.fetch_user(OWNER_ID)
                if creator:
                    self.creator_dm_channel = await creator.create_dm()
            except Exception as e:
                print(f"無法獲取創造者的私人聊天頻道: {e}")
                return
        
        if 7 <= current_hour < 8 and not self.greeting_status["morning"]:
            await self._send_greeting("morning")
        elif 22 <= current_hour < 23 and not self.greeting_status["evening"]:
            await self._send_greeting("evening")
        elif current_hour == 0:
            self.greeting_status = {"morning": False, "evening": False}

    async def _send_greeting(self, greeting_type):
        if not self.creator_dm_channel:
            return
        try:
            greeting_message = MORNING_GREETING if greeting_type == "morning" else EVENING_GREETING
            await self.creator_dm_channel.send(greeting_message)
            self.greeting_status[greeting_type] = True
            
            
            session_key = (self.creator_dm_channel.id, OWNER_ID)
            if session_key not in self.chat_sessions:
                chat = client_genai.chats.create(model='gemini-2.0-flash-lite') # Original model for greeting
                await asyncio.to_thread(chat.send_message, message=SPECIAL_ROLE_PROMPT_DEV)
                self.chat_sessions[session_key] = chat
            else:
                chat = self.chat_sessions[session_key]
            
            await asyncio.to_thread(chat.send_message, message=f"{greeting_type}問候已發送: {greeting_message}")
            print(f"已向創造者發送{greeting_type}問候")
        except Exception as e:
            print(f"發送問候訊息時發生錯誤: {e}")

    @app_commands.command(name="聊天", description="開始聊天")
    async def start_chat(self, interaction: discord.Interaction):
        if not interaction.channel:
            await interaction.response.send_message("無法取得頻道資訊！", ephemeral=True)
            return
        channel_id = interaction.channel.id
        if self.active_channels.get(channel_id, False):
            await interaction.response.send_message("我們不是已經在聊了嘛！", ephemeral=True)
        else:
            self.active_channels[channel_id] = True
            await interaction.response.send_message("好啊，聊天聊天！", ephemeral=True)

    @app_commands.command(name="聊天關閉", description="關閉 AI 聊天模式（不清除對話記憶）")
    async def end_chat(self, interaction: discord.Interaction):
        if not interaction.channel:
            await interaction.response.send_message("無法取得頻道資訊！", ephemeral=True)
            return
        channel_id = interaction.channel.id
        if self.active_channels.get(channel_id, False):
            self.active_channels[channel_id] = False
            await interaction.response.send_message("聊天模式已關閉，但對話記憶已保留，下次再聊時將接續之前的對話。", ephemeral=True)
        else:
            await interaction.response.send_message("目前沒有聊天進行中。", ephemeral=True)

    @app_commands.command(name="重置記憶", description="清除你在此頻道的對話記憶及長期記憶")
    async def reset_memory(self, interaction: discord.Interaction):
        if not interaction.channel:
            await interaction.response.send_message("無法取得頻道資訊！", ephemeral=True)
            return
        
        user_id = interaction.user.id
        channel_id = interaction.channel.id
        key = (channel_id, user_id)
        
        gemini_session_cleared = False
        if key in self.chat_sessions:
            del self.chat_sessions[key]
            gemini_session_cleared = True
        
        persistent_memory_cleared = self.user_memory_manager.clear_user_memory(user_id)

        response_messages = []
        if gemini_session_cleared:
            response_messages.append("你在這個頻道的 AI 對話階段記憶已重置。")
        if persistent_memory_cleared:
            response_messages.append("你的長期使用者記憶已重置。")
        
        if not response_messages:
            await interaction.response.send_message("目前無對話記憶需要重置。", ephemeral=True)
        else:
            await interaction.response.send_message("\n".join(response_messages), ephemeral=True)

    @app_commands.command(name="noremember", description="清除指定對象的 AI 對話記憶及長期記憶 (僅限擁有者使用)")
    async def noremember(self, interaction: discord.Interaction, target: str):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("你沒有權限使用此命令。", ephemeral=True)
            return
        try:
            target_id = int(target)
        except ValueError:
            await interaction.response.send_message("無效的使用者 ID。", ephemeral=True)
            return

        keys_to_delete = [key for key in self.chat_sessions if key[1] == target_id]
        gemini_sessions_cleared_count = 0
        if keys_to_delete:
            for key_to_del in keys_to_delete:
                if key_to_del in self.chat_sessions: # Check again before deleting
                    del self.chat_sessions[key_to_del]
                    gemini_sessions_cleared_count +=1
        
        persistent_memory_cleared = self.user_memory_manager.clear_user_memory(target_id)
        
        response_messages = []
        if gemini_sessions_cleared_count > 0:
            response_messages.append(f"已清除 ID 為 {target_id} 的 {gemini_sessions_cleared_count} 個 AI 對話階段記憶。")
        if persistent_memory_cleared:
            response_messages.append(f"已清除 ID 為 {target_id} 的長期使用者記憶。")

        if not response_messages:
            await interaction.response.send_message(f"找不到 ID 為 {target_id} 的使用者對話記憶。", ephemeral=True)
        else:
            await interaction.response.send_message("\n".join(response_messages), ephemeral=True)

    @app_commands.command(name="手動問候", description="手動發送問候給創造者 (僅限擁有者使用)")
    async def manual_greeting(self, interaction: discord.Interaction, greeting_type: str = "morning"):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("你沒有權限使用此命令。", ephemeral=True)
            return
        
        greeting_type = greeting_type.lower()
        if greeting_type not in ["morning", "evening"]:
            await interaction.response.send_message("問候類型必須是 'morning' 或 'evening'。", ephemeral=True)
            return # Changed default handling to an error message
        
        await self._send_greeting(greeting_type)
        await interaction.response.send_message(f"已手動發送{greeting_type}問候。", ephemeral=True)

    async def query_gemini(self, message_text: str, user_id: int, channel_id: int, display_name: str,
                           long_term_user_history: list = None,
                           channel_context: list = None) -> dict:
        key = (channel_id, user_id)
        
        # Construct the full message to send to Gemini, including context
        context_parts = []
        if long_term_user_history:
            context_parts.append(f"--- 以下是你與使用者 {display_name} (ID: {user_id}) 的部分長期對話歷史 (越接近的越新) ---")
            for entry in reversed(long_term_user_history):
                loc_desc = ""
                location = entry.get('location', {})
                if location.get('type') == 'server':
                    loc_desc = f"在伺服器 '{location.get('guild_name', '未知伺服器')}' 的頻道 '{location.get('channel_name', '未知頻道')}'"
                elif location.get('type') == 'dm':
                    loc_desc = "在私訊中"
                context_parts.append(f"[{entry.get('timestamp', '未知時間')}] {loc_desc} {display_name} 說: {entry.get('content', '')}")
            context_parts.append("--- 長期對話歷史結束 ---")

        if channel_context:
            context_parts.append(f"--- 以下是目前頻道 '{display_name}' (ID: {channel_id}) 的近期對話上下文 (越接近的越新) ---")
            for entry in reversed(channel_context):
                context_parts.append(f"[{entry.get('timestamp', '未知時間')}] {entry.get('user_name', '未知用戶')} (ID: {entry.get('user_id', '未知ID')}) 說: {entry.get('content', '')}")
            context_parts.append("--- 頻道上下文結束 ---")

        # Prepare the user's current message part
        if user_id != OWNER_ID:
            current_user_message_segment = f"[使用者 {display_name} (ID: {user_id}) 現在說]: {message_text}"
        else:
            current_user_message_segment = f"[創造者大人 {display_name} 說]: {message_text}"

        # Combine all parts for the Gemini prompt
        full_prompt_for_gemini = "\n\n".join(context_parts) + "\n\n" + current_user_message_segment if context_parts else current_user_message_segment
        
        if key not in self.chat_sessions:
            chat = client_genai.chats.create(model='gemini-2.0-flash') # As per original query_gemini
            system_prompt = SPECIAL_ROLE_PROMPT_DEV if user_id == OWNER_ID else SPECIAL_ROLE_PROMPT_NONDEV
            try:
                await asyncio.to_thread(chat.send_message, message=system_prompt)
            except Exception as e:
                print(f"Error sending system prompt to Gemini: {e}")
                return {"error": f"無法初始化 AI 對話: {e}"}
            self.chat_sessions[key] = chat
        else:
            chat = self.chat_sessions[key]
            
        try:
            response = await asyncio.to_thread(chat.send_message, message=full_prompt_for_gemini)
            return {"content": response.text}
        except types.StopCandidateException as e:
            print(f"Google Generative AI content blocked: {e}")
            return {"error": "抱歉，我的回應內容似乎觸犯了某些規定，無法顯示。"}
        except types.BrokenResponseError as e: # Handle broken response
            print(f"Google Generative AI broken response: {e}")
            if key in self.chat_sessions: del self.chat_sessions[key] # Attempt to clear broken session
            return {"error": "AI 回應時發生內部錯誤，請清除記憶並重試。"}
        except Exception as e:
            print(f"呼叫 Google Generative AI 發生例外: {e}")
            return {"error": "呼叫 AI 時發生錯誤，請再試一次。"}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.content.startswith('/'):
            return

        try:
            with open("blacklist.json", "r", encoding="utf-8") as f:
                data = json.load(f)
            if str(message.author.id) in data.get("blacklisted_users", {}):
                return
        except (FileNotFoundError, json.JSONDecodeError):
            pass # File not found or invalid, proceed as if no blacklist

        if not self.active_channels.get(message.channel.id, False):
            return

        # --- 新增：地點偵測與記憶儲存 ---
        location_info = {}
        if message.guild:
            location_info = {
                "type": "server",
                "guild_id": str(message.guild.id),
                "guild_name": message.guild.name,
                "channel_id": str(message.channel.id),
                "channel_name": message.channel.name
            }
        else: # DM
            location_info = {
                "type": "dm",
                "channel_id": str(message.channel.id)
            }

        # Prepare content for memory and Gemini (stripping, adding image URLs)
        user_input_content = message.content.strip()
        image_urls_text = ""
        if message.attachments:
            image_urls = [
                att.url for att in message.attachments
                if att.content_type and att.content_type.startswith("image")
            ]
            if image_urls:
                image_urls_text = "\n[附帶圖片: " + ", ".join(image_urls) + "]"
        
        # Content for storing in memory (includes image URLs as text)
        content_for_memory = user_input_content + image_urls_text if image_urls_text else user_input_content
        
        if not content_for_memory.strip(): # If message is empty after stripping and no images
            return

        # Store in persistent user memory
        self.user_memory_manager.add_message(message.author.id, content_for_memory, location_info)

        # Store in short-term channel context (if it's a server channel and not a DM)
        if message.guild:
            channel_context_entry = {
                "user_id": str(message.author.id),
                "user_name": message.author.display_name,
                "timestamp": message.created_at.isoformat(), # discord.Message.created_at is UTC
                "content": content_for_memory 
            }
            self.channel_contexts[message.channel.id].append(channel_context_entry)
        # --- 結束地點偵測與記憶儲存 ---

        # Content for Gemini query (original message.content + image URLs if any)
        user_input_for_gemini = message.content.strip() + image_urls_text

        if not user_input_for_gemini.strip(): # Double check if anything to send to AI
            return

        async with message.channel.typing():
            try:
                # Retrieve relevant histories for the query
                long_term_hist = self.user_memory_manager.get_user_history(message.author.id)
                
                current_chan_context_list = []
                if message.guild: # Only get channel context for guild channels
                    current_chan_context_list = list(self.channel_contexts.get(message.channel.id, []))

                result = await asyncio.wait_for(
                    self.query_gemini(
                        user_input_for_gemini, # This is the user's current direct message
                        message.author.id,
                        message.channel.id,
                        message.author.display_name,
                        long_term_user_history=long_term_hist,
                        channel_context=current_chan_context_list
                    ),
                    timeout=15.0 # Original timeout
                )
            except asyncio.TimeoutError:
                result = {"error": "回應超時"}
        
        if result.get("error"):
            reply = f"抱歉，處理你的訊息時發生錯誤：{result['error']}" # Provide more specific error
            await message.channel.send(reply)
        else:
            reply = result.get("content", "抱歉，沒有取得回覆。")
            if "\n\n" in reply:
                segments = reply.split("\n\n")
                for segment in segments:
                    if segment.strip():
                        await message.channel.send(segment)
                        await asyncio.sleep(0.5 + 0.5 * (len(segment) / 100))
            else:
                await message.channel.send(reply)
        
        # process_commands is usually not needed if only listening for non-command messages
        # but keeping it in case there's a subtle interaction not immediately obvious
        await self.bot.process_commands(message)

async def setup(bot: commands.Bot):
    await bot.add_cog(GeminiChatCog(bot))
