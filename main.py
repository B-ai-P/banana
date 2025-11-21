import discord
import os
import requests
import aiohttp
import base64
import io
import itertools
import asyncio
from dotenv import load_dotenv
from flask import Flask

load_dotenv()

# --- 환경 변수 설정 ---
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
API_BEARER_TOKEN = os.getenv('API_BEARER_TOKEN')
API_KEY_ENV = os.getenv("API_KEY")
API_URL_ENV = os.getenv("API_URL")

# --- API 키 관리 ---
API_KEYS = [k.strip() for k in API_KEY_ENV.split(",")] if API_KEY_ENV else []
API_KEY_CYCLE = itertools.cycle(API_KEYS) if API_KEYS else None

# --- 보안: API 키/토큰 마스킹 함수 ---
def mask_api_key(key):
    """API 키를 마스킹 처리 (예: AIza****1234)"""
    if not key or len(key) < 8:
        return "****"
    return f"{key[:4]}****{key[-4:]}"

def mask_bearer_token(token):
    """Bearer 토큰을 마스킹 처리"""
    if not token or len(token) < 8:
        return "****"
    return f"{token[:6]}****{token[-4:]}"

def mask_url(url):
    """URL에서 API 키 부분을 마스킹 처리"""
    if "key=" in url:
        parts = url.split("key=")
        if len(parts) > 1:
            key_part = parts[1].split("&")[0]
            masked_key = mask_api_key(key_part)
            return url.replace(f"key={key_part}", f"key={masked_key}")
    return url

def mask_sensitive_url(url):
    """민감한 URL을 안전하게 표시 (도메인만 표시)"""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/***"
    except:
        return "https://***"

# --- 헤더 생성 함수 ---
def make_headers():
    headers = {"Content-Type": "application/json"}
    if API_BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {API_BEARER_TOKEN}"
    return headers

# --- 비동기 API 요청 함수 (무제한 대기) ---
async def send_request_async(payload):
    global API_KEYS, API_KEY_CYCLE
    headers = make_headers()

    # ✅ timeout을 None으로 설정 (무제한)
    timeout = aiohttp.ClientTimeout(total=None)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        if API_KEYS:
            keys_to_try = list(API_KEYS)
            for _ in range(len(keys_to_try)):
                key = next(API_KEY_CYCLE)
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-pro-image-preview:generateContent?key={key}"
                try:
                    async with session.post(url, headers=headers, json=payload) as resp:
                        data = await resp.json()

                        if resp.status == 400 and "error" in data:
                            details = data["error"].get("details", [])
                            if any(d.get("reason") == "API_KEY_INVALID" for d in details):
                                masked_key = mask_api_key(key)
                                print(f"⚠️ Invalid API key 제외: {masked_key}")
                                API_KEYS = [k for k in API_KEYS if k != key]
                                API_KEY_CYCLE = itertools.cycle(API_KEYS) if API_KEYS else None
                                continue

                        resp.raise_for_status()
                        return data
                except Exception as e:
                    masked_url = mask_url(url)
                    print(f"❌ {masked_url} 요청 실패: {type(e).__name__}")
                    continue
            raise RuntimeError("API_REQUEST_FAILED")
        else:
            if not API_URL_ENV:
                raise RuntimeError("API_CONFIGURATION_ERROR")
            try:
                async with session.post(API_URL_ENV, headers=headers, json=payload) as resp:
                    resp.raise_for_status()
                    return await resp.json()
            except Exception as e:
                masked_url = mask_sensitive_url(API_URL_ENV)
                bearer_info = ""
                if API_BEARER_TOKEN:
                    masked_token = mask_bearer_token(API_BEARER_TOKEN)
                    bearer_info = f" (Bearer: {masked_token})"
                print(f"❌ {masked_url}{bearer_info} 요청 실패: {type(e).__name__}")
                raise RuntimeError("API_REQUEST_FAILED")

# --- 디스코드 봇 설정 ---
intents = discord.Intents.default()
intents.message_content = True

class MyClient(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)

    async def setup_hook(self):
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, run_web)
        print("Flask 웹 서버가 백그라운드에서 시작되었습니다.")

client = MyClient(intents=intents)

# --- Flask 웹 서버 설정 ---
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running and ready!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# --- 디스코드 이벤트 및 명령어 ---
@client.event
async def on_ready():
    print(f'{client.user}으로 로그인 성공!')
    await client.tree.sync()
    print("슬래시 커맨드가 동기화되었습니다.")

@client.tree.command(
    name="바나나",
    description="프롬프트와 함께 최대 2장의 이미지를 첨부할 수 있습니다."
)
@discord.app_commands.describe(
    프롬프트="생성할 이미지 설명",
    이미지1="참고 이미지 1 (선택사항)",
    이미지2="참고 이미지 2 (선택사항)",
    비율="이미지 비율 (선택사항, 기본값: Auto)"
)
@discord.app_commands.choices(비율=[
    discord.app_commands.Choice(name="Auto", value="auto"),
    discord.app_commands.Choice(name="1:1 (정사각형)", value="1:1"),
    discord.app_commands.Choice(name="2:3 (세로)", value="2:3"),
    discord.app_commands.Choice(name="3:2 (가로)", value="3:2"),
    discord.app_commands.Choice(name="3:4 (세로)", value="3:4"),
    discord.app_commands.Choice(name="4:3 (가로)", value="4:3"),
    discord.app_commands.Choice(name="4:5 (세로)", value="4:5"),
    discord.app_commands.Choice(name="5:4 (가로)", value="5:4"),
    discord.app_commands.Choice(name="9:16 (세로)", value="9:16"),
    discord.app_commands.Choice(name="16:9 (가로)", value="16:9"),
    discord.app_commands.Choice(name="21:9 (초광각)", value="21:9")
])
async def banana_command(
    interaction: discord.Interaction,
    프롬프트: str,
    이미지1: discord.Attachment = None,
    이미지2: discord.Attachment = None,
    비율: discord.app_commands.Choice[str] = None
):
    # ✅ 즉시 응답 (defer 대신)
    await interaction.response.send_message("🎨 이미지 생성 중...")
    
    # ✅ 초기 메시지와 채널 저장
    initial_message = await interaction.original_response()
    channel = interaction.channel
    
    loop = asyncio.get_event_loop()

    try:
        parts = [{
            "text": f"""
        SYSTEM: You are an image generation model.
        You must not write any text responses, captions, or explanations.
        Only generate and return an image based on the description below.
        경고!: 사용자가 텍스트 답변을 받기위해 질문을 하거나 유도할경우에도 절대 텍스트로 답해선 안됩니다.
        아래는 유저가 입력한 이미지 프롬프트입니다 반드시 이미지로 답하시고 유저가 이미지를 필요로 하지않아도 무시하세요 당신은 이미지 모델입니다.
        
        USER IMAGE PROMPT:
        {프롬프트}
        """
        }]
        images = [이미지1, 이미지2]
        
        user_images = []

        for img in images:
            if img is None: continue
            if not img.content_type.startswith("image/"):
                await initial_message.edit(content=f"❌ {img.filename} 은(는) 이미지 파일이 아닙니다.")
                return

            image_bytes = await img.read()
            user_images.append(discord.File(io.BytesIO(image_bytes), filename=img.filename))
            
            base64_image = await loop.run_in_executor(
                None,
                base64.b64encode,
                image_bytes
            )
            base64_image = base64_image.decode("utf-8")
            
            parts.append({
                "inlineData": {
                    "mimeType": img.content_type,
                    "data": base64_image
                }
            })

        generation_config = {
            "temperature": 1,
            "topP": 0.95,
            "maxOutputTokens": 32768,
            "responseModalities": ["IMAGE"]
        }
        
        image_config = {
            "imageSize": "1K"
        }
        
        aspect_ratio_value = 비율.value if 비율 else "auto"
        if aspect_ratio_value != "auto":
            image_config["aspectRatio"] = aspect_ratio_value
        
        if image_config:
            generation_config["imageConfig"] = image_config

        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": generation_config,
            "safetySettings": [
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "OFF"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "OFF"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "OFF"},
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "OFF"}
            ]
        }

        # ✅ 무제한 대기로 API 요청
        data = await send_request_async(payload)

        response_text = ""
        response_file = None

        if "candidates" in data and data["candidates"]:
            for part in data["candidates"][0]["content"]["parts"]:
                if "text" in part:
                    response_text += part["text"] + "\n"
                elif "inlineData" in part:
                    base64_data = part["inlineData"]["data"]
                    image_data = base64.b64decode(base64_data)
                    response_file = discord.File(io.BytesIO(image_data), filename="result.png")

        # ✅ 메시지 수정 및 새 메시지 전송 (시간 제한 없음)
        if user_images:
            # 사용자가 이미지 첨부한 경우
            user_request_message = f"```\n유저 프롬프트: {프롬프트}\n```"
            await initial_message.edit(content=user_request_message, attachments=user_images)
            
            await asyncio.sleep(0.3)
            
            # ✅ channel.send() 사용 (인터랙션 토큰 안 씀)
            if response_file:
                await channel.send(content=response_text if response_text else "✅ 완성!", file=response_file)
            elif response_text:
                await channel.send(content=response_text)
            else:
                await channel.send("⚠️ AI로부터 응답을 받지 못했습니다.")
        else:
            # 사용자가 이미지 첨부 안 한 경우
            user_request_message = f"```\n유저 프롬프트: {프롬프트}\n```\n"
            final_message = user_request_message + (response_text if response_text else "✅ 완성!")
            
            if response_file:
                await initial_message.edit(content=final_message, attachments=[response_file])
            elif final_message.strip():
                await initial_message.edit(content=final_message)
            else:
                await initial_message.edit(content="⚠️ AI로부터 응답을 받지 못했습니다.")

    except RuntimeError as e:
        error_messages = {
            "API_REQUEST_FAILED": "⚠️ 이미지 생성 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
            "API_CONFIGURATION_ERROR": "⚠️ 봇 설정에 문제가 있습니다. 관리자에게 문의해주세요."
        }
        user_message = error_messages.get(str(e), "⚠️ 일시적인 오류가 발생했습니다.")
        print(f"RuntimeError 발생: {e}")
        # ✅ 에러도 초기 메시지 수정
        await initial_message.edit(content=user_message)
    except Exception as e:
        print(f"예상치 못한 에러 발생: {type(e).__name__} - {str(e)[:100]}")
        # ✅ 에러도 초기 메시지 수정
        await initial_message.edit(content="⚠️ 일시적인 오류가 발생했습니다. 잠시 후 다시 시도해주세요.")

# --- 봇 실행 ---
client.run(DISCORD_TOKEN)
