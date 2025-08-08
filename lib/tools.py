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
from urllib.parse import urlparse
#Bind to logger
log = logger.bind(name="UMVPN-logger")

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

    