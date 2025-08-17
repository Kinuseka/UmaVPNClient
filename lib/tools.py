# import pip_system_certs.wrapt_requests
from bs4 import BeautifulSoup, ResultSet, Tag, NavigableString
from typing import Union, Iterable, Callable, List
from pythonping import ping
from loguru import logger
import concurrent.futures
import constants as cnts
import requests
import socket
import io
import sys
import os
import psutil
from urllib.parse import urlparse, urlencode
#Bind to logger
log = logger.bind(name="UMVPN-logger")

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def pinger(IP):
    if not IP:
        return False
    response = ping(IP, count=10)
    return response

def handle_ping(IPs):
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(pinger, IP) for IP in IPs]
    results = []
    for num, f in enumerate(futures):
        try:
            results.append(f.result())
        except Exception as e:
            log.exception(f'Issue occured while pinging IP: {IPs[num]}')
            results.append(False)
    return results

def dns_over_https(hostname):
    dns = cnts.DNS[0] #cloudflare
    json = {"name": hostname, "type": "A", "ct": "application/dns-json"}
    headers = {"accept": "application/dns-json"}
    response = requests.get(dns['url'], headers=headers, params=json, timeout=10)
    response.raise_for_status()
    return response.json()

def get_best_connection(data: dict):
    sorted_data = sorted(data, key=lambda x: (-x["speed"], x["duration"]))
    return sorted_data

def find_servers(params:dict):
    try:
        query_string = urlencode(params, doseq=True)
        response = requests.get(cnts.FULL_URL + "?" + query_string)
        response.raise_for_status()
        return True, response.json()
    except Exception as e:
        log.exception(f'Issue occured while fetching servers: {e}')
        return False
    return False, response

def download_connection(IP: str, target: str):
    try:
        FINAL_URL = cnts.FULL_URL_DOWNLOAD.format(ENDPOINT=cnts.ENDPOINT, URI=cnts.URI, IP=IP)
        print(f"Downloading: {FINAL_URL}")
        file_ovpn = requests.get(FINAL_URL)
        with open(target, "wb") as f:
            f.write(file_ovpn.content)
        return True
    except Exception as e:
        log.exception(f'Issue occured while downloading connection: {e}')
        return False
    return True

def find_existing_openvpn():
        """Find existing OpenVPN processes."""
        existing_processes = []
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if proc.info['name'].lower() in ['openvpn.exe', 'openvpn']:
                        existing_processes.append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
        except Exception as e:
            log.exception("Error finding existing OpenVPN processes")
        
        return existing_processes

def get_current_ip():
    try:
        response = requests.get('https://api.ipify.org?format=json')
        response.raise_for_status()
        return response.json()['ip']
    except Exception as e:
        log.exception(f'Issue occured while fetching current IP: {e}')
        return False