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
from urllib.parse import urlparse
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
        response = requests.get(cnts.FULL_URL, params=params)
        response.raise_for_status()
        return True, response.json()
    except Exception as e:
        log.exception(f'Issue occured while fetching servers: {e}')
        return False
    return False, response

def download_connection(IP: str):
    FINAL_URL = FULL_URL_DOWNLOAD.format(ENDPOINT=ENDPOINT, URI=URI, IP=IP)
    print(f"Downloading: {FINAL_URL}")
    file_ovpn = requests.get(FINAL_URL)
    with open("temp.ovpn", "wb") as f:
        f.write(file_ovpn.content)

