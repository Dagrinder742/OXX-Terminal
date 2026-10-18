import random


class Skill:
    def __init__(self):
        self.state = {"metrics": {}, "history": []}

    def perceive(self):
        self.state["metrics"] = {
            "temperature": random.randint(10, 30),
            "humidity": random.randint(40, 80),
            "light": random.randint(0, 100),
        }
        print("Perceive:", self.state["metrics"])
        return self.state["metrics"]

    def reason(self):
        metrics = self.state["metrics"]
        t = metrics.get("temperature", 20)
        h = metrics.get("humidity", 50)
        l = metrics.get("light", 50)
        actions = [
            f"adjust_temperature_to_{t}",
            f"regulate_humidity_to_{h}",
            f"set_lighting_level_{l}",
        ]
        print("Reason:", actions)
        return actions

    def evaluate(self, actions):
        scores = {action: len(action) for action in actions}
        print("Evaluate:", scores)
        best_action = max(actions, key=len)
        return best_action

    def act(self, action):
        print("Act:", action)
        return action

    def think(self, rounds=3):
        for _ in range(rounds):
            self.perceive()
            actions = self.reason()
            best_action = self.evaluate(actions)
            chosen = self.act(best_action)
            self.state["history"].append(chosen)
        return self.state["history"]


if __name__ == "__main__":
    Skill().think()
