import logging
import os
import requests
import io
import asyncio
from PIL import Image
from telegram import Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = "8421647372:AAHwA65W2lWL0vHdQKpfgEnpo34-Hnln28A" 
ADMIN_ID = 6776521775 
CHANNEL_ID = -1003630677020 
WATERMARK_PATH = "watermark.png"
FIREBASE_URL = "https://igizmo-ba1d0-default-rtdb.europe-west1.firebasedatabase.app/"

logging.basicConfig(level=logging.INFO)

def apply_watermark(img_content):
    try:
        base = Image.open(io.BytesIO(img_content)).convert("RGBA")
        if os.path.exists(WATERMARK_PATH):
            wm = Image.open(WATERMARK_PATH).convert("RGBA")
            wm_w = int(base.width * 0.25)
            wm_h = int(float(wm.height) * (wm_w / float(wm.width)))
            wm = wm.resize((wm_w, wm_h), Image.Resampling.LANCZOS)
            base.paste(wm, (base.width - wm_w - 20, base.height - wm_h - 20), wm)
        out = io.BytesIO()
        base.convert("RGB").save(out, format="JPEG", quality=85)
        return out.getvalue()
    except: return img_content

def fetch_and_watermark(url):
    return apply_watermark(requests.get(url).content)

async def check_firebase_tasks(context: ContextTypes.DEFAULT_TYPE):
    try:
        resp = requests.get(f"{FIREBASE_URL}/tasks.json")
        if resp.status_code != 200 or not resp.json(): return
        tasks = resp.json()

        for task_id, task in tasks.items():
            try:
                t_type = task.get("type")

                # ПУБЛІКАЦІЯ ОГОЛОШЕННЯ
                if t_type == "publish_ad":
                    ad_id = task.get("ad_id")
                    ad = requests.get(f"{FIREBASE_URL}/market_ads/{ad_id}.json").json()
                    if not ad: continue
                        
                    if ad.get('status') == 'pending_edit':
                        updates = ad.get('pending_updates', {})
                        old_price = int(ad.get('price', 0))
                        new_price = int(updates.get('price', old_price))
                        requests.patch(f"{FIREBASE_URL}/market_ads/{ad_id}.json", json={
                            "status": "active", "price": updates.get('price'), "special_price": updates.get('special_price'),
                            "description": updates.get('description'), "city": updates.get('city'),
                            "olx_link": updates.get('olx_link'), "mono_link": updates.get('mono_link')
                        })
                        requests.delete(f"{FIREBASE_URL}/market_ads/{ad_id}/pending_updates.json")
                        
                        msg_id = ad.get('message_id')
                        if msg_id and new_price < old_price:
                            spec = updates.get('special_price')
                            rep_txt = f"📉 <b>ЦІНУ ЗНИЖЕНО!</b>\nНова ціна: <b>{new_price} грн</b> 🔥"
                            if spec: rep_txt += f"\nДля своїх: <b>{spec} грн</b>"
                            try: await context.bot.send_message(chat_id=CHANNEL_ID, reply_to_message_id=msg_id, text=rep_txt, parse_mode="HTML")
                            except: pass
                        try: await context.bot.send_message(chat_id=ad.get('seller_id'), text="✅ Ваші зміни схвалено та опубліковано!")
                        except: pass

                    elif ad.get('status') == 'pending':
                        vip_mark = "🌟 <b>VIP ОГОЛОШЕННЯ</b>\n" if ad.get('vip') else ""
                        
                        # --- НАДІЙНИЙ КОД ДЛЯ КОНТАКТІВ ---
                        contacts = []
                        if ad.get('seller_username'):
                            contacts.append(f"@{ad.get('seller_username')}")
                        if ad.get('phone'):
                            contacts.append(ad.get('phone'))
                        contact_str = " | ".join(contacts) if contacts else "Не вказано"
                        
                        # --- НАДІЙНИЙ КОД ДЛЯ БЕЙДЖІВ ТА ЦІН ---
                        badges = []
                        if ad.get('negotiable'):
                            badges.append("Торг")
                        if ad.get('special_price'):
                            badges.append(f"Спец: {ad.get('special_price')} ₴")
                        badges_str = f" ({' | '.join(badges)})" if badges else ""
                        
                        desc = ad.get('description', 'Без опису')
                        if len(desc) > 300: 
                            desc = desc[:300] + "..."

                        post_text = (
                            f"{vip_mark}"
                            f"📱 <b>{ad.get('device')} {ad.get('model')}</b>\n\n"
                            f"💾 Пам'ять: {ad.get('storage')} | 🔋 АКБ: {ad.get('battery')}%\n"
                            f"📍 Місто: {ad.get('city')}\n\n"
                            f"📝 <b>Опис:</b> {desc}\n\n"
                            f"💰 <b>Ціна: {ad.get('price')} грн</b>{badges_str}\n\n"
                            f"👤 Продавець: {ad.get('seller_name')} ({contact_str})\n"
                            f"🛡 Опубліковано через iGizmo Market"
                        )
                        
                        photos = ad.get("photos", [])
                        published_msg_id = None
                        if photos:
                            loop = asyncio.get_running_loop()
                            tasks_img = [loop.run_in_executor(None, fetch_and_watermark, url) for url in photos[:10]]
                            processed_images = await asyncio.gather(*tasks_img)
                            media = [InputMediaPhoto(img_bytes, caption=post_text if i==0 else "", parse_mode="HTML") for i, img_bytes in enumerate(processed_images)]
                            msgs = await context.bot.send_media_group(CHANNEL_ID, media, read_timeout=60, write_timeout=60)
                            published_msg_id = msgs[0].message_id
                        else:
                            sent_msg = await context.bot.send_message(CHANNEL_ID, post_text, parse_mode="HTML")
                            published_msg_id = sent_msg.message_id

                        requests.patch(f"{FIREBASE_URL}/market_ads/{ad_id}.json", json={"status": "active", "message_id": published_msg_id})
                        try: await context.bot.send_message(chat_id=ad.get('seller_id'), text="🎉 Твоє оголошення успішно опубліковано в маркеті!")
                        except: pass

                # ТОВАР ПРОДАНО
                elif t_type == "sold_reply":
                    ad = requests.get(f"{FIREBASE_URL}/market_ads/{task.get('ad_id')}.json").json()
                    if ad and ad.get('message_id'):
                        try: await context.bot.send_message(chat_id=CHANNEL_ID, reply_to_message_id=ad.get('message_id'), text="🎉 <b>ПРОДАНО!</b> Цей пристрій знайшов нового власника.", parse_mode="HTML")
                        except: pass

                # СПОВІЩЕННЯ ЮЗЕРУ
                elif t_type == "notify_user":
                    try: await context.bot.send_message(chat_id=task.get('user_id'), text=task.get('text'))
                    except: pass

                # СПОВІЩЕННЯ АДМІНУ
                elif t_type == "notify_admin":
                    try: await context.bot.send_message(chat_id=ADMIN_ID, text=task.get('text'))
                    except: pass

                # РОЗСИЛКА (Broadcast)
                elif t_type == "broadcast":
                    users = requests.get(f"{FIREBASE_URL}/users.json").json()
                    if users:
                        bc_text = task.get("text", "")
                        bc_photo = task.get("photo_url", "")
                        btn_name = task.get("btn_name", "")
                        btn_url = task.get("btn_url", "")
                        
                        reply_markup = None
                        if btn_name and btn_url:
                            reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(btn_name, url=btn_url)]])

                        for u_id in users.keys():
                            try:
                                if bc_photo:
                                    await context.bot.send_photo(chat_id=u_id, photo=bc_photo, caption=bc_text, reply_markup=reply_markup, parse_mode="HTML")
                                else:
                                    await context.bot.send_message(chat_id=u_id, text=bc_text, reply_markup=reply_markup, parse_mode="HTML")
                                await asyncio.sleep(0.05) # Анти-спам ліміт Телеграму
                            except: pass

            except Exception as e:
                logging.error(f"Error processing task {task_id}: {e}")
            finally:
                requests.delete(f"{FIREBASE_URL}/tasks/{task_id}.json")

    except Exception as e: pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "🍏 <b>Вітаємо в iGizmo Market!</b>\n\n"
        "Це найсучасніший майданчик для безпечного продажу та купівлі техніки Apple.\n\n"
        "📱 <i>Тисячі клієнтів\n"
        "⚡️ Швидка публікація\n"
        "🛡 Повна безпека</i>\n\n"
        "Натисніть кнопку нижче, щоб відкрити додаток 👇"
    )
    
    keyboard = [[InlineKeyboardButton("🚀 Відкрити Додаток", web_app={"url": "https://igizmo-ba1d0.web.app/"})]] 
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(welcome_text, parse_mode="HTML", reply_markup=reply_markup)

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    
    app.job_queue.run_repeating(check_firebase_tasks, interval=5.0)
    
    print("🚀 iGizmo PRO (Fixed F-Strings) Started!")
    app.run_polling()

if __name__ == "__main__":
    main()