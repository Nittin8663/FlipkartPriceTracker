import requests
from bs4 import BeautifulSoup
import logging
from fake_useragent import UserAgent
import re
from datetime import datetime

class PriceTracker:
    def __init__(self, url):
        self.url = url
        self.logger = logging.getLogger(__name__)
        self.user_agent = UserAgent()
        
    def get_price(self):
        """Extract price from Flipkart product page"""
        try:
            headers = {
                'User-Agent': self.user_agent.random,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Connection': 'keep-alive',
            }
            
            response = requests.get(self.url, headers=headers, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Try different price selectors
            price_element = (
                soup.find('div', {'class': '_30jeq3 _16Jk6d'}) or
                soup.find('div', {'class': '_30jeq3'}) or
                soup.find('div', {'class': 'price'})
            )
            
            if not price_element:
                raise ValueError("Price element not found on the page")
                
            price_text = price_element.get_text().strip()
            price = float(re.sub(r'[^\d.]', '', price_text))
            
            # Get product title
            title_element = (
                soup.find('span', {'class': 'B_NuCI'}) or
                soup.find('h1', {'class': 'yhB1nd'})
            )
            title = title_element.get_text().strip() if title_element else "Product"
            
            return {
                'price': price,
                'title': title,
                'timestamp': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            }
                
        except requests.RequestException as e:
            self.logger.error(f"Network error: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Error extracting price: {e}")
            raise
