import telebot
from telebot import types
import os
import random
import time
import threading
import sqlite3
from datetime import datetime, timedelta

# Initialize Bot
API_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(API_TOKEN, threaded=True, num_threads=25)

ADMIN_KEY = "Eshu2005aru"
GROUP_ID = -1003746627836 

# ===== DATABASE SETUP (2-Week Persistent Memory) =====
DB_NAME = "quiz_history.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS history 
                 (question_hash TEXT PRIMARY KEY, last_used TIMESTAMP)''')
    conn.commit()
    conn.close()

def mark_question_used(question_text):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    q_hash = str(hash(question_text))
    c.execute("INSERT OR REPLACE INTO history (question_hash, last_used) VALUES (?, ?)", 
              (q_hash, datetime.now()))
    conn.commit()
    conn.close()

def get_used_question_hashes():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    two_weeks_ago = datetime.now() - timedelta(days=14)
    c.execute("SELECT question_hash FROM history WHERE last_used > ?", (two_weeks_ago,))
    used = {row[0] for row in c.fetchall()}
    conn.close()
    return used

init_db()

# ===== DATA STORAGE =====
question_bank = {} 
user_state = {}
user_step = {}
selected_chapters = {}
user_scores = {} 
quiz_active = {} 
skipped_this_q = set() 

current_poll_data = {
    "poll_id": None,
    "message_id": None,
    "active": False,
    "correct_id": None,
    "max_answers": 3,
    "skip_count": 0,
    "voter_count": 0
}

# [span_2](start_span)===== 1. DATABASE LOADER[span_2](end_span) =====
def load_questions():
    subjects = ["biology", "math", "reasoning", "physics", "chemistry"]
    for sub in subjects:
        try:
            path = f"questions/{sub}.txt"
            if not os.path.exists(path): continue
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            current_chapter = "General" 
            blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
            for block in blocks:
                lines = block.split("\n")
                for line in lines:
                    if line.lower().startswith("#chapter:"):
                        current_chapter = line.split(":")[1].strip()
                if "Answer:" in block:
                    question_bank.setdefault(sub, {}).setdefault(current_chapter, []).append(block)
            print(f"✅ {sub.capitalize()} loaded.")
        except Exception as e:
            print(f"❌ Error loading {sub}: {e}")

load_questions()

# [span_3](start_span)===== 2. CORE UTILITIES[span_3](end_span) =====
def init_user(uid, name):
    if uid not in user_scores:
        user_scores[uid] = {"name": name, "correct": 0, "wrong": 0, "skip": 0, "score": 0.0}

def get_report():
    if not user_scores: return "📊 No results to show."
    sorted_u = sorted(user_scores.values(), key=lambda x: x['score'], reverse=True)
    report = "📋 **DETAILED QUIZ REPORT** 📋\n━━━━━━━━━━━━━━\n"
    for u in sorted_u:
        total = u['correct'] + u['wrong'] + u['skip']
        report += (f"👤 **{u['name']}**\n"
                   f"📝 Total: {total} Qs\n"
                   f"✅ Correct: {u['correct']}\n"
                   f"❌ Wrong: {u['wrong']}\n"
                   f"⏩ Skipped: {u['skip']}\n"
                   f"🏆 **Score: {u['score']}**\n"
                   f"━━━━━━━━━━━━━━\n")
    return report

# [span_4](start_span)===== 3. EVENT HANDLERS[span_4](end_span) =====
@bot.poll_answer_handler()
def handle_poll_answer(poll_answer):
    uid = poll_answer.user.id
    init_user(uid, poll_answer.user.first_name)
    if str(poll_answer.poll_id) == str(current_poll_data["poll_id"]):
        current_poll_data["voter_count"] += 1
        if poll_answer.option_ids[0] == current_poll_data["correct_id"]:
            user_scores[uid]["correct"] += 1
            user_scores[uid]["score"] += 1.0
        else:
            user_scores[uid]["wrong"] += 1
            user_scores[uid]["score"] -= 0.5

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    uid = call.from_user.id
    if call.data.startswith("skip_"):
        target_pid = call.data.split("_")[1]
        if target_pid != str(current_poll_data["poll_id"]):
            bot.answer_callback_query(call.id, "❌ Question expired.")
            return
        if uid in skipped_this_q:
            bot.answer_callback_query(call.id, "⚠️ Already skipped!")
            return
        init_user(uid, call.from_user.first_name)
        skipped_this_q.add(uid)
        user_scores[uid]["skip"] += 1
        current_poll_data["skip_count"] += 1
        bot.answer_callback_query(call.id, "⏩ Skipped!")
    elif call.data == "stop_quiz":
        quiz_active[GROUP_ID] = False
        current_poll_data["active"] = False
        bot.answer_callback_query(call.id, "🛑 Stopping Quiz...")

# [span_5](start_span)===== 4. ADMIN INTERFACE[span_5](end_span) =====
@bot.message_handler(commands=['admin'])
def admin(message):
    user_step[message.chat.id] = "admin_key"
    bot.send_message(message.chat.id, "🔑 **Enter Admin Key:**")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "admin_key")
def check_key(m):
    if m.text == ADMIN_KEY:
        user_step[m.chat.id] = "subject"
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True).add("Biology", "Math", "Reasoning", "Physics", "Chemistry")
        bot.send_message(m.chat.id, "📚 **Subject:**", reply_markup=markup)

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "subject")
def sel_sub(m):
    sub = m.text.lower()
    if sub in question_bank:
        user_state[m.chat.id] = {'subject': sub}
        user_step[m.chat.id] = "mode"
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True).add("Mix (All) 🎯", "Chapter-wise 📂")
        bot.send_message(m.chat.id, "🎯 **Mode:**", reply_markup=markup)

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "mode")
def sel_mode(m):
    sub = user_state[m.chat.id]['subject']
    if "Mix" in m.text:
        user_state[m.chat.id]['chapters'] = list(question_bank[sub].keys())
        user_step[m.chat.id] = "count"
        bot.send_message(m.chat.id, "🔢 **Question Count:**", reply_markup=types.ReplyKeyboardRemove())
    else:
        user_step[m.chat.id] = "chapter"
        selected_chapters[m.chat.id] = set()
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        for ch in question_bank[sub]: markup.add(ch)
        markup.add("DONE ✅")
        bot.send_message(m.chat.id, "Select chapters:", reply_markup=markup)

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "chapter")
def sel_ch(m):
    if m.text == "DONE ✅":
        user_state[m.chat.id]['chapters'] = list(selected_chapters[m.chat.id])
        user_step[m.chat.id] = "count"
        bot.send_message(m.chat.id, "🔢 **Count:**", reply_markup=types.ReplyKeyboardRemove())
    else:
        selected_chapters[m.chat.id].add(m.text)
        bot.send_message(m.chat.id, f"➕ {m.text}")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "count")
def sel_count(m):
    user_state[m.chat.id]['count'] = int(m.text)
    user_step[m.chat.id] = "timer"
    bot.send_message(m.chat.id, "⏱️ **Global Timer (sec):**")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "timer")
def sel_timer(m):
    user_state[m.chat.id]['timer'] = int(m.text)
    user_step[m.chat.id] = "limit"
    bot.send_message(m.chat.id, "👤 **Answer Limit (Votes + Skips):**")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "limit")
def sel_limit(m):
    user_state[m.chat.id]['max_answers'] = int(m.text)
    user_step[m.chat.id] = "ready"
    bot.send_message(m.chat.id, "✅ Ready!", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("START QUIZ 🚀"))

# [span_6](start_span)===== 5. THE PRO QUIZ ENGINE[span_6](end_span) =====
@bot.message_handler(func=lambda m: m.text == "START QUIZ 🚀" and user_step.get(m.chat.id) == "ready")
def start_trigger(message):
    quiz_active[GROUP_ID] = True
    stop_btn = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🛑 STOP QUIZ", callback_data="stop_quiz"))
    bot.send_message(message.chat.id, "🚨 Quiz started. Click to stop:", reply_markup=stop_btn)
    threading.Thread(target=run_quiz, args=(message.chat.id,)).start()

def run_quiz(chat_id):
    global current_poll_data, skipped_this_q
    user_scores.clear()
    data = user_state[chat_id]
    sub = data['subject']
    
    all_available_pool = []
    for ch in data['chapters']: all_available_pool.extend(question_bank[sub].get(ch, []))
    
    # 2-Week Repetition Logic
    used_hashes = get_used_question_hashes()
    fresh_pool = [q for q in all_available_pool if str(hash(q)) not in used_hashes]
    
    # Fallback if fresh pool is empty
    if len(fresh_pool) < data['count']:
        bot.send_message(chat_id, "⚠️ Fresh pool low. Questions may repeat.")
        pool_to_use = all_available_pool
    else:
        pool_to_use = fresh_pool

    selected = random.sample(pool_to_use, min(data['count'], len(pool_to_use)))

    bot.send_message(GROUP_ID, f"🔔 **{sub.upper()} QUIZ STARTED!**")

    for block in selected:
        if not quiz_active.get(GROUP_ID): break
        
        # Log to Database
        mark_question_used(block)
        
        current_poll_data.update({"skip_count": 0, "voter_count": 0, "active": True})
        skipped_this_q.clear()
        
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        q_timer = data['timer']
        for line in lines:
            if line.lower().startswith("#time:"): q_timer = int(line.split(":")[1])

        clean_q = [line for line in lines if not line.lower().startswith("#")][0]
        options = [lines[1][3:], lines[2][3:], lines[3][3:], lines[4][3:]]
        ans = next((l.split(":")[-1].strip() for l in lines if "Answer:" in l), "A")
        correct_idx = ord(ans) - ord("A")

        poll_msg = bot.send_poll(GROUP_ID, clean_q, options, type='quiz', 
                                 correct_option_id=correct_idx, is_anonymous=False, open_period=q_timer)
        
        current_poll_data["poll_id"] = poll_msg.poll.id
        current_poll_data["message_id"] = poll_msg.message_id
        current_poll_data["correct_id"] = correct_idx

        skip_markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("⏩ Skip", callback_data=f"skip_{poll_msg.poll.id}"))
        btn_msg = bot.send_message(GROUP_ID, "Skip if you don't know:", reply_markup=skip_markup)

        # Sync Loop (0.5s checks)
        start_t = time.time()
        while time.time() - start_t < q_timer:
            if (current_poll_data["voter_count"] + current_poll_data["skip_count"]) >= data['max_answers']:
                break
            if not quiz_active.get(GROUP_ID): break
            time.sleep(0.5)

        try:
            bot.delete_message(GROUP_ID, btn_msg.message_id)
            if current_poll_data["active"]: bot.stop_poll(GROUP_ID, poll_msg.message_id)
        except: pass
        current_poll_data["active"] = False
        time.sleep(2)

    bot.send_message(GROUP_ID, get_report(), parse_mode="Markdown")
    bot.send_message(GROUP_ID, "🏁 **Session Complete.**")

if __name__ == "__main__":
    bot.infinity_polling(skip_pending=True)
    
