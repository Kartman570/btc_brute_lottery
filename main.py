import os
import sys
import time
import json
import requests
from datetime import datetime
from mnemonic import Mnemonic
from hdwallet import HDWallet
from hdwallet.symbols import BTC

DERIVATION_PATH = "m/44'/0'/0'/0/0"
BALANCE_CHECK_INTERVAL = 1  # seconds between API calls
BALANCE_RETRY_DELAY = 5  # seconds to wait on error
MAX_RETRIES = 3  # maximum number of retries for balance check
FOUND_ADDRESSES_FILE = "found_addresses.txt"
ERROR_LOG_FILE = "errors.log"

def log_error(error_type, details):
    """Log errors to file with timestamp"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(ERROR_LOG_FILE, "a") as f:
        f.write(f"{timestamp} | {error_type} | {details}\n")
    # Increment error counter
    if hasattr(log_error, 'error_count'):
        log_error.error_count += 1
    else:
        log_error.error_count = 1

def check_balance(address, retry_count=0):
    """Check address balance with retry logic"""
    if retry_count >= MAX_RETRIES:
        log_error("MAX_RETRIES_EXCEEDED", f"Address: {address}")
        return 0

    try:
        url = f"https://api.blockcypher.com/v1/btc/main/addrs/{address}"
        resp = requests.get(url, timeout=10)
        
        if resp.status_code == 200:
            try:
                data = resp.json()
                return data.get("final_balance", 0)
            except json.JSONDecodeError:
                log_error("JSON_DECODE_ERROR", f"Address: {address}")
                time.sleep(BALANCE_RETRY_DELAY)
                return check_balance(address, retry_count + 1)
                
        elif resp.status_code == 429:  # Rate limit
            # log_error("RATE_LIMIT! SWITCH TO ANOTHER API", f"Address: {address}, Status: {resp.status_code}")
            # Try mempool.space API as fallback
            try:
                fallback_url = f"https://mempool.space/api/address/{address}"
                fallback_resp = requests.get(fallback_url, timeout=10)
                if fallback_resp.status_code == 200:
                    data = fallback_resp.json()
                    # Calculate balance: funded - spent
                    funded = data["chain_stats"]["funded_txo_sum"]
                    spent = data["chain_stats"]["spent_txo_sum"]
                    balance = funded - spent
                    return balance
                else:
                    log_error("FALLBACK_API_ERROR", f"Address: {address}, Status: {fallback_resp.status_code}")
            except Exception as e:
                log_error("FALLBACK_API_ERROR", f"Address: {address}, Error: {str(e)}")
            
            log_error("RATE_LIMIT", f"Address: {address}, Status: {resp.status_code}")
            time.sleep(185)  # Wait longer on rate limit
            return check_balance(address, retry_count + 1)
            
        elif resp.status_code == 404:
            return 0
            
        elif resp.status_code >= 500:
            log_error("SERVER_ERROR", f"Address: {address}, Status: {resp.status_code}")
            time.sleep(BALANCE_RETRY_DELAY)
            return check_balance(address, retry_count + 1)
            
        else:
            log_error("API_ERROR", f"Address: {address}, Status: {resp.status_code}")
            time.sleep(BALANCE_RETRY_DELAY)
            return check_balance(address, retry_count + 1)
            
    except requests.exceptions.Timeout:
        log_error("TIMEOUT", f"Address: {address}")
        time.sleep(BALANCE_RETRY_DELAY)
        return check_balance(address, retry_count + 1)
        
    except requests.exceptions.ConnectionError:
        log_error("CONNECTION_ERROR", f"Address: {address}")
        time.sleep(BALANCE_RETRY_DELAY)
        return check_balance(address, retry_count + 1)
        
    except Exception as e:
        log_error("UNKNOWN_ERROR", f"Address: {address}, Error: {str(e)}")
        return 0

def save_found_address(address, balance, phrase=None):
    """Save found address with balance to file"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(FOUND_ADDRESSES_FILE, "a") as f:
            data = {
                "timestamp": timestamp,
                "address": address,
                "balance": balance,
                "phrase": phrase
            }
            f.write(json.dumps(data) + "\n")
            f.flush()  # Ensure immediate write
    except Exception as e:
        log_error("SAVE_ERROR", f"Failed to save address {address}: {str(e)}")

def generate_address_from_phrase(phrase):
    """Generate Bitcoin address from mnemonic phrase"""
    try:
        hdwallet = HDWallet(symbol=BTC)
        hdwallet.from_mnemonic(phrase)
        hdwallet.from_path(DERIVATION_PATH)
        return hdwallet.p2pkh_address()
    except Exception as e:
        log_error("ADDRESS_GENERATION_ERROR", f"Phrase: {phrase}, Error: {str(e)}")
        return None

def get_spinner():
    """Return next spinner character"""
    spinner = ['/', '-', '\\', '|']
    while True:
        for char in spinner:
            yield char

def main():
    print(f"Start generation at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Found addresses will be saved to: {FOUND_ADDRESSES_FILE}")
    print(f"Errors will be logged to: {ERROR_LOG_FILE}")
    
    mnemo = Mnemonic("english")
    wordlist = mnemo.wordlist
    spinner = get_spinner()
    
    total_generated = 0
    found_with_balance = 0
    error_count = 0
    
    try:
        while True:
            # Generate random phrase
            phrase = mnemo.generate(strength=128)
            address = generate_address_from_phrase(phrase)
            sys.stdout.write(f"\r{next(spinner)} Generating addresses... {total_generated} generated, {found_with_balance} with balance")
            sys.stdout.flush()
            
            if address:
                total_generated += 1
                
                # Check balance
                balance = check_balance(address)
                
                if balance > 0:
                    found_with_balance += 1
                    print(f"\n\nFound address with balance!")
                    print(f"Address: {address}")
                    print(f"Balance: {balance}")
                    print(f"Phrase: {phrase}")
                    
                    # Save to file
                    save_found_address(address, balance, phrase)
                
                time.sleep(BALANCE_CHECK_INTERVAL)
                
    except KeyboardInterrupt:
        print("\n\nScan interrupted by user")
    except Exception as e:
        log_error("CRITICAL_ERROR", f"Main loop error: {str(e)}")
        error_count += 1
    finally:
        print(f"\nScan completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Total addresses generated: {total_generated}")
        print(f"Addresses with balance: {found_with_balance}")
        print(f"Total errors: {error_count}")
        print(f"Results saved to: {FOUND_ADDRESSES_FILE}")
        print(f"Errors logged to: {ERROR_LOG_FILE}")

if __name__ == "__main__":
    if not os.path.exists(ERROR_LOG_FILE):
        with open(ERROR_LOG_FILE, "w") as f:
            f.write("")
    if not os.path.exists(FOUND_ADDRESSES_FILE):
        with open(FOUND_ADDRESSES_FILE, "w") as f:
            f.write("")
    
    # log_error("TEST", "TEST")
    # balance1 = check_balance("3Edf1tBMxUJUCMtnmAHza42z2ocjPKQGdu") # not empty
    # save_found_address("3Edf1tBMxUJUCMtnmAHza42z2ocjPKQGdu", balance1, "TEST")
    # balance2 = check_balance("1PMycacnJaSqwwJqjawXBErnLsZ7RkXUAs") # empty
    # save_found_address("1PMycacnJaSqwwJqjawXBErnLsZ7RkXUAs", balance2, "TEST")
    
    main()