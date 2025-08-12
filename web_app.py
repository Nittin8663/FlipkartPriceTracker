from flask import Flask, render_template, jsonify, request
import sqlite3
from datetime import datetime
import threading
import time
import logging
from pyngrok import ngrok

from price_tracker import PriceTracker
from telegram_handler import TelegramBot

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants - Updated with current time and user login
CURRENT_TIME = "2025-08-12 17:42:06"  # Updated current time
USER_LOGIN = "Nittin8663"
DATABASE_NAME = "price_history.db"
PORT = 5000

# Rest of the code remains the same...
