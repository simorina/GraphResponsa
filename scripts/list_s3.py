import boto3
from dotenv import load_dotenv

load_dotenv()

s3 = boto3.client("s3")  # legge credenziali/regione dalle env var (AWS_*)

print("Buckets:")
for bucket in s3.list_buckets()["Buckets"]:
    print(" -", bucket["Name"])

    resp = s3.list_objects_v2(Bucket=bucket["Name"])
    for obj in resp.get("Contents", []):
        print("     ", obj["Key"])
