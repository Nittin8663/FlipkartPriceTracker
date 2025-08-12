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
import socket
import psutil
import os
from contextlib import closing
import signal

app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Constants with your exact current time and login
CURRENT_TIME = "2025-08-12 18:17:38"
USER_LOGIN = "Nittin8663"
DATABASE_NAME = "price_history.db"
BASE_PORT = 8000

# Global tracking state
tracking_state = {
    'is_tracking': False,
    'tracker_thread': None,
    'current_data': None,
    'product_url': None,
    'threshold_price': None,
    'telegram_config': None,
    'last_error': None,
    'last_check_time': None
}

def cleanup_processes():
    """Clean up existing Python and ngrok processes"""
    try:
        for proc in psutil.process_iter(['pid', 'name', 'connections']):
            try:
                proc_name = proc.info['name'].lower()
                if 'python' in proc_name:
                    for conn in proc.info.get('connections', []):
                        if hasattr(conn, 'laddr') and conn.laddr.port in range(8000, 8100):
                            logger.info(f"Terminating Python process {proc.info['pid']} on port {conn.laddr.port}")
                            os.kill(proc.info['pid'], signal.SIGTERM)
                elif 'ngrok' in proc_name:
                    logger.info(f"Terminating ngrok process {proc.info['pid']}")
                    os.kill(proc.info['pid'], signal.SIGTERM)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        time.sleep(2)  # Wait for processes to terminate
    except Exception as e:
        logger.warning(f"Error during process cleanup: {e}")

def find_free_port(start_port=8000, max_port=8099):
    """Find a free port to use"""
    for port in range(start_port, max_port + 1):
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            try:
                sock.bind(('', port))
                logger.info(f"Found free port: {port}")
                return port
            except socket.error:
                continue
    raise RuntimeError("No free ports found in range 8000-8099")

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    logger.info("Received shutdown signal")
    cleanup_processes()
    os._exit(0)

# Register signal handlers
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

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
            # Extract the product ID and keep only essential parameters
            pid_match = re.search(r'pid=([A-Z0-9]+)', url)
            if pid_match:
                pid = pid_match.group(1)
                # Extract base URL
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
            backoff_factor=2,
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
            'Sec-Fetch-Site': 'none',
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
                        # Check different JSON-LD structures
                        if 'offers' in data:
                            price = data['offers'].get('price')
                            if price:
                                return float(price)
                        elif '@graph' in data:
                            for item in data['@graph']:
                                if 'offers' in item:
                                    price = item['offers'].get('price')
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
            'div.dyC4hf span._30jeq3',
            'div[data-price]'  # Additional selector for data attribute
        ]
        
        for selector in price_selectors:
            try:
                element = soup.select_one(selector)
                if element:
                    # Try to get price from data attribute first
                    if element.get('data-price'):
                        price = float(element['data-price'])
                        if price > 0:
                            return price
                    
                    # Try to get price from text content
                    price_text = element.text.strip()
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
                delay = base_delay * (2 ** attempt) + random.uniform(0, 2)
                if attempt > 0:
                    logger.info(f"Attempt {attempt + 1}: Waiting {delay:.2f} seconds")
                    time.sleep(delay)

                # Make the request
                response = self.session.get(
                    self.url,
                    headers=self._get_headers(),
                    timeout=(15, 30),  # Increased timeouts
                    allow_redirects=True
                )
                response.raise_for_status()
                
                # Update last check time
                tracking_state['last_check_time'] = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                
                # Log response details
                logger.info(f"Response status: {response.status_code}, Content length: {len(response.text)}")

                # Check for anti-bot measures
                if any(text in response.text.lower() for text in ['captcha', 'access denied', 'rate limit']):
                    raise Exception("Detected anti-bot measure")

                soup = BeautifulSoup(response.text, 'html.parser')

                # Try multiple price extraction methods
                price = (
                    self._extract_price_from_script(soup) or 
                    self._extract_price_from_html(soup)
                )

                if not price:
                    raise ValueError("Price not found in page content")

                # Get product title with multiple selectors
                title_selectors = [
                    'span.B_NuCI',
                    'h1.yhB1nd',
                    'h1._30jeq3',
                    'div._30jeq3',
                    'h1[class*="title"]'
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
                    'timestamp': tracking_state['last_check_time'],
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
                tracking_state['last_error'] = last_error
                logger.error(f"Failed to fetch price after {max_retries} attempts")
                raise Exception(f"Failed after {max_retries} attempts: {last_error}")

        raise Exception(f"Failed to fetch price after {max_retries} attempts")

# ... [Previous TelegramBot class and other functions remain the same] ...

if __name__ == '__main__':
    try:
        # Print startup banner
        print("\n=== Flipkart Price Tracker ===")
        print(f"Time: {CURRENT_TIME}")
        print(f"User: {USER_LOGIN}")
        print("===========================\n")
        
        # Cleanup existing processes
        logger.info("Cleaning up existing processes...")
        cleanup_processes()
        
        # Find an available port
        try:
            PORT = find_free_port()
        except RuntimeError as e:
            logger.error(f"Port error: {e}")
            print("Error: No available ports found. Please check running processes.")
            exit(1)
            
        logger.info(f"Selected port: {PORT}")
        
        # Initialize database
        init_database()
        
        # Start ngrok with the selected port
        try:
            ngrok_thread = threading.Thread(target=start_ngrok, daemon=True)
            ngrok_thread.start()
            time.sleep(2)
        except Exception as e:
            logger.error(f"Failed to start ngrok: {e}")
            print("Error: Failed to start ngrok. Please check your internet connection.")
            exit(1)
        
        # Start Flask application
        logger.info(f"Starting Flask application on port {PORT}")
        app.run(host='0.0.0.0', port=PORT, debug=False)
        
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
        cleanup_processes()
        
    except Exception as e:
        logger.error(f"Application startup error: {e}")
        cleanup_processes()
        raise
