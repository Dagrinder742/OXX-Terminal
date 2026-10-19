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
        actions = ["move", "attack", "defend"]
        random.shuffle(actions)
        print("Reason: ", actions)
        return actions

    def evaluate(self, actions):
        scores = [len(action) for action in actions]
        max_score = max(scores)
        max_index = scores.index(max_score)
        selected_action = actions[max_index]
        print("Evaluate: ", scores)
        return selected_action

    def act(self, action):
        print("Act: ", action)
        return action

    def think(self, rounds=3):
        for _ in range(rounds):
            metrics = self.perceive()
            actions = self.reason()
            selected_action = self.evaluate(actions)
            self.act(selected_action)
            self.state["history"].append(selected_action)
        return self.state["history"]

if __name__ == "__main__":
    Skill().think()
