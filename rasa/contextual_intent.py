"""Rasa NLU component for short replies that depend on the last caller prompt."""

import csv
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Dict, List

import joblib
from rasa.engine.graph import ExecutionContext, GraphComponent
from rasa.engine.recipes.default_recipe import DefaultV1Recipe
from rasa.engine.storage.resource import Resource
from rasa.engine.storage.storage import ModelStorage
from rasa.shared.nlu.constants import INTENT, INTENT_RANKING_KEY, TEXT
from rasa.shared.nlu.training_data.message import Message
from rasa.shared.nlu.training_data.training_data import TrainingData
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, make_pipeline


PREFIX = "scam-arena-context-v1 "
MIN_CONFIDENCE = 0.55
MIN_MARGIN = 0.15
INTENTS_BY_ACT = {
    "verify": {"yes": "verify"},
    "comply": {"yes": "comply", "no": "refuse"},
    "sensitive": {"no": "refuse"},
}


def normalize(text):
    text = unicodedata.normalize("NFKD", text.casefold().replace("đ", "d"))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return " ".join(re.findall(r"[a-z0-9]+", text))


@DefaultV1Recipe.register([DefaultV1Recipe.ComponentType.INTENT_CLASSIFIER], is_trainable=True)
class ContextualIntentClassifier(GraphComponent):
    def __init__(self, config, model_storage, resource, model=None):
        self._examples_path = Path(config["examples_path"])
        self._storage = model_storage
        self._resource = resource
        self._model = model

    @classmethod
    def create(cls, config: Dict[str, Any], model_storage: ModelStorage, resource: Resource,
               execution_context: ExecutionContext) -> GraphComponent:
        return cls(config, model_storage, resource)

    @classmethod
    def load(cls, config: Dict[str, Any], model_storage: ModelStorage, resource: Resource,
             execution_context: ExecutionContext, **kwargs) -> GraphComponent:
        with model_storage.read_from(resource) as directory:
            return cls(config, model_storage, resource, joblib.load(directory / "caller_acts.joblib"))

    def train(self, training_data: TrainingData) -> Resource:
        with self._examples_path.open(encoding="utf-8", newline="") as source:
            examples = list(csv.DictReader(source, delimiter="\t"))
        self._model = make_pipeline(
            FeatureUnion([
                ("words", TfidfVectorizer(ngram_range=(1, 2))),
                ("characters", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5))),
            ]),
            LogisticRegression(C=20, class_weight="balanced", max_iter=500),
        )
        self._model.fit([normalize(row["caller"]) for row in examples], [row["act"] for row in examples])
        with self._storage.write_to(self._resource) as directory:
            joblib.dump(self._model, directory / "caller_acts.joblib")
        return self._resource

    def classify(self, caller_line, polarity):
        clauses = re.split(r"[.!?;\n]+", caller_line)
        prompt = next((part.strip() for part in reversed(clauses) if part.strip()), "")
        scores = self._model.predict_proba([normalize(prompt)])[0]
        first, second = scores.argsort()[-2:][::-1]
        confidence = float(scores[first])
        if confidence < MIN_CONFIDENCE or confidence - scores[second] < MIN_MARGIN:
            return "unknown", confidence
        act = self._model.classes_[first]
        return INTENTS_BY_ACT.get(act, {}).get(polarity, "unknown"), confidence

    def process(self, messages: List[Message]) -> List[Message]:
        for message in messages:
            text = message.get(TEXT) or ""
            if not text.startswith(PREFIX):
                continue
            try:
                context = json.loads(text[len(PREFIX):])
                caller_line = context["caller_line"]
                polarity = context["polarity"]
                if not isinstance(caller_line, str) or polarity not in ("yes", "no"):
                    raise ValueError("Invalid contextual input")
                label, confidence = self.classify(caller_line, polarity)
            except (ValueError, TypeError, KeyError):
                label, confidence = "unknown", 0.0
            intent = {"name": label, "confidence": confidence, "contextual": True}
            message.set(INTENT, intent, add_to_output=True)
            message.set(INTENT_RANKING_KEY, [intent], add_to_output=True)
        return messages
