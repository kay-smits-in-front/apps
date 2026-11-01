"""LSTM over de laatste N dagen van één aandeel. Eén model voor alle aandelen: per aandeel zijn
er te weinig rijen om iets te leren. Voorspelt kans op daling, niets of stijging."""

import numpy as np
import torch
from torch import nn

CLASSES = 3


class Network(nn.Module):
    def __init__(self, channels: int, hidden: int, dropout: float):
        super().__init__()
        self.lstm = nn.LSTM(channels, hidden, batch_first=True)
        self.drop = nn.Dropout(dropout)
        self.out = nn.Linear(hidden, CLASSES)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        _, (hidden, _) = self.lstm(x)
        return self.out(self.drop(hidden[-1]))


class LstmModel:
    def __init__(self, hidden: int = 32, epochs: int = 8, lr: float = 1e-3, batch: int = 128,
                 dropout: float = 0.2, seed: int = 0):
        self.hidden, self.epochs, self.lr, self.batch, self.dropout, self.seed = hidden, epochs, lr, batch, dropout, seed
        self.network: Network | None = None

    def class_weights(self, labels: np.ndarray) -> torch.Tensor:
        """Zeldzame klassen tellen zwaarder, anders voorspelt het model altijd 'niets'."""
        counts = np.bincount(labels, minlength=CLASSES).clip(min=1)
        return torch.tensor(len(labels) / (CLASSES * counts), dtype=torch.float32)

    def fit(self, features: np.ndarray, labels: np.ndarray) -> None:
        torch.manual_seed(self.seed)
        x = torch.tensor(features, dtype=torch.float32)
        y = torch.tensor(labels, dtype=torch.long)
        self.network = Network(x.shape[2], self.hidden, self.dropout)
        optimiser = torch.optim.Adam(self.network.parameters(), lr=self.lr, weight_decay=1e-4)
        loss_fn = nn.CrossEntropyLoss(weight=self.class_weights(labels))
        self.network.train()
        for _ in range(self.epochs):
            order = torch.randperm(len(x))
            for start in range(0, len(x), self.batch):
                pick = order[start:start + self.batch]
                optimiser.zero_grad()
                loss_fn(self.network(x[pick]), y[pick]).backward()
                optimiser.step()

    def predict_proba(self, features: np.ndarray) -> np.ndarray:
        """Kans per klasse (rijen x 3)."""
        self.network.eval()
        with torch.no_grad():
            logits = self.network(torch.tensor(features, dtype=torch.float32))
        return torch.softmax(logits, dim=1).numpy()

    def save(self, path) -> None:
        settings = {"hidden": self.hidden, "dropout": self.dropout, "channels": self.network.lstm.input_size}
        torch.save({"settings": settings, "state": self.network.state_dict()}, path)

    @classmethod
    def load(cls, path) -> "LstmModel":
        saved = torch.load(path, weights_only=True)
        settings = saved["settings"]
        model = cls(hidden=settings["hidden"], dropout=settings["dropout"])
        model.network = Network(settings["channels"], settings["hidden"], settings["dropout"])
        model.network.load_state_dict(saved["state"])
        return model
