#!/usr/bin/env python3
"""
Complete Telegram Group Manager Bot - All in One File
AI-powered moderation with profile picture integration
Credits: @RoronoaRaku
"""

import asyncio
import json
import os
import logging
import base64
import io
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import difflib
import re
from collections import defaultdict
import random

# Pyrogram imports
from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message, User, ChatMember, InlineKeyboardMarkup, InlineKeyboardButton,
    ChatPermissions, ChatPrivileges
)
from pyrogram.errors import MessageDeleteForbidden, UserNotParticipant

# PIL imports for image processing
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import requests

# OpenAI import
from openai import OpenAI

# ==================================================
# CONFIGURATION
# ==================================================

class Config:
    """Configuration settings for Group Manager Bot"""
    
    # Bot credentials
    API_ID = int(os.getenv("API_ID", "12345"))
    API_HASH = os.getenv("API_HASH", "your_api_hash")
    BOT_TOKEN = os.getenv("BOT_TOKEN", "7628249044:AAHbskBpfeOM7zJViZI8N4pfwjT-rXyAOHo")
    
    # OpenAI API
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "your_openai_api_key")
    
    # Owner and sudo users
    BOT_OWNER = int(os.getenv("BOT_OWNER", "7751041527"))
    SUDO_USERS = [BOT_OWNER]
    
    # Moderation settings
    MAX_WARNINGS = int(os.getenv("MAX_WARNINGS", "3"))
    AUTO_DELETE_DELAY = int(os.getenv("AUTO_DELETE_DELAY", "10"))
    FLOOD_THRESHOLD = int(os.getenv("FLOOD_THRESHOLD", "5"))
    
    # AI settings
    SPAM_THRESHOLD = float(os.getenv("SPAM_THRESHOLD", "0.7"))
    TOXICITY_THRESHOLD = float(os.getenv("TOXICITY_THRESHOLD", "0.8"))
    
    # Image settings
    WELCOME_IMAGE_SIZE = (800, 400)
    PROFILE_PIC_SIZE = (150, 150)
    
    # Time multipliers
    TIME_MULTIPLIERS = {
        's': 1,
        'm': 60,
        'h': 3600,
        'd': 86400,
        'w': 604800,
    }
    
    # Developer info
    DEVELOPER = "@RoronoaRaku"
    DEVELOPER_ID = 7751041527
    
    # File paths
    BANNED_WORDS_FILE = "data/banned_words.txt"
    TEMP_BANS_FILE = "data/temp_bans.json"
    TEMP_MUTES_FILE = "data/temp_mutes.json"
    USER_WARNINGS_FILE = "data/warnings.json"
    
    # Rate limiting
    RATE_LIMIT_MESSAGES = 10
    RATE_LIMIT_WINDOW = 60
    
    # Content filtering
    SIMILAR_MESSAGE_THRESHOLD = 0.8
    MAX_MESSAGE_LENGTH = 4000
    
    # Image settings
    MAX_IMAGE_SIZE = 10 * 1024 * 1024
    SUPPORTED_IMAGE_FORMATS = ['JPEG', 'PNG', 'WEBP']
    
    @classmethod
    def is_admin(cls, user_id: int) -> bool:
        """Check if user is bot admin"""
        return user_id in cls.SUDO_USERS
    
    @classmethod
    def parse_time(cls, time_str: str) -> int:
        """Parse time string to seconds"""
        if not time_str:
            return 0
        
        # Extract number and unit
        import re
        match = re.match(r'(\d+)([smhdw]?)', time_str.lower())
        if not match:
            return 0
        
        number, unit = match.groups()
        number = int(number)
        unit = unit or 's'
        
        return number * cls.TIME_MULTIPLIERS.get(unit, 1)

# ==================================================
# LOGGING SETUP
# ==================================================

def setup_logging():
    """Setup logging configuration"""
    os.makedirs("logs", exist_ok=True)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/bot.log'),
            logging.StreamHandler()
        ]
    )
    
    # Create separate loggers
    bot_logger = logging.getLogger('bot')
    error_logger = logging.getLogger('errors')
    moderation_logger = logging.getLogger('moderation')
    
    # Add file handlers
    bot_handler = logging.FileHandler('logs/bot.log')
    error_handler = logging.FileHandler('logs/errors.log')
    moderation_handler = logging.FileHandler('logs/moderation.log')
    
    bot_logger.addHandler(bot_handler)
    error_logger.addHandler(error_handler)
    moderation_logger.addHandler(moderation_handler)
    
    return bot_logger

logger = setup_logging()

# ==================================================
# UTILITY FUNCTIONS
# ==================================================

async def is_admin(client: Client, chat_id: int, user_id: int) -> bool:
    """Check if user is admin in chat"""
    try:
        member = await client.get_chat_member(chat_id, user_id)
        return member.status in [enums.ChatMemberStatus.OWNER, enums.ChatMemberStatus.ADMINISTRATOR]
    except:
        return False

async def get_user_info(client: Client, user_identifier: str) -> Optional[User]:
    """Get user info by username or ID"""
    try:
        if user_identifier.startswith('@'):
            user_identifier = user_identifier[1:]
        
        if user_identifier.isdigit():
            user = await client.get_users(int(user_identifier))
        else:
            user = await client.get_users(user_identifier)
        
        return user
    except:
        return None

async def log_action(client: Client, chat_id: int, action: str):
    """Log moderation action"""
    logger.info(f"Chat {chat_id}: [%s] %s", datetime.now().strftime('%Y-%m-%d %H:%M:%S'), action)

# ==================================================
# DATABASE FUNCTIONS
# ==================================================

async def save_temp_restriction(chat_id: int, user_id: int, restriction_type: str, 
                              until_date: datetime, reason: str = ""):
    """Save temporary restriction (ban/mute) to file"""
    try:
        file_path = Config.TEMP_BANS_FILE if restriction_type == "ban" else Config.TEMP_MUTES_FILE
        
        # Load existing data
        restrictions = {}
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                restrictions = json.load(f)
        
        # Save restriction
        chat_key = str(chat_id)
        if chat_key not in restrictions:
            restrictions[chat_key] = {}
        
        restrictions[chat_key][str(user_id)] = {
            "until_date": until_date.isoformat(),
            "reason": reason,
            "timestamp": datetime.now().isoformat()
        }
        
        # Save to file
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w') as f:
            json.dump(restrictions, f, indent=2)
            
    except Exception as e:
        logger.error(f"Failed to save temp restriction: {e}")

async def remove_temp_restriction(chat_id: int, user_id: int, restriction_type: str):
    """Remove temporary restriction from file"""
    try:
        file_path = Config.TEMP_BANS_FILE if restriction_type == "ban" else Config.TEMP_MUTES_FILE
        
        if not os.path.exists(file_path):
            return
        
        with open(file_path, 'r') as f:
            restrictions = json.load(f)
        
        chat_key = str(chat_id)
        user_key = str(user_id)
        
        if chat_key in restrictions and user_key in restrictions[chat_key]:
            del restrictions[chat_key][user_key]
            
            with open(file_path, 'w') as f:
                json.dump(restrictions, f, indent=2)
                
    except Exception as e:
        logger.error(f"Failed to remove temp restriction: {e}")

async def save_user_warning(chat_id: int, user_id: int, reason: str, warned_by: int) -> int:
    """Save user warning and return total warning count"""
    try:
        # Load existing warnings
        warnings = {}
        if os.path.exists(Config.USER_WARNINGS_FILE):
            with open(Config.USER_WARNINGS_FILE, 'r') as f:
                warnings = json.load(f)
        
        # Create chat entry if not exists
        chat_key = str(chat_id)
        if chat_key not in warnings:
            warnings[chat_key] = {}
        
        # Create user entry if not exists
        user_key = str(user_id)
        if user_key not in warnings[chat_key]:
            warnings[chat_key][user_key] = []
        
        # Add warning
        warning = {
            "reason": reason,
            "warned_by": warned_by,
            "timestamp": datetime.now().isoformat()
        }
        
        warnings[chat_key][user_key].append(warning)
        
        # Save to file
        os.makedirs(os.path.dirname(Config.USER_WARNINGS_FILE), exist_ok=True)
        with open(Config.USER_WARNINGS_FILE, 'w') as f:
            json.dump(warnings, f, indent=2)
        
        warning_count = len(warnings[chat_key][user_key])
        logger.info(f"Added warning for user {user_id} in chat {chat_id}. Total: {warning_count}")
        
        return warning_count
        
    except Exception as e:
        logger.error(f"Failed to save user warning: {e}")
        return 0

async def get_user_warnings(chat_id: int, user_id: int) -> List[Dict]:
    """Get all warnings for a user"""
    try:
        if not os.path.exists(Config.USER_WARNINGS_FILE):
            return []
        
        with open(Config.USER_WARNINGS_FILE, 'r') as f:
            warnings = json.load(f)
        
        chat_key = str(chat_id)
        user_key = str(user_id)
        
        if chat_key in warnings and user_key in warnings[chat_key]:
            return warnings[chat_key][user_key]
        
        return []
        
    except Exception as e:
        logger.error(f"Failed to get user warnings: {e}")
        return []

async def remove_user_warning(chat_id: int, user_id: int) -> bool:
    """Remove last warning for a user"""
    try:
        if not os.path.exists(Config.USER_WARNINGS_FILE):
            return False
        
        with open(Config.USER_WARNINGS_FILE, 'r') as f:
            warnings = json.load(f)
        
        chat_key = str(chat_id)
        user_key = str(user_id)
        
        if chat_key in warnings and user_key in warnings[chat_key]:
            if warnings[chat_key][user_key]:
                warnings[chat_key][user_key].pop()
                
                with open(Config.USER_WARNINGS_FILE, 'w') as f:
                    json.dump(warnings, f, indent=2)
                
                logger.info(f"Removed warning for user {user_id} in chat {chat_id}")
                return True
        
        return False
        
    except Exception as e:
        logger.error(f"Failed to remove user warning: {e}")
        return False

# ==================================================
# CONTENT FILTERING
# ==================================================

class ContentFilter:
    """Content filtering class for detecting inappropriate content"""
    
    def __init__(self):
        self.banned_words = set()
        self.load_banned_words()
    
    def load_banned_words(self):
        """Load banned words from file"""
        try:
            if os.path.exists(Config.BANNED_WORDS_FILE):
                with open(Config.BANNED_WORDS_FILE, 'r', encoding='utf-8') as f:
                    self.banned_words = {word.strip().lower() for word in f.readlines() if word.strip()}
                logger.info(f"Loaded {len(self.banned_words)} banned words")
            else:
                # Create default banned words file
                os.makedirs(os.path.dirname(Config.BANNED_WORDS_FILE), exist_ok=True)
                default_words = [
                    "spam", "scam", "fake", "fraud", "porn", "adult", "xxx",
                    "gambling", "casino", "bet", "lottery", "investment", "crypto"
                ]
                with open(Config.BANNED_WORDS_FILE, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(default_words))
                self.banned_words = set(default_words)
        except Exception as e:
            logger.error(f"Failed to load banned words: {e}")
            self.banned_words = set()
    
    def contains_banned_words(self, text: str) -> bool:
        """Check if text contains banned words"""
        if not text:
            return False
        
        text_lower = text.lower()
        for word in self.banned_words:
            if word in text_lower:
                logger.info(f"Banned word detected: {word}")
                return True
        return False
    
    def check_spam_patterns(self, text: str) -> dict:
        """Check text for various spam patterns"""
        if not text:
            return {"is_spam": False, "confidence": 0.0, "reasons": []}
        
        reasons = []
        confidence = 0.0
        
        # Check for excessive caps
        caps_ratio = sum(1 for c in text if c.isupper()) / len(text) if text else 0
        if caps_ratio > 0.5 and len(text) > 10:
            reasons.append("excessive_caps")
            confidence += 0.3
        
        # Check for excessive emojis
        emoji_count = len([c for c in text if ord(c) > 127])
        if emoji_count > len(text) * 0.3:
            reasons.append("excessive_emojis")
            confidence += 0.2
        
        # Check for repetitive characters
        if re.search(r'(.)\1{4,}', text):
            reasons.append("repetitive_chars")
            confidence += 0.2
        
        # Check for common spam phrases
        spam_phrases = ["click here", "free money", "earn money", "join now", "limited time"]
        for phrase in spam_phrases:
            if phrase.lower() in text.lower():
                reasons.append("spam_phrase")
                confidence += 0.4
                break
        
        return {
            "is_spam": confidence > 0.5,
            "confidence": min(confidence, 1.0),
            "reasons": reasons
        }

# ==================================================
# AI ANALYSIS
# ==================================================

class AIAnalyzer:
    """AI-powered content analysis using OpenAI"""
    
    def __init__(self):
        self.openai_client = OpenAI(api_key=Config.OPENAI_API_KEY) if Config.OPENAI_API_KEY != "your_openai_api_key" else None
    
    async def analyze_message_content(self, message_text: str) -> dict:
        """Analyze message content for spam, toxicity, and other issues"""
        if not self.openai_client or not message_text:
            return {"spam_score": 0.0, "toxicity_score": 0.0, "is_appropriate": True}
        
        try:
            prompt = f"""
            Analyze this message for spam and toxicity. Return JSON with:
            - spam_score (0.0-1.0): likelihood of being spam
            - toxicity_score (0.0-1.0): toxicity level
            - is_appropriate (boolean): suitable for group chat
            - issues (array): list of detected issues
            
            Message: "{message_text}"
            """
            
            response = self.openai_client.chat.completions.create(
                model="gpt-4o",  # the newest OpenAI model is "gpt-4o" which was released May 13, 2024. do not change this unless explicitly requested by the user
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            return result
            
        except Exception as e:
            logger.error(f"AI analysis failed: {e}")
            return {"spam_score": 0.0, "toxicity_score": 0.0, "is_appropriate": True}
    
    async def check_suspicious_account(self, user: User) -> dict:
        """Check if user account appears suspicious"""
        if not self.openai_client:
            return {"is_suspicious": False, "confidence": 0.0, "indicators": []}
        
        try:
            # Analyze user profile
            indicators = []
            confidence = 0.0
            
            # Check profile picture
            if not user.photo:
                indicators.append("no_profile_picture")
                confidence += 0.2
            
            # Check username patterns
            if user.username:
                if re.match(r'^[a-zA-Z]+\d{4,}$', user.username):
                    indicators.append("suspicious_username_pattern")
                    confidence += 0.3
            else:
                indicators.append("no_username")
                confidence += 0.1
            
            # Check name patterns
            if user.first_name:
                if len(user.first_name) < 2 or user.first_name.isdigit():
                    indicators.append("suspicious_name")
                    confidence += 0.2
            
            return {
                "is_suspicious": confidence > 0.4,
                "confidence": min(confidence, 1.0),
                "indicators": indicators
            }
            
        except Exception as e:
            logger.error(f"Suspicious account check failed: {e}")
            return {"is_suspicious": False, "confidence": 0.0, "indicators": []}

# ==================================================
# IMAGE PROCESSING
# ==================================================

class ImageProcessor:
    """Image processing for welcome/leave messages"""
    
    @staticmethod
    async def create_welcome_image(user: User, chat_title: str) -> Optional[bytes]:
        """Create welcome image with user profile picture"""
        try:
            # Create base image
            img = Image.new('RGB', Config.WELCOME_IMAGE_SIZE, color=(54, 57, 63))
            draw = ImageDraw.Draw(img)
            
            # Add gradient background
            for y in range(Config.WELCOME_IMAGE_SIZE[1]):
                color_ratio = y / Config.WELCOME_IMAGE_SIZE[1]
                r = int(54 + (88 - 54) * color_ratio)
                g = int(57 + (101 - 57) * color_ratio)
                b = int(63 + (242 - 63) * color_ratio)
                draw.line([(0, y), (Config.WELCOME_IMAGE_SIZE[0], y)], fill=(r, g, b))
            
            # Try to get user profile picture
            profile_img = None
            try:
                if user.photo:
                    # Note: This would require downloading the photo in a real implementation
                    # For now, create a placeholder
                    profile_img = Image.new('RGB', Config.PROFILE_PIC_SIZE, color=(100, 100, 100))
                else:
                    profile_img = Image.new('RGB', Config.PROFILE_PIC_SIZE, color=(100, 100, 100))
            except:
                profile_img = Image.new('RGB', Config.PROFILE_PIC_SIZE, color=(100, 100, 100))
            
            # Make profile picture circular
            mask = Image.new('L', Config.PROFILE_PIC_SIZE, 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse([0, 0] + list(Config.PROFILE_PIC_SIZE), fill=255)
            
            profile_img = profile_img.resize(Config.PROFILE_PIC_SIZE)
            profile_img.putalpha(mask)
            
            # Paste profile picture
            profile_x = (Config.WELCOME_IMAGE_SIZE[0] - Config.PROFILE_PIC_SIZE[0]) // 2
            profile_y = 50
            img.paste(profile_img, (profile_x, profile_y), profile_img)
            
            # Add text
            try:
                font_large = ImageFont.truetype("arial.ttf", 36)
                font_medium = ImageFont.truetype("arial.ttf", 24)
            except:
                font_large = ImageFont.load_default()
                font_medium = ImageFont.load_default()
            
            # Welcome text
            welcome_text = f"Welcome {user.first_name}!"
            text_bbox = draw.textbbox((0, 0), welcome_text, font=font_large)
            text_width = text_bbox[2] - text_bbox[0]
            text_x = (Config.WELCOME_IMAGE_SIZE[0] - text_width) // 2
            text_y = profile_y + Config.PROFILE_PIC_SIZE[1] + 30
            draw.text((text_x, text_y), welcome_text, fill='white', font=font_large)
            
            # Chat title
            chat_text = f"to {chat_title}"
            text_bbox = draw.textbbox((0, 0), chat_text, font=font_medium)
            text_width = text_bbox[2] - text_bbox[0]
            text_x = (Config.WELCOME_IMAGE_SIZE[0] - text_width) // 2
            text_y += 50
            draw.text((text_x, text_y), chat_text, fill='lightgray', font=font_medium)
            
            # Convert to bytes
            img_bytes = io.BytesIO()
            img.save(img_bytes, format='PNG')
            img_bytes.seek(0)
            
            return img_bytes.getvalue()
            
        except Exception as e:
            logger.error(f"Failed to create welcome image: {e}")
            return None

# ==================================================
# MESSAGE TEMPLATES
# ==================================================

class MessageTemplates:
    """Message templates for various bot responses"""
    
    WELCOME_TEMPLATES = [
        "🎉 **Welcome to {chat_title}!**\n\nHey {user_name}! 👋\nWe're excited to have you join our community!\n\nFeel free to introduce yourself and don't forget to read our rules! 📋",
        "🌟 **A warm welcome to {user_name}!**\n\nWelcome to {chat_title}! 🎊\nHope you have a great time here and make new friends! 🤝\n\nDon't hesitate to ask if you need any help! 💙",
        "🎈 **Welcome aboard, {user_name}!**\n\nYou've just joined {chat_title}! 🏠\nWe're a friendly community and we're happy to have you here! 😊\n\nEnjoy your stay and feel at home! 🌈"
    ]
    
    FAREWELL_TEMPLATES = [
        "👋 **Farewell, {user_name}!**\n\nIt's sad to see you leave {chat_title}... 😢\nHope to see you again someday! 🌟\n\nTake care and best wishes! 💙",
        "🚪 **{user_name} has left the building!**\n\nThanks for being part of {chat_title}! 🙏\nYou'll always be welcome back! 🏠\n\nUntil we meet again! ✨"
    ]
    
    @classmethod
    def get_welcome_message(cls, user: User, chat_title: str, is_suspicious: bool = False) -> str:
        """Get personalized welcome message"""
        template = random.choice(cls.WELCOME_TEMPLATES)
        message = template.format(
            user_name=user.first_name,
            chat_title=chat_title
        )
        
        if is_suspicious:
            message += "\n\n⚠️ **Note to admins:** This account shows suspicious indicators and may require verification."
        
        return message
    
    @classmethod
    def get_farewell_message(cls, user: User, chat_title: str) -> str:
        """Get personalized farewell message"""
        template = random.choice(cls.FAREWELL_TEMPLATES)
        return template.format(
            user_name=user.first_name,
            chat_title=chat_title
        )

# ==================================================
# MAIN BOT CLASS
# ==================================================

class GroupManagerBot:
    def __init__(self):
        self.app = Client(
            "group_manager_bot",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            bot_token=Config.BOT_TOKEN
        )
        
        self.content_filter = ContentFilter()
        self.ai_analyzer = AIAnalyzer()
        self.image_processor = ImageProcessor()
        
        # Message tracking for flood protection
        self.user_messages = defaultdict(list)
        self.user_message_history = defaultdict(list)
        
        self.register_handlers()
    
    def register_handlers(self):
        """Register all bot handlers"""
        # Basic commands
        self.app.on_message(filters.command("start"))(self.start_command)
        self.app.on_message(filters.command("help"))(self.help_command)
        self.app.on_message(filters.command("about"))(self.about_command)
        self.app.on_message(filters.command("credits"))(self.credits_command)
        
        # Admin commands
        self.register_admin_handlers()
        
        # Moderation commands
        self.register_moderation_handlers()
        
        # Welcome/leave handlers
        self.register_welcome_handlers()
        
        # Spam detection
        self.register_spam_handlers()
    
    def register_admin_handlers(self):
        """Register admin command handlers"""
        
        @self.app.on_message(filters.command("kick") & filters.group)
        async def kick_user(client, message):
            """Kick a user from the group"""
            if not await is_admin(client, message.chat.id, message.from_user.id):
                await message.reply_text("❌ **Access Denied**\nYou need admin privileges to use this command.")
                return
                
            try:
                # Get target user
                if message.reply_to_message:
                    user_to_kick = message.reply_to_message.from_user
                    reason = " ".join(message.command[1:]) if len(message.command) > 1 else "No reason specified"
                elif len(message.command) > 1:
                    user_to_kick = await get_user_info(client, message.command[1])
                    if not user_to_kick:
                        await message.reply_text("❌ User not found.")
                        return
                    reason = " ".join(message.command[2:]) if len(message.command) > 2 else "No reason specified"
                else:
                    await message.reply_text("📝 **Usage:** `/kick @username [reason]` or reply to a message")
                    return
                
                # Check if target is admin
                if await is_admin(client, message.chat.id, user_to_kick.id):
                    await message.reply_text("❌ Cannot kick an administrator.")
                    return
                
                # Create confirmation keyboard
                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Confirm Kick", callback_data=f"kick_confirm_{user_to_kick.id}"),
                        InlineKeyboardButton("❌ Cancel", callback_data=f"kick_cancel_{user_to_kick.id}")
                    ]
                ])
                
                await message.reply_text(
                    f"⚠️ **Confirm Kick**\n\n"
                    f"**User:** {user_to_kick.first_name} (@{user_to_kick.username or 'No username'})\n"
                    f"**Reason:** {reason}\n"
                    f"**Requested by:** {message.from_user.first_name}\n\n"
                    f"Are you sure you want to kick this user?",
                    reply_markup=keyboard
                )
                
            except Exception as e:
                logger.error(f"Error in kick command: {e}")
                await message.reply_text(f"❌ Error: {str(e)}")
        
        @self.app.on_callback_query(filters.regex("kick_confirm_"))
        async def confirm_kick(client, callback_query):
            """Confirm kick action"""
            user_id = int(callback_query.data.split("_")[2])
            
            try:
                await client.ban_chat_member(callback_query.message.chat.id, user_id)
                await client.unban_chat_member(callback_query.message.chat.id, user_id)
                
                await callback_query.edit_message_text(
                    f"👢 **User Kicked**\n\n"
                    f"**User ID:** `{user_id}`\n"
                    f"**Kicked by:** {callback_query.from_user.first_name}\n"
                    f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                
                await log_action(client, callback_query.message.chat.id, f"User {user_id} kicked by {callback_query.from_user.id}")
                
            except Exception as e:
                await callback_query.edit_message_text(f"❌ Failed to kick user: {str(e)}")
        
        @self.app.on_callback_query(filters.regex("kick_cancel_"))
        async def cancel_kick(client, callback_query):
            """Cancel kick action"""
            await callback_query.edit_message_text("❌ **Kick Cancelled**\n\nNo action was taken.")
        
        @self.app.on_message(filters.command("ban") & filters.group)
        async def ban_user(client, message):
            """Ban a user permanently"""
            if not await is_admin(client, message.chat.id, message.from_user.id):
                await message.reply_text("❌ **Access Denied**\nYou need admin privileges to use this command.")
                return
                
            try:
                # Get target user
                if message.reply_to_message:
                    user_to_ban = message.reply_to_message.from_user
                    reason = " ".join(message.command[1:]) if len(message.command) > 1 else "No reason specified"
                elif len(message.command) > 1:
                    user_to_ban = await get_user_info(client, message.command[1])
                    if not user_to_ban:
                        await message.reply_text("❌ User not found.")
                        return
                    reason = " ".join(message.command[2:]) if len(message.command) > 2 else "No reason specified"
                else:
                    await message.reply_text("📝 **Usage:** `/ban @username [reason]` or reply to a message")
                    return
                
                # Check if target is admin
                if await is_admin(client, message.chat.id, user_to_ban.id):
                    await message.reply_text("❌ Cannot ban an administrator.")
                    return
                
                # Create confirmation keyboard
                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("✅ Confirm Ban", callback_data=f"ban_confirm_{user_to_ban.id}"),
                        InlineKeyboardButton("❌ Cancel", callback_data=f"ban_cancel_{user_to_ban.id}")
                    ]
                ])
                
                await message.reply_text(
                    f"⚠️ **Confirm Ban**\n\n"
                    f"**User:** {user_to_ban.first_name} (@{user_to_ban.username or 'No username'})\n"
                    f"**Reason:** {reason}\n"
                    f"**Requested by:** {message.from_user.first_name}\n\n"
                    f"Are you sure you want to ban this user permanently?",
                    reply_markup=keyboard
                )
                
            except Exception as e:
                logger.error(f"Error in ban command: {e}")
                await message.reply_text(f"❌ Error: {str(e)}")
        
        @self.app.on_callback_query(filters.regex("ban_confirm_"))
        async def confirm_ban(client, callback_query):
            """Confirm ban action"""
            user_id = int(callback_query.data.split("_")[2])
            
            try:
                await client.ban_chat_member(callback_query.message.chat.id, user_id)
                
                await callback_query.edit_message_text(
                    f"🔨 **User Banned**\n\n"
                    f"**User ID:** `{user_id}`\n"
                    f"**Banned by:** {callback_query.from_user.first_name}\n"
                    f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                
                await log_action(client, callback_query.message.chat.id, f"User {user_id} banned by {callback_query.from_user.id}")
                
            except Exception as e:
                await callback_query.edit_message_text(f"❌ Failed to ban user: {str(e)}")
        
        @self.app.on_message(filters.command("tban") & filters.group)
        async def temp_ban_user(client, message):
            """Temporarily ban a user"""
            if not await is_admin(client, message.chat.id, message.from_user.id):
                await message.reply_text("❌ **Access Denied**\nYou need admin privileges to use this command.")
                return
                
            try:
                # Parse command
                if len(message.command) < 3 and not message.reply_to_message:
                    await message.reply_text(
                        "📝 **Usage:** `/tban @username 1h [reason]` or reply to message\n\n"
                        "**Time formats:**\n"
                        "• s = seconds\n"
                        "• m = minutes\n"
                        "• h = hours\n"
                        "• d = days\n\n"
                        "**Example:** `/tban @user 2h spamming`"
                    )
                    return
                    
                # Get target user
                if message.reply_to_message:
                    user_to_ban = message.reply_to_message.from_user
                    duration_str = message.command[1]
                    reason = " ".join(message.command[2:]) if len(message.command) > 2 else "No reason specified"
                else:
                    user_to_ban = await get_user_info(client, message.command[1])
                    if not user_to_ban:
                        await message.reply_text("❌ User not found.")
                        return
                    duration_str = message.command[2]
                    reason = " ".join(message.command[3:]) if len(message.command) > 3 else "No reason specified"
                
                # Parse duration
                duration_seconds = Config.parse_time(duration_str)
                if duration_seconds <= 0:
                    await message.reply_text("❌ Invalid time format. Use: 1h, 30m, 2d, etc.")
                    return
                
                # Check if target is admin
                if await is_admin(client, message.chat.id, user_to_ban.id):
                    await message.reply_text("❌ Cannot ban an administrator.")
                    return
                
                # Ban user
                until_date = datetime.now() + timedelta(seconds=duration_seconds)
                await client.ban_chat_member(
                    message.chat.id,
                    user_to_ban.id,
                    until_date=until_date
                )
                
                # Save temporary ban
                await save_temp_restriction(
                    message.chat.id, user_to_ban.id, "ban", until_date, reason
                )
                
                await message.reply_text(
                    f"⏰ **Temporary Ban Applied**\n\n"
                    f"**User:** {user_to_ban.first_name} (@{user_to_ban.username or 'No username'})\n"
                    f"**Duration:** {duration_str}\n"
                    f"**Reason:** {reason}\n"
                    f"**Unban Time:** {until_date.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"**Banned by:** {message.from_user.first_name}"
                )
                
                # Log action
                await log_action(
                    client, message.chat.id,
                    f"User {user_to_ban.id} temp banned for {duration_str} by {message.from_user.id}"
                )
                
            except Exception as e:
                logger.error(f"Error in tban command: {e}")
                await message.reply_text(f"❌ Error: {str(e)}")
        
        @self.app.on_message(filters.command("unban") & filters.group)
        async def unban_user(client, message):
            """Unban a user"""
            if not await is_admin(client, message.chat.id, message.from_user.id):
                await message.reply_text("❌ **Access Denied**\nYou need admin privileges to use this command.")
                return
                
            try:
                # Get target user
                if message.reply_to_message:
                    user_to_unban = message.reply_to_message.from_user
                elif len(message.command) > 1:
                    user_to_unban = await get_user_info(client, message.command[1])
                    if not user_to_unban:
                        await message.reply_text("❌ User not found.")
                        return
                else:
                    await message.reply_text("📝 **Usage:** `/unban @username` or reply to a message")
                    return
                
                # Unban user
                await client.unban_chat_member(message.chat.id, user_to_unban.id)
                
                # Remove from temp restrictions
                await remove_temp_restriction(message.chat.id, user_to_unban.id, "ban")
                
                await message.reply_text(
                    f"✅ **User Unbanned**\n\n"
                    f"**User:** {user_to_unban.first_name} (@{user_to_unban.username or 'No username'})\n"
                    f"**Unbanned by:** {message.from_user.first_name}\n"
                    f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                
                # Log action
                await log_action(
                    client, message.chat.id,
                    f"User {user_to_unban.id} unbanned by {message.from_user.id}"
                )
                
            except Exception as e:
                logger.error(f"Error in unban command: {e}")
                await message.reply_text(f"❌ Error: {str(e)}")
        
        @self.app.on_message(filters.command("mute") & filters.group)
        async def mute_user(client, message):
            """Mute a user"""
            if not await is_admin(client, message.chat.id, message.from_user.id):
                await message.reply_text("❌ **Access Denied**\nYou need admin privileges to use this command.")
                return
                
            try:
                # Get target user
                if message.reply_to_message:
                    user_to_mute = message.reply_to_message.from_user
                    reason = " ".join(message.command[1:]) if len(message.command) > 1 else "No reason specified"
                elif len(message.command) > 1:
                    user_to_mute = await get_user_info(client, message.command[1])
                    if not user_to_mute:
                        await message.reply_text("❌ User not found.")
                        return
                    reason = " ".join(message.command[2:]) if len(message.command) > 2 else "No reason specified"
                else:
                    await message.reply_text("📝 **Usage:** `/mute @username [reason]` or reply to a message")
                    return
                
                # Check if target is admin
                if await is_admin(client, message.chat.id, user_to_mute.id):
                    await message.reply_text("❌ Cannot mute an administrator.")
                    return
                
                # Mute user
                await client.restrict_chat_member(
                    message.chat.id,
                    user_to_mute.id,
                    ChatPermissions()
                )
                
                await message.reply_text(
                    f"🔇 **User Muted**\n\n"
                    f"**User:** {user_to_mute.first_name} (@{user_to_mute.username or 'No username'})\n"
                    f"**Reason:** {reason}\n"
                    f"**Muted by:** {message.from_user.first_name}\n"
                    f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                
                # Log action
                await log_action(
                    client, message.chat.id,
                    f"User {user_to_mute.id} muted by {message.from_user.id}"
                )
                
            except Exception as e:
                logger.error(f"Error in mute command: {e}")
                await message.reply_text(f"❌ Error: {str(e)}")
        
        @self.app.on_message(filters.command("promote") & filters.group)
        async def promote_user(client, message):
            """Promote a user to admin"""
            if not await is_admin(client, message.chat.id, message.from_user.id):
                await message.reply_text("❌ **Access Denied**\nYou need admin privileges to use this command.")
                return
                
            try:
                # Get target user
                if message.reply_to_message:
                    user_to_promote = message.reply_to_message.from_user
                    custom_title = " ".join(message.command[1:]) if len(message.command) > 1 else "Admin"
                elif len(message.command) > 1:
                    user_to_promote = await get_user_info(client, message.command[1])
                    if not user_to_promote:
                        await message.reply_text("❌ User not found.")
                        return
                    custom_title = " ".join(message.command[2:]) if len(message.command) > 2 else "Admin"
                else:
                    await message.reply_text("📝 **Usage:** `/promote @username [title]` or reply to a message")
                    return
                
                # Check if user is already admin
                if await is_admin(client, message.chat.id, user_to_promote.id):
                    await message.reply_text("❌ User is already an administrator.")
                    return
                
                # Promote user
                await client.promote_chat_member(
                    message.chat.id,
                    user_to_promote.id,
                    privileges=ChatPrivileges(
                        can_delete_messages=True,
                        can_restrict_members=True,
                        can_invite_users=True,
                        can_pin_messages=True,
                        can_promote_members=False
                    )
                )
                
                # Set custom title if provided
                if custom_title and custom_title != "Admin":
                    try:
                        await client.set_administrator_title(
                            message.chat.id,
                            user_to_promote.id,
                            custom_title
                        )
                    except:
                        pass
                
                await message.reply_text(
                    f"⬆️ **User Promoted**\n\n"
                    f"**User:** {user_to_promote.first_name} (@{user_to_promote.username or 'No username'})\n"
                    f"**Title:** {custom_title}\n"
                    f"**Promoted by:** {message.from_user.first_name}\n"
                    f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                
                # Log action
                await log_action(
                    client, message.chat.id,
                    f"User {user_to_promote.id} promoted by {message.from_user.id}"
                )
                
            except Exception as e:
                logger.error(f"Error in promote command: {e}")
                await message.reply_text(f"❌ Error: {str(e)}")
        
        @self.app.on_message(filters.command("demote") & filters.group)
        async def demote_user(client, message):
            """Demote an admin to regular user"""
            if not await is_admin(client, message.chat.id, message.from_user.id):
                await message.reply_text("❌ **Access Denied**\nYou need admin privileges to use this command.")
                return
                
            try:
                # Get target user
                if message.reply_to_message:
                    user_to_demote = message.reply_to_message.from_user
                elif len(message.command) > 1:
                    user_to_demote = await get_user_info(client, message.command[1])
                    if not user_to_demote:
                        await message.reply_text("❌ User not found.")
                        return
                else:
                    await message.reply_text("📝 **Usage:** `/demote @username` or reply to a message")
                    return
                
                # Check if user is actually an admin
                if not await is_admin(client, message.chat.id, user_to_demote.id):
                    await message.reply_text("❌ User is not an administrator.")
                    return
                
                # Demote user
                await client.promote_chat_member(
                    message.chat.id,
                    user_to_demote.id,
                    privileges=ChatPrivileges(
                        can_delete_messages=False,
                        can_restrict_members=False,
                        can_invite_users=False,
                        can_pin_messages=False,
                        can_promote_members=False
                    )
                )
                
                await message.reply_text(
                    f"⬇️ **User Demoted**\n\n"
                    f"**User:** {user_to_demote.first_name} (@{user_to_demote.username or 'No username'})\n"
                    f"**Demoted by:** {message.from_user.first_name}\n"
                    f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                
                # Log action
                await log_action(
                    client, message.chat.id,
                    f"User {user_to_demote.id} demoted by {message.from_user.id}"
                )
                
            except Exception as e:
                logger.error(f"Error in demote command: {e}")
                await message.reply_text(f"❌ Error: {str(e)}")
        
        @self.app.on_message(filters.command("tmute") & filters.group)
        async def temp_mute_user(client, message):
            """Temporarily mute a user"""
            if not await is_admin(client, message.chat.id, message.from_user.id):
                await message.reply_text("❌ **Access Denied**\nYou need admin privileges to use this command.")
                return
                
            try:
                # Parse command
                if len(message.command) < 3 and not message.reply_to_message:
                    await message.reply_text(
                        "📝 **Usage:** `/tmute @username 1h [reason]` or reply to message\n\n"
                        "**Time formats:**\n"
                        "• s = seconds\n"
                        "• m = minutes\n"
                        "• h = hours\n"
                        "• d = days\n\n"
                        "**Example:** `/tmute @user 30m spamming`"
                    )
                    return
                    
                # Get target user
                if message.reply_to_message:
                    user_to_mute = message.reply_to_message.from_user
                    duration_str = message.command[1]
                    reason = " ".join(message.command[2:]) if len(message.command) > 2 else "No reason specified"
                else:
                    user_to_mute = await get_user_info(client, message.command[1])
                    if not user_to_mute:
                        await message.reply_text("❌ User not found.")
                        return
                    duration_str = message.command[2]
                    reason = " ".join(message.command[3:]) if len(message.command) > 3 else "No reason specified"
                
                # Parse duration
                duration_seconds = Config.parse_time(duration_str)
                if duration_seconds <= 0:
                    await message.reply_text("❌ Invalid time format. Use: 1h, 30m, 2d, etc.")
                    return
                
                # Check if target is admin
                if await is_admin(client, message.chat.id, user_to_mute.id):
                    await message.reply_text("❌ Cannot mute an administrator.")
                    return
                
                # Mute user
                until_date = datetime.now() + timedelta(seconds=duration_seconds)
                await client.restrict_chat_member(
                    message.chat.id,
                    user_to_mute.id,
                    ChatPermissions(),
                    until_date=until_date
                )
                
                # Save temporary mute
                await save_temp_restriction(
                    message.chat.id, user_to_mute.id, "mute", until_date, reason
                )
                
                await message.reply_text(
                    f"⏰ **Temporary Mute Applied**\n\n"
                    f"**User:** {user_to_mute.first_name} (@{user_to_mute.username or 'No username'})\n"
                    f"**Duration:** {duration_str}\n"
                    f"**Reason:** {reason}\n"
                    f"**Unmute Time:** {until_date.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"**Muted by:** {message.from_user.first_name}"
                )
                
                # Log action
                await log_action(
                    client, message.chat.id,
                    f"User {user_to_mute.id} temp muted for {duration_str} by {message.from_user.id}"
                )
                
            except Exception as e:
                logger.error(f"Error in tmute command: {e}")
                await message.reply_text(f"❌ Error: {str(e)}")
        
        @self.app.on_message(filters.command("unmute") & filters.group)
        async def unmute_user(client, message):
            """Unmute a user"""
            if not await is_admin(client, message.chat.id, message.from_user.id):
                await message.reply_text("❌ **Access Denied**\nYou need admin privileges to use this command.")
                return
                
            try:
                # Get target user
                if message.reply_to_message:
                    user_to_unmute = message.reply_to_message.from_user
                elif len(message.command) > 1:
                    user_to_unmute = await get_user_info(client, message.command[1])
                    if not user_to_unmute:
                        await message.reply_text("❌ User not found.")
                        return
                else:
                    await message.reply_text("📝 **Usage:** `/unmute @username` or reply to a message")
                    return
                
                # Unmute user by restoring default permissions
                await client.restrict_chat_member(
                    message.chat.id,
                    user_to_unmute.id,
                    ChatPermissions(
                        can_send_messages=True,
                        can_send_media_messages=True,
                        can_send_polls=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True,
                        can_change_info=False,
                        can_invite_users=True,
                        can_pin_messages=False
                    )
                )
                
                # Remove from temp restrictions
                await remove_temp_restriction(message.chat.id, user_to_unmute.id, "mute")
                
                await message.reply_text(
                    f"🔊 **User Unmuted**\n\n"
                    f"**User:** {user_to_unmute.first_name} (@{user_to_unmute.username or 'No username'})\n"
                    f"**Unmuted by:** {message.from_user.first_name}\n"
                    f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                
                # Log action
                await log_action(
                    client, message.chat.id,
                    f"User {user_to_unmute.id} unmuted by {message.from_user.id}"
                )
                
            except Exception as e:
                logger.error(f"Error in unmute command: {e}")
                await message.reply_text(f"❌ Error: {str(e)}")
        
        @self.app.on_message(filters.command("lock") & filters.group)
        async def lock_chat(client, message):
            """Lock chat for non-admins"""
            if not await is_admin(client, message.chat.id, message.from_user.id):
                await message.reply_text("❌ **Access Denied**\nYou need admin privileges to use this command.")
                return
                
            try:
                # Lock chat - restrict all members to no permissions
                await client.set_chat_permissions(
                    message.chat.id,
                    ChatPermissions(
                        can_send_messages=False,
                        can_send_media_messages=False,
                        can_send_polls=False,
                        can_send_other_messages=False,
                        can_add_web_page_previews=False,
                        can_change_info=False,
                        can_invite_users=False,
                        can_pin_messages=False
                    )
                )
                
                await message.reply_text(
                    f"🔒 **Chat Locked**\n\n"
                    f"**Locked by:** {message.from_user.first_name}\n"
                    f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"Only administrators can send messages now.\n"
                    f"Use `/unlock` to restore permissions."
                )
                
                # Log action
                await log_action(
                    client, message.chat.id,
                    f"Chat locked by {message.from_user.id}"
                )
                
            except Exception as e:
                logger.error(f"Error in lock command: {e}")
                await message.reply_text(f"❌ Error: {str(e)}")
        
        @self.app.on_message(filters.command("unlock") & filters.group)
        async def unlock_chat(client, message):
            """Unlock chat for all members"""
            if not await is_admin(client, message.chat.id, message.from_user.id):
                await message.reply_text("❌ **Access Denied**\nYou need admin privileges to use this command.")
                return
                
            try:
                # Unlock chat - restore default permissions
                await client.set_chat_permissions(
                    message.chat.id,
                    ChatPermissions(
                        can_send_messages=True,
                        can_send_media_messages=True,
                        can_send_polls=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True,
                        can_change_info=False,
                        can_invite_users=True,
                        can_pin_messages=False
                    )
                )
                
                await message.reply_text(
                    f"🔓 **Chat Unlocked**\n\n"
                    f"**Unlocked by:** {message.from_user.first_name}\n"
                    f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"All members can send messages again."
                )
                
                # Log action
                await log_action(
                    client, message.chat.id,
                    f"Chat unlocked by {message.from_user.id}"
                )
                
            except Exception as e:
                logger.error(f"Error in unlock command: {e}")
                await message.reply_text(f"❌ Error: {str(e)}")
        
        @self.app.on_message(filters.command("settings") & filters.group)
        async def bot_settings(client, message):
            """Show bot settings and configuration"""
            if not await is_admin(client, message.chat.id, message.from_user.id):
                await message.reply_text("❌ **Access Denied**\nYou need admin privileges to view settings.")
                return
                
            try:
                settings_text = (
                    f"⚙️ **Bot Settings**\n\n"
                    f"**🛡️ Moderation Settings:**\n"
                    f"• Max Warnings: {Config.MAX_WARNINGS}\n"
                    f"• Auto-delete Delay: {Config.AUTO_DELETE_DELAY}s\n"
                    f"• Flood Threshold: {Config.FLOOD_THRESHOLD} msgs/min\n\n"
                    f"**🤖 AI Settings:**\n"
                    f"• Spam Threshold: {Config.SPAM_THRESHOLD}\n"
                    f"• Toxicity Threshold: {Config.TOXICITY_THRESHOLD}\n\n"
                    f"**📊 Performance:**\n"
                    f"• Rate Limit: {Config.RATE_LIMIT_MESSAGES} msgs/min\n"
                    f"• Max Message Length: {Config.MAX_MESSAGE_LENGTH}\n"
                    f"• Max Image Size: {Config.MAX_IMAGE_SIZE // (1024*1024)}MB\n\n"
                    f"**📝 Content Filter:**\n"
                    f"• Banned Words: Active\n"
                    f"• Similar Message Detection: {Config.SIMILAR_MESSAGE_THRESHOLD}\n\n"
                    f"**Credits: @RoronoaRaku**"
                )
                
                await message.reply_text(settings_text)
                
            except Exception as e:
                logger.error(f"Error in settings command: {e}")
                await message.reply_text(f"❌ Error: {str(e)}")
        
        @self.app.on_message(filters.command("purge") & filters.group)
        async def purge_messages(client, message):
            """Delete multiple messages"""
            if not await is_admin(client, message.chat.id, message.from_user.id):
                await message.reply_text("❌ **Access Denied**\nYou need admin privileges to use this command.")
                return
                
            try:
                # Get count and start message
                count = 100  # Default
                if len(message.command) > 1:
                    try:
                        count = int(message.command[1])
                        count = min(count, 200)  # Limit to 200 messages
                    except ValueError:
                        pass
                
                start_id = message.reply_to_message.id if message.reply_to_message else message.id
                
                # Collect and delete messages
                deleted_count = 0
                message_ids = [start_id]  # Include the start message
                
                # Get message IDs to delete (manual collection)
                try:
                    current_id = start_id
                    while len(message_ids) < count:
                        current_id -= 1
                        if current_id <= 0:
                            break
                        message_ids.append(current_id)
                    
                    # Delete messages individually since batch delete isn't working
                    for msg_id in message_ids:
                        try:
                            await client.delete_messages(message.chat.id, msg_id)
                            deleted_count += 1
                        except Exception as e:
                            logger.debug(f"Could not delete message {msg_id}: {e}")
                            continue
                    
                    # Delete the purge command message
                    try:
                        await message.delete()
                    except:
                        pass
                    
                    # Send confirmation (will auto-delete)
                    confirmation = await client.send_message(
                        message.chat.id,
                        f"🗑️ **Purge Complete**\n\n"
                        f"**Deleted:** {deleted_count} messages\n"
                        f"**Purged by:** {message.from_user.first_name}\n"
                        f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    
                    # Auto-delete confirmation after 5 seconds
                    await asyncio.sleep(5)
                    try:
                        await confirmation.delete()
                    except:
                        pass
                        
                except Exception as e:
                    await message.reply_text(f"❌ Purge failed: Limited bot permissions for message history")
                
                # Log action
                await log_action(
                    client, message.chat.id,
                    f"{deleted_count} messages purged by {message.from_user.id}"
                )
                
            except Exception as e:
                logger.error(f"Error in purge command: {e}")
                await message.reply_text(f"❌ Error: {str(e)}")
    
    def register_moderation_handlers(self):
        """Register moderation command handlers"""
        
        @self.app.on_message(filters.command("warn") & filters.group)
        async def warn_user(client, message):
            """Warn a user"""
            if not await is_admin(client, message.chat.id, message.from_user.id):
                await message.reply_text("❌ **Access Denied**\nYou need admin privileges to use this command.")
                return
                
            try:
                # Get target user
                if message.reply_to_message:
                    user_to_warn = message.reply_to_message.from_user
                    reason = " ".join(message.command[1:]) if len(message.command) > 1 else "No reason specified"
                elif len(message.command) > 1:
                    user_to_warn = await get_user_info(client, message.command[1])
                    if not user_to_warn:
                        await message.reply_text("❌ User not found.")
                        return
                    reason = " ".join(message.command[2:]) if len(message.command) > 2 else "No reason specified"
                else:
                    await message.reply_text("📝 **Usage:** `/warn @username [reason]` or reply to a message")
                    return
                    
                # Check if target is admin
                if await is_admin(client, message.chat.id, user_to_warn.id):
                    await message.reply_text("❌ Cannot warn an administrator.")
                    return
                
                # Add warning
                warnings_count = await save_user_warning(
                    message.chat.id, user_to_warn.id, reason, message.from_user.id
                )
                
                # Create action buttons based on warning count
                keyboard = []
                if warnings_count >= Config.MAX_WARNINGS:
                    keyboard = [
                        [
                            InlineKeyboardButton("🔨 Ban User", callback_data=f"warn_ban_{user_to_warn.id}"),
                            InlineKeyboardButton("👢 Kick User", callback_data=f"warn_kick_{user_to_warn.id}")
                        ],
                        [
                            InlineKeyboardButton("🔇 Mute 1h", callback_data=f"warn_mute_{user_to_warn.id}_3600"),
                            InlineKeyboardButton("❌ Clear Warnings", callback_data=f"warn_clear_{user_to_warn.id}")
                        ]
                    ]
                else:
                    keyboard = [
                        [
                            InlineKeyboardButton("❌ Remove Warning", callback_data=f"warn_remove_{user_to_warn.id}"),
                            InlineKeyboardButton("📊 View All Warnings", callback_data=f"warn_view_{user_to_warn.id}")
                        ]
                    ]
                
                warning_text = (
                    f"⚠️ **User Warned** {'(MAX REACHED!)' if warnings_count >= Config.MAX_WARNINGS else ''}\n\n"
                    f"**User:** {user_to_warn.first_name} (@{user_to_warn.username or 'No username'})\n"
                    f"**Reason:** {reason}\n"
                    f"**Warnings:** {warnings_count}/{Config.MAX_WARNINGS}\n"
                    f"**Warned by:** {message.from_user.first_name}\n"
                    f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                )
                
                if warnings_count >= Config.MAX_WARNINGS:
                    warning_text += "🚨 **Maximum warnings reached!**\nChoose an action:\n\n"
                
                await message.reply_text(
                    warning_text,
                    reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
                )
                
                # Log action
                await log_action(
                    client, message.chat.id,
                    f"User {user_to_warn.id} warned by {message.from_user.id}. Total warnings: {warnings_count}"
                )
                
            except Exception as e:
                logger.error(f"Error in warn command: {e}")
                await message.reply_text(f"❌ Error: {str(e)}")
        
        @self.app.on_callback_query(filters.regex("warn_remove_"))
        async def warn_remove_action(client, callback_query):
            """Remove last warning from user"""
            # Check if user is admin
            if not await is_admin(client, callback_query.message.chat.id, callback_query.from_user.id):
                await callback_query.answer("❌ You need admin privileges.", show_alert=True)
                return
                
            user_id = int(callback_query.data.split("_")[2])
            
            try:
                success = await remove_user_warning(callback_query.message.chat.id, user_id)
                
                if success:
                    warnings_count = await get_user_warnings(callback_query.message.chat.id, user_id)
                    
                    await callback_query.edit_message_text(
                        f"✅ **Warning Removed**\n\n"
                        f"**User ID:** `{user_id}`\n"
                        f"**Remaining Warnings:** {len(warnings_count)}/{Config.MAX_WARNINGS}\n"
                        f"**Removed by:** {callback_query.from_user.first_name}\n"
                        f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                else:
                    await callback_query.answer("❌ No warnings found for this user.", show_alert=True)
                    
            except Exception as e:
                await callback_query.answer(f"❌ Error: {str(e)}", show_alert=True)
        
        @self.app.on_message(filters.command("unwarn") & filters.group)
        async def unwarn_user(client, message):
            """Remove last warning from user (admin only)"""
            if not await is_admin(client, message.chat.id, message.from_user.id):
                await message.reply_text("❌ **Access Denied**\nYou need admin privileges to remove warnings.")
                return
                
            try:
                if message.reply_to_message:
                    target_user = message.reply_to_message.from_user
                elif len(message.command) > 1:
                    target_user = await get_user_info(client, message.command[1])
                    if not target_user:
                        await message.reply_text("❌ User not found.")
                        return
                else:
                    await message.reply_text("📝 **Usage:** `/unwarn @username` or reply to a message")
                    return
                
                success = await remove_user_warning(message.chat.id, target_user.id)
                
                if success:
                    warnings_count = await get_user_warnings(message.chat.id, target_user.id)
                    await message.reply_text(
                        f"✅ **Warning Removed**\n\n"
                        f"**User:** {target_user.first_name} (@{target_user.username or 'No username'})\n"
                        f"**Remaining Warnings:** {len(warnings_count)}/{Config.MAX_WARNINGS}\n"
                        f"**Removed by:** {message.from_user.first_name}\n"
                        f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    await log_action(client, message.chat.id, f"Warning removed from user {target_user.id} by {message.from_user.id}")
                else:
                    await message.reply_text("❌ No warnings found for this user.")
                    
            except Exception as e:
                logger.error(f"Error in unwarn command: {e}")
                await message.reply_text(f"❌ Error: {str(e)}")
        
        @self.app.on_message(filters.command("warnings") & filters.group)
        async def check_warnings(client, message):
            """Check user warnings"""
            try:
                # Get target user
                if message.reply_to_message:
                    target_user = message.reply_to_message.from_user
                elif len(message.command) > 1:
                    target_user = await get_user_info(client, message.command[1])
                    if not target_user:
                        await message.reply_text("❌ User not found.")
                        return
                else:
                    target_user = message.from_user
                
                warnings = await get_user_warnings(message.chat.id, target_user.id)
                
                if not warnings:
                    await message.reply_text(
                        f"✅ **No Warnings**\n\n"
                        f"**User:** {target_user.first_name} (@{target_user.username or 'No username'})\n"
                        f"This user has a clean record!"
                    )
                    return
                
                warnings_text = (
                    f"📊 **Warning Report**\n\n"
                    f"**User:** {target_user.first_name} (@{target_user.username or 'No username'})\n"
                    f"**Total Warnings:** {len(warnings)}/{Config.MAX_WARNINGS}\n\n"
                    f"**Recent Warnings:**\n"
                )
                
                for i, warning in enumerate(warnings[-3:], 1):  # Show last 3 warnings
                    warnings_text += (
                        f"{i}. {warning['reason']}\n"
                        f"   📅 {warning['timestamp']}\n\n"
                    )
                
                if len(warnings) > 3:
                    warnings_text += f"... and {len(warnings) - 3} more\n\n"
                
                if len(warnings) >= Config.MAX_WARNINGS:
                    warnings_text += "🚨 **Maximum warnings reached!**\n\n"
                
                await message.reply_text(warnings_text)
                
            except Exception as e:
                logger.error(f"Error in warnings command: {e}")
                await message.reply_text(f"❌ Error: {str(e)}")
        
        @self.app.on_message(filters.command("info") & filters.group)
        async def user_info(client, message):
            """Get detailed user information"""
            try:
                # Get target user
                if message.reply_to_message:
                    target_user = message.reply_to_message.from_user
                elif len(message.command) > 1:
                    target_user = await get_user_info(client, message.command[1])
                    if not target_user:
                        await message.reply_text("❌ User not found.")
                        return
                else:
                    await message.reply_text("📝 **Usage:** `/info @username` or reply to a message")
                    return
                
                # Get chat member info
                try:
                    member = await client.get_chat_member(message.chat.id, target_user.id)
                    status = member.status.name
                    joined_date = member.joined_date.strftime('%Y-%m-%d %H:%M:%S') if member.joined_date else "Unknown"
                except:
                    status = "Unknown"
                    joined_date = "Unknown"
                
                # Get warnings
                warnings = await get_user_warnings(message.chat.id, target_user.id)
                
                info_text = (
                    f"👤 **User Information**\n\n"
                    f"**Name:** {target_user.first_name} {target_user.last_name or ''}\n"
                    f"**Username:** @{target_user.username or 'None'}\n"
                    f"**User ID:** `{target_user.id}`\n"
                    f"**Status:** {status}\n"
                    f"**Joined:** {joined_date}\n"
                    f"**Warnings:** {len(warnings)}/{Config.MAX_WARNINGS}\n"
                    f"**Is Bot:** {'Yes' if target_user.is_bot else 'No'}\n"
                    f"**Is Premium:** {'Yes' if target_user.is_premium else 'No'}\n\n"
                    f"**Requested by:** {message.from_user.first_name}"
                )
                
                await message.reply_text(info_text)
                
            except Exception as e:
                logger.error(f"Error in info command: {e}")
                await message.reply_text(f"❌ Error: {str(e)}")
        
        @self.app.on_message(filters.command("report") & filters.group)
        async def report_user(client, message):
            """Report a user to admins"""
            try:
                if not message.reply_to_message:
                    await message.reply_text(
                        "📝 **Usage:** Reply to a message to report the user\n\n"
                        "**Example:** Reply to spam message and type `/report`"
                    )
                    return
                
                reported_user = message.reply_to_message.from_user
                reporter = message.from_user
                
                # Create report message
                report_text = (
                    f"🚨 **User Report**\n\n"
                    f"**Reported User:** {reported_user.first_name} (@{reported_user.username or 'No username'})\n"
                    f"**Reported by:** {reporter.first_name} (@{reporter.username or 'No username'})\n"
                    f"**Chat:** {message.chat.title}\n"
                    f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"**Reported Message:**\n`{message.reply_to_message.text or 'Media/Sticker/Other'}`\n\n"
                    f"**Action Required:** Please review and take appropriate action."
                )
                
                # Create action buttons for admins
                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("🚫 Ban User", callback_data=f"report_ban_{reported_user.id}"),
                        InlineKeyboardButton("🔇 Mute User", callback_data=f"report_mute_{reported_user.id}")
                    ],
                    [
                        InlineKeyboardButton("⚠️ Warn User", callback_data=f"report_warn_{reported_user.id}"),
                        InlineKeyboardButton("🗑️ Delete Message", callback_data=f"report_delete_{message.reply_to_message.id}")
                    ],
                    [
                        InlineKeyboardButton("✅ Mark Resolved", callback_data=f"report_resolve_{reported_user.id}")
                    ]
                ])
                
                # Send report to admins
                await client.send_message(
                    message.chat.id,
                    report_text,
                    reply_markup=keyboard
                )
                
                # Delete user report command
                try:
                    await message.delete()
                except:
                    pass
                
                # Log report
                await log_action(
                    client, message.chat.id,
                    f"User {reported_user.id} reported by {reporter.id}"
                )
                
            except Exception as e:
                logger.error(f"Error in report command: {e}")
                await message.reply_text(f"❌ Error: {str(e)}")
        
        @self.app.on_callback_query(filters.regex("report_"))
        async def handle_report_actions(client, callback_query):
            """Handle report action buttons"""
            if not await is_admin(client, callback_query.message.chat.id, callback_query.from_user.id):
                await callback_query.answer("❌ You need admin privileges.", show_alert=True)
                return
            
            action_data = callback_query.data.split("_")
            action = action_data[1]
            target_id = int(action_data[2])
            
            try:
                if action == "ban":
                    await client.ban_chat_member(callback_query.message.chat.id, target_id)
                    await callback_query.edit_message_text(
                        f"✅ **Report Resolved**\n\n"
                        f"**Action:** User banned\n"
                        f"**By:** {callback_query.from_user.first_name}\n"
                        f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    
                elif action == "mute":
                    await client.restrict_chat_member(
                        callback_query.message.chat.id,
                        target_id,
                        ChatPermissions()
                    )
                    await callback_query.edit_message_text(
                        f"✅ **Report Resolved**\n\n"
                        f"**Action:** User muted\n"
                        f"**By:** {callback_query.from_user.first_name}\n"
                        f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    
                elif action == "warn":
                    await save_user_warning(callback_query.message.chat.id, target_id, "Report violation", callback_query.from_user.id)
                    await callback_query.edit_message_text(
                        f"✅ **Report Resolved**\n\n"
                        f"**Action:** Warning issued\n"
                        f"**By:** {callback_query.from_user.first_name}\n"
                        f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    
                elif action == "delete":
                    try:
                        await client.delete_messages(callback_query.message.chat.id, target_id)
                        await callback_query.edit_message_text(
                            f"✅ **Report Resolved**\n\n"
                            f"**Action:** Message deleted\n"
                            f"**By:** {callback_query.from_user.first_name}\n"
                            f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                        )
                    except:
                        await callback_query.answer("❌ Could not delete message", show_alert=True)
                        
                elif action == "resolve":
                    await callback_query.edit_message_text(
                        f"✅ **Report Resolved**\n\n"
                        f"**Action:** Marked as resolved (no action taken)\n"
                        f"**By:** {callback_query.from_user.first_name}\n"
                        f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                    
            except Exception as e:
                await callback_query.answer(f"❌ Error: {str(e)}", show_alert=True)
    
    def register_welcome_handlers(self):
        """Register welcome and leave message handlers"""
        
        @self.app.on_message(filters.new_chat_members)
        async def welcome_new_member(client, message):
            """Welcome new members with personalized images"""
            try:
                for user in message.new_chat_members:
                    if user.is_bot:
                        continue
                    
                    # Check if account is suspicious
                    suspicious_check = await self.ai_analyzer.check_suspicious_account(user)
                    is_suspicious = suspicious_check.get("is_suspicious", False)
                    
                    # Create welcome message
                    welcome_text = MessageTemplates.get_welcome_message(
                        user, message.chat.title, is_suspicious
                    )
                    
                    # Create welcome image
                    welcome_image = await self.image_processor.create_welcome_image(
                        user, message.chat.title
                    )
                    
                    # Create inline keyboard
                    keyboard = InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("👤 User Info", callback_data=f"user_info_{user.id}"),
                            InlineKeyboardButton("📋 Rules", callback_data="show_rules")
                        ]
                    ])
                    
                    if is_suspicious:
                        keyboard.inline_keyboard.append([
                            InlineKeyboardButton("🚫 Ban Suspicious User", callback_data=f"ban_suspicious_{user.id}"),
                            InlineKeyboardButton("✅ Approve User", callback_data=f"approve_suspicious_{user.id}")
                        ])
                    
                    # Send welcome message
                    if welcome_image:
                        await client.send_photo(
                            message.chat.id,
                            welcome_image,
                            caption=welcome_text,
                            reply_markup=keyboard
                        )
                    else:
                        await message.reply_text(welcome_text, reply_markup=keyboard)
                    
                    # Log join
                    await log_action(
                        client, message.chat.id,
                        f"New member joined: {user.id} ({'suspicious' if is_suspicious else 'normal'})"
                    )
                    
            except Exception as e:
                logger.error(f"Error in welcome handler: {e}")
        
        @self.app.on_message(filters.left_chat_member)
        async def farewell_member(client, message):
            """Send farewell message when member leaves"""
            try:
                if message.left_chat_member.is_bot:
                    return
                
                farewell_text = MessageTemplates.get_farewell_message(
                    message.left_chat_member, message.chat.title
                )
                
                farewell_msg = await message.reply_text(farewell_text)
                
                # Auto-delete after 30 seconds
                await asyncio.sleep(30)
                try:
                    await farewell_msg.delete()
                except:
                    pass
                    
            except Exception as e:
                logger.error(f"Error in farewell handler: {e}")
    
    def register_spam_handlers(self):
        """Register spam detection and filtering handlers"""
        
        @self.app.on_message(filters.group & ~filters.command([
            "start", "help", "about", "credits", "kick", "ban", "tban", "unban",
            "mute", "tmute", "unmute", "promote", "demote", "warn", "unwarn",
            "warnings", "info", "report", "lock", "unlock", "settings", "purge"
        ]))
        async def message_filter(client, message):
            """Main message filtering and spam detection"""
            try:
                # Skip if user is admin
                if await is_admin(client, message.chat.id, message.from_user.id):
                    return
                
                # Flood protection
                await self.check_flood(client, message)
                
                # Content filtering
                if message.text:
                    await self.check_content_filter(client, message)
                    await self.check_ai_spam(client, message)
                    await self.check_similar_messages(client, message)
                
                # Link spam detection
                if message.text and any(x in message.text.lower() for x in ['http', 'www.', 't.me']):
                    await self.check_link_spam(client, message)
                    
            except Exception as e:
                logger.error(f"Error in message filter: {e}")
        
        @self.app.on_edited_message(filters.group)
        async def edited_message_filter(client, message):
            """Filter edited messages"""
            try:
                # Skip if user is admin
                if await is_admin(client, message.chat.id, message.from_user.id):
                    return
                
                # Check content
                if message.text:
                    await self.check_content_filter(client, message)
                    
            except Exception as e:
                logger.error(f"Error in edited message filter: {e}")
    
    async def check_flood(self, client, message):
        """Check for message flooding"""
        user_id = message.from_user.id
        chat_id = message.chat.id
        current_time = datetime.now()
        
        # Clean old messages
        self.user_messages[user_id] = [
            msg_time for msg_time in self.user_messages[user_id]
            if (current_time - msg_time).seconds < Config.RATE_LIMIT_WINDOW
        ]
        
        # Add current message
        self.user_messages[user_id].append(current_time)
        
        # Check if flooding
        if len(self.user_messages[user_id]) > Config.FLOOD_THRESHOLD:
            try:
                # Delete message
                await message.delete()
                
                # Warn user about flooding
                warning_msg = await client.send_message(
                    chat_id,
                    f"⚠️ **Flood Detected**\n\n"
                    f"**User:** {message.from_user.first_name}\n"
                    f"**Messages:** {len(self.user_messages[user_id])} in {Config.RATE_LIMIT_WINDOW}s\n"
                    f"**Action:** Message deleted\n\n"
                    f"Please slow down your messaging."
                )
                
                # Auto-delete warning
                await asyncio.sleep(Config.AUTO_DELETE_DELAY)
                try:
                    await warning_msg.delete()
                except:
                    pass
                
                # Log flood
                await log_action(
                    client, chat_id,
                    f"Flood detected from user {user_id}: {len(self.user_messages[user_id])} messages"
                )
                
                # Clear user messages to prevent spam
                self.user_messages[user_id] = []
                
            except Exception as e:
                logger.error(f"Error handling flood: {e}")
    
    async def check_content_filter(self, client, message):
        """Check message against content filters"""
        if not message.text:
            return
        
        # Check banned words
        if self.content_filter.contains_banned_words(message.text):
            try:
                await message.delete()
                await log_action(
                    client, message.chat.id,
                    f"Message from {message.from_user.id} deleted: inappropriate content"
                )
            except Exception as e:
                logger.error(f"Error deleting inappropriate message: {e}")
        
        # Check spam patterns
        spam_check = self.content_filter.check_spam_patterns(message.text)
        if spam_check["is_spam"] and spam_check["confidence"] > Config.SPAM_THRESHOLD:
            try:
                await message.delete()
                await log_action(
                    client, message.chat.id,
                    f"Spam message from {message.from_user.id} deleted: {spam_check['reasons']}"
                )
            except Exception as e:
                logger.error(f"Error deleting spam message: {e}")
    
    async def check_ai_spam(self, client, message):
        """Use AI to detect spam content"""
        if not message.text or not self.ai_analyzer.openai_client:
            return
        
        try:
            analysis = await self.ai_analyzer.analyze_message_content(message.text)
            
            if analysis.get("spam_score", 0) > Config.SPAM_THRESHOLD:
                await message.delete()
                await log_action(
                    client, message.chat.id,
                    f"AI spam detection: message from {message.from_user.id} deleted (score: {analysis['spam_score']})"
                )
                
        except Exception as e:
            logger.error(f"Error in AI spam detection: {e}")
    
    async def check_similar_messages(self, client, message):
        """Check for repeated similar messages"""
        if not message.text:
            return
        
        user_id = message.from_user.id
        
        # Store message in history
        self.user_message_history[user_id].append(message.text)
        
        # Keep only recent messages
        if len(self.user_message_history[user_id]) > 5:
            self.user_message_history[user_id] = self.user_message_history[user_id][-5:]
        
        # Check similarity
        if len(self.user_message_history[user_id]) >= 3:
            recent_messages = self.user_message_history[user_id][-3:]
            
            for i, msg1 in enumerate(recent_messages[:-1]):
                for msg2 in recent_messages[i+1:]:
                    similarity = difflib.SequenceMatcher(None, msg1, msg2).ratio()
                    
                    if similarity > Config.SIMILAR_MESSAGE_THRESHOLD:
                        try:
                            await message.delete()
                            await log_action(
                                client, message.chat.id,
                                f"Similar message from {user_id} deleted (similarity: {similarity:.2f})"
                            )
                            return
                        except Exception as e:
                            logger.error(f"Error deleting similar message: {e}")
    
    async def check_link_spam(self, client, message):
        """Check for link spam"""
        if not message.text:
            return
        
        # Count links in message
        link_patterns = [r'http[s]?://', r'www\.', r't\.me/', r'@\w+']
        link_count = sum(len(re.findall(pattern, message.text, re.IGNORECASE)) for pattern in link_patterns)
        
        if link_count > 2:  # More than 2 links considered spam
            try:
                await message.delete()
                await log_action(
                    client, message.chat.id,
                    f"Link spam from {message.from_user.id} deleted ({link_count} links)"
                )
            except Exception as e:
                logger.error(f"Error deleting link spam: {e}")
    
    async def start_command(self, client, message):
        """Start command handler"""
        welcome_text = (
            "🤖 **Welcome to Group Manager Bot!**\n\n"
            "I'm an AI-powered Telegram group management bot with advanced features:\n\n"
            "🛡️ **Advanced Moderation**\n"
            "• Kick, ban, mute with time limits\n"
            "• AI-powered spam detection\n"
            "• Auto-delete unwanted content\n\n"
            "👋 **Smart Welcome System**\n"
            "• Personalized messages with profile pictures\n"
            "• Custom leave notifications\n\n"
            "⚡ **Admin Tools**\n"
            "• Promote/demote users\n"
            "• Anti-flood protection\n"
            "• Comprehensive logging\n\n"
            "📱 Use /help to see all commands\n"
            "ℹ️ Use /about for detailed information\n\n"
            "**Credits: @RoronoaRaku**"
        )
        
        await message.reply_text(welcome_text)
    
    async def help_command(self, client, message):
        """Help command handler"""
        help_text = (
            "🔧 **Bot Commands Help**\n\n"
            "**👑 Admin Commands:**\n"
            "`/kick` - Remove user from group\n"
            "`/ban` - Ban user permanently\n"
            "`/tban` - Temporary ban with time\n"
            "`/unban` - Remove ban from user\n"
            "`/mute` - Mute user indefinitely\n"
            "`/tmute` - Temporary mute with time\n"
            "`/unmute` - Remove mute from user\n"
            "`/promote` - Promote user to admin\n"
            "`/demote` - Demote admin to user\n"
            "`/lock` - Lock chat for non-admins\n"
            "`/unlock` - Unlock chat permissions\n"
            "`/purge` - Delete multiple messages\n\n"
            "**🛡️ Moderation Commands:**\n"
            "`/warn` - Issue warning to user\n"
            "`/unwarn` - Remove last warning (admin only)\n"
            "`/warnings` - Check user warnings\n"
            "`/report` - Report user to admins\n"
            "`/info` - User information\n"
            "`/rules` - Group rules\n"
            "`/settings` - Bot settings\n\n"
            "**Time formats:** s=seconds, m=minutes, h=hours, d=days\n\n"
            "**Credits: @RoronoaRaku**"
        )
        
        await message.reply_text(help_text)
    
    async def about_command(self, client, message):
        """About command handler"""
        about_text = (
            "🤖 **About Group Manager Bot**\n\n"
            "**🔥 Advanced Features:**\n"
            "• AI-powered spam & toxicity detection\n"
            "• Intelligent content filtering\n"
            "• Automated moderation actions\n"
            "• Custom welcome messages with profile pics\n"
            "• Comprehensive admin tools\n\n"
            "**🛡️ Protection Systems:**\n"
            "• Real-time message analysis\n"
            "• Flood protection\n"
            "• Link spam detection\n"
            "• Fake account identification\n"
            "• Warning system with escalation\n\n"
            "**🎨 Smart Features:**\n"
            "• Dynamic welcome images\n"
            "• Personalized messages\n"
            "• Interactive admin panels\n"
            "• Automatic cleanup\n\n"
            "**🛡️ Security & Performance:**\n"
            "• Real-time threat detection\n"
            "• Optimized for large groups\n"
            "• Privacy-focused design\n\n"
            "**Credits: @RoronoaRaku**"
        )
        
        await message.reply_text(about_text)
    
    async def credits_command(self, client, message):
        """Credits command handler"""
        credits_text = (
            "👨‍💻 **Developer Credits**\n\n"
            "**Created by:** @RoronoaRaku\n"
            "**Specialization:** AI-powered Telegram automation\n"
            "**Features:** Advanced group management & moderation\n\n"
            "**🔧 Technologies Used:**\n"
            "• Python + Pyrogram\n"
            "• OpenAI GPT-4o for AI analysis\n"
            "• PIL for image processing\n"
            "• Advanced content filtering\n\n"
            "**🚀 Open Source Project**\n"
            "Built with ❤️ for the Telegram community\n\n"
            "**Contact:** @RoronoaRaku for support & suggestions"
        )
        
        await message.reply_text(credits_text)
    
    async def run(self):
        """Start the bot"""
        try:
            logger.info("=" * 50)
            logger.info("Group Manager Bot Starting")
            logger.info("Developed by @RoronoaRaku")
            logger.info(f"Startup time: {datetime.now()}")
            logger.info("=" * 50)
            
            print("🤖 Group Manager Bot")
            print("👨‍💻 Developed by @RoronoaRaku")
            print("🚀 Starting bot...")
            
            logger.info("Starting Group Manager Bot...")
            logger.info("Developed by @RoronoaRaku")
            
            await self.app.start()
            
            bot_info = await self.app.get_me()
            logger.info("Bot started successfully!")
            logger.info(f"Bot username: @{bot_info.username}")
            logger.info("Bot is ready to manage groups!")
            
            await self.app.idle()
            
        except Exception as e:
            logger.error(f"Bot startup failed: {e}")
        finally:
            await self.app.stop()

# ==================================================
# MAIN EXECUTION
# ==================================================

async def main():
    """Main function"""
    # Create data directories
    os.makedirs("data", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    
    # Initialize and run bot
    bot = GroupManagerBot()
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())
