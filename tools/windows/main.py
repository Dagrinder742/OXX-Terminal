import math_helpers

items = [
    {"name": "bolts", "cost": 10, "revenue": 20},
    {"name": "nuts", "cost": 5, "revenue": 10},
    {"name": "screws", "cost": 15, "revenue": 0}
]

for item in items:
    try:
        profit_margin = math_helpers.calculate_profit_margin(item["cost"], item["revenue"])
        print(f"{item['name']}: Profit Margin = {profit_margin:.2f}")
    except ZeroDivisionError as e:
        print(f"{item['name']}: {e}")
