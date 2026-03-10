import os
from flask import Flask, request, abort
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
import anthropic

# ==========================================
# ตั้งค่า Keys (แก้ไขตรงนี้)
# ==========================================
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# ==========================================
# ตั้งค่าระบบ (ไม่ต้องแก้ไข)
# ==========================================
app = Flask(__name__)
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# เก็บประวัติการสนทนาของแต่ละคน
conversation_history = {}

# ==========================================
# System Prompt — บุคลิกของ Bot
# (แก้ไขได้ตามต้องการ)
# ==========================================
SYSTEM_PROMPT = """คุณคือผู้ช่วย AI ที่ฉลาดและเป็นมิตร สำหรับตอบคำถามทั่วไปและช่วยเหลือด้าน Customer Service

หน้าที่ของคุณ:
- ตอบคำถามทั่วไปอย่างสุภาพและเป็นประโยชน์
- ช่วยแก้ปัญหาให้ลูกค้าอย่างตรงประเด็น
- ถ้าไม่รู้คำตอบ ให้บอกตรง ๆ และแนะนำให้ติดต่อเจ้าหน้าที่

กฎการตอบ:
- ตอบเป็นภาษาไทยเสมอ (ถ้าถามภาษาไทย)
- ตอบกระชับ ไม่เยิ่นเย้อ
- สุภาพและเป็นมิตรตลอด
"""

# ==========================================
# รับ Webhook จาก Line
# ==========================================
@app.route("/webhook", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# ==========================================
# ประมวลผลข้อความที่ได้รับ
# ==========================================
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text

    # สร้างประวัติการสนทนาถ้ายังไม่มี
    if user_id not in conversation_history:
        conversation_history[user_id] = []

    # เพิ่มข้อความผู้ใช้เข้าประวัติ
    conversation_history[user_id].append({
        "role": "user",
        "content": user_message
    })

    # จำกัดประวัติไว้แค่ 10 ข้อความล่าสุด (ประหยัด API)
    if len(conversation_history[user_id]) > 10:
        conversation_history[user_id] = conversation_history[user_id][-10:]

    # ส่งไปให้ Claude ตอบ
    response = claude_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=conversation_history[user_id]
    )

    ai_reply = response.content[0].text

    # เพิ่มคำตอบของ AI เข้าประวัติ
    conversation_history[user_id].append({
        "role": "assistant",
        "content": ai_reply
    })

    # ส่งคำตอบกลับไปหาผู้ใช้ใน Line
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        line_bot_api.reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=ai_reply)]
            )
        )

# ==========================================
# เริ่มต้น Server
# ==========================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
