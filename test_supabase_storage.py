import os
from supabase import create_client

url = os.environ.get("SUPABASE_URL", "https://yfgciamhzjvarwgzosto.supabase.co")
key = os.environ.get("SUPABASE_SERVICE_KEY", "")
supabase = create_client(url, key)

bucket = "knowledge-base"
path = "documents/1773762490353_edital_n_292025_-_sisu_2026.md"

try:
    res = supabase.storage.from_(bucket).download(path)
    print("Download successful!")
    print(res[:500])
except Exception as e:
    print("Error:", e)
