import re

# Read the file with auto-detecting encoding (try utf-8 and utf-16)
for encoding in ["utf-8", "utf-16", "utf-16-le", "latin-1"]:
    try:
        with open("Dump20260528 (3).sql", "r", encoding=encoding) as f:
            content = f.read()
        print(f"Successfully read with {encoding}. Length: {len(content)}")
        break
    except Exception as e:
        continue

# Find all CREATE TABLE blocks
matches = re.finditer(r"CREATE TABLE\s+`([^`]+)`\s*\((.*?)\)\s*ENGINE", content, re.DOTALL | re.IGNORECASE)
for m in matches:
    table_name = m.group(1)
    body = m.group(2).strip()
    # print first couple lines of body
    body_lines = [line.strip() for line in body.split("\n")]
    print(f"\nTable: {table_name}")
    for line in body_lines:
        if "key" in line.lower() or "constraint" in line.lower():
            print(f"  {line}")
