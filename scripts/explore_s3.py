import boto3
from dotenv import load_dotenv
from collections import Counter

load_dotenv()

s3 = boto3.client("s3")
bucket = "graphresponsa-archivio-392900064778"

resp = s3.list_objects_v2(Bucket=bucket, Delimiter="/")
print("Top-level prefixes:")
for p in resp.get("CommonPrefixes", []):
    print(" -", p["Prefix"])
print("Top-level files (no prefix):", [o["Key"] for o in resp.get("Contents", [])])
print()

paginator = s3.get_paginator("list_objects_v2")
prefix_ext_count = Counter()
total = 0
sample = {}
for page in paginator.paginate(Bucket=bucket):
    for obj in page.get("Contents", []):
        key = obj["Key"]
        total += 1
        top = key.split("/")[0] if "/" in key else "(root)"
        ext = key.rsplit(".", 1)[-1] if "." in key else "(none)"
        prefix_ext_count[(top, ext)] += 1
        sample.setdefault((top, ext), key)

print("Totale oggetti:", total)
print("Conteggio per (prefisso, estensione):")
for (top, ext), n in sorted(prefix_ext_count.items()):
    print(f"  {top}/*.{ext}: {n}  esempio: {sample[(top, ext)]}")
