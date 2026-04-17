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
bot = telebot.TeleBot(API_TOKEN, threaded=True, num_threads=20)

ADMIN_KEY = "Eshu2005aru"
GROUP_ID = -1003746627836 

# ===== DATABASE SETUP (1-Month Memory) =====
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
    "skip_msg_id": None,
    "active": False,
    "correct_id": None,
    "max_answers": 3,
    "current_voter_count": 0
}

# ===== LOAD QUESTIONS =====
def load_questions():
    subjects = ["biology", "math", "reasoning", "physics", "chemistry"]
    for sub in subjects:
        try:
            path = f"questions/{sub}.txt"
            if not os.path.exists(path): continue
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
            for block in blocks:
                lines = block.split("\n")
                current_chapter = "General"
                for line in lines:
                    if line.lower().startswith("#chapter:"):
                        current_chapter = line.split(":")[1].strip()
                if "Answer:" in block:
                    question_bank.setdefault(sub, {}).setdefault(current_chapter, []).append(block)
        except Exception as e: print(f"❌ Error loading {sub}: {e}")

load_questions()

# ===== HANDLERS (FAST TRIGGERS) =====

@bot.poll_answer_handler()
def handle_poll_answer(poll_answer):
    global current_poll_data
    user_id = poll_answer.user.id
    
    # Track Scores
    if user_id not in user_scores:
        user_scores[user_id] = {"name": poll_answer.user.first_name, "correct": 0, "wrong": 0, "score": 0.0}
    
    if poll_answer.poll_id == current_poll_data["poll_id"]:
        current_poll_data["current_voter_count"] += 1
        
        if poll_answer.option_ids[0] == current_poll_data["correct_id"]:
            user_scores[user_id]["correct"] += 1
            user_scores[user_id]["score"] += 1.0
        else:
            user_scores[user_id]["wrong"] += 1
            user_scores[user_id]["score"] -= 0.5

        # TRIGGER 1: If max students answered, close poll instantly
        if current_poll_data["current_voter_count"] >= current_poll_data["max_answers"]:
            current_poll_data["active"] = False 

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    global current_poll_data
    
    # TRIGGER 2: If someone clicks skip, close poll instantly
    if call.data.startswith("skip_"):
        if current_poll_data["active"] and call.data.replace("skip_", "") == current_poll_data["poll_id"]:
            current_poll_data["active"] = False
            bot.answer_callback_query(call.id, "Skipping to next question...")
            bot.edit_message_text("⏩ **Question skipped.**", GROUP_ID, call.message.message_id)

    elif call.data == "stop_quiz_admin":
        quiz_running[call.message.chat.id] = False
        bot.answer_callback_query(call.id, "Quiz will stop now.")

# ===== QUIZ ENGINE =====

def run_quiz(chat_id):
    global current_poll_data
    user_scores.clear()
    data = user_state[chat_id]
    
    # Load and filter questions
    full_pool = []
    for ch in data['chapters']: 
        full_pool.extend(question_bank[data['subject']].get(ch, []))
    
    recent = get_recent_questions()
    available = [q for q in full_pool if q not in recent]
    if len(available) < data['count']: available = full_pool 
    
    selected = random.sample(available, min(data['count'], len(available)))
    bot.send_message(GROUP_ID, f"🚀 **{data['subject'].upper()} QUIZ STARTED!**")

    for block in selected:
        if not quiz_running.get(chat_id): break

        # Parse Question
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        clean_q = [line for line in lines if not line.lower().startswith("#")][0]
        options = [lines[1][3:], lines[2][3:], lines[3][3:], lines[4][3:]]
        ans_letter = next(l for l in lines if "Answer:" in l).split(":")[-1].strip().upper()
        correct_idx = ord(ans_letter) - ord("A")

        # Send Poll
        poll_msg = bot.send_poll(
            GROUP_ID, clean_q, options, 
            type='quiz', correct_option_id=correct_idx, 
            is_anonymous=False, open_period=data['timer']
        )
        
        # Skip Button
        markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("⏭️ Skip Question", callback_data=f"skip_{poll_msg.poll.id}"))
        skip_msg = bot.send_message(GROUP_ID, "👆 Click to skip if disinterested.", reply_markup=markup)

        current_poll_data.update({
            "poll_id": poll_msg.poll.id, 
            "message_id": poll_msg.message_id, 
            "active": True, 
            "correct_id": correct_idx,
            "max_answers": data['max_answers'],
            "current_voter_count": 0
        })

        # Speed Loop: Monitor triggers every 0.1 seconds
        start_t = time.time()
        while time.time() - start_t < data['timer']:
            if not current_poll_data["active"] or not quiz_running.get(chat_id):
                break 
            time.sleep(0.1)

        # Immediate Cleanup and Next Question
        try:
            bot.stop_poll(GROUP_ID, poll_msg.message_id)
            bot.delete_message(GROUP_ID, skip_msg.message_id)
        except: pass
        
        mark_used(block)
        current_poll_data["active"] = False
        time.sleep(1) # Short gap between questions

    bot.send_message(GROUP_ID, "🏁 **Quiz Finished!** Check /scorecard")

# ===== ADMIN SETUP & COMMANDS =====

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "🤖 **Quiz Fast-Bot**\n/admin - Start\n/scorecard - Stats")

@bot.message_handler(commands=['admin'])
def admin_prompt(message):
    user_step[message.chat.id] = "key"
    bot.send_message(message.chat.id, "🔑 Key?")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "key")
def check_key(message):
    if message.text == ADMIN_KEY:
        user_step[message.chat.id] = "sub"
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True).add("Biology", "Math", "Reasoning", "Physics", "Chemistry")
        bot.send_message(message.chat.id, "Subject?", reply_markup=markup)

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "sub")
def set_sub(message):
    sub = message.text.lower()
    if sub in question_bank:
        user_state[message.chat.id] = {'subject': sub}
        user_step[message.chat.id] = "mode"
        bot.send_message(message.chat.id, "Mode?", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("Mix (All) 🎯", "Chapter-wise 📂"))

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "mode")
def set_mode(message):
    sub = user_state[message.chat.id]['subject']
    if "Mix" in message.text:
        user_state[message.chat.id]['chapters'] = list(question_bank[sub].keys())
        user_step[message.chat.id] = "count"
        bot.send_message(message.chat.id, "Count?")
    else:
        user_step[message.chat.id] = "ch"
        selected_chapters[message.chat.id] = set()
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        for ch in question_bank[sub]: markup.add(ch)
        markup.add("DONE")
        bot.send_message(message.chat.id, "Chapters?", reply_markup=markup)

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "ch")
def handle_ch_sel(message):
    if message.text == "DONE":
        user_state[message.chat.id]['chapters'] = list(selected_chapters[message.chat.id])
        user_step[message.chat.id] = "count"
        bot.send_message(message.chat.id, "Count?")
    else:
        selected_chapters[message.chat.id].add(message.text)
        bot.send_message(message.chat.id, f"Added {message.text}")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "count")
def set_count(message):
    user_state[message.chat.id]['count'] = int(message.text)
    user_step[message.chat.id] = "timer"
    bot.send_message(message.chat.id, "Timer (sec)?")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "timer")
def set_timer(message):
    user_state[message.chat.id]['timer'] = int(message.text)
    user_step[message.chat.id] = "max"
    bot.send_message(message.chat.id, "Stop question after how many answers?")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "max")
def set_max(message):
    user_state[message.chat.id]['max_answers'] = int(message.text)
    user_step[message.chat.id] = "ready"
    bot.send_message(message.chat.id, "Ready!", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("START 🚀"))

@bot.message_handler(func=lambda m: m.text == "START 🚀" and user_step.get(m.chat.id) == "ready")
def go(message):
    quiz_running[message.chat.id] = True
    markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🛑 STOP", callback_data="stop_quiz_admin"))
    bot.send_message(message.chat.id, "Admin Controls", reply_markup=markup)
    threading.Thread(target=run_quiz, args=(message.chat.id,)).start()

@bot.message_handler(commands=['scorecard'])
def show_scores(message):
    if not user_scores: return bot.send_message(message.chat.id, "No data.")
    s = sorted(user_scores.values(), key=lambda x: x['score'], reverse=True)
    bot.send_message(message.chat.id, "\n".join([f"{u['name']}: {u['score']} pts" for u in s[:10]]))

if __name__ == "__main__":
    bot.infinity_polling()
