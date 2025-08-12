from flask import Flask, render_template, jsonify, request
import sqlite3
from datetime import datetime
import threading
import time
import logging
from pyngrok import ngrok

from price_tracker import PriceTracker
from telegram_handler import TelegramBot
from config import *

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

def store_price_data(data):
    """Store price data in database"""
    with sqlite3.connect(DATABASE_NAME) as conn:
        conn.execute('''
            INSERT INTO price_history 
            (product_url, product_title, price, timestamp, threshold_price)
            VALUES (?, ?, ?, ?, ?)
        ''', (
            tracking_state['product_url'],
            data['title'],
            data['price'],
            data['timestamp'],
            tracking_state['threshold_price']
        ))
        conn.commit()

def price_tracking_thread():
    """Background thread for price tracking"""
    tracker = PriceTracker(tracking_state['product_url'])
    telegram_bot = TelegramBot(**tracking_state['telegram_config'])
    
    while tracking_state['is_tracking']:
        try:
            data = tracker.get_price()
            data['url'] = tracking_state['product_url']
            tracking_state['current_data'] = data
            
            # Store in database
            store_price_data(data)
            
            # Check price threshold
            if data['price'] <= tracking_state['threshold_price']:
                telegram_bot.send_price_alert(data, tracking_state['threshold_price'])
            
            time.sleep(CHECK_INTERVAL)
            
        except Exception as e:
            logger.error(f"Error in price tracking: {e}")
            time.sleep(CHECK_INTERVAL)

@app.route('/')
def home():
    return render_template('index.html',
                         current_time=CURRENT_TIME,
                         user_login=USER_LOGIN)

@app.route('/api/start_tracking', methods=['POST'])
def start_tracking():
    global tracking_state
    
    try:
        data = request.get_json()
        tracking_state.update({
            'product_url': data['url'],
            'threshold_price': float(data['threshold_price']),
            'telegram_config': {
                'token': data['telegram_token'],
                'chat_id': data['telegram_chat_id']
            },
            'is_tracking': True
        })
        
        if not tracking_state['tracker_thread'] or not tracking_state['tracker_thread'].is_alive():
            tracking_state['tracker_thread'] = threading.Thread(
                target=price_tracking_thread,
                daemon=True
            )
            tracking_state['tracker_thread'].start()
        
        return jsonify({
            'status': 'success',
            'message': 'Price tracking started successfully'
        })
        
    except Exception as e:
        logger.error(f"Failed to start tracking: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 400

@app.route('/api/stop_tracking')
def stop_tracking():
    tracking_state['is_tracking'] = False
    return jsonify({
        'status': 'success',
        'message': 'Price tracking stopped'
    })

@app.route('/api/status')
def get_status():
    return jsonify({
        'is_tracking': tracking_state['is_tracking'],
        'current_data': tracking_state['current_data'],
        'product_url': tracking_state['product_url'],
        'threshold_price': tracking_state['threshold_price']
    })

@app.route('/api/price_history')
def get_price_history():
    with sqlite3.connect(DATABASE_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.execute('''
            SELECT * FROM price_history
            ORDER BY timestamp DESC
            LIMIT 50
        ''')
        history = [dict(row) for row in cursor.fetchall()]
    
    return jsonify(history)

def start_ngrok():
    """Start ngrok tunnel"""
    try:
        http_tunnel = ngrok.connect(PORT)
        logger.info(f'Ngrok tunnel URL: {http_tunnel.public_url}')
    except Exception as e:
        logger.error(f"Failed to start ngrok: {e}")

if __name__ == '__main__':
    init_database()
    threading.Thread(target=start_ngrok, daemon=True).start()
    app.run(debug=DEBUG_MODE, port=PORT)
