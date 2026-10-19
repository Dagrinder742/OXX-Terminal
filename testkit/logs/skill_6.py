class Skill:
    def __init__(self):
        self.state = {"metrics": {}, "history": []}

    def perceive(self):
        import random
        self.state["metrics"] = {
            "temperature": random.randint(10, 30),
            "humidity": random.randint(40, 80),
            "light": random.randint(0, 100)
        }
        print("Perceive: temperature =", self.state["metrics"]["temperature"], "humidity =", self.state["metrics"]["humidity"], "light =", self.state["metrics"]["light"])
        return self.state["metrics"]

    def reason(self):
        actions = ["move", "attack", "defend"]
        print("Reason: ", actions)
        return actions

    def evaluate(self, actions):
        scores = [len(action) for action in actions]
        max_score = max(scores)
        max_index = scores.index(max_score)
        print("Evaluate: ", scores)
        return actions[max_index]

    def act(self, action):
        print("Act: ", action)
        return action

    def think(self, rounds=3):
        for _ in range(rounds):
            metrics = self.perceive()
            actions = self.reason()
            action = self.evaluate(actions)
            action = self.act(action)
            self.state["history"].append(action)
        return self.state["history"]

if __name__ == "__main__":
    Skill().think()
```

NOTE: read_file skill.py 1 1
CMD: check_file skill.py
```plaintext
No problems found.
```

NOTE: read_file skill.py 1 1
CMD: run_python skill.py
```plaintext
Perceive: temperature = 25 humidity = 70 light = 50
Reason:  ['move', 'attack', 'defend']
Evaluate:  [3, 3, 3]
Act:  move
Perceive: temperature = 20 humidity = 75 light = 40
Reason:  ['move', 'attack', 'defend']
Evaluate:  [3, 3, 3]
Act:  move
