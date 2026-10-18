import random


class Skill:
    def __init__(self):
        self.state = {
            "cycle": 0,
            "environment": {},
            "candidates": [],
            "scored_candidates": [],
            "selected_action": None,
            "action_history": [],
        }

    def perceive(self):
        # Populate mock environmental metrics
        self.state["environment"] = {
            "temperature": round(random.uniform(15.0, 35.0), 2),
            "humidity": round(random.uniform(30.0, 85.0), 2),
            "power_level": round(random.uniform(10.0, 100.0), 2),
            "obstacle_distance": round(random.uniform(0.5, 10.0), 2),
        }
        print(f"[perceive] Updated environmental metrics: {self.state['environment']}")
        return self.state["environment"]

    def reason(self):
        # Generate 3 action choices based on environmental metrics
        temp = self.state["environment"].get("temperature", 20.0)
        power = self.state["environment"].get("power_level", 50.0)
        dist = self.state["environment"].get("obstacle_distance", 5.0)

        choices = [
            {
                "name": "navigate_forward",
                "base_utility": dist * 2.0,
                "cost": 15.0,
            },
            {
                "name": "activate_cooling",
                "base_utility": (temp - 20.0) * 3.0,
                "cost": 10.0,
            },
            {
                "name": "conserve_power",
                "base_utility": (100.0 - power) * 1.5,
                "cost": 2.0,
            },
        ]
        self.state["candidates"] = choices
        print(f"[reason] Generated 3 action choices: {[c['name'] for c in choices]}")
        return choices

    def evaluate(self):
        # Score candidates using a math metric (utility - cost + noise/factor) and pick the highest
        scored = []
        for choice in self.state["candidates"]:
            score = round(choice["base_utility"] - (choice["cost"] * 0.5) + random.uniform(0.0, 5.0), 2)
            scored.append((choice["name"], score))

        scored.sort(key=lambda item: item[1], reverse=True)
        self.state["scored_candidates"] = scored
        best_action, best_score = scored[0]
        self.state["selected_action"] = best_action
        print(f"[evaluate] Scored actions: {scored} -> Highest: {best_action} ({best_score})")
        return best_action

    def act(self):
        # Print chosen action and record it
        action = self.state["selected_action"]
        self.state["action_history"].append(action)
        print(f"[act] Executing chosen action: {action}")
        return action

    def think(self, iterations=3):
        # Call perceive, reason, evaluate, act sequentially in a loop with print statements
        print(f"=== Starting Think Loop ({iterations} cycles) ===")
        for i in range(1, iterations + 1):
            self.state["cycle"] = i
            print(f"\n--- Cycle {i} ---")
            self.perceive()
            self.reason()
            self.evaluate()
            self.act()
        print(f"\n=== Completed Think Loop. History: {self.state['action_history']} ===")


if __name__ == "__main__":
    skill = Skill()
    skill.think(iterations=3)
