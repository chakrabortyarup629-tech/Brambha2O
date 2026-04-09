import telebot
from telebot import types
import os
import random
import time
import threading

# Initialize Bot
API_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(API_TOKEN, threaded=True, num_threads=10)

ADMIN_KEY = "Eshu2005aru"
GROUP_ID = -1003746627836 

# ===== DATA STORAGE =====
question_bank = {}
user_state = {}
user_step = {}
selected_chapters = {}
user_scores = {} # Detailed tracking for Scorecard

# ===== QUIZ TRACKER =====
current_poll_data = {
    "poll_id": None,
    "message_id": None,
    "active": False,
    "correct_id": None,
    "max_answers": 3 
}

# ===== 1. LOAD QUESTIONS =====
def load_questions():
    try:
        path = "questions/biology.txt"
        if not os.path.exists(path):
            print("❌ biology.txt not found")
            return
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        current_chapter = ""
        for block in text.split("\n\n"):
            lines = block.strip().split("\n")
            for line in lines:
                if line.startswith("#chapter:"):
                    current_chapter = line.split(":")[1].strip()
            if "Answer:" in block:
                question_bank.setdefault("biology", {}).setdefault(current_chapter, []).append(block)
        print("Questions loaded ✅")
    except Exception as e:
        print("Error loading questions:", e)

load_questions()

# ===== 2. POLL HANDLERS (Scorecard & Auto-Close) =====

@bot.poll_answer_handler()
def handle_poll_answer(poll_answer):
    user_id = poll_answer.user.id
    user_name = poll_answer.user.first_name
    
    if user_id not in user_scores:
        user_scores[user_id] = {"name": user_name, "correct": 0, "wrong": 0, "total": 0, "score": 0.0}

    if poll_answer.poll_id == current_poll_data["poll_id"]:
        user_scores[user_id]["total"] += 1
        selected_id = poll_answer.option_ids[0]
        
        if selected_id == current_poll_data["correct_id"]:
            user_scores[user_id]["correct"] += 1
            user_scores[user_id]["score"] += 1.0
        else:
            user_scores[user_id]["wrong"] += 1
            user_scores[user_id]["score"] -= 0.5 # Negative Marking

@bot.poll_handler(func=lambda poll: True)
def watch_poll_limit(poll):
    global current_poll_data
    if poll.id == current_poll_data["poll_id"]:
        limit = current_poll_data["max_answers"]
        if poll.total_voter_count >= limit and current_poll_data["active"]:
            try:
                bot.stop_poll(GROUP_ID, current_poll_data["message_id"])
                current_poll_data["active"] = False 
            except:
                pass

# ===== 3. ADMIN SETUP FLOW =====

@bot.message_handler(commands=['admin'])
def admin(message):
    user_step[message.chat.id] = "admin_key"
    bot.send_message(message.chat.id, "🔑 Enter Admin Key:")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "admin_key")
def check_admin(message):
    if message.text == ADMIN_KEY:
        user_step[message.chat.id] = "mode"
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True).add("Mix (All) 🎯", "Chapter-wise 📂")
        bot.send_message(message.chat.id, "Choose Mode:", reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "❌ Wrong Key")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "mode")
def handle_mode(message):
    chat_id = message.chat.id
    if message.text == "Mix (All) 🎯":
        user_state[chat_id] = {'chapters': list(question_bank["biology"].keys())}
        user_step[chat_id] = "count"
        bot.send_message(chat_id, "🔢 Total Questions:")
    else:
        user_step[chat_id] = "chapter"
        selected_chapters[chat_id] = set()
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        for ch in question_bank["biology"]: markup.add(ch)
        markup.add("DONE ✅")
        bot.send_message(chat_id, "Select chapters:", reply_markup=markup)

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "chapter")
def select_chapter(message):
    if message.text == "DONE ✅":
        user_state[message.chat.id] = {'chapters': list(selected_chapters[message.chat.id])}
        user_step[message.chat.id] = "count"
        bot.send_message(message.chat.id, "🔢 Total Questions:")
    else:
        selected_chapters[message.chat.id].add(message.text)
        bot.send_message(message.chat.id, f"✅ Added: {message.text}")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "count")
def save_count(message):
    user_state[message.chat.id]['count'] = int(message.text)
    user_step[message.chat.id] = "timer"
    bot.send_message(message.chat.id, "⏱️ Timer per question (sec):")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "timer")
def save_timer(message):
    user_state[message.chat.id]['timer'] = int(message.text)
    user_step[message.chat.id] = "max_ans"
    bot.send_message(message.chat.id, "👤 Auto-close after how many students answer?")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "max_ans")
def save_max_ans(message):
    user_state[message.chat.id]['max_answers'] = int(message.text)
    user_step[message.chat.id] = "start"
    bot.send_message(message.chat.id, "Ready?", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("START QUIZ 🚀"))

# ===== 4. QUIZ ENGINE =====

def run_quiz(chat_id):
    global current_poll_data
    user_scores.clear() # Reset scorecard for new quiz
    data = user_state[chat_id]
    
    pool = []
    for ch in data['chapters']:
        pool.extend(question_bank["biology"].get(ch, []))
    
    selected = random.sample(pool, min(data['count'], len(pool)))
    current_poll_data["max_answers"] = data['max_answers']

    bot.send_message(GROUP_ID, f"🚀 **Quiz Started!**\nQuestions: {len(selected)}\nLimit: {data['max_answers']} answers")

    for block in selected:
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        question = lines[0]
        options = [lines[1][3:], lines[2][3:], lines[3][3:], lines[4][3:]]
        ans = "A"
        for l in lines:
            if "Answer:" in l: ans = l.split(":")[-1].strip()
        correct_idx = ord(ans) - ord("A")

        poll_msg = bot.send_poll(GROUP_ID, question, options, type='quiz', correct_option_id=correct_idx, is_anonymous=False)

        current_poll_data.update({
            "poll_id": poll_msg.poll.id,
            "message_id": poll_msg.message_id,
            "active": True,
            "correct_id": correct_idx
        })

        # Wait Loop
        start_time = time.time()
        while time.time() - start_time < data['timer']:
            if not current_poll_data["active"]: break 
            time.sleep(1)

        if current_poll_data["active"]:
            try: bot.stop_poll(GROUP_ID, poll_msg.message_id)
            except: pass
            current_poll_data["active"] = False
        
        time.sleep(2) 

    bot.send_message(GROUP_ID, "🏁 Quiz Over! Use /scorecard to see results.")

@bot.message_handler(func=lambda m: m.text == "START QUIZ 🚀")
def trigger_quiz(message):
    threading.Thread(target=run_quiz, args=(message.chat.id,)).start()
    bot.send_message(message.chat.id, "Quiz is running...")

# ===== 5. DETAILED SCORECARD COMMAND =====

@bot.message_handler(commands=['scorecard', 'leaderboard'])
def show_scorecard(message):
    if not user_scores:
        return bot.send_message(message.chat.id, "📊 No results to show yet.")
    
    sorted_data = sorted(user_scores.values(), key=lambda x: x['score'], reverse=True)
    report = "📋 **DETAILED QUIZ RESULT** 📋\n━━━━━━━━━━━━━━━━━━━━\n"
    
    for u in sorted_data:
        report += (
            f"👤 **{u['name']}**\n"
            f"🔹 Attended: {u['total']}\n"
            f"✅ Correct: {u['correct']}\n"
            f"❌ Wrong: {u['wrong']}\n"
            f"🏆 **Final Score: {u['score']}**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
        )
    
    bot.send_message(message.chat.id, report, parse_mode="Markdown")

if __name__ == "__main__":
    bot.remove_webhook()
    bot.infinity_polling()
