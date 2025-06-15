import os
import sys
import time
import json
import requests
from datetime import datetime
from mnemonic import Mnemonic
from hdwallet import HDWallet
from hdwallet.symbols import BTC
import itertools

DERIVATION_PATH = "m/44'/0'/0'/0/0"
BALANCE_CHECK_INTERVAL = 1  # seconds between API calls
BALANCE_RETRY_DELAY = 5  # seconds to wait on error
MAX_RETRIES = 3  # maximum number of retries for balance check
FOUND_ADDRESSES_FILE = "found_addresses.txt"
ERROR_LOG_FILE = "errors.log"
COLD_LOG_FILE = "cold_log.jsonl"  # New file for cold logging

def log_error(error_type, details, wallet_info=None):
    """Log errors to file with timestamp and wallet info"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    error_data = {
        "timestamp": timestamp,
        "error_type": error_type,
        "details": details
    }
    
    # Add wallet info if available
    if wallet_info:
        error_data.update(wallet_info)
    
    with open(ERROR_LOG_FILE, "a") as f:
        f.write(json.dumps(error_data) + "\n")
        f.flush()

def check_balance(address, retry_count=0, wallet_info=None):
    """Check address balance with retry logic"""
    if retry_count >= MAX_RETRIES:
        log_error("MAX_RETRIES_EXCEEDED", "Maximum retries exceeded", wallet_info)
        return 0

    try:
        url = f"https://api.blockcypher.com/v1/btc/main/addrs/{address}"
        resp = requests.get(url, timeout=10)
        
        if resp.status_code == 200:
            try:
                data = resp.json()
                return data.get("final_balance", 0)
            except json.JSONDecodeError:
                log_error("JSON_DECODE_ERROR", "Failed to parse response as JSON", wallet_info)
                time.sleep(BALANCE_RETRY_DELAY)
                return check_balance(address, retry_count + 1, wallet_info)
                
        elif resp.status_code == 429:  # Rate limit
            # Try mempool.space API as fallback
            try:
                url = f"https://mempool.space/api/address/{address}"
                resp = requests.get(url, timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    funded = data.get("chain_stats", {}).get("funded_txo_sum", 0)
                    spent = data.get("chain_stats", {}).get("spent_txo_sum", 0)
                    return funded - spent
            except Exception as e:
                log_error("FALLBACK_API_ERROR", f"Error: {str(e)}", wallet_info)
            
            log_error("RATE_LIMIT", f"Status: {resp.status_code}", wallet_info)
            time.sleep(185)  # Wait longer on rate limit
            return check_balance(address, retry_count + 1, wallet_info)
            
        elif resp.status_code == 404:
            return 0
            
        elif resp.status_code >= 500:
            log_error("SERVER_ERROR", f"Status: {resp.status_code}", wallet_info)
            time.sleep(BALANCE_RETRY_DELAY)
            return check_balance(address, retry_count + 1, wallet_info)
            
        else:
            log_error("API_ERROR", f"Status: {resp.status_code}", wallet_info)
            time.sleep(BALANCE_RETRY_DELAY)
            return check_balance(address, retry_count + 1, wallet_info)
            
    except requests.exceptions.Timeout:
        log_error("TIMEOUT", "Request timed out", wallet_info)
        time.sleep(BALANCE_RETRY_DELAY)
        return check_balance(address, retry_count + 1, wallet_info)
        
    except requests.exceptions.ConnectionError:
        log_error("CONNECTION_ERROR", "Failed to connect to API", wallet_info)
        time.sleep(BALANCE_RETRY_DELAY)
        return check_balance(address, retry_count + 1, wallet_info)
        
    except Exception as e:
        log_error("UNKNOWN_ERROR", f"Error: {str(e)}", wallet_info)
        return 0

def save_found_address(address, balance, phrase=None, private_key=None):
    """Save found address with balance to file"""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(FOUND_ADDRESSES_FILE, "a") as f:
            data = {
                "timestamp": timestamp,
                "address": address,
                "balance": balance,
                "phrase": phrase,
                "private_key": private_key
            }
            f.write(json.dumps(data) + "\n")
            f.flush()  # Ensure immediate write
    except Exception as e:
        log_error("SAVE_ERROR", f"Failed to save address {address}: {str(e)}")

def generate_address_from_phrase(phrase):
    """Generate Bitcoin address and private key from mnemonic phrase"""
    try:
        hdwallet = HDWallet(symbol=BTC)
        hdwallet.from_mnemonic(phrase)
        hdwallet.from_path(DERIVATION_PATH)
        return hdwallet.p2pkh_address(), hdwallet.private_key()
    except Exception as e:
        log_error("ADDRESS_GENERATION_ERROR", f"Phrase: {phrase}, Error: {str(e)}")
        return None, None

def get_spinner():
    """Get spinner iterator"""
    return itertools.cycle(['/', '-', '\\', '|'])

def save_cold_log(wallet_info, has_balance):
    """Save optimized wallet info to cold log"""
    try:
        cold_data = {
            "address": wallet_info["address"],
            "phrase": wallet_info["phrase"],
            "private_key": wallet_info["private_key"],
            "has_balance": has_balance
        }
        with open(COLD_LOG_FILE, "a") as f:
            f.write(json.dumps(cold_data) + "\n")
            f.flush()
    except Exception as e:
        log_error("COLD_LOG_ERROR", f"Failed to save cold log: {str(e)}", wallet_info)

def main():
    print(f"Start generation at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Found addresses will be saved to: {FOUND_ADDRESSES_FILE}")
    print(f"Errors will be logged to: {ERROR_LOG_FILE}")
    print(f"Cold logs will be saved to: {COLD_LOG_FILE}")
    
    mnemo = Mnemonic("english")
    wordlist = mnemo.wordlist
    
    total_generated = 0
    found_with_balance = 0
    error_count = 0
    
    spinner = get_spinner()
    
    try:
        while True:
            # Generate random phrase
            phrase = mnemo.generate(strength=128)
            address, private_key = generate_address_from_phrase(phrase)
            
            if address:
                total_generated += 1
                
                # Prepare wallet info for logging
                wallet_info = {
                    "address": address,
                    "phrase": phrase,
                    "private_key": private_key
                }
                
                # Check balance
                balance = check_balance(address, wallet_info=wallet_info)
                has_balance = balance > 0
                
                # Save to cold log
                save_cold_log(wallet_info, has_balance)
                
                if has_balance:
                    found_with_balance += 1
                    print(f"\nFound address with balance!")
                    print(f"Address: {address}")
                    print(f"Balance: {balance}")
                    print(f"Phrase: {phrase}")
                    print(f"Private Key: {private_key}")
                    
                    # Save to file
                    save_found_address(address, balance, phrase, private_key)
                
                # Update progress after each iteration
                sys.stdout.write(f"\r{next(spinner)} Generating addresses... {total_generated} generated, {found_with_balance} with balance, {error_count} errors")
                sys.stdout.flush()
                
                time.sleep(BALANCE_CHECK_INTERVAL)
                
    except KeyboardInterrupt:
        print("\n\nScan interrupted by user")
    except Exception as e:
        log_error("CRITICAL_ERROR", f"Main loop error: {str(e)}")
    finally:
        print(f"\nScan completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Total addresses generated: {total_generated}")
        print(f"Addresses with balance: {found_with_balance}")
        print(f"Results saved to: {FOUND_ADDRESSES_FILE}")
        print(f"Errors logged to: {ERROR_LOG_FILE}")
        print(f"Cold logs saved to: {COLD_LOG_FILE}")

if __name__ == "__main__":
    if not os.path.exists(ERROR_LOG_FILE):
        with open(ERROR_LOG_FILE, "w") as f:
            f.write("")
    if not os.path.exists(FOUND_ADDRESSES_FILE):
        with open(FOUND_ADDRESSES_FILE, "w") as f:
            f.write("")
    if not os.path.exists(COLD_LOG_FILE):
        with open(COLD_LOG_FILE, "w") as f:
            f.write("")
    
    # log_error("TEST", "TEST")
    # balance1 = check_balance("3Edf1tBMxUJUCMtnmAHza42z2ocjPKQGdu") # not empty
    # save_found_address("3Edf1tBMxUJUCMtnmAHza42z2ocjPKQGdu", balance1, "TEST")
    # balance2 = check_balance("1PMycacnJaSqwwJqjawXBErnLsZ7RkXUAs") # empty
    # save_found_address("1PMycacnJaSqwwJqjawXBErnLsZ7RkXUAs", balance2, "TEST")
    
    main()