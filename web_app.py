from flask import Flask, render_template, jsonify, request
import sqlite3
from datetime import datetime
import threading
import time
import logging
from pyngrok import ngrok

from price_tracker import PriceTracker
from telegram_handler import TelegramBot

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Constants - Updated with your current time
CURRENT_TIME = "2025-08-12 17:45:22"  # Your current time
USER_LOGIN = "Nittin8663"
DATABASE_NAME = "price_history.db"
PORT = 8000  # Changed to port 8000

# Global tracking state
tracking_state = {
    'is_tracking': False,
    'tracker_thread': None,
    'current_data': None,
    'product_url': None,
    'threshold_price': None,
    'telegram_config': None
}

def init_database():
    """Initialize SQLite database"""
    try:
        with sqlite3.connect(DATABASE_NAME) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_url TEXT,
                    product_title TEXT,
                    price REAL,
                    timestamp DATETIME,
                    threshold_price REAL
                )
            ''')
            conn.commit()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization error: {e}")
        raise

def start_ngrok():
    """Start ngrok tunnel"""
    try:
        http_tunnel = ngrok.connect(PORT)
        public_url = http_tunnel.public_url
        logger.info(f'✨ Ngrok tunnel URL: {public_url}')
        return public_url
    except Exception as e:
        logger.error(f"Ngrok tunnel error: {e}")
        raise

if __name__ == '__main__':
    try:
        logger.info(f"Starting Flipkart Price Tracker...")
        logger.info(f"Current time: {CURRENT_TIME}")
        logger.info(f"User login: {USER_LOGIN}")
        
        # Initialize database
        init_database()
        
        # Start ngrok in a separate thread
        ngrok_thread = threading.Thread(target=start_ngrok, daemon=True)
        ngrok_thread.start()
        
        # Start Flask application
        logger.info(f"Starting Flask application on port {PORT}")
        app.run(host='0.0.0.0', port=PORT, debug=False)
        
    except Exception as e:
        logger.error(f"Application startup error: {e}")
        raise
