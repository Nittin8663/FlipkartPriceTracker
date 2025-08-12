from flask import Flask, render_template, jsonify, request
import sqlite3
from datetime import datetime
import threading
import time
import logging
from pyngrok import ngrok
import requests
from bs4 import BeautifulSoup
import re
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import random
import json

app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants with exact current time and login
CURRENT_TIME = "2025-08-12 18:04:14"
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
    'telegram_config': None,
    'last_error': None
}

class PriceTracker:
    def __init__(self, url):
        self.url = self._clean_flipkart_url(url)
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.131 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        ]
        self.session = self._create_session()

    def _clean_flipkart_url(self, url):
        """Clean Flipkart URL to get essential parameters"""
        try:
            # Extract the product ID
            pid_match = re.search(r'pid=([A-Z0-9]+)', url)
            if pid_match:
                pid = pid_match.group(1)
                # Keep the original URL but remove tracking parameters
                base_url = url.split('?')[0]
                clean_url = f"{base_url}?pid={pid}"
                logger.info(f"Cleaned URL: {clean_url}")
                return clean_url
            return url
        except Exception as e:
            logger.error(f"Error cleaning URL: {e}")
            return url

    def _create_session(self):
        session = requests.Session()
        retry_strategy = Retry(
            total=5,
            backoff_factor=1.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=3,
            pool_maxsize=10
        )
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _get_headers(self):
        return {
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-GB,en-US;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document'
        }

    def _extract_price_from_script(self, soup):
        """Extract price from JSON-LD script tags"""
        try:
            scripts = soup.find_all('script', type='application/ld+json')
            for script in scripts:
                try:
                    data = json.loads(script.string)
                    if isinstance(data, dict):
                        # Check for different JSON-LD structures
                        if 'offers' in data:
                            price = data['offers'].get('price')
                        elif '@graph' in data:
                            for item in data['@graph']:
                                if 'offers' in item:
                                    price = item['offers'].get('price')
                                    if price:
                                        return float(price)
                        if price:
                            return float(price)
                except (json.JSONDecodeError, TypeError):
                    continue
        except Exception as e:
            logger.error(f"Error extracting price from script: {e}")
        return None

    def _extract_price_from_html(self, soup):
        """Extract price using multiple CSS selectors"""
        price_selectors = [
            'div._30jeq3._16Jk6d',
            'div.CEmiEU div._30jeq3',
            'div._16Jk6d',
            'div._30jeq3',
            'div.dyC4hf div._30jeq3',
            'div.dyC4hf span._30jeq3'
        ]
        
        for selector in price_selectors:
            try:
                element = soup.select_one(selector)
                if element:
                    price_text = element.text.strip()
                    # Remove ₹ symbol and commas, then convert to float
                    price = float(re.sub(r'[^\d.]', '', price_text))
                    if price > 0:
                        logger.info(f"Price found with selector {selector}: ₹{price:,.2f}")
                        return price
            except Exception as e:
                logger.warning(f"Error with selector {selector}: {e}")
                continue
        return None

    def get_price(self):
        max_retries = 5
        base_delay = 3
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # Add jitter to delay
                delay = base_delay * (1.5 ** attempt) + random.uniform(0, 2)
                if attempt > 0:
                    logger.info(f"Attempt {attempt + 1}: Waiting {delay:.2f} seconds")
                    time.sleep(delay)

                # Make the request
                response = self.session.get(
                    self.url,
                    headers=self._get_headers(),
                    timeout=(10, 20),
                    allow_redirects=True
                )
                response.raise_for_status()
                
                # Log response status and content length
                logger.info(f"Response status: {response.status_code}, Content length: {len(response.text)}")

                # Check for anti-bot measures
                if any(text in response.text.lower() for text in ['captcha', 'access denied', 'rate limit']):
                    raise Exception("Detected anti-bot measure")

                soup = BeautifulSoup(response.text, 'html.parser')

                # Try to get price from JSON-LD first
                price = self._extract_price_from_script(soup)
                
                # If JSON-LD fails, try HTML selectors
                if not price:
                    price = self._extract_price_from_html(soup)

                if not price:
                    raise ValueError("Price not found in page content")

                # Get product title
                title_selectors = [
                    'span.B_NuCI',
                    'h1.yhB1nd',
                    'h1._30jeq3',
                    'div._30jeq3'
                ]

                title = None
                for selector in title_selectors:
                    title_elem = soup.select_one(selector)
                    if title_elem:
                        title = title_elem.text.strip()
                        break

                if not title:
                    raise ValueError("Product title not found")

                # Log successful price fetch
                logger.info(f"Successfully fetched price for '{title}': ₹{price:,.2f}")

                return {
                    'title': title,
                    'price': price,
                    'timestamp': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
                    'attempt': attempt + 1
                }

            except requests.Timeout as e:
                last_error = f"Timeout error on attempt {attempt + 1}: {str(e)}"
                logger.warning(last_error)
            except requests.ConnectionError as e:
                last_error = f"Connection error on attempt {attempt + 1}: {str(e)}"
                logger.warning(last_error)
            except requests.RequestException as e:
                last_error = f"Request error on attempt {attempt + 1}: {str(e)}"
                logger.warning(last_error)
            except Exception as e:
                last_error = f"Error on attempt {attempt + 1}: {str(e)}"
                logger.warning(last_error)

            if attempt == max_retries - 1:
                logger.error(f"Failed to fetch price after {max_retries} attempts")
                raise Exception(f"Failed after {max_retries} attempts: {last_error}")

        raise Exception(f"Failed to fetch price after {max_retries} attempts")

class TelegramBot:
    def __init__(self, token, chat_id):
        self.token = token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{token}"
        self.session = requests.Session()

    def send_price_alert(self, data, threshold_price):
        try:
            message = (
                f"🔔 Price Alert!\n\n"
                f"Product: {data['title']}\n"
                f"Current Price: ₹{data['price']:,.2f}\n"
                f"Target Price: ₹{threshold_price:,.2f}\n"
                f"Savings: ₹{(threshold_price - data['price']):,.2f}\n\n"
                f"🛍️ Product URL:\n{data['url']}\n\n"
                f"⏰ Time: {data['timestamp']}"
            )
            
            params = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': 'HTML',
                'disable_web_page_preview': False
            }
            
            response = self.session.post(
                f"{self.api_url}/sendMessage",
                params=params,
                timeout=10
            )
            response.raise_for_status()
            
            logger.info(f"Price alert sent: ₹{data['price']:,.2f} <= ₹{threshold_price:,.2f}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")
            return False

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
                    threshold_price REAL,
                    price_change REAL
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
            cursor = conn.cursor()
            
            # Get previous price
            cursor.execute('''
                SELECT price FROM price_history 
                WHERE product_url = ? 
                ORDER BY timestamp DESC LIMIT 1
            ''', (tracking_state['product_url'],))
            
            prev_price = cursor.fetchone()
            price_change = data['price'] - prev_price[0] if prev_price else 0
                
            # Insert new price data
            cursor.execute('''
                INSERT INTO price_history 
                (product_url, product_title, price, timestamp, threshold_price, price_change)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (
                tracking_state['product_url'],
                data['title'],
                data['price'],
                data['timestamp'],
                tracking_state['threshold_price'],
                price_change
            ))
            conn.commit()
            
        logger.info(f"Price data stored: ₹{data['price']:,.2f} (Change: ₹{price_change:,.2f})")
    except Exception as e:
        logger.error(f"Error storing price data: {e}")

def price_tracking_thread():
    """Background thread for price tracking"""
    logger.info("Price tracking thread started")
    tracker = PriceTracker(tracking_state['product_url'])
    telegram_bot = TelegramBot(**tracking_state['telegram_config'])
    
    consecutive_errors = 0
    max_consecutive_errors = 5
    
    while tracking_state['is_tracking']:
        try:
            data = tracker.get_price()
            data['url'] = tracking_state['product_url']
            tracking_state['current_data'] = data
            tracking_state['last_error'] = None
            
            store_price_data(data)
            
            if data['price'] <= tracking_state['threshold_price']:
                telegram_bot.send_price_alert(data, tracking_state['threshold_price'])
            
            consecutive_errors = 0
            time.sleep(60)
            
        except Exception as e:
            consecutive_errors += 1
            error_msg = str(e)
            tracking_state['last_error'] = error_msg
            logger.error(f"Error in price tracking (attempt {consecutive_errors}): {error_msg}")
            
            if consecutive_errors >= max_consecutive_errors:
                logger.error("Too many consecutive errors, stopping tracking")
                tracking_state['is_tracking'] = False
                break
                
            sleep_time = min(60 * (2 ** (consecutive_errors - 1)), 300)
            logger.info(f"Waiting {sleep_time} seconds before next attempt")
            time.sleep(sleep_time)

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
        
        if not data['url'].startswith('https://www.flipkart.com'):
            raise ValueError("Invalid Flipkart URL")
            
        tracking_state.update({
            'product_url': data['url'],
            'threshold_price': float(data['threshold_price']),
            'telegram_config': {
                'token': data['telegram_token'],
                'chat_id': data['telegram_chat_id']
            },
            'is_tracking': True,
            'last_error': None
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
        
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 400
    except Exception as e:
        logger.error(f"Failed to start tracking: {e}")
        return jsonify({
            'status': 'error',
            'message': 'Internal server error'
        }), 500

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
        'threshold_price': tracking_state['threshold_price'],
        'last_error': tracking_state['last_error']
    })

@app.route('/api/price_history')
def get_price_history():
    try:
        with sqlite3.connect(DATABASE_NAME) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute('''
                SELECT *
                FROM price_history
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
        print("\n=== Flipkart Price Tracker ===")
        print(f"Time: {CURRENT_TIME}")
        print(f"User: {USER_LOGIN}")
        print("===========================\n")
        
        init_database()
        
        ngrok_thread = threading.Thread(target=start_ngrok, daemon=True)
        ngrok_thread.start()
        time.sleep(2)
        
        logger.info(f"Starting Flask application on port {PORT}")
        app.run(host='0.0.0.0', port=PORT, debug=False)
        
    except Exception as e:
        logger.error(f"Application startup error: {e}")
        raise
