import telebot
import sqlite3
import queue
import threading
import requests
import schedule
import time
from telebot import types

TOKEN = '6177118870:AAFRYcdn905BX3GjZ-6KtwdHSIH_KcWAgYk'
ADMIN_ID = '902786019'
TMDB_API_KEY = '564937c29dc7d4268cd1a24ad2bc7d64'

bot = telebot.TeleBot(TOKEN)

with sqlite3.connect('anime.db') as conn:
    conn.execute('''
        CREATE TABLE IF NOT EXISTS anime (
            name TEXT,
            episode TEXT,
            file_id TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS user_anime (
            user_id INTEGER,
            anime_name TEXT
        )
    ''')

task_queue = queue.Queue()

def worker():
    while True:
        task = task_queue.get()
        if task is None:
            break
        task()
        task_queue.task_done()

threading.Thread(target=worker, daemon=True).start()

def get_anime_info(anime_name):
    response = requests.get(f'https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={anime_name}')
    data = response.json()

    if data['results']:
        anime_info = data['results'][0]
        description = anime_info['overview']
        poster_path = anime_info['poster_path']

        return description, f"https://image.tmdb.org/t/p/w500{poster_path}"

    return None, None

@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome_message = (
        "Привет! Я бот для просмотра аниме. Вот список команд, которые вы можете использовать:\n\n"
        "- `/anime`: Показывает список доступных аниме.\n"
        "- `/profile`: Показывает список аниме, которые вы добавили в список Смотрю.\n\n"
        "- `/search`: Выполняет поиск аниме.\n\n"
    )
    markup = types.ReplyKeyboardMarkup(row_width=3)
    itembtn1 = types.KeyboardButton('/anime')
    itembtn2 = types.KeyboardButton('/profile')
    itembtn3 = types.KeyboardButton('/search')
    markup.add(itembtn1, itembtn2, itembtn3)
    bot.send_message(message.chat.id, welcome_message, reply_markup=markup)

@bot.message_handler(content_types=['video'])
def handle_video(message):
    def task():
        if str(message.from_user.id) == ADMIN_ID:
            if message.caption:
                try:
                    anime_name, episode_number = message.caption.strip('"').split('",')
                    anime_name = anime_name.strip()
                    episode_number = episode_number.strip()

                    with sqlite3.connect('anime.db') as conn:
                        conn.execute("INSERT INTO anime VALUES (?, ?, ?)", (anime_name, episode_number, message.video.file_id))
                    bot.reply_to(message, f'Видео успешно загружено для аниме {anime_name}, серия {episode_number}.')
                except ValueError:
                    bot.reply_to(message, 'Пожалуйста, предоставьте название аниме и номер серии в подписи, используя следующий формат: "название аниме", номер серии.')
            else:
                bot.reply_to(message, 'Пожалуйста, предоставьте название аниме и номер серии в подписи, используя следующий формат: "название аниме", номер серии.')
    task_queue.put(task)

@bot.message_handler(commands=['anime'])
def send_anime_list(message):
    def task():
        with sqlite3.connect('anime.db') as conn:
            rows = conn.execute("SELECT name, COUNT(episode) FROM anime GROUP BY name")
        markup = types.InlineKeyboardMarkup()
        for row in rows:
            markup.add(types.InlineKeyboardButton(text=row[0], callback_data=f"list:{row[0]}"))
        bot.send_message(message.chat.id, 'Доступные аниме:', reply_markup=markup)
    task_queue.put(task)

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    def task():
        data = call.data.split(':')
        action = data[0]

        if action == 'list':
            anime_name = data[1]
            description, poster_url = get_anime_info(anime_name)

            with sqlite3.connect('anime.db') as conn:
                rows = conn.execute("SELECT episode FROM anime WHERE name = ?", (anime_name,)).fetchall()

            if rows:
                markup = types.InlineKeyboardMarkup()
                for row in rows:
                    markup.add(types.InlineKeyboardButton(text=row[0], callback_data=f"watch:{anime_name}:{row[0]}"))
                markup.add(types.InlineKeyboardButton(text="Добавить в список просмотра", callback_data=f"add_to_watchlist:{anime_name}"))
                markup.add(types.InlineKeyboardButton(text="Удалить из списка просмотра", callback_data=f"remove_from_watchlist:{anime_name}"))
                bot.send_photo(call.message.chat.id, poster_url, caption=f'{anime_name}\n{description}', reply_markup=markup)
            else:
                bot.answer_callback_query(call.id, 'Это аниме не найдено.')
        elif action == 'add_to_watchlist':
            anime_name = data[1]
            with sqlite3.connect('anime.db') as conn:
                # Проверяем, есть ли уже аниме в списке просмотра пользователя
                result = conn.execute("SELECT 1 FROM user_anime WHERE user_id = ? AND anime_name = ?", (call.from_user.id, anime_name)).fetchone()
                # Если аниме еще нет в списке, добавляем его
                if result is None:
                    conn.execute("INSERT INTO user_anime VALUES (?, ?)", (call.from_user.id, anime_name))
                    bot.answer_callback_query(call.id, f'Аниме {anime_name} было добавлено в ваш список просмотра.')
                else:
                    bot.answer_callback_query(call.id, f'Аниме {anime_name} уже есть в вашем списке просмотра.')
        elif action == 'remove_from_watchlist':
            anime_name = data[1]
            with sqlite3.connect('anime.db') as conn:
                conn.execute("DELETE FROM user_anime WHERE user_id = ? AND anime_name = ?", (call.from_user.id, anime_name))
            bot.answer_callback_query(call.id, f'Аниме {anime_name} было удалено из вашего списка просмотра.')
        else:
            anime_name, episode_number = data[1:]
            episode_number = int(episode_number)
            if action == 'prev':
                episode_number -= 1
            elif action == 'next':
                episode_number += 1

            with sqlite3.connect('anime.db') as conn:
                result = conn.execute("SELECT file_id FROM anime WHERE name = ? AND episode = ?", (anime_name, episode_number)).fetchone()

            if result is not None:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton(text="Предыдущая серия", callback_data=f"prev:{anime_name}:{episode_number}"),
                           types.InlineKeyboardButton(text="Следующая серия", callback_data=f"next:{anime_name}:{episode_number}"),
                           types.InlineKeyboardButton(text="Вернуться к списку серий", callback_data=f"list:{anime_name}"))
                bot.edit_message_media(types.InputMediaVideo(result[0], caption=f'Серия {episode_number} аниме {anime_name}'), call.message.chat.id, call.message.message_id, reply_markup=markup)
            else:
                bot.answer_callback_query(call.id, 'Этот эпизод аниме не найден.')
    task_queue.put(task)

@bot.message_handler(commands=['delete'])
def delete_anime_episode(message):
    def task():
        if str(message.from_user.id) == ADMIN_ID:
            command = message.text.split(' ', 2)
            if len(command) < 3:
                bot.reply_to(message, 'Пожалуйста, укажите название аниме и номер серии.')
                return

            anime_name = command[1]
            episode_number = command[2]

            with sqlite3.connect('anime.db') as conn:
                conn.execute("DELETE FROM anime WHERE name = ? AND episode = ?", (anime_name, episode_number))

            bot.reply_to(message, f'Серия {episode_number} аниме {anime_name} была удалена.')
        else:
            bot.reply_to(message, 'Только администратор может удалять серии.')
    task_queue.put(task)

@bot.message_handler(commands=['delete_all'])
def delete_all_anime_episodes(message):
    def task():
        if str(message.from_user.id) == ADMIN_ID:
            command = message.text.split(' ', 1)
            if len(command) < 2:
                bot.reply_to(message, 'Пожалуйста, укажите название аниме.')
                return

            anime_name = command[1]

            with sqlite3.connect('anime.db') as conn:
                conn.execute("DELETE FROM anime WHERE name = ?", (anime_name,))

            bot.reply_to(message, f'Все серии аниме {anime_name} были удалены.')
        else:
            bot.reply_to(message, 'Только администратор может удалять все серии аниме.')
    task_queue.put(task)

@bot.message_handler(commands=['profile'])
def show_profile(message):
    with sqlite3.connect('anime.db') as conn:
        rows = conn.execute("SELECT anime_name FROM user_anime WHERE user_id = ?",
                                (message.from_user.id,)).fetchall()
    if rows:
        anime_list = '\n'.join(row[0] for row in rows)
        markup = types.InlineKeyboardMarkup()
        for row in rows:
            markup.add(types.InlineKeyboardButton(text=row[0], callback_data=f"list:{row[0]}"))
        bot.send_message(message.chat.id, f'Вы смотрите следующие аниме:\n{anime_list}', reply_markup=markup)
    else:
        bot.reply_to(message, 'Вы пока не смотрите ни одного аниме.')

USER_STATE = {}

def set_user_state(user_id, state):
    USER_STATE[user_id] = state

def get_user_state(user_id):
    return USER_STATE.get(user_id)

@bot.message_handler(commands=['search'])
def search_anime(message):
    set_user_state(message.from_user.id, 'SEARCH')
    bot.reply_to(message, 'Введите название аниме')

@bot.message_handler(func=lambda message: get_user_state(message.from_user.id) == 'SEARCH')
def handle_search(message):
    anime_name = message.text
    with sqlite3.connect('anime.db') as conn:
        rows = conn.execute("SELECT name FROM anime WHERE name LIKE ?", ('%' + anime_name + '%',)).fetchall()
    if rows:
        markup = types.InlineKeyboardMarkup()
        for row in rows:
            markup.add(types.InlineKeyboardButton(text=row[0], callback_data=f"list:{row[0]}"))
        bot.send_message(message.chat.id, 'Вот что я нашел:', reply_markup=markup)
    else:
        bot.reply_to(message, 'Извините, я не смог найти аниме с таким названием.')
    set_user_state(message.from_user.id, None)

bot.polling()