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
bot = telebot.TeleBot(API_TOKEN, threaded=True, num_threads=15)

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
    conn = sqlite3.connect('quiz_history.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO history VALUES (?, ?)", (q_text, datetime.now()))
    conn.commit()
    conn.close()

def get_recent_questions():
    conn = sqlite3.connect('quiz_history.db')
    c = conn.cursor()
    one_month_ago = datetime.now() - timedelta(days=30)
    c.execute("SELECT q_text FROM history WHERE used_date > ?", (one_month_ago,))
    rows = c.fetchall()
    conn.close()
    return {row[0] for row in rows}

init_db()

# ===== DATA STORAGE =====
question_bank = {} 
user_state = {}
user_step = {}
selected_chapters = {}
user_scores = {} 
skip_votes = {} # {poll_id: set(user_ids)}
quiz_running = {} # {chat_id: bool}

current_poll_data = {
    "poll_id": None,
    "message_id": None,
    "skip_msg_id": None,
    "active": False,
    "correct_id": None,
    "max_answers": 3 
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

# ===== HANDLERS =====

@bot.poll_answer_handler()
def handle_poll_answer(poll_answer):
    user_id = poll_answer.user.id
    if user_id not in user_scores:
        user_scores[user_id] = {"name": poll_answer.user.first_name, "correct": 0, "wrong": 0, "total": 0, "score": 0.0}
    
    if poll_answer.poll_id == current_poll_data["poll_id"]:
        user_scores[user_id]["total"] += 1
        if poll_answer.option_ids[0] == current_poll_data["correct_id"]:
            user_scores[user_id]["correct"] += 1
            user_scores[user_id]["score"] += 1.0
        else:
            user_scores[user_id]["wrong"] += 1
            user_scores[user_id]["score"] -= 0.5

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    global current_poll_data
    
    if call.data.startswith("skip_"):
        poll_id = call.data.replace("skip_", "")
        if not current_poll_data["active"] or poll_id != current_poll_data["poll_id"]:
            return bot.answer_callback_query(call.id, "Question already closed!")

        user_id = call.from_user.id
        skip_votes.setdefault(poll_id, set()).add(user_id)
        
        count = len(skip_votes[poll_id])
        target = current_poll_data["max_answers"]

        if count >= target:
            current_poll_data["active"] = False # Signals run_quiz to move on
            bot.edit_message_text(f"⏩ **Skipped by consensus ({count}/{target})**", GROUP_ID, call.message.message_id)
        else:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton(f"⏭️ Skip ({count}/{target})", callback_data=call.data))
            bot.edit_message_reply_markup(GROUP_ID, call.message.message_id, reply_markup=markup)
            bot.answer_callback_query(call.id, f"Vote added: {count}/{target}")

    elif call.data == "stop_quiz_admin":
        quiz_running[call.message.chat.id] = False
        bot.edit_message_text("🛑 **Stop command received. Finishing current question...**", call.message.chat.id, call.message.message_id)

# ===== COMMANDS =====

@bot.message_handler(commands=['start'])
def start(message):
    user_step[message.chat.id] = None 
    bot.send_message(message.chat.id, "👋 **Quiz Bot 3.0**\n/admin - Setup\n/scorecard - Results\n/stop - Emergency Stop")

@bot.message_handler(commands=['admin'])
def admin_cmd(message):
    user_step[message.chat.id] = "admin_key"
    bot.send_message(message.chat.id, "🔑 **Enter Admin Key:**")

@bot.message_handler(commands=['stop'])
def stop_cmd(message):
    quiz_running[message.chat.id] = False
    bot.send_message(message.chat.id, "🛑 Quiz marked to stop.")

@bot.message_handler(commands=['scorecard'])
def scorecard(message):
    if not user_scores: return bot.send_message(message.chat.id, "📊 No records.")
    sorted_data = sorted(user_scores.values(), key=lambda x: x['score'], reverse=True)
    report = "📋 **TOP RESULTS**\n"
    for i, u in enumerate(sorted_data[:10]):
        report += f"{i+1}. **{u['name']}** | ⭐ {u['score']}\n"
    bot.send_message(message.chat.id, report)

# ===== ADMIN FLOW =====

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "admin_key")
def check_key(message):
    if message.text == ADMIN_KEY:
        user_step[message.chat.id] = "subject"
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True).add("Biology", "Math", "Reasoning", "Physics", "Chemistry")
        bot.send_message(message.chat.id, "📚 **Select Subject:**", reply_markup=markup)
    else: bot.send_message(message.chat.id, "❌ Invalid.")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "subject")
def set_sub(message):
    sub = message.text.lower()
    if sub in question_bank:
        user_state[message.chat.id] = {'subject': sub}
        user_step[message.chat.id] = "mode"
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True).add("Mix (All) 🎯", "Chapter-wise 📂")
        bot.send_message(message.chat.id, "Select Mode:", reply_markup=markup)

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "mode")
def set_mode(message):
    sub = user_state[message.chat.id]['subject']
    if message.text == "Mix (All) 🎯":
        user_state[message.chat.id]['chapters'] = list(question_bank[sub].keys())
        user_step[message.chat.id] = "count"
        bot.send_message(message.chat.id, "🔢 **Question Count:**")
    else:
        user_step[message.chat.id] = "chapter"
        selected_chapters[message.chat.id] = set()
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        for ch in question_bank[sub]: markup.add(ch)
        markup.add("DONE ✅")
        bot.send_message(message.chat.id, "Select chapters:", reply_markup=markup)

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "chapter")
def set_ch(message):
    if message.text == "DONE ✅":
        user_state[message.chat.id]['chapters'] = list(selected_chapters[message.chat.id])
        user_step[message.chat.id] = "count"
        bot.send_message(message.chat.id, "🔢 **Question Count:**")
    else:
        selected_chapters[message.chat.id].add(message.text)
        bot.send_message(message.chat.id, f"✅ Added {message.text}")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "count")
def set_count(message):
    user_state[message.chat.id]['count'] = int(message.text)
    user_step[message.chat.id] = "timer"
    bot.send_message(message.chat.id, "⏱️ **Seconds per question:**")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "timer")
def set_timer(message):
    user_state[message.chat.id]['timer'] = int(message.text)
    user_step[message.chat.id] = "max_ans"
    bot.send_message(message.chat.id, "👤 **Votes needed to Skip/Stop Poll:**")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "max_ans")
def set_max(message):
    user_state[message.chat.id]['max_answers'] = int(message.text)
    user_step[message.chat.id] = "ready"
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True).add("START QUIZ 🚀")
    bot.send_message(message.chat.id, "Setup complete!", reply_markup=markup)

# ===== QUIZ ENGINE =====

@bot.message_handler(func=lambda m: m.text == "START QUIZ 🚀" and user_step.get(m.chat.id) == "ready")
def start_quiz_thread(message):
    quiz_running[message.chat.id] = True
    # Control panel for admin
    markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🛑 STOP QUIZ", callback_data="stop_quiz_admin"))
    bot.send_message(message.chat.id, "🎮 **Admin Control Panel**", reply_markup=markup)
    
    threading.Thread(target=run_quiz, args=(message.chat.id,)).start()

def run_quiz(chat_id):
    global current_poll_data
    user_scores.clear()
    data = user_state[chat_id]
    
    # Filter 1-month memory
    full_pool = []
    for ch in data['chapters']: full_pool.extend(question_bank[data['subject']].get(ch, []))
    
    recent = get_recent_questions()
    available = [q for q in full_pool if q not in recent]
    
    if len(available) < data['count']:
        available = full_pool # Reset if not enough new questions
    
    selected = random.sample(available, min(data['count'], len(available)))
    bot.send_message(GROUP_ID, f"🔔 **{data['subject'].upper()} QUIZ BEGUN!**")

    for block in selected:
        if not quiz_running.get(chat_id): break

        lines = [l.strip() for l in block.split("\n") if l.strip()]
        clean_q = [line for line in lines if not line.lower().startswith("#")][0]
        options = [lines[1][3:], lines[2][3:], lines[3][3:], lines[4][3:]]
        
        ans_line = next(l for l in lines if "Answer:" in l)
        ans_letter = ans_line.split(":")[-1].strip().upper()
        correct_idx = ord(ans_letter) - ord("A")

        poll_msg = bot.send_poll(
            GROUP_ID, clean_q, options, 
            type='quiz', correct_option_id=correct_idx, 
            is_anonymous=False, open_period=data['timer']
        )
        
        # Democratic Skip Button
        markup = types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton(f"⏭️ Skip (0/{data['max_answers']})", callback_data=f"skip_{poll_msg.poll.id}")
        )
        skip_msg = bot.send_message(GROUP_ID, "🗳️ **Need a skip?**", reply_markup=markup)

        current_poll_data.update({
            "poll_id": poll_msg.poll.id, 
            "message_id": poll_msg.message_id, 
            "skip_msg_id": skip_msg.message_id,
            "active": True, 
            "correct_id": correct_idx,
            "max_answers": data['max_answers']
        })

        # Wait loop (checks for timer, skip consensus, or admin stop)
        start_t = time.time()
        while time.time() - start_t < data['timer']:
            if not current_poll_data["active"] or not quiz_running.get(chat_id): break
            time.sleep(1)

        # Cleanup current question
        try:
            bot.stop_poll(GROUP_ID, poll_msg.message_id)
            bot.delete_message(GROUP_ID, skip_msg.message_id)
        except: pass
        
        mark_used(block) # Remember this question for 1 month
        current_poll_data["active"] = False
        time.sleep(2) 

    bot.send_message(GROUP_ID, "🏁 **Quiz Finished!** Check /scorecard")

if __name__ == "__main__":
    bot.infinity_polling(skip_pending=True)
            
