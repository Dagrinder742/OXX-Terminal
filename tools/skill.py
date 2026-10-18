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
        print(f"Perceive: {self.state['metrics']}")
        return self.state["metrics"]

    def reason(self):
        actions = [
            f"adjust_temperature_to_{self.state['metrics'].get('temperature', 20)}",
            f"regulate_humidity_to_{self.state['metrics'].get('humidity', 60)}",
            f"calibrate_lighting_to_{self.state['metrics'].get('light', 50)}",
        ]
        print(f"Reason: {actions}")
        return actions

    def evaluate(self, actions):
        scores = {action: len(action) for action in actions}
        print(f"Evaluate: {scores}")
        best_action = max(actions, key=len)
        return best_action

    def act(self, action):
        print(f"Act: {action}")
        return action

    def think(self, rounds=3):
        for _ in range(rounds):
            self.perceive()
            actions = self.reason()
            chosen_action = self.evaluate(actions)
            self.act(chosen_action)
            self.state["history"].append(chosen_action)
        return self.state["history"]


if __name__ == "__main__":
    Skill().think()
