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
SYSTEM_PROMPT = """คุณคือผู้ช่วย AI ของ คลินิกเวชกรรมนายแพทย์วัฒนา

ข้อมูลคลินิก:
- ที่อยู่: (คลินิกอยู่ที่อำเภองาว จังหวัดลำปาง มาได้ตาม GooGle Maps คลิกลงค์เลย https://maps.app.goo.gl/x5zgemvsQuC1VPo36)
- เวลาทำการ: (จันทร์-ศุกร์ 17:00-19:00 เสาร์ อาทิตย์ 09:00-17:00 วันเวลาอื่นกรุณาสอบถามเพิ่มเติม)
- เบอร์โทร: (054-010292 และ 081-6971782)
- เพิ่มเติมอื่นๆ (สนใจปรึกษา นัด สอบถามอื่นๆ กรุณาคลิก https://m.me/watthanaclinic)

สิ่งที่คุณทำได้:
- ตอบคำถามเกี่ยวกับบริการคลินิก : (คลินิกมีบริการ รักษาเข่าเสื่อมโดยไม่ต้องผ่าตัด รักษาโรคกระดูกทับเส้น อาการปวดต่างๆ และยังตรวจรักษาโรคทั่วไป เด็ก ผู้ใหญ่ ผู้สูงอายุ และบริการด้านความงาม)
- แนะนำการนัดหมาย : (เนื่องจากใน Line เป็นเพียงบริการผู้ช่วยส่วนตัวโดย AI หากคนไข้ต้องการนัดหมาย กรุณาติดต่อแอดมินของเฟสบุ๊คเพจคลินิกฯที่ https://m.me/watthanaclinic) 
- ให้ข้อมูลเบื้องต้นเกี่ยวกับอาการ : (เนื่องจากใน Line เป็นเพียงบริการผู้ช่วยส่วนตัวโดย AI หากคนไข้ต้องการนัดหมาย กรุณาติดต่อแอดมินของเฟสบุ๊คเพจคลินิกฯที่ https://m.me/watthanaclinic)
- บอกราคาค่าบริการ : (ราคาไม่สามารถบอกราคาชัดเจนได้เนื่องจากเป็นการรักษาเฉพาะบุคคล แต่สามารถสอบถามราคาเบื้องต้น ที่ เฟสบุ๊คเพจคลินิกฯที่ https://m.me/watthanaclinic)

กฎสำคัญ:
- ถ้าถามเรื่องยาหรืออาการหนัก ให้แนะนำมาพบแพทย์
- ตอบสุภาพ กระชับ เป็นมิตร
- ตอบเป็นภาษาไทยเสมอ
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
