import telebot
from telebot import types
import os
import random
import time
import threading
import sqlite3
from datetime import datetime, timedelta

# ===== INITIALIZATION =====
API_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(API_TOKEN, threaded=True, num_threads=25)

ADMIN_KEY = "Eshu2005aru"
GROUP_ID = -1003746627836 

# ===== DATABASE (1-Month Memory) =====
def init_db():
    conn = sqlite3.connect('quiz_history.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS history 
                 (q_text TEXT PRIMARY KEY, used_date TIMESTAMP)''')
    conn.commit()
    conn.close()

def mark_used(q_text):
    try:
        conn = sqlite3.connect('quiz_history.db')
        c = conn.cursor()
        c.execute("INSERT OR REPLACE INTO history VALUES (?, ?)", (q_text, datetime.now()))
        conn.commit()
        conn.close()
    except: pass

def get_recent_questions():
    try:
        conn = sqlite3.connect('quiz_history.db')
        c = conn.cursor()
        one_month_ago = datetime.now() - timedelta(days=30)
        c.execute("SELECT q_text FROM history WHERE used_date > ?", (one_month_ago,))
        rows = c.fetchall()
        conn.close()
        return {row[0] for row in rows}
    except: return set()

init_db()

# ===== DATA STORAGE =====
question_bank = {} 
user_state = {}
user_step = {}
selected_chapters = {}
user_scores = {} 
quiz_running = {} 

current_poll_data = {
    "poll_id": None,
    "message_id": None,
    "active": False,
    "correct_id": None,
    "max_answers": 3,
    "voters": 0
}

# ===== SMART LOAD (Fixes "General" issue) =====
def load_questions():
    subjects = ["biology", "math", "reasoning", "physics", "chemistry"]
    for sub in subjects:
        try:
            path = f"questions/{sub}.txt"
            if not os.path.exists(path): continue
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            
            blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
            current_chapter = "General" 
            
            for block in blocks:
                lines = block.split("\n")
                filtered_lines = []
                for line in lines:
                    if line.strip().lower().startswith("#chapter:"):
                        current_chapter = line.split(":")[1].strip()
                    else:
                        filtered_lines.append(line)
                
                clean_block = "\n".join(filtered_lines)
                if "Answer:" in clean_block:
                    question_bank.setdefault(sub, {}).setdefault(current_chapter, []).append(clean_block)
            print(f"✅ {sub.capitalize()} loaded.")
        except Exception as e:
            print(f"❌ Error loading {sub}: {e}")

load_questions()

# ===== SPEED TRIGGERS (Skip & Auto-Next) =====

@bot.poll_answer_handler()
def handle_poll_answer(poll_answer):
    global current_poll_data
    uid = poll_answer.user.id
    
    if uid not in user_scores:
        user_scores[uid] = {"name": poll_answer.user.first_name, "correct": 0, "wrong": 0, "score": 0.0}
    
    if poll_answer.poll_id == current_poll_data["poll_id"]:
        current_poll_data["voters"] += 1
        
        # Scoring
        if poll_answer.option_ids[0] == current_poll_data["correct_id"]:
            user_scores[uid]["correct"] += 1
            user_scores[uid]["score"] += 1.0
        else:
            user_scores[uid]["wrong"] += 1
            user_scores[uid]["score"] -= 0.5

        # TRIGGER 1: Auto-close when max answers reached
        if current_poll_data["voters"] >= current_poll_data["max_answers"]:
            current_poll_data["active"] = False 

@bot.callback_query_handler(func=lambda call: True)
def handle_skip_or_stop(call):
    global current_poll_data
    
    # TRIGGER 2: Instant Skip
    if call.data.startswith("skip_"):
        if current_poll_data["active"] and call.data.replace("skip_", "") == current_poll_data["poll_id"]:
            current_poll_data["active"] = False
            bot.answer_callback_query(call.id, "Skipping to next...")
            bot.edit_message_text("⏩ **Question Skipped!**", GROUP_ID, call.message.message_id)

    elif call.data == "stop_quiz":
        quiz_running[call.message.chat.id] = False
        bot.answer_callback_query(call.id, "Stopping after this question.")

# ===== QUIZ ENGINE =====

def run_quiz(chat_id):
    global current_poll_data
    user_scores.clear()
    data = user_state[chat_id]
    
    full_pool = []
    for ch in data['chapters']: 
        full_pool.extend(question_bank[data['subject']].get(ch, []))
    
    recent = get_recent_questions()
    available = [q for q in full_pool if q not in recent]
    if len(available) < data['count']: available = full_pool 
    
    selected = random.sample(available, min(data['count'], len(available)))
    bot.send_message(GROUP_ID, f"🔥 **QUIZ START: {data['subject'].upper()}**")

    for block in selected:
        if not quiz_running.get(chat_id): break

        lines = [l.strip() for l in block.split("\n") if l.strip()]
        clean_q = lines[0]
        options = [lines[1][3:], lines[2][3:], lines[3][3:], lines[4][3:]]
        ans_letter = next(l for l in lines if "Answer:" in l).split(":")[-1].strip().upper()
        correct_idx = ord(ans_letter) - ord("A")

        poll_msg = bot.send_poll(
            GROUP_ID, clean_q, options, 
            type='quiz', correct_option_id=correct_idx, 
            is_anonymous=False, open_period=data['timer']
        )
        
        markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("⏭️ Skip", callback_data=f"skip_{poll_msg.poll.id}"))
        skip_msg = bot.send_message(GROUP_ID, "No interest? Click skip to move on.", reply_markup=markup)

        current_poll_data.update({
            "poll_id": poll_msg.poll.id, "active": True, "correct_id": correct_idx,
            "max_answers": data['max_answers'], "voters": 0
        })

        # Speed monitor loop (checks every 0.1s)
        start_t = time.time()
        while time.time() - start_t < data['timer']:
            if not current_poll_data["active"] or not quiz_running.get(chat_id): break
            time.sleep(0.1)

        try:
            bot.stop_poll(GROUP_ID, poll_msg.message_id)
            bot.delete_message(GROUP_ID, skip_msg.message_id)
        except: pass
        
        mark_used(block)
        current_poll_data["active"] = False
        time.sleep(1.2) 

    bot.send_message(GROUP_ID, "🏁 **Quiz Finished!** Check /scorecard")

# ===== ADMIN COMMANDS =====

@bot.message_handler(commands=['start'])
def welcome(message):
    bot.send_message(message.chat.id, "⚡ **Fast Quiz Bot**\n/admin - Start Setup\n/scorecard - Ranking")

@bot.message_handler(commands=['admin'])
def admin_setup(message):
    user_step[message.chat.id] = "key"
    bot.send_message(message.chat.id, "🔑 **Admin Key:**")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "key")
def key_check(message):
    if message.text == ADMIN_KEY:
        user_step[message.chat.id] = "sub"
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True).add("Biology", "Math", "Reasoning", "Physics", "Chemistry")
        bot.send_message(message.chat.id, "Select Subject:", reply_markup=markup)
    else: bot.send_message(message.chat.id, "❌ Invalid Key.")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "sub")
def sub_check(message):
    sub = message.text.lower()
    if sub in question_bank:
        user_state[message.chat.id] = {'subject': sub}
        user_step[message.chat.id] = "mode"
        bot.send_message(message.chat.id, "Mode?", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("Mix (All) 🎯", "Chapter-wise 📂"))

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "mode")
def mode_check(message):
    sub = user_state[message.chat.id]['subject']
    if "Mix" in message.text:
        user_state[message.chat.id]['chapters'] = list(question_bank[sub].keys())
        user_step[message.chat.id] = "count"
        bot.send_message(message.chat.id, "Question Count:")
    else:
        user_step[message.chat.id] = "ch"
        selected_chapters[message.chat.id] = set()
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        for ch in question_bank[sub]: markup.add(ch)
        markup.add("DONE ✅")
        bot.send_message(message.chat.id, "Select Chapters:", reply_markup=markup)

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "ch")
def ch_sel(message):
    if message.text == "DONE ✅":
        user_state[message.chat.id]['chapters'] = list(selected_chapters[message.chat.id])
        user_step[message.chat.id] = "count"
        bot.send_message(message.chat.id, "Question Count:")
    else:
        selected_chapters[message.chat.id].add(message.text)
        bot.send_message(message.chat.id, f"Added: {message.text}")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "count")
def count_check(message):
    user_state[message.chat.id]['count'] = int(message.text)
    user_step[message.chat.id] = "timer"
    bot.send_message(message.chat.id, "Timer (Seconds):")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "timer")
def timer_check(message):
    user_state[message.chat.id]['timer'] = int(message.text)
    user_step[message.chat.id] = "max"
    bot.send_message(message.chat.id, "Auto-Next after how many answers?")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "max")
def max_check(message):
    user_state[message.chat.id]['max_answers'] = int(message.text)
    user_step[message.chat.id] = "ready"
    bot.send_message(message.chat.id, "Configuration Loaded!", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("🚀 START QUIZ"))

@bot.message_handler(func=lambda m: m.text == "🚀 START QUIZ" and user_step.get(m.chat.id) == "ready")
def launch(message):
    quiz_running[message.chat.id] = True
    markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🛑 STOP QUIZ", callback_data="stop_quiz"))
    bot.send_message(message.chat.id, "Admin Controls:", reply_markup=markup)
    threading.Thread(target=run_quiz, args=(message.chat.id,)).start()

@bot.message_handler(commands=['scorecard'])
def score_report(message):
    if not user_scores: return bot.send_message(message.chat.id, "📊 No scores yet.")
    s = sorted(user_scores.values(), key=lambda x: x['score'], reverse=True)
    report = "🏆 **Leaderboard**\n" + "\n".join([f"{u['name']}: {u['score']} pts" for u in s[:10]])
    bot.send_message(message.chat.id, report)

if __name__ == "__main__":
    bot.infinity_polling()
        
