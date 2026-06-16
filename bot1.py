"""
GOOD HQ BOT - Production Grade Telegram Bot
Single file implementation with all fixes applied.
"""

import os
import re
import json
import time
import glob
import random
import hashlib
import threading
import importlib
from typing import Optional, List, Dict, Any, Tuple, Set
from datetime import datetime, timedelta
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
from logging.handlers import RotatingFileHandler
import logging
import sys
import shutil

import requests
import telebot
from telebot import types
from telebot.apihelper import ApiException

# ===================================================================
#                           CONFIGURATION
# ===================================================================

@dataclass
class Config:
    """Application configuration with environment variable support."""
    
    # Required environment variables
    TELEGRAM_TOKEN: str = os.getenv('TELEGRAM_TOKEN', '')
    ADMIN_ID: int = int(os.getenv('ADMIN_ID', '0'))
    
    # Optional with defaults
    RESULTS_DIR: str = os.getenv('RESULTS_DIR', 'results')
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')
    MAX_THREADS: int = int(os.getenv('MAX_THREADS', '3'))
    CHUNK_SIZE: int = int(os.getenv('CHUNK_SIZE', '100'))
    MAX_MESSAGE_LENGTH: int = 4000
    EDIT_RETRY_COUNT: int = 3
    EDIT_RETRY_DELAY: float = 0.5
    BIN_CACHE_TTL: int = 86400  # 24 hours
    PROXY_FILE: str = 'proxies.json'
    BANNED_FILE: str = 'banned.json'
    
    def validate(self) -> bool:
        """Validate required configuration."""
        if not self.TELEGRAM_TOKEN:
            raise ValueError("TELEGRAM_TOKEN environment variable is required")
        if not self.ADMIN_ID:
            raise ValueError("ADMIN_ID environment variable is required")
        return True

config = Config()

# ===================================================================
#                           LOGGER
# ===================================================================

class Logger:
    """Application logger with rotation and structured logging."""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._setup()
        return cls._instance
    
    def _setup(self):
        self.logger = logging.getLogger('GoodBot')
        self.logger.setLevel(getattr(logging, config.LOG_LEVEL))
        
        # Console handler
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(logging.DEBUG)
        console_formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        )
        console.setFormatter(console_formatter)
        self.logger.addHandler(console)
        
        # File handler with rotation
        try:
            file_handler = RotatingFileHandler(
                'bot.log',
                maxBytes=10*1024*1024,  # 10MB
                backupCount=5
            )
            file_handler.setLevel(logging.INFO)
            file_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)
        except Exception as e:
            self.logger.warning(f"Could not create log file: {e}")
    
    def get(self):
        return self.logger

logger = Logger().get()

# ===================================================================
#                           SECURITY
# ===================================================================

class SecurityManager:
    """Security management including authentication and validation."""
    
    def __init__(self):
        self._admin_id = config.ADMIN_ID
        self._banned_file = config.BANNED_FILE
        self._banned_cache = {}
        self._cache_lock = threading.Lock()
        self._load_banned()
    
    def _load_banned(self):
        """Load banned users from file."""
        try:
            if os.path.exists(self._banned_file):
                with open(self._banned_file, 'r', encoding='utf-8') as f:
                    self._banned_cache = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load banned list: {e}")
            self._banned_cache = {}
    
    def _save_banned(self):
        """Save banned users to file."""
        try:
            with open(self._banned_file, 'w', encoding='utf-8') as f:
                json.dump(self._banned_cache, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save banned list: {e}")
    
    def is_admin(self, user_id: int) -> bool:
        """Check if user is the bot admin."""
        return user_id == self._admin_id
    
    def is_banned(self, user_id: int) -> Tuple[bool, Optional[str]]:
        """Check if user is banned. Returns (is_banned, expiry_date_str)."""
        with self._cache_lock:
            user_id_str = str(user_id)
            if user_id_str not in self._banned_cache:
                return False, None
            
            ban_info = self._banned_cache[user_id_str]
            banned_until = ban_info.get('banned_until')
            
            if banned_until:
                try:
                    until = datetime.strptime(banned_until, '%Y-%m-%d %H:%M:%S')
                    if datetime.now() < until:
                        return True, banned_until
                    else:
                        # Auto-unban expired
                        del self._banned_cache[user_id_str]
                        self._save_banned()
                        return False, None
                except:
                    return True, None
            else:
                return True, None
    
    def ban_user(self, user_id: int, hours: int = 0, reason: str = "Violation") -> str:
        """Ban user. hours=0 for permanent."""
        with self._cache_lock:
            user_id_str = str(user_id)
            
            if hours == 0:
                banned_until = None
                duration_text = "Permanent"
            else:
                banned_until = (datetime.now() + timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')
                duration_text = f"{hours} hours"
            
            self._banned_cache[user_id_str] = {
                "banned_until": banned_until,
                "reason": reason,
                "banned_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            self._save_banned()
            return duration_text
    
    def unban_user(self, user_id: int) -> bool:
        """Unban user."""
        with self._cache_lock:
            user_id_str = str(user_id)
            if user_id_str in self._banned_cache:
                del self._banned_cache[user_id_str]
                self._save_banned()
                return True
            return False
    
    def get_banned_list(self) -> Dict:
        """Get list of banned users."""
        with self._cache_lock:
            return self._banned_cache.copy()
    
    def validate_proxy(self, proxy: str) -> bool:
        """Validate proxy format."""
        patterns = [
            r'^socks5://[^:]+:[^@]+@[\d.]+:\d+$',
            r'^socks5://[\d.]+:\d+$',
            r'^http://[^:]+:[^@]+@[\d.]+:\d+$',
            r'^http://[\d.]+:\d+$',
            r'^https://[^:]+:[^@]+@[\d.]+:\d+$',
            r'^https://[\d.]+:\d+$',
        ]
        return any(re.match(pattern, proxy) for pattern in patterns)
    
    def sanitize_file_path(self, path: str) -> str:
        """Sanitize file path to prevent path traversal."""
        sanitized = re.sub(r'\.\./', '', path)
        sanitized = re.sub(r'\.\.\\', '', sanitized)
        sanitized = re.sub(r'[^a-zA-Z0-9_.-]', '', sanitized)
        return sanitized

security = SecurityManager()

# ===================================================================
#                           CACHE
# ===================================================================

class Cache:
    """Thread-safe in-memory cache with TTL support."""
    
    def __init__(self, default_ttl_seconds: int = 300):
        self._cache = {}
        self._lock = threading.Lock()
        self._default_ttl = default_ttl_seconds
        self._cleanup_thread = threading.Thread(target=self._auto_cleanup, daemon=True)
        self._cleanup_thread.start()
    
    def _auto_cleanup(self):
        """Background thread for periodic cleanup."""
        while True:
            time.sleep(60)  # Clean every minute
            self.cleanup()
    
    def get(self, key: str) -> Optional[Any]:
        """Get item from cache if not expired."""
        with self._lock:
            if key not in self._cache:
                return None
            
            item = self._cache[key]
            if item['expires_at'] < datetime.now():
                del self._cache[key]
                return None
            
            return item['value']
    
    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None):
        """Set item in cache with TTL."""
        with self._lock:
            self._cache[key] = {
                'value': value,
                'expires_at': datetime.now() + timedelta(
                    seconds=ttl_seconds or self._default_ttl
                )
            }
    
    def delete(self, key: str):
        """Remove item from cache."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
    
    def clear(self):
        """Clear all cache."""
        with self._lock:
            self._cache.clear()
    
    def cleanup(self):
        """Remove expired items."""
        with self._lock:
            now = datetime.now()
            expired = [
                key for key, item in self._cache.items()
                if item['expires_at'] < now
            ]
            for key in expired:
                del self._cache[key]
            if expired:
                logger.debug(f"Cache cleanup: removed {len(expired)} expired items")

cache = Cache()

# ===================================================================
#                           STORAGE
# ===================================================================

class AtomicFileWriter:
    """Atomic file writer with backup and recovery."""
    
    def __init__(self, filepath: str, backup_count: int = 3):
        self.filepath = filepath
        self.backup_count = backup_count
        self._lock = threading.Lock()
        self._ensure_directory()
    
    def _ensure_directory(self):
        """Ensure directory exists."""
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
    
    def _create_backup(self):
        """Create backup of existing file."""
        if os.path.exists(self.filepath):
            backup_dir = os.path.join(config.RESULTS_DIR, 'backups')
            os.makedirs(backup_dir, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_name = f"{os.path.basename(self.filepath)}.{timestamp}.bak"
            backup_path = os.path.join(backup_dir, backup_name)
            shutil.copy2(self.filepath, backup_path)
            
            # Rotate old backups
            backups = sorted([
                f for f in os.listdir(backup_dir)
                if f.startswith(os.path.basename(self.filepath))
            ])
            while len(backups) > self.backup_count:
                try:
                    os.remove(os.path.join(backup_dir, backups.pop(0)))
                except:
                    pass
    
    def write(self, data: Any) -> bool:
        """Write data atomically."""
        with self._lock:
            try:
                self._create_backup()
                temp_path = f"{self.filepath}.tmp"
                
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                
                os.replace(temp_path, self.filepath)
                return True
            except Exception as e:
                logger.error(f"Error writing {self.filepath}: {e}")
                return False
    
    def read(self, default: Any = None) -> Any:
        """Read data from file."""
        with self._lock:
            try:
                if os.path.exists(self.filepath):
                    with open(self.filepath, 'r', encoding='utf-8') as f:
                        return json.load(f)
                return default
            except json.JSONDecodeError:
                logger.error(f"JSON decode error in {self.filepath}")
                return default
            except Exception as e:
                logger.error(f"Error reading {self.filepath}: {e}")
                return default

class StorageManager:
    """Centralized storage management."""
    
    def __init__(self):
        self._writers = {}
        self._ensure_directories()
    
    def _ensure_directories(self):
        """Ensure all required directories exist."""
        dirs = [
            config.RESULTS_DIR,
            os.path.join(config.RESULTS_DIR, 'backups'),
        ]
        for d in dirs:
            os.makedirs(d, exist_ok=True)
    
    def get_writer(self, filename: str) -> AtomicFileWriter:
        """Get or create atomic writer for file."""
        if filename not in self._writers:
            path = os.path.join(config.RESULTS_DIR, filename)
            self._writers[filename] = AtomicFileWriter(path)
        return self._writers[filename]
    
    def save_result(self, result: Dict):
        """Save check result."""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        line = f"{result['cc']}|{result['bank']}|{result['country']}|{result['gate']}|{timestamp}\n"
        
        if result['status'] in ['charged', 'cvv']:
            writer = self.get_writer('hit.txt')
        elif result['status'] == 'low':
            writer = self.get_writer('low.txt')
        else:
            return
        
        with writer._lock:
            with open(writer.filepath, 'a', encoding='utf-8') as f:
                f.write(line)

storage = StorageManager()

# ===================================================================
#                           PROXY MANAGER
# ===================================================================

class ProxyManager:
    """Thread-safe proxy management."""
    
    def __init__(self):
        self._file = config.PROXY_FILE
        self._proxies = {}
        self._lock = threading.Lock()
        self._load()
    
    def _load(self):
        """Load proxies from file."""
        try:
            if os.path.exists(self._file):
                with open(self._file, 'r', encoding='utf-8') as f:
                    self._proxies = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load proxies: {e}")
            self._proxies = {}
    
    def _save(self):
        """Save proxies to file."""
        try:
            with open(self._file, 'w', encoding='utf-8') as f:
                json.dump(self._proxies, f, indent=4)
        except Exception as e:
            logger.error(f"Failed to save proxies: {e}")
    
    def get_proxy(self, user_id: int) -> Optional[str]:
        """Get proxy for user."""
        with self._lock:
            user_id_str = str(user_id)
            if user_id_str in self._proxies:
                return self._proxies[user_id_str].get('proxy')
            return None
    
    def set_proxy(self, user_id: int, proxy_url: str) -> bool:
        """Set proxy for user."""
        if not security.validate_proxy(proxy_url):
            return False
        
        with self._lock:
            user_id_str = str(user_id)
            self._proxies[user_id_str] = {
                'proxy': proxy_url,
                'set_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            self._save()
            return True
    
    def remove_proxy(self, user_id: int) -> bool:
        """Remove proxy for user."""
        with self._lock:
            user_id_str = str(user_id)
            if user_id_str in self._proxies:
                del self._proxies[user_id_str]
                self._save()
                return True
            return False

proxy_manager = ProxyManager()

# ===================================================================
#                           CC PROCESSOR
# ===================================================================

class CCProcessor:
    """Credit card processing and validation."""
    
    def __init__(self):
        self._gate_modules = self._load_gates()
        logger.info(f"Loaded {len(self._gate_modules)} gate modules")
    
    def _load_gates(self) -> List:
        """Load gate modules."""
        gates = []
        for gate_file in glob.glob('gate*.py'):
            if gate_file.endswith('__init__.py'):
                continue
            module_name = gate_file.replace('.py', '')
            try:
                module = importlib.import_module(module_name)
                if hasattr(module, 'Tele'):
                    gates.append(module)
                    logger.debug(f"Loaded gate: {module_name}")
            except Exception as e:
                logger.warning(f"Failed to load gate {module_name}: {e}")
        
        if not gates:
            # Fallback dummy gate
            class DummyGate:
                @staticmethod
                def Tele(cc, proxies=None):
                    import random
                    responses = [
                        '{"status": "success", "message": "Payment successful"}',
                        '{"status": "error", "error": {"message": "Insufficient funds"}}',
                        '{"status": "error", "error": {"message": "Do not honor"}}'
                    ]
                    return random.choice(responses)
            gates.append(DummyGate)
        
        return gates
    
    def extract_cc(self, text: str) -> List[str]:
        """Extract credit card numbers from text."""
        if not text:
            return []
        
        results = []
        seen = set()
        
        # Pattern 1: Standard delimiter format
        pattern1 = r'(\d{15,16})\s*[|\|:;/]\s*(\d{1,2})\s*[|\|:;/]\s*(\d{2,4})\s*[|\|:;/]\s*(\d{3,4})'
        matches = re.findall(pattern1, text, re.IGNORECASE)
        for match in matches:
            card = self._format_cc(match[0], match[1], match[2], match[3])
            if card and card not in seen:
                seen.add(card)
                results.append(card)
        
        # Pattern 2: Space separated
        if not results:
            pattern2 = r'(\d{15,16})\s+(\d{1,2})\s+(\d{2,4})\s+(\d{3,4})'
            matches = re.findall(pattern2, text, re.IGNORECASE)
            for match in matches:
                card = self._format_cc(match[0], match[1], match[2], match[3])
                if card and card not in seen:
                    seen.add(card)
                    results.append(card)
        
        # Pattern 3: Dash separated
        if not results:
            text_no_dash = re.sub(r'(\d{4})-(\d{4})-(\d{4})-(\d{4})', r'\1\2\3\4', text)
            if text_no_dash != text:
                results = self.extract_cc(text_no_dash)
        
        return results
    
    def _format_cc(self, number: str, month: str, year: str, cvv: str) -> Optional[str]:
        """Format CC components into standard format."""
        try:
            month = month.zfill(2)
            if len(year) == 4:
                year = year[2:4]
            else:
                year = year.zfill(2)
            cvv = cvv.zfill(3)
            
            if 1 <= int(month) <= 12 and len(year) == 2 and len(cvv) == 3:
                return f"{number}|{month}|{year}|{cvv}"
        except:
            pass
        return None
    
    def is_expired(self, cc: str) -> bool:
        """Check if card is expired."""
        try:
            parts = cc.split('|')
            if len(parts) >= 3:
                month = int(parts[1])
                year = int(parts[2])
                if len(parts[2]) == 2:
                    year += 2000
                
                now = datetime.now()
                return (year < now.year) or (year == now.year and month < now.month)
        except:
            pass
        return False
    
    def get_bin_info(self, cc: str) -> Tuple[str, str]:
        """Get BIN information from cache or API."""
        if not cc or len(cc) < 6:
            return "Unknown", "Unknown"
        
        bin_key = cc[:6]
        cache_key = f"bin_{bin_key}"
        
        # Try cache first
        cached = cache.get(cache_key)
        if cached:
            return cached.get('bin', 'Unknown'), cached.get('type', 'Unknown')
        
        try:
            response = requests.get(
                f'https://bins.antipublic.cc/bins/{bin_key}',
                timeout=5
            )
            if response.status_code == 200:
                data = response.json()
                country = data.get('country_name', 'Unknown')
                flag = data.get('country_flag', '')
                bank = data.get('bank', 'Unknown')
                brand = data.get('brand', 'Unknown')
                card_type = data.get('type', 'Unknown')
                level = data.get('level', '')
                
                bin_text = f"{bank} - {country} ({flag})" if flag else f"{bank} - {country}"
                card_text = f"{brand} - {card_type} ({level})" if level else f"{brand} - {card_type}"
                
                cache.set(cache_key, {
                    'bin': bin_text,
                    'type': card_text
                }, ttl_seconds=config.BIN_CACHE_TTL)
                
                return bin_text, card_text
        except Exception as e:
            logger.debug(f"BIN lookup failed for {bin_key}: {e}")
        
        return "Unknown", "Unknown"
    
    def check_card(self, cc: str, proxy: Optional[str] = None) -> Dict:
        """Check a single card with random gate."""
        start_time = time.time()
        
        result = {
            'cc': cc,
            'gate': 'N/A',
            'status': 'unknown',
            'status_text': '❌ UNKNOWN',
            'bin': 'Unknown',
            'card_type': 'Unknown',
            'bank': 'Unknown',
            'country': 'Unknown',
            'taken': 0.0,
            'response': 'No response'
        }
        
        try:
            if not self._gate_modules:
                result['status'] = 'error'
                result['status_text'] = '❌ No gates available'
                return result
            
            # Select random gate
            gate = random.choice(self._gate_modules)
            gate_name = gate.__name__
            result['gate'] = gate_name
            
            # Prepare proxies
            proxies = None
            if proxy:
                proxies = {'http': proxy, 'https': proxy}
            
            # Call gate with timeout
            try:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        gate.Tele, cc, proxies
                    )
                    response = future.result(timeout=30)
            except Exception as e:
                result['status'] = 'error'
                result['status_text'] = f'❌ Gate error: {str(e)[:50]}'
                result['taken'] = round(time.time() - start_time, 2)
                return result
            
            # Parse response
            response_str = str(response)
            result['response'] = response_str[:500]
            
            # Determine status
            status, status_text = self._determine_status(response_str)
            result['status'] = status
            result['status_text'] = status_text
            
            # Get BIN info
            bin_text, card_type = self.get_bin_info(cc)
            result['bin'] = bin_text
            result['card_type'] = card_type
            
            # Extract bank and country
            if ' - ' in bin_text:
                parts = bin_text.split(' - ')
                result['bank'] = parts[0].strip()
                result['country'] = parts[1].strip() if len(parts) > 1 else 'Unknown'
            else:
                result['bank'] = bin_text
                result['country'] = 'Unknown'
            
        except Exception as e:
            logger.error(f"Error checking card {cc[:6]}: {e}")
            result['status'] = 'error'
            result['status_text'] = f'❌ Error: {str(e)[:50]}'
        
        result['taken'] = round(time.time() - start_time, 2)
        return result
    
    def _determine_status(self, response: str) -> Tuple[str, str]:
        """Determine status from response."""
        response_lower = response.lower()
        
        # Hit indicators
        hit_keywords = [
            'succeeded', 'success', 'thank you', 'payment successful',
            'approved', 'charge', 'paid', 'complete', 'confirmation',
            'appreciate', 'appreciated', 'redirect_to', 'thank',
            'redirectUrl', 'Successful!', 'hide_form', 'redirect_url',
            'Form entry saved', 'Success!'
        ]
        if any(k in response_lower for k in hit_keywords):
            return 'charged', '✅ PAYMENT SUCCESSFUL ✅'
        
        # CVV/Live indicators
        cvv_keywords = [
            '3d_secure', 'authentication_required', 'action_required',
            'verification', 'redirect', 'authenticate', 'challenge_required',
            'requires_source_action', 'CompletePaymentChallenge', 'requires_action',
            'nextAction', 'Verifying', 'verifying', 'call_next_method'
        ]
        if any(k in response_lower for k in cvv_keywords):
            return 'cvv', '💎 CVV LIVE 💎'
        
        # Low funds indicators
        low_keywords = [
            'insufficient funds', 'low funds', 'insufficient',
            'INSUFFICIENT_FUNDS', 'insufficient_funds', 'Insufficient Funds'
        ]
        if any(k in response_lower for k in low_keywords):
            return 'low', '💰 LOW FUNDS 💰'
        
        # CCN only indicators
        ccn_keywords = [
            'security code is incorrect', 'incorrect_cvv', 'cvv',
            'INCORRECT_CVV', 'Your card number is incorrect'
        ]
        if any(k in response_lower for k in ccn_keywords):
            return 'ccn', '⚠️ CCN ONLY ⚠️'
        
        # Expired indicators
        expired_keywords = ['expired', 'exp_date', 'card has expired']
        if any(k in response_lower for k in expired_keywords):
            return 'expired', '📅 EXPIRED CARD'
        
        # Declined indicators
        declined_keywords = [
            'declined', 'do_not_honor', 'generic_decline', 'card_declined',
            'cannot be processed', 'cannot process your order'
        ]
        if any(k in response_lower for k in declined_keywords):
            return 'declined', '❌ DECLINED ❌'
        
        # Default
        return 'unknown', '❌ UNKNOWN RESPONSE'
    
    def process_batch(self, ccs: List[str], proxy: Optional[str] = None,
                     max_workers: Optional[int] = None) -> List[Dict]:
        """Process multiple cards concurrently."""
        if not ccs:
            return []
        
        workers = max_workers or config.MAX_THREADS
        results = []
        results_lock = threading.Lock()
        
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_cc = {
                executor.submit(self.check_card, cc, proxy): cc
                for cc in ccs
            }
            
            for future in as_completed(future_to_cc):
                try:
                    result = future.result(timeout=60)
                    with results_lock:
                        results.append(result)
                except Exception as e:
                    cc = future_to_cc[future]
                    logger.error(f"Batch processing error for {cc[:6]}: {e}")
                    with results_lock:
                        results.append({
                            'cc': cc,
                            'status': 'error',
                            'status_text': f'❌ Error: {str(e)[:50]}',
                            'taken': 0.0,
                            'gate': 'Error',
                            'bin': 'Unknown',
                            'card_type': 'Unknown'
                        })
        
        return results

cc_processor = CCProcessor()

# ===================================================================
#                           TELEGRAM BOT
# ===================================================================

class GoodBot:
    """Main bot class with production-grade features."""
    
    def __init__(self):
        self.bot = telebot.TeleBot(config.TELEGRAM_TOKEN, parse_mode='HTML')
        self._active_checks: Set[int] = set()
        self._lock = threading.Lock()
        self._setup_handlers()
        logger.info("Bot initialized")
    
    def _setup_handlers(self):
        """Setup all message handlers."""
        self.bot.message_handler(commands=['start'])(self.cmd_start)
        self.bot.message_handler(commands=['v1'])(self.cmd_single_check)
        self.bot.message_handler(commands=['v', '.v'])(self.cmd_mass_check)
        self.bot.message_handler(commands=['proxy'])(self.cmd_proxy)
        self.bot.message_handler(commands=['id'])(self.cmd_id)
        self.bot.message_handler(commands=['stats'])(self.cmd_stats)
        self.bot.message_handler(commands=['ban'])(self.cmd_ban)
        self.bot.message_handler(commands=['unban'])(self.cmd_unban)
        self.bot.message_handler(commands=['bannedlist'])(self.cmd_bannedlist)
        self.bot.message_handler(content_types=['document'])(self.handle_file)
    
    def _safe_edit(self, message_id: int, chat_id: int, text: str) -> bool:
        """Safely edit message with retry."""
        if not text:
            return False
        
        # Truncate if too long
        if len(text) > config.MAX_MESSAGE_LENGTH:
            text = text[:config.MAX_MESSAGE_LENGTH - 100] + "\n...(truncated)"
        
        for attempt in range(config.EDIT_RETRY_COUNT):
            try:
                self.bot.edit_message_text(
                    text,
                    chat_id=chat_id,
                    message_id=message_id,
                    parse_mode='HTML'
                )
                return True
            except ApiException as e:
                error_str = str(e)
                if 'message is not modified' in error_str:
                    return True
                if 'message can\'t be edited' in error_str:
                    return False
                if 'message to edit not found' in error_str:
                    return False
                if attempt < config.EDIT_RETRY_COUNT - 1:
                    time.sleep(config.EDIT_RETRY_DELAY * (attempt + 1))
                    continue
                logger.warning(f"Failed to edit message {message_id}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error editing message: {e}")
                break
        
        return False
    
    def _send_message(self, chat_id: int, text: str) -> Optional[int]:
        """Send message with length check and chunking."""
        if not text:
            return None
        
        if len(text) <= config.MAX_MESSAGE_LENGTH:
            try:
                msg = self.bot.send_message(chat_id, text, parse_mode='HTML')
                return msg.message_id
            except ApiException as e:
                if 'message is too long' in str(e):
                    # Fallback to chunking
                    return self._send_chunked_message(chat_id, text)
                logger.error(f"Failed to send message: {e}")
                return None
            except Exception as e:
                logger.error(f"Failed to send message: {e}")
                return None
        
        return self._send_chunked_message(chat_id, text)
    
    def _send_chunked_message(self, chat_id: int, text: str) -> Optional[int]:
        """Send long message in chunks."""
        chunks = []
        while text:
            if len(text) <= config.MAX_MESSAGE_LENGTH:
                chunks.append(text)
                break
            split_at = text[:config.MAX_MESSAGE_LENGTH].rfind('\n')
            if split_at == -1:
                split_at = config.MAX_MESSAGE_LENGTH
            chunks.append(text[:split_at])
            text = text[split_at:]
        
        last_id = None
        for i, chunk in enumerate(chunks):
            try:
                if i == 0:
                    msg = self.bot.send_message(chat_id, chunk, parse_mode='HTML')
                    last_id = msg.message_id
                else:
                    self.bot.send_message(chat_id, chunk, parse_mode='HTML')
                time.sleep(0.1)  # Rate limit between messages
            except Exception as e:
                logger.error(f"Failed to send chunk: {e}")
        return last_id
    
    def _is_authorized(self, user_id: int) -> Tuple[bool, str]:
        """Check if user is authorized. Returns (authorized, reason)."""
        # Check if admin
        if security.is_admin(user_id):
            return True, "admin"
        
        # Check if banned
        is_banned, until = security.is_banned(user_id)
        if is_banned:
            if until:
                return False, f"banned_until_{until}"
            return False, "banned_permanent"
        
        # Only admin allowed
        return False, "not_admin"
    
    def _get_user_name(self, message) -> str:
        """Get user display name."""
        if message.from_user.username:
            return f"@{message.from_user.username}"
        return message.from_user.first_name or "Unknown"
    
    # ===============================================================
    #                         COMMANDS
    # ===============================================================
    
    def cmd_start(self, message):
        """Start command."""
        user_id = message.chat.id
        authorized, reason = self._is_authorized(user_id)
        
        if not authorized:
            if reason.startswith('banned_until_'):
                until = reason.replace('banned_until_', '')
                self._send_message(message.chat.id, f"⛔ <b>BANNED UNTIL</b>\n{until}")
            else:
                self._send_message(message.chat.id, "❌ <b>Access denied.</b>\nThis bot is private.")
            return
        
        welcome = """
🚀 <b>GOOD HQ BOT</b> 🚀
━━━━━━━━━━━━━━━━━━━━━━━━

👑 <b>Admin Mode</b> (Private)
📊 <b>Status:</b> Active

━━━━━━━━━━━━━━━━━━━━━━━━
🎮 <b>COMMANDS:</b>

• Send .txt file - Mass check
• <code>/v</code> or <code>.v</code> - Live mass check
• <code>/v1</code> - Single card check
• <code>/id</code> - Get user ID
• <code>/proxy</code> - Set your proxy
• <code>/stats</code> - Bot statistics
• <code>/ban</code> - Ban user
• <code>/unban</code> - Unban user
• <code>/bannedlist</code> - List banned users

━━━━━━━━━━━━━━━━━━━━━━━━
"""
        self._send_message(message.chat.id, welcome)
    
    def cmd_single_check(self, message):
        """Single card check."""
        user_id = message.chat.id
        authorized, reason = self._is_authorized(user_id)
        
        if not authorized:
            self._send_message(message.chat.id, "❌ <b>Access denied.</b>")
            return
        
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            self._send_message(
                message.chat.id,
                "Usage: <code>/v1 cc|mm|yy|cvv</code>\n"
                "Example: <code>/v1 4744770173288524|12|26|213</code>"
            )
            return
        
        ccs = cc_processor.extract_cc(args[1])
        if not ccs:
            self._send_message(message.chat.id, "❌ No valid CC found!")
            return
        
        # Send initial message
        status_msg = self._send_message(
            message.chat.id,
            "🔄 <b>Checking...</b>"
        )
        if not status_msg:
            return
        
        # Get proxy if set
        proxy = proxy_manager.get_proxy(user_id)
        
        # Process card
        cc = ccs[0]
        result = cc_processor.check_card(cc, proxy)
        
        # Build response
        response = f"""
<b>Cc:</b> <code>{result['cc']}</code>
<b>Gate:</b> {result['gate']}
<b>State:</b> {result['status_text']}
<b>Bin:</b> {result['bin']}
<b>{result['card_type']}</b>
━━━━━━━━━━━━━━━━━━━━━━━━
<b>Taken:</b> {result['taken']}s
<b>Check By:</b> {self._get_user_name(message)}
"""
        
        self._safe_edit(status_msg, message.chat.id, response)
        
        # Save results
        if result['status'] in ['charged', 'cvv', 'low']:
            storage.save_result({
                'cc': result['cc'],
                'status': result['status'],
                'bank': result['bank'],
                'country': result['country'],
                'gate': result['gate']
            })
    
    def cmd_mass_check(self, message):
        """Mass check command."""
        user_id = message.chat.id
        authorized, reason = self._is_authorized(user_id)
        
        if not authorized:
            self._send_message(message.chat.id, "❌ <b>Access denied.</b>")
            return
        
        # Extract CCs
        ccs = []
        
        # Check if replying to a message
        if message.reply_to_message:
            replied = message.reply_to_message.text or message.reply_to_message.caption or ''
            ccs = cc_processor.extract_cc(replied)
        
        # Check command arguments
        args = message.text.split(maxsplit=1)
        if len(args) > 1 and not ccs:
            ccs = cc_processor.extract_cc(args[1])
        
        if not ccs:
            self._send_message(
                message.chat.id,
                "❌ No valid CC found!\n"
                "Usage: <code>/v cc|mm|yy|cvv</code>"
            )
            return
        
        # Filter expired cards
        valid_ccs = [cc for cc in ccs if not cc_processor.is_expired(cc)]
        
        if not valid_ccs:
            self._send_message(message.chat.id, "⚠️ All cards are expired!")
            return
        
        logger.info(f"Mass check: {len(valid_ccs)} cards from {user_id}")
        
        # Send initial status
        status_msg = self._send_message(
            message.chat.id,
            f"🔄 <b>Checking {len(valid_ccs)} cards...</b>\nProgress: 0/{len(valid_ccs)}"
        )
        if not status_msg:
            return
        
        # Get proxy
        proxy = proxy_manager.get_proxy(user_id)
        
        # Mark as active
        with self._lock:
            self._active_checks.add(user_id)
        
        results = []
        hits = []
        progress_lock = threading.Lock()
        last_update = 0
        
        try:
            # Process in chunks
            batch_size = config.CHUNK_SIZE
            for i in range(0, len(valid_ccs), batch_size):
                batch = valid_ccs[i:i+batch_size]
                batch_results = cc_processor.process_batch(batch, proxy)
                results.extend(batch_results)
                
                # Track hits
                for r in batch_results:
                    if r['status'] in ['charged', 'cvv', 'low']:
                        hits.append(r)
                        storage.save_result({
                            'cc': r['cc'],
                            'status': r['status'],
                            'bank': r.get('bank', 'Unknown'),
                            'country': r.get('country', 'Unknown'),
                            'gate': r.get('gate', 'Unknown')
                        })
                
                # Update progress (throttled)
                current_progress = min(i + len(batch), len(valid_ccs))
                current_time = time.time()
                if current_progress == len(valid_ccs) or current_time - last_update > 1:
                    self._safe_edit(
                        status_msg,
                        message.chat.id,
                        f"🔄 <b>Checking {len(valid_ccs)} cards...</b>\n"
                        f"Progress: {current_progress}/{len(valid_ccs)}\n"
                        f"Hits: {len(hits)}"
                    )
                    last_update = current_time
                
        finally:
            with self._lock:
                self._active_checks.discard(user_id)
        
        # Build final response
        if hits:
            response = f"✅ <b>CHECK COMPLETE</b>\n"
            response += f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            response += f"<b>Total Cards:</b> {len(valid_ccs)}\n"
            response += f"<b>Hits:</b> {len(hits)}\n"
            response += f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            
            # Add hit details (max 10 to avoid message length issues)
            for i, hit in enumerate(hits[:10]):
                response += f"<b>{i+1}.</b> <code>{hit['cc'][:16]}</code> | {hit['status_text']} | {hit['gate']}\n"
            
            if len(hits) > 10:
                response += f"\n... and {len(hits) - 10} more hits"
            
            self._safe_edit(status_msg, message.chat.id, response)
        else:
            self._safe_edit(
                status_msg,
                message.chat.id,
                f"✅ <b>CHECK COMPLETE</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"<b>Total Cards:</b> {len(valid_ccs)}\n"
                f"<b>Hits:</b> 0"
            )
    
    def cmd_proxy(self, message):
        """Set or view proxy."""
        user_id = message.chat.id
        authorized, reason = self._is_authorized(user_id)
        
        if not authorized:
            self._send_message(message.chat.id, "❌ <b>Access denied.</b>")
            return
        
        args = message.text.split(maxsplit=1)
        
        if len(args) < 2:
            current = proxy_manager.get_proxy(user_id)
            if current:
                self._send_message(
                    message.chat.id,
                    f"🔗 <b>Your proxy:</b>\n<code>{current}</code>\n\n"
                    f"Use <code>/proxy off</code> to disable"
                )
            else:
                self._send_message(
                    message.chat.id,
                    "<b>📝 Proxy Commands:</b>\n"
                    "<code>/proxy socks5://user:pass@ip:port</code>\n"
                    "<code>/proxy off</code>\n"
                    "<code>/proxy</code> - to view"
                )
            return
        
        proxy_input = args[1].strip()
        
        if proxy_input.lower() == "off":
            if proxy_manager.remove_proxy(user_id):
                self._send_message(message.chat.id, "✅ <b>Proxy disabled!</b>")
            else:
                self._send_message(message.chat.id, "❌ <b>No active proxy to disable.</b>")
            return
        
        if proxy_manager.set_proxy(user_id, proxy_input):
            self._send_message(
                message.chat.id,
                f"✅ <b>Proxy set!</b>\n<code>{proxy_input}</code>\n\n"
                f"Use <code>/proxy off</code> to disable"
            )
        else:
            self._send_message(
                message.chat.id,
                "❌ <b>Invalid proxy format!</b>\n"
                "Use: <code>socks5://user:pass@ip:port</code>"
            )
    
    def cmd_id(self, message):
        """Get user ID."""
        user_id = message.chat.id
        authorized, reason = self._is_authorized(user_id)
        
        if not authorized:
            self._send_message(message.chat.id, "❌ <b>Access denied.</b>")
            return
        
        user = message.from_user
        response = f"""
🆔 <b>USER ID INFO</b>
━━━━━━━━━━━━━━━━━━━━━━━━

👤 <b>Username:</b> @{user.username if user.username else 'None'}
🆔 <b>User ID:</b> <code>{user.id}</code>
📅 <b>Name:</b> {user.first_name or ''} {user.last_name or ''}
"""
        self._send_message(message.chat.id, response)
    
    def cmd_stats(self, message):
        """Get bot statistics."""
        user_id = message.chat.id
        authorized, reason = self._is_authorized(user_id)
        
        if not authorized:
            self._send_message(message.chat.id, "❌ <b>Access denied.</b>")
            return
        
        # Count results
        hit_count = 0
        low_count = 0
        try:
            hit_file = os.path.join(config.RESULTS_DIR, 'hit.txt')
            low_file = os.path.join(config.RESULTS_DIR, 'low.txt')
            if os.path.exists(hit_file):
                with open(hit_file, 'r') as f:
                    hit_count = sum(1 for _ in f)
            if os.path.exists(low_file):
                with open(low_file, 'r') as f:
                    low_count = sum(1 for _ in f)
        except:
            pass
        
        response = f"""
📊 <b>BOT STATISTICS</b>
━━━━━━━━━━━━━━━━━━━━━━━━

👑 <b>Admin ID:</b> <code>{config.ADMIN_ID}</code>
⚙️ <b>Active Gates:</b> {len(cc_processor._gate_modules)}
📈 <b>Total Hits:</b> {hit_count}
💰 <b>Low Funds:</b> {low_count}
🔄 <b>Active Checks:</b> {len(self._active_checks)}
━━━━━━━━━━━━━━━━━━━━━━━━
"""
        self._send_message(message.chat.id, response)
    
    def cmd_ban(self, message):
        """Ban a user."""
        user_id = message.chat.id
        authorized, reason = self._is_authorized(user_id)
        
        if not authorized:
            return
        
        args = message.text.split()
        if len(args) < 2:
            self._send_message(
                message.chat.id,
                "Usage: <code>/ban [user_id] [hours] [reason]</code>\n"
                "Example: <code>/ban 123456789 24 Abuse</code>\n"
                "Use 0 for permanent"
            )
            return
        
        target_id = int(args[1])
        hours = int(args[2]) if len(args) > 2 else 24
        reason = " ".join(args[3:]) if len(args) > 3 else "Violation of rules"
        
        duration = security.ban_user(target_id, hours, reason)
        self._send_message(
            message.chat.id,
            f"✅ <b>User {target_id} banned for {duration}</b>\n"
            f"Reason: {reason}"
        )
        
        # Notify user
        try:
            self.bot.send_message(
                target_id,
                f"⛔ <b>BANNED</b>\n"
                f"Reason: {reason}\n"
                f"Duration: {duration}"
            )
        except:
            pass
    
    def cmd_unban(self, message):
        """Unban a user."""
        user_id = message.chat.id
        authorized, reason = self._is_authorized(user_id)
        
        if not authorized:
            return
        
        args = message.text.split()
        if len(args) < 2:
            self._send_message(
                message.chat.id,
                "Usage: <code>/unban [user_id]</code>"
            )
            return
        
        target_id = int(args[1])
        if security.unban_user(target_id):
            self._send_message(
                message.chat.id,
                f"✅ <b>User {target_id} unbanned!</b>"
            )
        else:
            self._send_message(
                message.chat.id,
                f"❌ <b>User {target_id} is not banned.</b>"
            )
    
    def cmd_bannedlist(self, message):
        """List banned users."""
        user_id = message.chat.id
        authorized, reason = self._is_authorized(user_id)
        
        if not authorized:
            return
        
        banned = security.get_banned_list()
        if not banned:
            self._send_message(message.chat.id, "📋 <b>No banned users.</b>")
            return
        
        response = "📋 <b>BANNED USERS</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n"
        for uid, info in banned.items():
            until = info.get('banned_until', 'Permanent')
            response += f"👤 <b>ID:</b> {uid}\n"
            response += f"⏰ <b>Until:</b> {until}\n"
            response += f"📝 <b>Reason:</b> {info.get('reason', 'Unknown')}\n"
            response += "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        
        self._send_message(message.chat.id, response)
    
    # ===============================================================
    #                       FILE HANDLER
    # ===============================================================
    
    def handle_file(self, message):
        """Handle uploaded TXT file for mass check."""
        user_id = message.chat.id
        authorized, reason = self._is_authorized(user_id)
        
        if not authorized:
            self._send_message(message.chat.id, "❌ <b>Access denied.</b>")
            return
        
        try:
            # Download file
            file_info = self.bot.get_file(message.document.file_id)
            downloaded = self.bot.download_file(file_info.file_path)
            content = downloaded.decode('utf-8', errors='ignore')
            
            # Extract CCs
            ccs = cc_processor.extract_cc(content)
            
            if not ccs:
                self._send_message(message.chat.id, "❌ No valid CC found in file!")
                return
            
            # Filter expired
            valid_ccs = [cc for cc in ccs if not cc_processor.is_expired(cc)]
            
            if not valid_ccs:
                self._send_message(message.chat.id, "⚠️ All cards are expired!")
                return
            
            logger.info(f"File check: {len(valid_ccs)} cards from {user_id}")
            
            # Send status
            status_msg = self._send_message(
                message.chat.id,
                f"🔄 <b>Processing {len(valid_ccs)} cards...</b>\n"
                f"Progress: 0/{len(valid_ccs)}"
            )
            if not status_msg:
                return
            
            # Get proxy
            proxy = proxy_manager.get_proxy(user_id)
            
            # Process
            hits = []
            processed = 0
            last_update = 0
            
            with self._lock:
                self._active_checks.add(user_id)
            
            try:
                batch_size = config.CHUNK_SIZE
                for i in range(0, len(valid_ccs), batch_size):
                    batch = valid_ccs[i:i+batch_size]
                    batch_results = cc_processor.process_batch(batch, proxy)
                    processed += len(batch_results)
                    
                    for r in batch_results:
                        if r['status'] in ['charged', 'cvv', 'low']:
                            hits.append(r)
                            storage.save_result({
                                'cc': r['cc'],
                                'status': r['status'],
                                'bank': r.get('bank', 'Unknown'),
                                'country': r.get('country', 'Unknown'),
                                'gate': r.get('gate', 'Unknown')
                            })
                    
                    # Update progress
                    current_time = time.time()
                    if processed == len(valid_ccs) or current_time - last_update > 1:
                        self._safe_edit(
                            status_msg,
                            message.chat.id,
                            f"🔄 <b>Processing {len(valid_ccs)} cards...</b>\n"
                            f"Progress: {processed}/{len(valid_ccs)}\n"
                            f"Hits: {len(hits)}"
                        )
                        last_update = current_time
                
            finally:
                with self._lock:
                    self._active_checks.discard(user_id)
            
            # Send results
            if hits:
                response = f"✅ <b>FILE PROCESSING COMPLETE</b>\n"
                response += f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                response += f"<b>Total Cards:</b> {len(valid_ccs)}\n"
                response += f"<b>Hits:</b> {len(hits)}\n"
                response += f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                
                # Show hits (limit to avoid message length)
                for i, hit in enumerate(hits[:15]):
                    response += f"<b>{i+1}.</b> <code>{hit['cc'][:16]}</code> | {hit['status_text']} | {hit['gate']}\n"
                
                if len(hits) > 15:
                    response += f"\n... and {len(hits) - 15} more hits"
                
                self._safe_edit(status_msg, message.chat.id, response)
            else:
                self._safe_edit(
                    status_msg,
                    message.chat.id,
                    f"✅ <b>FILE PROCESSING COMPLETE</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"<b>Total Cards:</b> {len(valid_ccs)}\n"
                    f"<b>Hits:</b> 0"
                )
                
        except Exception as e:
            logger.error(f"File processing error: {e}")
            self._send_message(
                message.chat.id,
                f"❌ <b>Error processing file:</b>\n{str(e)[:100]}"
            )
    
    # ===============================================================
    #                       RUN
    # ===============================================================
    
    def run(self):
        """Start the bot."""
        try:
            config.validate()
        except ValueError as e:
            logger.error(f"Configuration error: {e}")
            print(f"❌ Configuration error: {e}")
            return
        
        print("=" * 50)
        print("🚀 GOOD HQ BOT - PRODUCTION VERSION")
        print("=" * 50)
        print(f"👑 Admin ID: {config.ADMIN_ID}")
        print(f"⚙️ Gates Loaded: {len(cc_processor._gate_modules)}")
        print(f"📁 Results Dir: {config.RESULTS_DIR}")
        print(f"🔒 Security: Private mode (Admin only)")
        print("=" * 50)
        print("✅ Bot is running...")
        print("=" * 50)
        
        try:
            self.bot.delete_webhook()
            self.bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except KeyboardInterrupt:
            logger.info("Bot stopped by user")
            print("\n🛑 Bot stopped")
        except Exception as e:
            logger.error(f"Bot error: {e}")
            print(f"❌ Bot error: {e}")

# ===================================================================
#                           MAIN
# ===================================================================

if __name__ == "__main__":
    bot = GoodBot()
    bot.run()
