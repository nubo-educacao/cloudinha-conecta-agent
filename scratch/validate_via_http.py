import urllib.request
import json

base_url = "http://localhost:8000"

cards = [
    "439c3bea-5bde-4b90-95d2-7657eeeab436",
    "cdbd3c2d-9800-4d5a-b375-367c44812f46",
    "637143da-aeb3-4a57-91da-794ed343ad77",
    "fb754aed-004b-4289-829c-acc18e101145",
    "2a7aa8e7-fd0b-4aff-958e-90a72b9b180a"
]

for cid in cards:
    url = f"{base_url}/cards/{cid}"
    data = json.dumps({"bdd_validated": True}).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="PATCH", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            print(f"Card {cid} updated: bdd_validated={res.get('bdd_validated')}")
    except Exception as e:
        print(f"Error updating card {cid}: {e}")
