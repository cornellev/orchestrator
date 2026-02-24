
import random


fruits = [
    "apple",
    "banana",
    "cherry",
    "date",
    "elderberry",
    "fig",
    "grape",
    "honeydew",
    "kiwi",
    "lemon",
    "mango",
    "nectarine",
    "orange",
    "papaya",
    "quince",
    "raspberry",
    "strawberry",
    "tangerine"
]

adjectives = [
    "angry",
    "brave",
    "calm",
    "delightful",
    "eager",
    "fancy",
    "graceful",
    "happy",
    "jolly",
    "kind",
    "lively",
    "mysterious",
    "noble",
    "proud",
    "silly",
    "witty",
    "zealous"
]

def generate_name() -> str:
    return f"{random.choice(adjectives).capitalize()}{random.choice(fruits).capitalize()}"