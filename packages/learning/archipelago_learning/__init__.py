from .dqn import Learner
from .peer import PeerError, decode, encode, offer, rollback

__all__ = ["Learner", "PeerError", "TorchLearner", "decode", "encode", "offer", "rollback"]


def __getattr__(name):  # torch is imported only when TorchLearner is actually requested
    if name == "TorchLearner":
        from .torch_dqn import TorchLearner

        return TorchLearner
    raise AttributeError(name)
