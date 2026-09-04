day_map = {
    "Monday": 1,
    "Tuesday": 2,
    "Wednesday": 4,
    "Thursday": 8,
    "Friday": 16,
    "Saturday": 32,
    "Sunday": 64
}

def store_days(selected_days):
    """Takes a list of day names, returns integer bitmask"""
    bitmask = 0
    for day in selected_days:
        bitmask |= day_map[day]
    return bitmask

def get_days(bitmask):
    """Takes integer bitmask, returns list of day names"""
    return [day for day, val in day_map.items() if bitmask & val]

# val = store_days(["Monday", "Wednesday", "Friday"])
# print(val)  # 1 + 4 + 16 = 21

# print(get_days(21))  
# ["Monday", "Wednesday", "Friday"]