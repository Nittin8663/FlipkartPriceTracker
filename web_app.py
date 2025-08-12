from flask import Flask, render_template, jsonify, request
import sqlite3
from datetime import datetime
import threading
import time
import logging
from pyngrok import ngrok

app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants with your current time and login
CURRENT_TIME = "2025-08-12 17:48:30"
USER_LOGIN = "Nittin8663"
DATABASE_NAME = "price_history.db"
PORT = 8000

# Global tracking state
tracking_state = {
    'is_tracking': False,
    'tracker_thread': None,
    'current_data': None,
    'product_url': None,
    'threshold_price': None,
    'telegram_config': None
}

class PriceTracker:
    def __init__(self, url):
        self.url = url
        
    def get_price(self):
        """Simulate price tracking for testing"""
        return {
            'title': 'Test Product',
            'price': 1000.0,
            'timestamp': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        }

class TelegramBot:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        
    def send_price_alert(self, data, threshold_price):
        """Simulate sending telegram alert"""
        logger.info(f"Price alert sent: {data['price']} <= {threshold_price}")
        return True

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

def store_price_data(data):
    """Store price data in database"""
    try:
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
        logger.info(f"Price data stored: {data['price']}")
    except Exception as e:
        logger.error(f"Error storing price data: {e}")

def price_tracking_thread():
    """Background thread for price tracking"""
    logger.info("Price tracking thread started")
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
            
            time.sleep(60)  # Check every minute
            
        except Exception as e:
            logger.error(f"Error in price tracking: {e}")
            time.sleep(60)

    logger.info("Price tracking thread stopped")

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
        
        logger.info(f"Tracking started for URL: {data['url']}")
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
    logger.info("Tracking stopped")
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
    try:
        with sqlite3.connect(DATABASE_NAME) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT * FROM price_history
                ORDER BY timestamp DESC
                LIMIT 50
            ''')
            history = [dict(row) for row in cursor.fetchall()]
        return jsonify(history)
    except Exception as e:
        logger.error(f"Error fetching price history: {e}")
        return jsonify([])

def start_ngrok():
    """Start ngrok tunnel"""
    try:
        http_tunnel = ngrok.connect(PORT)
        public_url = http_tunnel.public_url
        logger.info(f'Ngrok tunnel URL: {public_url}')
        print(f'\n✨ Flipkart Price Tracker is running at: {public_url}\n')
    except Exception as e:
        logger.error(f"Failed to start ngrok: {e}")
        raise

if __name__ == '__main__':
    try:
        # Print startup banner
        print("\n=== Flipkart Price Tracker ===")
        print(f"Time: {CURRENT_TIME}")
        print(f"User: {USER_LOGIN}")
        print("===========================\n")
        
        # Initialize database
        init_database()
        
        # Start ngrok in a separate thread
        ngrok_thread = threading.Thread(target=start_ngrok, daemon=True)
        ngrok_thread.start()
        time.sleep(2)  # Wait for ngrok to start
        
        # Start Flask application
        logger.info(f"Starting Flask application on port {PORT}")
        app.run(host='0.0.0.0', port=PORT, debug=False)
        
    except Exception as e:
        logger.error(f"Application startup error: {e}")
        raise
