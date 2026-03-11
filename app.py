import os
import sqlite3
from datetime import datetime
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
# ตั้งค่า Keys
# ==========================================
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# ==========================================
# ตั้งค่าระบบ
# ==========================================
app = Flask(__name__)
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)
claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ==========================================
# ตั้งค่าฐานข้อมูล SQLite
# ==========================================
DB_PATH = "clinic_bot.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS customers (
            user_id TEXT PRIMARY KEY,
            name TEXT,
            phone TEXT,
            last_visit TEXT,
            notes TEXT,
            created_at TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            role TEXT,
            message TEXT,
            timestamp TEXT
        )
    ''')
    conn.commit()
    conn.close()

def get_customer(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM customers WHERE user_id = ?", (user_id,))
    customer = c.fetchone()
    conn.close()
    return customer

def save_customer(user_id, name=None, phone=None, notes=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    existing = get_customer(user_id)
    if existing:
        if name: c.execute("UPDATE customers SET name = ? WHERE user_id = ?", (name, user_id))
        if phone: c.execute("UPDATE customers SET phone = ? WHERE user_id = ?", (phone, user_id))
        if notes: c.execute("UPDATE customers SET notes = ? WHERE user_id = ?", (notes, user_id))
        c.execute("UPDATE customers SET last_visit = ? WHERE user_id = ?", (now, user_id))
    else:
        c.execute(
            "INSERT INTO customers (user_id, name, phone, last_visit, notes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, name, phone, now, notes, now)
        )
    conn.commit()
    conn.close()

def get_conversation_history(user_id, limit=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT role, message FROM conversations WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    )
    rows = c.fetchall()
    conn.close()
    return [{"role": row[0], "content": row[1]} for row in reversed(rows)]

def save_message(user_id, role, message):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "INSERT INTO conversations (user_id, role, message, timestamp) VALUES (?, ?, ?, ?)",
        (user_id, role, message, now)
    )
    conn.commit()
    conn.close()

# ==========================================
# System Prompt — คลินิกเวชกรรมนายแพทย์วัฒนา
# ==========================================
SYSTEM_PROMPT = """คุณคือผู้ช่วย AI ของ คลินิกเวชกรรมนายแพทย์วัฒนา มีหน้าที่ดูแลและให้ข้อมูลแก่คนไข้อย่างสุภาพ อบอุ่น และเป็นมิตร

=== ข้อมูลคลินิก ===
- เว็บไซต์: https://watthanaclinic.com
- ที่อยู่: อำเภองาว จังหวัดลำปาง (ดูแผนที่: https://maps.app.goo.gl/x5zgemvsQuC1VPo36)
- Facebook Page: https://www.facebook.com/watthanaclinic
- เวลาทำการ: จันทร์-ศุกร์ 17:00-19:00 น. / เสาร์-อาทิตย์ 09:00-17:00 น.
- เบอร์โทร: 054-010292 และ 081-6971782
- ติดต่อ/นัดหมาย: https://m.me/watthanaclinic

=== จุดเด่นของคลินิก ===
- รักษาข้อเข่าเสื่อมโดยไม่ต้องผ่าตัด เจ็บน้อย ฟื้นตัวไว ปลอดภัย เห็นผลจริง
- บริการเสริมความงามโดยแพทย์ผู้เชี่ยวชาญ ผลลัพธ์เป็นธรรมชาติ มั่นใจได้
- คุณหมอใจดี เป็นกันเอง ให้คำแนะนำดี ราคาไม่แพง

=== บริการของคลินิก ===
1. รักษาข้อเข่าเสื่อมโดยไม่ต้องผ่าตัด
2. รักษาโรคกระดูกทับเส้นประสาท
3. รักษาอาการปวดต่าง ๆ
4. ตรวจรักษาโรคทั่วไป (เด็ก ผู้ใหญ่ ผู้สูงอายุ)
5. บริการเสริมความงาม: โบท็อกซ์ ฟิลเลอร์ เมโส ทรีตเมนต์ผิวหน้า ดูแลความงามครบวงจร
6. โปรแกรม Cerebrolysin ฟื้นฟูสมองและระบบประสาท (แรกในภาคเหนือ)
7. สเต็มเซลล์ฟื้นฟูข้อเข่าและระบบประสาท
8. กลุ่มโรคป่วยเล็กน้อยทั่วไป (Simple Diseases) โรคหวัด และไข้หวัดใหญ่: อาการคัดจมูก ไอ เจ็บคอ มีไข้ โรคกระเพาะอาหาร: อาการปวดท้อง ท้องอืด หรือแสบร้อนกลางอก ท้องเสีย/อาหารเป็นพิษ: อาการคลื่นไส้ อาเจียน ถ่ายเหลว ตาแดง: โรคติดต่อที่มักระบาดในช่วงหน้าฝน ผื่นคัน/ภูมิแพ้ผิวหนัง: อาการทางผิวหนังทั่วไป 
9. ฉีดยาคุมกำเนิด
10. ฉีดวัคซีน วัคซีนไข้หวัดใหญ่ วัคซีนปอดอักเสบ เป็นต้น

Facebook
Facebook
 +4

=== เสียงตอบรับจากลูกค้าจริง ===
- "คุณหมอใจดีเป็นกันเอง ให้คำแนะนำดีมากทุกเรื่อง"
- "คุณหมอใจดี พูดเพราะ ราคาไม่แพงเลย"
- "คุณหมอรักษาเก่งมาก ผิวหนังอักเสบที่รักษาที่อื่นไม่หาย มาที่นี่ 2-3 วันดีขึ้นเลย"
- "มาจากเชียงราย มาหายที่อำเภองาว ประทับใจมาก"

=== สิ่งที่คุณทำได้ ===
- ตอบคำถามเกี่ยวกับบริการคลินิก
- แนะนำการนัดหมายผ่านช่องทาง https://m.me/watthanaclinic
- ให้ข้อมูลเบื้องต้นเกี่ยวกับอาการ
- ราคาไม่สามารถบอกชัดเจนเนื่องจากเป็นการรักษาเฉพาะบุคคล ให้สอบถามเพิ่มเติมที่ https://m.me/watthanaclinic

=== กฎสำคัญ ===
- ถ้าลูกค้าบอกชื่อ ให้จำและเรียกชื่อในการสนทนาต่อไป
- ต้องถามกลับคนไข้เสมอว่ามีอาการเป็นอย่างไร หรือต้องการสอบถามอะไรเพิ่มเติม
- ถ้าถามเรื่องยาหรืออาการหนัก ให้แนะนำมาพบแพทย์
- ถ้าไม่สามารถตอบได้ ให้แจ้งว่า "รบกวนโทรติดต่อที่ 054-010292 หรือ 081-6971782 หรือทักแชท Facebook ได้ที่ https://m.me/watthanaclinic"
- ตอบสุภาพ กระชับ เป็นมิตร มีความห่วงใย
- ตอบเป็นภาษาไทยเสมอ

=== คำถามที่พบบ่อย ===
Q: ค่าตรวจทั่วไปเท่าไหร่?
A: ค่าตรวจทั่วไปเริ่มต้นที่ 150 บาทค่ะ

Q: ต้องนัดล่วงหน้าไหม?
A: ไม่ต้องนัด สามารถ Walk-in ได้เลยค่ะ

Q: มีที่จอดรถไหม?
A: มีที่จอดรถฟรีหน้าคลินิกค่ะ

Q: สนใจโปรแกรมรักษากระดูกทับเส้นประสาท
A: คลินิกรักษาโดยใช้ยาฉีดและยาทาน มีการรักษาแบบฉีดยาเฉพาะจุด ฉีดยาแก้อาการชา ฉีดยาแก้ปวดกระดูกทับเส้น ดริปวิตามินสูตรพิเศษบำรุงเส้นประสาท ฉีดสเต็มเซลล์ฟื้นฟู และการดริป Cerebrolysin ที่แรกในภาคเหนือ สนใจจองคิวได้ที่ https://m.me/watthanaclinic ค่ะ

Q: สนใจโปรแกรมกรดอะมิโนฟื้นฟูสมองและความจำ (Cerebrolysin)
A: เป็นวิตามินสูตรเฉพาะทางทางหลอดเลือดดำ ช่วยบำบัดอาการทางสมอง เช่น เส้นเลือดในสมองตีบหรือแตก (Stroke) ความจำเสื่อม สมองเสื่อม สมาธิสั้น ราคาเริ่มต้น 3,900 บาท จำนวนครั้งขึ้นอยู่กับคุณหมอประเมินค่ะ

Q: สนใจโปรแกรมฟื้นฟูข้อเข่าเสื่อม
A: คุณหมอมีประสบการณ์ 9 ปี รักษาเข่าเสื่อมมากกว่า 10,000 เคส เรียนจบหลักสูตรจากเยอรมันโดยตรง มีการฉีดสเต็มเซลล์+สารโกรทแฟคเตอร์กระตุ้นการสร้างคอลลาเจน เป็นคนแรกของภาคเหนือ สนใจจองคิวได้ที่ https://m.me/watthanaclinic ค่ะ

Q: บริการความงามมีอะไรบ้าง?
A: มีบริการครบวงจรค่ะ ได้แก่ โบท็อกซ์ ฟิลเลอร์ เมโส ทรีตเมนต์ผิวหน้า ดูแลโดยแพทย์ผู้เชี่ยวชาญ ผลลัพธ์เป็นธรรมชาติ สอบถามรายละเอียดเพิ่มเติมได้ที่ https://m.me/watthanaclinic ค่ะ
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
# ประมวลผลข้อความ
# ==========================================
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id = event.source.user_id
    user_message = event.message.text

    save_customer(user_id)

    customer = get_customer(user_id)
    customer_info = ""
    if customer and customer[1]:
        customer_info = f"\n[ข้อมูลลูกค้า: ชื่อ={customer[1]}, เบอร์={customer[2] or 'ไม่มี'}, หมายเหตุ={customer[4] or 'ไม่มี'}]"

    history = get_conversation_history(user_id, limit=10)
    save_message(user_id, "user", user_message)
    history.append({"role": "user", "content": user_message})

    response = claude_client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT + customer_info,
        messages=history
    )

    ai_reply = response.content[0].text
    save_message(user_id, "assistant", ai_reply)

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
init_db()
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
