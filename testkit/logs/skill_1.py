import random
<<<<<<< Updated upstream
<<<<<<< Updated upstream


=======
>>>>>>> Stashed changes
=======
>>>>>>> Stashed changes
class Skill:
    def __init__(self):
        self.state = {"metrics": {}, "history": []}

    def perceive(self):
        self.state["metrics"] = {
            "temperature": random.randint(10, 30),
            "humidity": random.randint(40, 80),
<<<<<<< Updated upstream
<<<<<<< Updated upstream
            "light": random.randint(0, 100),
        }
        print("Perceive:", self.state["metrics"])
=======
            "light": random.randint(0, 100)
        }
        print("Perceive: ", self.state["metrics"])
>>>>>>> Stashed changes
=======
            "light": random.randint(0, 100)
        }
        print("Perceive: ", self.state["metrics"])
>>>>>>> Stashed changes
        return self.state["metrics"]

    def reason(self):
        temp = self.state["metrics"].get("temperature", 20)
        hum = self.state["metrics"].get("humidity", 60)
        light = self.state["metrics"].get("light", 50)
        actions = [
            f"set_temperature_{temp}C",
            f"regulate_humidity_{hum}pct",
            f"adjust_illumination_{light}lux",
        ]
        print("Reason:", actions)
        return actions

    def evaluate(self, actions):
        scores = {action: len(action) for action in actions}
<<<<<<< Updated upstream
<<<<<<< Updated upstream
        print("Evaluate:", scores)
        best_action = max(actions, key=len)
        return best_action
=======
=======
>>>>>>> Stashed changes
        max_score = max(scores.values())
        action_with_max_score = [action for action, score in scores.items() if score == max_score][0]
        print("Evaluate: ", scores)
        return action_with_max_score
<<<<<<< Updated upstream
>>>>>>> Stashed changes
=======
>>>>>>> Stashed changes

    def act(self, action):
        print("Act:", action)
        return action

    def think(self, rounds=3):
        for _ in range(rounds):
            self.perceive()
            actions = self.reason()
<<<<<<< Updated upstream
<<<<<<< Updated upstream
            best = self.evaluate(actions)
            chosen = self.act(best)
            self.state["history"].append(chosen)
=======
            action = self.evaluate(actions)
            action = self.act(action)
            self.state["history"].append(action)
>>>>>>> Stashed changes
=======
            action = self.evaluate(actions)
            action = self.act(action)
            self.state["history"].append(action)
>>>>>>> Stashed changes
        return self.state["history"]


if __name__ == "__main__":
    Skill().think()
