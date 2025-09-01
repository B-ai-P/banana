import discord
import os
import requests # 동기 함수는 유지하되, async 함수를 새로 만듭니다.
import aiohttp # 비동기 HTTP 요청을 위해 추가
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

# --- 헤더 생성 함수 ---
def make_headers():
    headers = {"Content-Type": "application/json"}
    if API_BEARER_TOKEN:
        headers["Authorization"] = f"Bearer {API_BEARER_TOKEN}"
    return headers

# --- 비동기 API 요청 함수 (새로 추가 및 수정) ---
async def send_request_async(payload):
    global API_KEYS, API_KEY_CYCLE
    headers = make_headers()

    async with aiohttp.ClientSession() as session:
        if API_KEYS:
            keys_to_try = list(API_KEYS)
            for _ in range(len(keys_to_try)):
                key = next(API_KEY_CYCLE)
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image-preview:generateContent?key={key}"
                try:
                    async with session.post(url, headers=headers, json=payload, timeout=30) as resp:
                        data = await resp.json()

                        if resp.status == 400 and "error" in data:
                            details = data["error"].get("details", [])
                            if any(d.get("reason") == "API_KEY_INVALID" for d in details):
                                print(f"⚠️ Invalid API key 제외: {key}")
                                API_KEYS = [k for k in API_KEYS if k != key]
                                API_KEY_CYCLE = itertools.cycle(API_KEYS) if API_KEYS else None
                                continue

                        resp.raise_for_status()
                        return data
                except Exception as e:
                    print(f"❌ {url} 요청 실패: {e}")
                    continue
            raise RuntimeError("🚨 모든 API KEY 실패")
        else:
            if not API_URL_ENV:
                raise RuntimeError("🚨 API_KEY도 API_URL도 없음. 환경변수 확인하세요.")
            try:
                async with session.post(API_URL_ENV, headers=headers, json=payload, timeout=30) as resp:
                    resp.raise_for_status()
                    return await resp.json()
            except Exception as e:
                print(f"❌ {API_URL_ENV} 요청 실패: {e}")
                raise

# --- 디스코드 봇 설정 ---
intents = discord.Intents.default()
intents.message_content = True

class MyClient(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = discord.app_commands.CommandTree(self)

    async def setup_hook(self):
        # Flask 앱을 백그라운드에서 실행
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, run_web)
        print("Flask 웹 서버가 백그라운드에서 시작되었습니다.")

client = MyClient(intents=intents)

# --- Flask 웹 서버 설정 (봇을 깨우기 위함) ---
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running and ready!"

def run_web():
    app.run(host="0.0.0.0", port=10000)


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
async def banana_command(
    interaction: discord.Interaction,
    프롬프트: str,
    이미지1: discord.Attachment = None,
    이미지2: discord.Attachment = None
):
    # defer()를 최대한 빨리 실행하는 것이 중요
    await interaction.response.defer()
    
    # 현재 이벤트 루프를 가져옴
    loop = asyncio.get_event_loop()

    try:
        parts = [{"text": f"Image generation prompt: {프롬프트}"}]
        images = [이미지1, 이미지2]
        
        # 사용자 입력 이미지를 저장할 리스트
        user_images = []

        for img in images:
            if img is None: continue
            if not img.content_type.startswith("image/"):
                await interaction.followup.send(f"❌ {img.filename} 은(는) 이미지 파일이 아닙니다.")
                return

            image_bytes = await img.read()
            
            # 사용자가 첨부한 원본 이미지 저장
            user_images.append(discord.File(io.BytesIO(image_bytes), filename=img.filename))
            
            # base64 인코딩
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

        # 첨부파일이 있으면 먼저 사용자 요청 정보를 보냄
        if user_images:
            user_request_message = f"```\n유저 프롬프트: {프롬프트}\n```"
            await interaction.followup.send(content=user_request_message, files=user_images)

        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"maxOutputTokens": 4000, "temperature": 1},
            "safetySettings": [
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "OFF"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "OFF"},
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "OFF"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "OFF"},
                {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "OFF"}
            ]
        }

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

        # AI 응답 전송
        if user_images:
            # 이미 첫 번째 메시지에서 사용자 요청을 보냈으므로, AI 응답만 보냄
            if response_file:
                await interaction.followup.send(content=response_text if response_text else "", file=response_file)
            elif response_text:
                await interaction.followup.send(content=response_text)
            else:
                await interaction.followup.send("⚠️ AI로부터 응답을 받지 못했습니다.")
        else:
            # 첨부파일이 없으면 한 번에 보냄 (기존 방식)
            user_request_message = f"```\n유저 프롬프트: {프롬프트}\n```\n"
            final_message = user_request_message + (response_text if response_text else "")
            
            if response_file:
                await interaction.followup.send(content=final_message, file=response_file)
            elif final_message.strip():
                await interaction.followup.send(content=final_message)
            else:
                await interaction.followup.send("⚠️ AI로부터 응답을 받지 못했습니다.")

    except Exception as e:
        print(f"에러 발생: {e}")
        await interaction.followup.send(f"⚠️ 오류 발생: {e}")

# --- 봇 실행 ---
client.run(DISCORD_TOKEN)
