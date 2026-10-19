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
        actions = ["action1", "action2", "action3"]
        print("Reason: ", actions)
        return actions

    def evaluate(self, actions):
        scores = [len(action) for action in actions]
        max_score = max(scores)
        max_index = scores.index(max_score)
        action_with_max_score = actions[max_index]
        print("Evaluate: ", scores)
        return action_with_max_score

    def act(self, action):
        print("Act: ", action)
        return action

    def think(self, rounds=3):
        for _ in range(rounds):
            metrics = self.perceive()
            actions = self.reason()
            action_to_take = self.evaluate(actions)
            self.act(action_to_take)
            self.state["history"].append(action_to_take)
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
Reason:  ['action1', 'action2', 'action3']
Evaluate:  [6, 6, 6]
Act:  action1
Perceive: temperature = 18 humidity = 60 light = 80
Reason:  ['action1', 'action2', 'action3']
Evaluate:  [6, 6, 6]
Act:  action2
Perceive: temperature = 22 humidity = 50 light = 70
Reason:  ['action1', 'action2', 'action3']
Evaluate:  [6, 6, 6]
Act:  action3
