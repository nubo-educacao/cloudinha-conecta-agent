import os
from supabase import create_client, Client

url = os.environ.get("SUPABASE_URL", "https://acwqgvoelgsbaixjbwqp.supabase.co")
key = os.environ.get("SUPABASE_SERVICE_KEY", "")
supabase: Client = create_client(url, key)

sprint_id = "844f30c0-01ad-44a5-b9e7-82c8a20de31b"
resp = supabase.table("cards").update({"bdd_validated": True}).eq("sprint_id", sprint_id).execute()
print(f"Updated cards: {len(resp.data)}")
for card in resp.data:
    print(f"- {card['title']}: status={card['status']}, bdd_validated={card['bdd_validated']}")
