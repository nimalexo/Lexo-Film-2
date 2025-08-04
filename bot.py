import sqlite3
import os
import asyncio
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
)
from dotenv import load_dotenv

# --- Load Environment Variables ---
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
PRIVATE_CHANNEL_ID = int(os.getenv("PRIVATE_CHANNEL_ID"))

# --- Channels users must join ---
CHANNELS_TO_JOIN = ["@lexobit"]

# Define states for the search conversation
GET_MOVIE_NAME = 1

# --- Database Functions ---
def connect_db():
    """Connects to the database and creates tables if they don't exist."""
    db_conn = sqlite3.connect("videos.db", check_same_thread=False)
    cursor = db_conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS videos (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, message_id INTEGER NOT NULL);")
    cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY);")
    db_conn.commit()
    return db_conn, cursor

# --- Membership Check Function ---
async def is_user_member(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Checks if a user is a member of all required channels."""
    for channel in CHANNELS_TO_JOIN:
        try:
            member = await context.bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                return False
        except Exception:
            return False
    return True

# --- Main Bot Functions ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /start command, registers new users, shows the menu, or handles deep links."""
    user = update.message.from_user
    try:
        db_conn, cursor = connect_db()
        cursor.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user.id,))
        db_conn.commit()
        db_conn.close()
    except Exception as e:
        print(f"Error registering user: {e}")
    
    if context.args and len(context.args) > 0:
        await send_video_by_id(update, context, context.args[0])
        return

    keyboard = [["🔍 Search Movie"], ["📊 Bot Stats", "❓ Help"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        f"Hello {user.first_name}! 👋\n\nWelcome to the Movie Bot. Please choose an option from the menu below:",
        reply_markup=reply_markup
    )

async def send_video_by_id(update: Update, context: ContextTypes.DEFAULT_TYPE, video_id: str):
    """Sends a video based on its ID (for deep linking), checking membership first."""
    if not await is_user_member(update.message.from_user.id, context):
        buttons = []
        for channel in CHANNELS_TO_JOIN:
            buttons.append([InlineKeyboardButton(f"Join {channel}", url=f"https://t.me/{channel.lstrip('@')}")])
        reply_markup = InlineKeyboardMarkup(buttons)
        await update.message.reply_text(
            "❌ To get this file, you must first join our channel(s). After joining, please click the original link again.",
            reply_markup=reply_markup
        )
        return

    db_conn, cursor = connect_db()
    cursor.execute("SELECT message_id FROM videos WHERE id = ?", (video_id,))
    result = cursor.fetchone()
    db_conn.close()
    if result:
        message_id_to_copy = result[0]
        try:
            sent_video = await context.bot.copy_message(chat_id=update.message.chat_id, from_chat_id=PRIVATE_CHANNEL_ID, message_id=message_id_to_copy)
            warning_message = await update.message.reply_text("❗️ This file will be automatically deleted in 30 seconds.")
            ids_to_delete = [sent_video.message_id, warning_message.message_id]
            asyncio.create_task(delete_messages_after_delay(context.bot, update.message.chat_id, ids_to_delete, 30))
        except Exception as e:
            await update.message.reply_text(f"Sorry, an error occurred while sending the file: {e}")
    else:
        await update.message.reply_text("Sorry, the link is invalid or the requested movie was not found. 😔")

# --- Search Conversation Functions ---

async def ask_for_movie_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Asks the user for the movie name after checking membership."""
    if not await is_user_member(update.message.from_user.id, context):
        buttons = []
        for channel in CHANNELS_TO_JOIN:
            buttons.append([InlineKeyboardButton(f"Join {channel}", url=f"https://t.me/{channel.lstrip('@')}")])
        reply_markup = InlineKeyboardMarkup(buttons)
        await update.message.reply_text(
            "❌ To use the bot, you must first join our channel(s). After joining, please click the '🔍 Search Movie' button again.",
            reply_markup=reply_markup
        )
        return ConversationHandler.END

    await update.message.reply_text("Please send the name of the movie you want to search for. To cancel, type /cancel.")
    return GET_MOVIE_NAME

async def search_received_movie_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receives the movie name and searches for it."""
    query = update.message.text
    db_conn, cursor = connect_db()
    cursor.execute("SELECT message_id FROM videos WHERE name LIKE ?", (f"%{query}%",))
    result = cursor.fetchone()
    db_conn.close()

    if result:
        message_id_to_copy = result[0]
        try:
            sent_video = await context.bot.copy_message(chat_id=update.message.chat_id, from_chat_id=PRIVATE_CHANNEL_ID, message_id=message_id_to_copy)
            warning_message = await update.message.reply_text("❗️ This file will be automatically deleted in 30 seconds.")
            ids_to_delete = [sent_video.message_id, warning_message.message_id]
            asyncio.create_task(delete_messages_after_delay(context.bot, update.message.chat_id, ids_to_delete, 30))
        except Exception as e:
            await update.message.reply_text(f"Sorry, an error occurred while sending the file: {e}")
    else:
        await update.message.reply_text("Sorry, that movie could not be found. Please try again. 😔")
    
    return ConversationHandler.END

async def cancel_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels the search conversation."""
    await update.message.reply_text("Search operation has been canceled.")
    return ConversationHandler.END

# --- Other Commands and Menu Functions ---

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("To search for a movie, please use the '🔍 Search Movie' button from the menu.")

async def bot_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays bot statistics."""
    db_conn, cursor = connect_db()
    cursor.execute("SELECT COUNT(id) FROM videos")
    total_videos = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(user_id) FROM users")
    total_users = cursor.fetchone()[0]
    db_conn.close()
    await update.message.reply_text(f"📊 Bot Statistics:\n\nTotal Users: {total_users}\nTotal Movies: {total_videos}")

async def get_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates a deep link for a video (Admin only)."""
    if update.message.from_user.id != ADMIN_ID: return
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Usage: `/getlink Movie Name`")
        return
    db_conn, cursor = connect_db()
    cursor.execute("SELECT id FROM videos WHERE name LIKE ?", (f"%{query}%",))
    result = cursor.fetchone()
    db_conn.close()
    if result:
        video_id = result[0]
        link = f"https://t.me/{context.bot.username}?start={video_id}"
        await update.message.reply_text(f"Dedicated link for '{query}':\n\n`{link}`", parse_mode='Markdown')
    else:
        await update.message.reply_text("A movie with this name was not found.")

async def delete_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Deletes a video record from the database (Admin only)."""
    if update.message.from_user.id != ADMIN_ID: return
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text("Usage: `/delvideo Movie Name`")
        return
    db_conn, cursor = connect_db()
    cursor.execute("SELECT id FROM videos WHERE name LIKE ?", (f"%{query}%",))
    result = cursor.fetchone()
    if result:
        cursor.execute("DELETE FROM videos WHERE name LIKE ?", (f"%{query}%",))
        db_conn.commit()
        db_conn.close()
        await update.message.reply_text(f"✅ The record for '{query}' has been successfully deleted from the database.")
    else:
        db_conn.close()
        await update.message.reply_text("A movie with this name was not found in the database.")

# --- Background Functions ---

async def index_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Indexes new videos posted in the private channel."""
    if update.channel_post and update.channel_post.video:
        message = update.channel_post
        video_name = message.caption
        if not video_name:
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"⚠️ A video was posted in the channel without a caption and was not indexed.")
            return
        message_id = message.message_id
        try:
            db_conn, cursor = connect_db()
            cursor.execute("INSERT INTO videos (name, message_id) VALUES (?, ?)", (video_name.strip(), message_id))
            db_conn.commit()
            db_conn.close()
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"✅ The video '{video_name}' has been indexed successfully.")
        except sqlite3.IntegrityError:
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"⚠️ A video with the name '{video_name}' has already been registered.")
        except Exception as e:
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"Error during indexing: {e}")

async def delete_messages_after_delay(bot, chat_id, message_ids, delay):
    """A background task to delete a list of messages after a specified delay."""
    await asyncio.sleep(delay)
    for message_id in message_ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as e:
            print(f"Could not delete message {message_id}: {e}")

# --- Main Application Setup ---
def main():
    """Starts and runs the bot."""
    if not all([TELEGRAM_TOKEN, ADMIN_ID, PRIVATE_CHANNEL_ID]):
        print("Error: One or more environment variables are not set.")
        return
        
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # --- Conversation Handler for Search ---
    search_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 Search Movie$"), ask_for_movie_name)],
        states={
            GET_MOVIE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, search_received_movie_name)],
        },
        fallbacks=[CommandHandler("cancel", cancel_search)],
        per_message=False
    )
    application.add_handler(search_conv_handler)

    # --- Other Command and Message Handlers ---
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("getlink", get_link))
    application.add_handler(CommandHandler("stats", bot_stats))
    application.add_handler(CommandHandler("cancel", cancel_search)) 
    application.add_handler(CommandHandler("delvideo", delete_video))

    application.add_handler(MessageHandler(filters.Regex("^📊 Bot Stats$"), bot_stats))
    application.add_handler(MessageHandler(filters.Regex("^❓ Help$"), help_command))
    application.add_handler(MessageHandler(filters.Chat(chat_id=PRIVATE_CHANNEL_ID) & filters.VIDEO, index_video))
    
    print("Bot started successfully and is now polling...")
    application.run_polling()

if __name__ == "__main__":
    main()