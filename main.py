import telebot
from telebot import types
import os
import random
import time
import threading # Added for non-blocking quiz loops

API_TOKEN = os.getenv("BOT_TOKEN")
bot = telebot.TeleBot(API_TOKEN)

ADMIN_KEY = "Eshu2005aru"
GROUP_ID = -1003746627836

# ===== DATA =====
question_bank = {}
user_state = {}
user_step = {}
selected_chapters = {}
active_quizzes = {} # Track if a quiz is running per chat

# ===== LOAD QUESTIONS =====
def load_questions():
    try:
        # Ensure directory exists
        if not os.path.exists("questions/biology.txt"):
            print("File not found: questions/biology.txt")
            return

        with open("questions/biology.txt", "r", encoding="utf-8") as f:
            content = f.read()

        # Split by double newline to get blocks
        blocks = content.strip().split("\n\n")
        current_chapter = "General"

        for block in blocks:
            lines = [line.strip() for line in block.split("\n") if line.strip()]
            
            # Check for chapter header
            header_line = next((l for l in lines if l.startswith("#chapter:")), None)
            if header_line:
                current_chapter = header_line.split(":")[1].strip()
                continue # Skip the header block itself

            # Validate block has question, 4 options, and answer
            if len(lines) >= 6 and "Answer:" in lines[-1]:
                question_bank.setdefault("biology", {}).setdefault(current_chapter, []).append(lines)

        print(f"Questions loaded: {len(question_bank.get('biology', {}))} chapters found. ✅")

    except Exception as e:
        print("Error loading questions:", e)

load_questions()

# ===== QUIZ LOGIC (Threaded) =====
def run_quiz_thread(chat_id, data):
    chapters = data['chapters']
    count = data['count']
    timer = data['timer']
    
    pool = []
    for ch in chapters:
        pool.extend(question_bank["biology"].get(ch, []))
    
    # Safely sample questions
    num_to_send = min(count, len(pool))
    questions = random.sample(pool, num_to_send)

    bot.send_message(chat_id, f"🚀 Starting quiz with {num_to_send} questions!")

    for lines in questions:
        # Check if quiz was stopped (optional logic)
        question_text = lines[0]
        options = [lines[1][3:], lines[2][3:], lines[3][3:], lines[4][3:]]
        
        # Parse Answer (Expected format: "Answer: A")
        ans_line = lines[-1]
        ans_char = ans_line.split(":")[-1].strip().upper()
        correct_idx = ord(ans_char) - ord("A")

        try:
            bot.send_poll(
                chat_id=GROUP_ID,
                question=question_text,
                options=options,
                type="quiz",
                correct_option_id=correct_idx,
                is_anonymous=False,
                open_period=timer
            )
        except Exception as e:
            print(f"Error sending poll: {e}")
        
        time.sleep(timer + 2) # Buffer for Telegram processing

    bot.send_message(chat_id, "🏁 Quiz Finished!")

# ===== HANDLERS =====

@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(message.chat.id, "👋 Welcome! Use /admin to configure the quiz.")

@bot.message_handler(commands=['admin'])
def admin(message):
    user_step[message.chat.id] = "admin_key"
    bot.send_message(message.chat.id, "🔑 Enter Admin Key:")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "admin_key")
def check_admin(message):
    if message.text == ADMIN_KEY:
        user_step[message.chat.id] = "subject"
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add("Biology")
        bot.send_message(message.chat.id, "✅ Access Granted. Choose Subject:", reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "❌ Wrong key.")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "subject")
def handle_subject(message):
    user_state[message.chat.id] = {}
    user_step[message.chat.id] = "mode"
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("Mix 🎯", "Chapter-wise 📂")
    bot.send_message(message.chat.id, "Choose Mode:", reply_markup=markup)

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "mode")
def handle_mode(message):
    if message.text == "Mix 🎯":
        user_state[message.chat.id]['chapters'] = list(question_bank["biology"].keys())
        user_step[message.chat.id] = "count"
        bot.send_message(message.chat.id, "🔢 Enter number of questions:")
    elif message.text == "Chapter-wise 📂":
        user_step[message.chat.id] = "chapter"
        selected_chapters[message.chat.id] = set()
        show_chapters(message.chat.id)

def show_chapters(chat_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    for ch in question_bank["biology"]:
        markup.add(ch)
    markup.add("DONE ✅")
    bot.send_message(chat_id, "Select chapters then click DONE:", reply_markup=markup)

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "chapter")
def select_chapter(message):
    if message.text == "DONE ✅":
        if not selected_chapters.get(message.chat.id):
            return bot.send_message(message.chat.id, "Please select at least one chapter!")
        user_state[message.chat.id]['chapters'] = list(selected_chapters[message.chat.id])
        user_step[message.chat.id] = "count"
        bot.send_message(message.chat.id, "🔢 Enter number of questions:")
    else:
        selected_chapters[message.chat.id].add(message.text)
        bot.send_message(message.chat.id, f"✅ Added: {message.text}")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "count")
def save_count(message):
    try:
        user_state[message.chat.id]['count'] = int(message.text)
        user_step[message.chat.id] = "timer"
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("15", "30", "45", "60")
        bot.send_message(message.chat.id, "⏱️ Select seconds per question:", reply_markup=markup)
    except:
        bot.send_message(message.chat.id, "❌ Please send a valid number.")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "timer")
def save_timer(message):
    try:
        user_state[message.chat.id]['timer'] = int(message.text)
        user_step[message.chat.id] = "ready"
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("START QUIZ 🚀")
        bot.send_message(message.chat.id, "Ready to go?", reply_markup=markup)
    except:
        bot.send_message(message.chat.id, "❌ Select from the options.")

@bot.message_handler(func=lambda m: user_step.get(m.chat.id) == "ready")
def start_quiz(message):
    if message.text == "START QUIZ 🚀":
        data = user_state.get(message.chat.id)
        # Run quiz in a separate thread so the bot stays responsive
        threading.Thread(target=run_quiz_thread, args=(message.chat.id, data)).start()
        user_step[message.chat.id] = None # Reset state

# ===== RUN =====
print("Bot Running...")
bot.polling(none_stop=True)
