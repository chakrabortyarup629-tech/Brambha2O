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

# ===== QUIZ TRACKER =====
current_poll_data = {
    "poll_id": None,
    "message_id": None,
    "active": False,
    "correct_id": None,
    "max_answers": 3 
}

# ===== 1. LOAD ALL SUBJECTS =====
def load_questions():
    # Added Physics and Chemistry to the supported list
    subjects = ["biology", "math", "reasoning", "physics", "chemistry"]
    for sub in subjects:
        try:
            path = f"questions/{sub}.txt"
            if not os.path.exists(path):
                print(f"⚠️ Missing file: {path}")
                continue
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            current_chapter = "General"
            for block in text.split("\n\n"):
                block = block.strip()
                if "Answer:" in block:
                    lines = block.split("\n")
                    for line in lines:
                        if line.lower().startswith("#chapter:"):
                            current_chapter = line.split(":")[1].strip()
                    question_bank.setdefault(sub, {}).setdefault(current_chapter, []).append(block)
            print(f"✅ {sub.capitalize()} loaded successfully.")
        except Exception as e:
            print(f"❌ Error loading {sub}: {e}")

load_questions()

# ===== 2. PRIMARY COMMANDS =====

@bot.message_handler(commands=['start'])
def start(message):
    user_step[message.chat.id] = None 
    bot.send_message(message.chat.id, "👋 **Welcome to Quiz Bot!**\n\nCommands:\n/admin - Start Setup\n/scorecard - Detailed Results\n/leaderboard - Quick Standings", parse_mode="Markdown")

@bot.message_handler(commands=['admin'])
def admin(message):
    user_step[message.chat.id] = "admin_key"
    bot.send_message(message.chat.id, "🔑 **Enter Admin Access Key:**", parse_mode="Markdown")

@bot.message_handler(commands=['scorecard', 'leaderboard', 'result'])
def show_scorecard(message):
    if not user_scores:
        return bot.send_message(message.chat.id, "📊 No quiz data available yet.")
    
    sorted_data = sorted(user_scores.values(), key=lambda x: x['score'], reverse=True)
    report = "📋 **QUIZ ANALYTICS REPORT** 📋\n━━━━━━━━━━━━━━━━━━━━\n"
    
    for u in sorted_data:
        report += (
            f"👤 **{u['name']}**\n"
            f"✅ Correct: {u['correct']}  |  ❌ Wrong: {u['wrong']}\n"
            f"🏆 **Final Score: {u['score']}**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
        )
    bot.send_message(message.chat.id, report, parse_mode="Markdown")

# ===== 3. VOTE TRACKING & NEGATIVE MARKING =====

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
            user_scores[user_id]["score"] -= 0.5 # Negative Marking 0.5

@bot.poll_handler(func=lambda poll: True)
def watch_poll_limit(poll):
    if poll.id == current_poll_data["poll_id"]:
        if poll.total_voter_count >= current_poll_data["max_answers"] and current_poll_data["active"]:
            try:
                bot.stop_poll(GROUP_ID, current_poll_data["message_id"])
                current_poll_data["active"] = False
            except: pass

# ===== 4. ADMIN CONFIGURATION FLOW =====

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "admin_key")
def check_admin(message):
    if message.text == ADMIN_KEY:
        user_step[message.chat.id] = "subject"
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        # Added Physics and Chemistry buttons
        markup.add("Biology", "Math", "Reasoning", "Physics", "Chemistry")
        bot.send_message(message.chat.id, "📚 **Select Subject:**", reply_markup=markup, parse_mode="Markdown")
    else:
        bot.send_message(message.chat.id, "❌ Incorrect Key.")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "subject")
def handle_subject(message):
    sub = message.text.lower()
    if sub in question_bank:
        user_state[message.chat.id] = {'subject': sub}
        user_step[message.chat.id] = "mode"
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True).add("Mix (All) 🎯", "Chapter-wise 📂")
        bot.send_message(message.chat.id, f"✅ Selected: {message.text}\nChoose Mode:", reply_markup=markup)
    else: bot.send_message(message.chat.id, "❌ Error: Subject file empty or missing.")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "mode")
def handle_mode(message):
    sub = user_state[message.chat.id]['subject']
    if message.text == "Mix (All) 🎯":
        user_state[message.chat.id]['chapters'] = list(question_bank[sub].keys())
        user_step[message.chat.id] = "count"
        bot.send_message(message.chat.id, "🔢 **How many questions?**")
    else:
        user_step[message.chat.id] = "chapter"
        selected_chapters[message.chat.id] = set()
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        for ch in question_bank[sub]: markup.add(ch)
        markup.add("DONE ✅")
        bot.send_message(message.chat.id, "Select chapters (one by one) then click DONE:", reply_markup=markup)

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "chapter")
def select_chapter(message):
    if message.text == "DONE ✅":
        if not selected_chapters.get(message.chat.id):
             return bot.send_message(message.chat.id, "❌ Select at least one chapter!")
        user_state[message.chat.id]['chapters'] = list(selected_chapters[message.chat.id])
        user_step[message.chat.id] = "count"
        bot.send_message(message.chat.id, "🔢 **How many questions?**")
    else:
        selected_chapters[message.chat.id].add(message.text)
        bot.send_message(message.chat.id, f"➕ Added: {message.text}")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "count")
def save_count(message):
    try:
        user_state[message.chat.id]['count'] = int(message.text)
        user_step[message.chat.id] = "timer"
        bot.send_message(message.chat.id, "⏱️ **Timer per question (Seconds):**")
    except: bot.send_message(message.chat.id, "❌ Enter a number.")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "timer")
def save_timer(message):
    try:
        user_state[message.chat.id]['timer'] = int(message.text)
        user_step[message.chat.id] = "max_ans"
        bot.send_message(message.chat.id, "👤 **Answer limit to close poll early:**")
    except: bot.send_message(message.chat.id, "❌ Enter a number.")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "max_ans")
def save_max_ans(message):
    try:
        user_state[message.chat.id]['max_answers'] = int(message.text)
        user_step[message.chat.id] = "start_ready"
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True).add("START QUIZ 🚀")
        bot.send_message(message.chat.id, "⚙️ Configuration Complete!", reply_markup=markup)
    except: bot.send_message(message.chat.id, "❌ Enter a number.")

# ===== 5. QUIZ ENGINE =====

@bot.message_handler(func=lambda m: m.text == "START QUIZ 🚀" and user_step.get(m.chat.id) == "start_ready")
def trigger_quiz(message):
    threading.Thread(target=run_quiz_thread, args=(message.chat.id,)).start()
    bot.send_message(message.chat.id, "🚀 Quiz started in the group!")

def run_quiz_thread(chat_id):
    global current_poll_data
    user_scores.clear() # Fresh start for every quiz
    data = user_state[chat_id]
    sub = data['subject']
    
    # Mix selection logic
    pool = []
    for ch in data['chapters']:
        pool.extend(question_bank[sub].get(ch, []))
    
    selected = random.sample(pool, min(data['count'], len(pool)))
    current_poll_data["max_answers"] = data['max_answers']

    bot.send_message(GROUP_ID, f"🔔 **ATTENTION: {sub.upper()} QUIZ BEGINS!**")

    for block in selected:
        # Parse logic
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        question = lines[0]
        options = [lines[1][3:], lines[2][3:], lines[3][3:], lines[4][3:]]
        ans = "A"
        for l in lines:
            if "Answer:" in l: ans = l.split(":")[-1].strip()
        correct_idx = ord(ans) - ord("A")

        poll_msg = bot.send_poll(GROUP_ID, question, options, type='quiz', correct_option_id=correct_idx, is_anonymous=False)
        timer_msg = bot.send_message(GROUP_ID, f"⏱️ Time: {data['timer']}s")

        current_poll_data.update({"poll_id": poll_msg.poll.id, "message_id": poll_msg.message_id, "active": True, "correct_id": correct_idx})

        # Countdown logic
        start_t = time.time()
        while time.time() - start_t < data['timer']:
            if not current_poll_data["active"]: break
            # Update visible timer every 5s
            elapsed = int(time.time() - start_t)
            if elapsed > 0 and elapsed % 5 == 0:
                try: bot.edit_message_text(f"⏱️ Time Left: {data['timer'] - elapsed}s", GROUP_ID, timer_msg.message_id)
                except: pass
            time.sleep(1)

        # Cleanup
        try:
            bot.delete_message(GROUP_ID, timer_msg.message_id)
            if current_poll_data["active"]: bot.stop_poll(GROUP_ID, poll_msg.message_id)
        except: pass
        current_poll_data["active"] = False
        time.sleep(2) # Short break between questions

    bot.send_message(GROUP_ID, "🏁 **Quiz Completed!**\nUse /scorecard to check your stats.")

# ===== STARTUP =====
if __name__ == "__main__":
    print("Bot is alive...")
    bot.remove_webhook()
    time.sleep(1)
    bot.infinity_polling(skip_pending=True)
