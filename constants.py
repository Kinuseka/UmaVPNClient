from urllib.parse import urlencode
ENDPOINT = "https://api.umavpn.top"
URI = "/api/server"
params = {
    "sites": "uma",
    "sites": "dmm",
    "take": 20,
    "orderBy": "timestamp"
}
query_string = urlencode(params, doseq=True)
FULL_URL = f"{ENDPOINT}{URI}"
FULL_URL_QUERY = f"{ENDPOINT}{URI}?{query_string}"
FULL_URL_DOWNLOAD = "{ENDPOINT}{URI}/{IP}/config?variant=current"
GITHUB_ENDPOINT = "https://github.com/Kinuseka/UmaVPNClient"
UPDATE_ENDPOINT = "https://github.com/Kinuseka/UmaVPNClient"