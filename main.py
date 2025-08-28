import discord
import os
import requests
import base64
import io
import threading
import itertools
from dotenv import load_dotenv
from flask import Flask

load_dotenv()

DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
API_BEARER_TOKEN = os.getenv('API_BEARER_TOKEN')

API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN")
API_KEY_ENV = os.getenv("API_KEY")   # "키1,키2,키3" 이런 식일 수 있음
API_URL_ENV = os.getenv("API_URL")

# API_KEY 관리
API_KEYS = [k.strip() for k in API_KEY_ENV.split(",")] if API_KEY_ENV else []
API_KEY_CYCLE = itertools.cycle(API_KEYS) if API_KEYS else None

def make_headers():
    headers = {"Content-Type": "application/json"}
    if API_BEARER_TOKEN:  # bearer 있을 때만 붙임
        headers["Authorization"] = f"Bearer {API_BEARER_TOKEN}"
    return headers

def send_request(payload):
    global API_KEYS, API_KEY_CYCLE

    headers = make_headers()

    if API_KEYS:  
        # API_KEY 모드 (고정 URL)
        keys_to_try = list(API_KEYS)  # 현재 남은 키 만큼
        for _ in range(len(keys_to_try)):
            key = next(API_KEY_CYCLE)
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image-preview:generateContent?key={key}"
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=30)
                data = resp.json()

                # 키가 invalid일 때 제외
                if resp.status_code == 400 and "error" in data:
                    details = data["error"].get("details", [])
                    if any(d.get("reason") == "API_KEY_INVALID" for d in details):
                        print(f"⚠️ Invalid API key 제외: {key}")
                        API_KEYS = [k for k in API_KEYS if k != key]
                        API_KEY_CYCLE = itertools.cycle(API_KEYS) if API_KEYS else None
                        continue  # 다음 키 시도

                resp.raise_for_status()
                return data

            except Exception as e:
                print(f"❌ {url} 요청 실패: {e}")
                continue
        raise RuntimeError("🚨 모든 API KEY 실패")

    else:
        # API_URL 모드 (API_KEY가 없을 때)
        if not API_URL_ENV:
            raise RuntimeError("🚨 API_KEY도 API_URL도 없음. 환경변수 확인하세요.")
        try:
            resp = requests.post(API_URL_ENV, headers=headers, json=payload, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"❌ {API_URL_ENV} 요청 실패: {e}")
            raise

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
        images = [이미지1, 이미지2]
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

        # === 보내는 요청 로그 ===
        import json, traceback
        print("===== REQUEST PAYLOAD =====")
        print(json.dumps(payload, indent=2, ensure_ascii=False)[:2000])

        # 요청 보내기
        data = send_request(payload)

        # === 받은 응답 로그 ===
        print("===== RESPONSE DATA =====")
        print(json.dumps(data, indent=2, ensure_ascii=False)[:2000])

        # 응답 처리
        response_text = ""
        files = []

        if "candidates" in data and data["candidates"]:
            cand = data["candidates"][0]
            if "content" in cand and "parts" in cand["content"]:
                for part in cand["content"]["parts"]:
                    if "text" in part:
                        response_text += part["text"] + "\n"
                    elif "inlineData" in part:
                        base64_data = part["inlineData"]["data"]
                        image_data = base64.b64decode(base64_data)
                        file_obj = io.BytesIO(image_data)
                        files.append(discord.File(file_obj, filename="result.png"))

        if files and response_text:
            await interaction.followup.send(content=response_text, files=files)
        elif files:
            await interaction.followup.send(files=files)
        elif response_text:
            await interaction.followup.send(content=response_text)
        else:
            print("⚠️ 응답에 candidates/inlineData 없음 → AI가 비어 있는 응답을 반환")
            await interaction.followup.send("⚠️ AI로부터 응답을 받지 못했습니다.")

    except Exception as e:
        # 에러까지 풀로그
        import traceback, json
        print("===== ERROR START =====")
        print("예외 메시지:", e)
        traceback.print_exc()
        try:
            print("=== 마지막 응답 데이터 ===")
            print(json.dumps(data, indent=2, ensure_ascii=False)[:2000])
        except:
            print("응답 JSON 없음")
        print("===== ERROR END =====")

        await interaction.followup.send("⚠️ 처리 중 오류가 발생했습니다.")

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is running!"

def run_web():
    app.run(host="0.0.0.0", port=10000)

threading.Thread(target=run_web).start()

# 아래는 디스코드 봇 실행
client.run(DISCORD_TOKEN)
