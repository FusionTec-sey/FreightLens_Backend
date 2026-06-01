import re

with open("Dump20260528 (3).sql", "r", encoding="utf-8") as f:
    content = f.read()

# Find the CREATE TABLE statement for container_details
m = re.search(r"CREATE TABLE\s+`container_details`\s*\((.*?)\)\s*ENGINE", content, re.DOTALL | re.IGNORECASE)
if m:
    print("Table: container_details")
    print(m.group(1).strip())
else:
    print("container_details table not found in dump")

m02 = re.search(r"CREATE TABLE\s+`container_details02`\s*\((.*?)\)\s*ENGINE", content, re.DOTALL | re.IGNORECASE)
if m02:
    print("\nTable: container_details02")
    print(m02.group(1).strip())
