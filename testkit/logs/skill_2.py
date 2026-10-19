import random

class Skill:
    def __init__(self):
        self.state = {"metrics": {}, "history": []}

    def perceive(self):
        temperature = random.randint(10, 30)
        humidity = random.randint(40, 80)
        light = random.randint(0, 100)
        self.state["metrics"] = {"temperature": temperature, "humidity": humidity, "light": light}
        print("Perceive: temperature =", temperature, "humidity =", humidity, "light =", light)
        return self.state["metrics"]

    def reason(self):
        actions = ["run", "jump", "swim"]
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
            action = self.evaluate(actions)
            action = self.act(action)
            self.state["history"].append(action)
        return self.state["history"]

if __name__ == "__main__":
    Skill().think()
