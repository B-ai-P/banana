import discord
import os
import requests
import base64
import io
from dotenv import load_dotenv

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

@tree.command(name="바나나", description="AI에게 텍스트 또는 텍스트+이미지로 요청을 보냅니다.")
async def banana_command(interaction: discord.Interaction, 프롬프트: str, 이미지: discord.Attachment = None):
    await interaction.response.defer()

    try:
        parts = [{"text": 프롬프트}]

        if 이미지:
            if not 이미지.content_type.startswith('image/'):
                await interaction.followup.send("이미지 파일만 업로드할 수 있습니다. (png, jpg 등)")
                return

            image_bytes = await 이미지.read()
            base64_image = base64.b64encode(image_bytes).decode('utf-8')

            parts.append({
                "inlineData": {
                    "mimeType": 이미지.content_type,
                    "data": base64_image
                }
            })

        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "safetySettings": [
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "OFF"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "OFF"},
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "OFF"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "OFF"},
                {"category": "HARM_CATEGORY_CIVIC_INTEGRITY", "threshold": "OFF"}
            ],
            "generationConfig": {"maxOutputTokens": 4444}
        }

        response = requests.post(API_URL, headers=API_HEADERS, json=payload)
        response.raise_for_status()

        data = response.json()

        response_text = ""
        response_file = None

        if 'candidates' in data and data['candidates']:
            for part in data['candidates'][0]['content']['parts']:
                if 'text' in part:
                    response_text += part['text'] + "\n"
                elif 'inlineData' in part:
                    base64_data = part['inlineData']['data']
                    image_data = base64.b64decode(base64_data)
                    response_file = discord.File(io.BytesIO(image_data), filename="result.png")

        if response_file:
            await interaction.followup.send(content=response_text, file=response_file)
        elif response_text:
            await interaction.followup.send(content=response_text)
        else:
            await interaction.followup.send("AI로부터 응답을 받지 못했습니다.")

    except Exception as e:
        print(f"오류 발생: {e}")
        await interaction.followup.send(f"처리 중 오류가 발생했습니다: {e}")

client.run(DISCORD_TOKEN)
