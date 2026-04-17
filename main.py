import telebot
from telebot import types
import os
import random
import time
import threading

# Initialize Bot
API_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(API_TOKEN, threaded=True, num_threads=20)

ADMIN_KEY = "Eshu2005aru"
GROUP_ID = -1003746627836 

# ===== DATA STORAGE =====
question_bank = {} 
user_state = {}
user_step = {}
selected_chapters = {}
user_scores = {} 
used_questions = set()
quiz_active = {} 
skipped_this_q = set() 

current_poll_data = {
    "poll_id": None,
    "message_id": None,
    "active": False,
    "correct_id": None,
    "max_answers": 3,
    "skip_count": 0,
    "total_voters": 0
}

# ===== 1. LOAD QUESTIONS =====
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
        except: pass

load_questions()

# ===== 2. HANDLERS =====

def init_user(uid, name):
    if uid not in user_scores:
        user_scores[uid] = {"name": name, "correct": 0, "wrong": 0, "skip": 0, "score": 0.0}

@bot.poll_answer_handler()
def handle_poll_answer(poll_answer):
    uid = poll_answer.user.id
    init_user(uid, poll_answer.user.first_name)
    if poll_answer.poll_id == current_poll_data["poll_id"]:
        current_poll_data["total_voters"] += 1
        if poll_answer.option_ids[0] == current_poll_data["correct_id"]:
            user_scores[uid]["correct"] += 1
            user_scores[uid]["score"] += 1.0
        else:
            user_scores[uid]["wrong"] += 1
            user_scores[uid]["score"] -= 0.5

@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    uid = call.from_user.id
    if call.data == "skip_question":
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
        bot.answer_callback_query(call.id, "🛑 Stopping...")

# ===== 3. SCORECARD GENERATOR =====

def get_report_text():
    if not user_scores: return "📊 No data available."
    sorted_data = sorted(user_scores.values(), key=lambda x: x['score'], reverse=True)
    report = "📋 **DETAILED QUIZ REPORT** 📋\n━━━━━━━━━━━━━━\n"
    for u in sorted_data:
        total_q = u['correct'] + u['wrong'] + u['skip']
        report += (f"👤 **{u['name']}**\n"
                   f"📝 Total: {total_q} Qs\n"
                   f"✅ Correct: {u['correct']}\n"
                   f"❌ Wrong: {u['wrong']}\n"
                   f"⏩ Skipped: {u['skip']}\n"
                   f"🏆 **Score: {u['score']}**\n"
                   f"━━━━━━━━━━━━━━\n")
    return report

@bot.message_handler(commands=['scorecard', 'result'])
def show_scorecard(message):
    bot.send_message(message.chat.id, get_report_text(), parse_mode="Markdown")

# ===== 4. ADMIN SETUP =====

@bot.message_handler(commands=['admin'])
def admin(message):
    user_step[message.chat.id] = "admin_key"
    bot.send_message(message.chat.id, "🔑 **Enter Admin Key:**")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "admin_key")
def check_admin(message):
    if message.text == ADMIN_KEY:
        user_step[message.chat.id] = "subject"
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True).add("Biology", "Math", "Reasoning", "Physics", "Chemistry")
        bot.send_message(message.chat.id, "📚 **Subject:**", reply_markup=markup)

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "subject")
def handle_sub(message):
    sub = message.text.lower()
    user_state[message.chat.id] = {'subject': sub}
    user_step[message.chat.id] = "mode"
    bot.send_message(message.chat.id, "🎯 **Mode:**", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("Mix (All) 🎯", "Chapter-wise 📂"))

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "mode")
def handle_mode(message):
    sub = user_state[message.chat.id]['subject']
    if "Mix" in message.text:
        user_state[message.chat.id]['chapters'] = list(question_bank[sub].keys())
        user_step[message.chat.id] = "count"
        bot.send_message(message.chat.id, "🔢 **Count:**")
    else:
        user_step[message.chat.id] = "chapter"
        selected_chapters[message.chat.id] = set()
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        for ch in question_bank[sub]: markup.add(ch)
        markup.add("DONE ✅")
        bot.send_message(message.chat.id, "Select chapters:", reply_markup=markup)

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "chapter")
def select_ch(message):
    if message.text == "DONE ✅":
        user_state[message.chat.id]['chapters'] = list(selected_chapters[message.chat.id])
        user_step[message.chat.id] = "count"
        bot.send_message(message.chat.id, "🔢 **Count:**")
    else:
        selected_chapters[message.chat.id].add(message.text)
        bot.send_message(message.chat.id, f"➕ {message.text}")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "count")
def save_count(message):
    user_state[message.chat.id]['count'] = int(message.text)
    user_step[message.chat.id] = "timer"
    bot.send_message(message.chat.id, "⏱️ **Timer:**")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "timer")
def save_timer(message):
    user_state[message.chat.id]['timer'] = int(message.text)
    user_step[message.chat.id] = "max_ans"
    bot.send_message(message.chat.id, "👤 **Answer Limit:**")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "max_ans")
def save_max(message):
    user_state[message.chat.id]['max_answers'] = int(message.text)
    user_step[message.chat.id] = "ready"
    bot.send_message(message.chat.id, "Ready!", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).add("START QUIZ 🚀"))

# ===== 5. ENGINE =====

@bot.message_handler(func=lambda m: m.text == "START QUIZ 🚀" and user_step.get(m.chat.id) == "ready")
def trigger_quiz(message):
    quiz_active[GROUP_ID] = True
    stop_markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("🛑 STOP QUIZ", callback_data="stop_quiz"))
    bot.send_message(message.chat.id, "🚀 Quiz started in group.", reply_markup=stop_markup)
    threading.Thread(target=run_quiz, args=(message.chat.id,)).start()

def run_quiz(chat_id):
    global current_poll_data, used_questions, skipped_this_q
    user_scores.clear()
    data = user_state[chat_id]
    sub = data['subject']
    
    full_pool = []
    for ch in data['chapters']: full_pool.extend(question_bank[sub].get(ch, []))
    available = [q for q in full_pool if q not in used_questions]
    if len(available) < data['count']: available = full_pool; used_questions.clear()
    
    selected = random.sample(available, min(data['count'], len(available)))
    for q in selected: used_questions.add(q)

    bot.send_message(GROUP_ID, f"🔔 **{sub.upper()} QUIZ STARTED!**")

    for block in selected:
        if not quiz_active.get(GROUP_ID): break 
        
        current_poll_data.update({"skip_count": 0, "total_voters": 0})
        skipped_this_q.clear()
        
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        q_timer = data['timer']
        for line in lines:
            if line.lower().startswith("#time:"):
                try: q_timer = int(line.split(":")[1].strip())
                except: pass

        clean_q = [line for line in lines if not line.lower().startswith("#")][0]
        options = [lines[1][3:], lines[2][3:], lines[3][3:], lines[4][3:]]
        ans = next((l.split(":")[-1].strip() for l in lines if "Answer:" in l), "A")
        correct_idx = ord(ans) - ord("A")

        skip_markup = types.InlineKeyboardMarkup().add(types.InlineKeyboardButton("⏩ Skip", callback_data="skip_question"))
        poll_msg = bot.send_poll(GROUP_ID, clean_q, options, type='quiz', correct_option_id=correct_idx, is_anonymous=False, open_period=q_timer)
        btn_msg = bot.send_message(GROUP_ID, "Skip if you don't know:", reply_markup=skip_markup)

        current_poll_data.update({"poll_id": poll_msg.poll.id, "message_id": poll_msg.message_id, "active": True, "correct_id": correct_idx})

        start_t = time.time()
        while time.time() - start_t < q_timer:
            # CHECK LIMIT EVERY SECOND
            if (current_poll_data["total_voters"] + current_poll_data["skip_count"]) >= current_poll_data["max_answers"]:
                current_poll_data["active"] = False
                break
            if not quiz_active.get(GROUP_ID): break
            time.sleep(1)

        try:
            bot.delete_message(GROUP_ID, btn_msg.message_id)
            if current_poll_data["active"]: bot.stop_poll(GROUP_ID, poll_msg.message_id)
        except: pass
        current_poll_data["active"] = False
        time.sleep(2) 

    # SEND FINAL REPORT TO GROUP
    bot.send_message(GROUP_ID, get_report_text(), parse_mode="Markdown")
    bot.send_message(GROUP_ID, "🏁 **Quiz Finished!**")

if __name__ == "__main__":
    bot.infinity_polling(skip_pending=True)
