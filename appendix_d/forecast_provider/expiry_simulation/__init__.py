"""Phase 3T-B: Shadow用FEFO Simulation。"""

from .domain import ExpiryPolicy, ExpirySimulation, build_expiry_policy, simulate_expiry
from .service import ExpirySimulationBatch, ExpirySimulationBlocked, ExpirySimulationService

__all__ = [
    "ExpiryPolicy", "ExpirySimulation", "ExpirySimulationBatch",
    "ExpirySimulationBlocked", "ExpirySimulationService",
    "build_expiry_policy", "simulate_expiry",
]
