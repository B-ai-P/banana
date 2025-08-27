import discord
import os
import requests
import base64
import io
import threading
from dotenv import load_dotenv
from flask import Flask

load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
API_BEARER_TOKEN = os.getenv('API_BEARER_TOKEN')

API_URL = os.getenv('API_URL')
API_HEADERS = {
    "Authorization": f"Bearer {API_BEARER_TOKEN}",
    "Content-Type": "application/json"
}

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = discord.app_commands.CommandTree(client)

@client.event
async def on_ready():
    print(f'{client.user}으로 로그인 성공!')
    await tree.sync()
    print("슬래시 커맨드가 동기화되었습니다.")

@tree.command(
    name="바나나",
    description="프롬프트와 함께 최대 2장의 이미지를 첨부할 수 있습니다."
)
async def banana_command(
    interaction: discord.Interaction,
    프롬프트: str,
    이미지1: discord.Attachment = None,
    이미지2: discord.Attachment = None
):
    await interaction.response.defer()

    try:
        # 기본 텍스트 파트
        parts = [{"text": 프롬프트}]

        # 첨부 이미지를 리스트에 담아서 반복 처리
        images = [이미지1, 이미지2]  # 최대 2개 슬롯
        for img in images:
            if img is None:
                continue
            if not img.content_type.startswith("image/"):
                await interaction.followup.send(
                    f"❌ {img.filename} 은(는) 이미지 파일이 아닙니다."
                )
                return

            image_bytes = await img.read()
            base64_image = base64.b64encode(image_bytes).decode("utf-8")

            parts.append({
                "inlineData": {
                    "mimeType": img.content_type,
                    "data": base64_image
                }
            })

        # 실제 payload
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": parts
                }
            ],
            "generationConfig": {
                "maxOutputTokens": 4000,
                "temperature": 1
            },
            "safetySettings": [
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "OFF"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "OFF"},
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "OFF"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "OFF"},
                {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "OFF"}
            ]
        }

        response = requests.post(API_URL, headers=API_HEADERS, json=payload)
        response.raise_for_status()
        data = response.json()

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

        if response_file:
            await interaction.followup.send(content=response_text, file=response_file)
        elif response_text:
            await interaction.followup.send(content=response_text)
        else:
            await interaction.followup.send("⚠️ AI로부터 응답을 받지 못했습니다.")

    except Exception as e:
        print(f"에러 발생: {e}")
        await interaction.followup.send(f"⚠️ 오류 발생: {e}")

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

def run_web():
    app.run(host="0.0.0.0", port=10000)

threading.Thread(target=run_web).start()

# 아래는 디스코드 봇 실행
client.run(DISCORD_TOKEN)
