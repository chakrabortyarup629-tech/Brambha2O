import telebot
from telebot import types
import os
import random
import time
import threading

# Initialize Bot
API_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(API_TOKEN, threaded=True, num_threads=15)

ADMIN_KEY = "Eshu2005aru"
GROUP_ID = -1003746627836 

# ===== DATA STORAGE =====
question_bank = {} 
user_state = {}
user_step = {}
selected_chapters = {}
user_scores = {} 

current_poll_data = {
    "poll_id": None,
    "message_id": None,
    "active": False,
    "correct_id": None,
    "max_answers": 3 
}

# ===== 1. SMART LOAD QUESTIONS =====
def load_questions():
    subjects = ["biology", "math", "reasoning", "physics", "chemistry"]
    for sub in subjects:
        try:
            path = f"questions/{sub}.txt"
            if not os.path.exists(path): continue
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            
            # Start with 'General' - it only stays 'General' if you don't use #chapter:
            current_chapter = "General" 
            blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
            
            for block in blocks:
                lines = block.split("\n")
                # Look for a NEW chapter tag
                for line in lines:
                    if line.lower().startswith("#chapter:"):
                        current_chapter = line.split(":")[1].strip()
                
                if "Answer:" in block:
                    # Stays in the 'current_chapter' until a new #chapter tag is found
                    question_bank.setdefault(sub, {}).setdefault(current_chapter, []).append(block)
            
            print(f"✅ {sub.capitalize()} loaded.")
        except Exception as e:
            print(f"❌ Error loading {sub}: {e}")

load_questions()

# ===== 2. POLL HANDLERS (Scores & Auto-Stop) =====

@bot.poll_answer_handler()
def handle_poll_answer(poll_answer):
    user_id = poll_answer.user.id
    name = poll_answer.user.first_name
    
    if user_id not in user_scores:
        user_scores[user_id] = {"name": name, "correct": 0, "wrong": 0, "total": 0, "score": 0.0}
    
    if poll_answer.poll_id == current_poll_data["poll_id"]:
        user_scores[user_id]["total"] += 1
        if poll_answer.option_ids[0] == current_poll_data["correct_id"]:
            user_scores[user_id]["correct"] += 1
            user_scores[user_id]["score"] += 1.0
        else:
            user_scores[user_id]["wrong"] += 1
            user_scores[user_id]["score"] -= 0.5 # Negative Marking

@bot.poll_handler(func=lambda poll: True)
def watch_poll_limit(poll):
    if poll.id == current_poll_data["poll_id"]:
        limit = current_poll_data["max_answers"]
        if poll.total_voter_count >= limit and current_poll_data["active"]:
            try:
                bot.stop_poll(GROUP_ID, current_poll_data["message_id"])
                current_poll_data["active"] = False
            except: pass

# ===== 3. PRIMARY COMMANDS =====

@bot.message_handler(commands=['start'])
def start(message):
    user_step[message.chat.id] = None 
    bot.send_message(message.chat.id, "👋 **Quiz Bot 2.0 Ready**\n/admin - Admin Setup\n/scorecard - Full Results Sheet")

@bot.message_handler(commands=['admin'])
def admin(message):
    user_step[message.chat.id] = "admin_key"
    bot.send_message(message.chat.id, "🔑 **Enter Admin Key:**")

@bot.message_handler(commands=['scorecard', 'result', 'leaderboard'])
def show_scorecard(message):
    if not user_scores:
        return bot.send_message(message.chat.id, "📊 No records found.")
    
    sorted_data = sorted(user_scores.values(), key=lambda x: x['score'], reverse=True)
    report = "📋 **DETAILED SCORECARD** 📋\n━━━━━━━━━━━━━━\n"
    for u in sorted_data:
        report += f"👤 **{u['name']}**\n✅ {u['correct']} | ❌ {u['wrong']} | 🏆 {u['score']} pts\n━━━━━━━━━━━━━━\n"
    bot.send_message(message.chat.id, report, parse_mode="Markdown")

# ===== 4. ADMIN SETUP =====

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "admin_key")
def check_admin(message):
    if message.text == ADMIN_KEY:
        user_step[message.chat.id] = "subject"
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        markup.add("Biology", "Math", "Reasoning", "Physics", "Chemistry")
        bot.send_message(message.chat.id, "📚 **Select Subject:**", reply_markup=markup)
    else: bot.send_message(message.chat.id, "❌ Wrong Key.")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "subject")
def handle_subject(message):
    sub = message.text.lower()
    if sub in question_bank:
        user_state[message.chat.id] = {'subject': sub}
        user_step[message.chat.id] = "mode"
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True).add("Mix (All) 🎯", "Chapter-wise 📂")
        bot.send_message(message.chat.id, "Choose Mode:", reply_markup=markup)
    else: bot.send_message(message.chat.id, "❌ No questions found for this subject.")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "mode")
def handle_mode(message):
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
        bot.send_message(message.chat.id, "Select chapters then DONE:", reply_markup=markup)

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "chapter")
def select_chapter(message):
    if message.text == "DONE ✅":
        user_state[message.chat.id]['chapters'] = list(selected_chapters[message.chat.id])
        user_step[message.chat.id] = "count"
        bot.send_message(message.chat.id, "🔢 **Question Count:**")
    else:
        selected_chapters[message.chat.id].add(message.text)
        bot.send_message(message.chat.id, f"➕ Added: {message.text}")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "count")
def save_count(message):
    user_state[message.chat.id]['count'] = int(message.text)
    user_step[message.chat.id] = "timer"
    bot.send_message(message.chat.id, "⏱️ **Seconds per poll:**")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "timer")
def save_timer(message):
    user_state[message.chat.id]['timer'] = int(message.text)
    user_step[message.chat.id] = "max_ans"
    bot.send_message(message.chat.id, "👤 **Max students to auto-close:**")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "max_ans")
def save_max_ans(message):
    user_state[message.chat.id]['max_answers'] = int(message.text)
    user_step[message.chat.id] = "start_ready"
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True).add("START QUIZ 🚀")
    bot.send_message(message.chat.id, "Ready to go!", reply_markup=markup)

# ===== 5. QUIZ ENGINE (With Circle Timer) =====

@bot.message_handler(func=lambda m: m.text == "START QUIZ 🚀" and user_step.get(m.chat.id) == "start_ready")
def trigger_quiz(message):
    threading.Thread(target=run_quiz, args=(message.chat.id,)).start()
    bot.send_message(message.chat.id, "🚀 Quiz Sequence Active!")

def run_quiz(chat_id):
    global current_poll_data
    user_scores.clear()
    data = user_state[chat_id]
    sub = data['subject']
    pool = []
    for ch in data['chapters']: pool.extend(question_bank[sub].get(ch, []))
    selected = random.sample(pool, min(data['count'], len(pool)))
    current_poll_data["max_answers"] = data['max_answers']

    bot.send_message(GROUP_ID, f"🔔 **{sub.upper()} QUIZ STARTED!**")

    for block in selected:
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        
        # Filter out metadata tags for the question text
        clean_q = [line for line in lines if not line.lower().startswith("#chapter:")][0]
        
        options = [lines[1][3:], lines[2][3:], lines[3][3:], lines[4][3:]]
        ans = "A"
        for l in lines:
            if "Answer:" in l: ans = l.split(":")[-1].strip()
        correct_idx = ord(ans) - ord("A")

        # NATIVE CIRCLE TIMER ENABLED HERE
        poll_msg = bot.send_poll(
            GROUP_ID, clean_q, options, 
            type='quiz', correct_option_id=correct_idx, 
            is_anonymous=False, 
            open_period=data['timer']
        )

        current_poll_data.update({"poll_id": poll_msg.poll.id, "message_id": poll_msg.message_id, "active": True, "correct_id": correct_idx})

        # Wait Loop for Early Closure
        start_t = time.time()
        while time.time() - start_t < data['timer']:
            if not current_poll_data["active"]: break 
            time.sleep(1)

        # Ensure poll is stopped if manual limit reached before timer
        if current_poll_data["active"]:
            try: bot.stop_poll(GROUP_ID, poll_msg.message_id)
            except: pass

        current_poll_data["active"] = False
        time.sleep(2) 

    bot.send_message(GROUP_ID, "🏁 **Quiz Finished!**\nUse /scorecard to see results.")

if __name__ == "__main__":
    bot.remove_webhook()
    time.sleep(1)
    bot.infinity_polling(skip_pending=True)
