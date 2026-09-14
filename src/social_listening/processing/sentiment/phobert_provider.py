"""PhoBERT Vietnamese sentiment provider (Source B)."""

from __future__ import annotations

import os
from typing import Any

from social_listening.processing.sentiment.provider import (
    DEFAULT_PHOBERT_MODEL,
    SENTIMENT_LABELS,
    SENTIMENT_PROVIDER_PHOBERT,
    SentimentPrediction,
    one_hot_prediction,
)
from social_listening.processing.sentiment.text_prep import prepare_sentiment_text

_LABEL_ALIASES = {
    "neg": "negative",
    "negative": "negative",
    "pos": "positive",
    "positive": "positive",
    "neu": "neutral",
    "neutral": "neutral",
}


def normalize_model_label(raw: str) -> str:
    key = str(raw or "").strip().lower()
    if key not in _LABEL_ALIASES:
        raise ValueError(
            f"unexpected PhoBERT label {raw!r}; "
            f"expected one of {sorted(_LABEL_ALIASES)}"
        )
    return _LABEL_ALIASES[key]


def build_label_index_map(id2label: dict[Any, Any]) -> dict[str, int]:
    """
    Map canonical labels → class index using ``model.config.id2label``.

    Fails loudly if NEG/POS/NEU (or long forms) are incomplete/ambiguous.
    """
    if not id2label:
        raise ValueError("model.config.id2label is empty")

    label_to_idx: dict[str, int] = {}
    for raw_id, raw_label in id2label.items():
        idx = int(raw_id)
        canon = normalize_model_label(str(raw_label))
        if canon in label_to_idx and label_to_idx[canon] != idx:
            raise ValueError(
                f"duplicate id2label mapping for {canon}: "
                f"{label_to_idx[canon]} and {idx} in {id2label}"
            )
        label_to_idx[canon] = idx

    missing = SENTIMENT_LABELS - set(label_to_idx)
    if missing:
        raise ValueError(
            f"model.id2label missing required labels {sorted(missing)}; got {id2label}"
        )
    if len(label_to_idx) != 3:
        raise ValueError(
            f"expected exactly 3 sentiment classes, got {label_to_idx} from {id2label}"
        )
    return label_to_idx


class PhoBERTSentimentProvider:
    """Load ``wonrax/phobert-base-vietnamese-sentiment`` once per process."""

    name = SENTIMENT_PROVIDER_PHOBERT

    def __init__(
        self,
        model_name: str | None = None,
        *,
        batch_size: int | None = None,
        max_length: int | None = None,
    ) -> None:
        self.model_name = (
            model_name
            or os.getenv("SENTIMENT_PHOBERT_MODEL")
            or DEFAULT_PHOBERT_MODEL
        ).strip()
        self.batch_size = int(
            batch_size
            or os.getenv("SENTIMENT_BATCH_SIZE")
            or 32
        )
        self.max_length = int(
            max_length
            or os.getenv("SENTIMENT_MAX_LENGTH")
            or 256
        )
        self._tokenizer = None
        self._model = None
        self._device = None
        self._label_to_idx: dict[str, int] | None = None
        self._load()

    def _load(self) -> None:
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:  # pragma: no cover - env dependent
            raise RuntimeError(
                "PhoBERT requires torch and transformers. "
                "Install with: pip install torch transformers"
            ) from exc

        tokenizer = AutoTokenizer.from_pretrained(self.model_name, use_fast=False)
        model = AutoModelForSequenceClassification.from_pretrained(self.model_name)
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        model.to(device)
        model.eval()

        label_to_idx = build_label_index_map(dict(model.config.id2label or {}))

        self._tokenizer = tokenizer
        self._model = model
        self._device = device
        self._label_to_idx = label_to_idx
        self._torch = torch

    @property
    def id2label(self) -> dict[int, str]:
        assert self._model is not None
        return {int(k): str(v) for k, v in dict(self._model.config.id2label).items()}

    @property
    def label_to_idx(self) -> dict[str, int]:
        assert self._label_to_idx is not None
        return self._label_to_idx

    def predict(self, text: str) -> SentimentPrediction:
        return self.predict_batch([text])[0]

    def predict_batch(self, texts: list[str]) -> list[SentimentPrediction]:
        if not texts:
            return []
        assert self._tokenizer is not None
        assert self._model is not None
        assert self._device is not None
        assert self._label_to_idx is not None

        prepared = [prepare_sentiment_text(t) for t in texts]
        results: list[SentimentPrediction] = [
            one_hot_prediction("neutral", self.name) for _ in prepared
        ]

        nonempty_idx = [i for i, t in enumerate(prepared) if t]
        if not nonempty_idx:
            return list(results)

        torch = self._torch
        out_preds: list[SentimentPrediction] = []
        for start in range(0, len(nonempty_idx), self.batch_size):
            chunk_idx = nonempty_idx[start : start + self.batch_size]
            chunk_texts = [prepared[i] for i in chunk_idx]
            inputs = self._tokenizer(
                chunk_texts,
                return_tensors="pt",
                truncation=True,
                padding=True,
                max_length=self.max_length,
            )
            inputs = {k: v.to(self._device) for k, v in inputs.items()}
            with torch.no_grad():
                logits = self._model(**inputs).logits
                probs = torch.softmax(logits, dim=-1).cpu().numpy()
                pred_ids = logits.argmax(dim=-1).cpu().numpy()

            for row, pred_id in zip(probs, pred_ids):
                out_preds.append(self._prediction_from_probs(row, int(pred_id)))

        # out_preds aligns with nonempty_idx order across chunks
        for i, pred in zip(nonempty_idx, out_preds):
            results[i] = pred
        return results

    def _prediction_from_probs(self, probs, pred_id: int) -> SentimentPrediction:
        assert self._label_to_idx is not None
        neg_i = self._label_to_idx["negative"]
        neu_i = self._label_to_idx["neutral"]
        pos_i = self._label_to_idx["positive"]
        negative_score = float(probs[neg_i])
        neutral_score = float(probs[neu_i])
        positive_score = float(probs[pos_i])
        raw_label = self.id2label.get(pred_id)
        if raw_label is None:
            raise ValueError(f"pred_id {pred_id} missing from id2label={self.id2label}")
        label = normalize_model_label(raw_label)
        confidence = max(negative_score, neutral_score, positive_score)
        return SentimentPrediction(
            label=label,
            provider=self.name,
            negative_score=negative_score,
            neutral_score=neutral_score,
            positive_score=positive_score,
            sentiment_confidence=confidence,
        )
