import json
import logging
import math
import os
import random
import time
from pathlib import Path

from .base import Plugin


logger = logging.getLogger("loki.plugins.ai_brain")


class A2CBrainPlugin(Plugin):
    """Lightweight on-device actor-critic brain.

    This plugin uses a tiny linear A2C model with hand-crafted observations so it
    can run without external ML dependencies.
    """

    ACTIONS = ["scan", "channel_hop", "focus_ap", "idle", "cooldown"]
    FEATURES = 8

    def __init__(self, config=None):
        super().__init__(config or {})

        cfg = self.config if isinstance(self.config, dict) else {}
        self.enabled = bool(cfg.get("enabled", True))
        self.learning = bool(cfg.get("learning", False))
        self.debug = bool(cfg.get("debug", False))
        self.deterministic = bool(cfg.get("deterministic", False))
        self.model_name = str(cfg.get("model", "local-a2c"))
        self.gamma = float(cfg.get("gamma", 0.95))
        self.actor_lr = float(cfg.get("actor_lr", 0.05))
        self.critic_lr = float(cfg.get("critic_lr", 0.10))
        self.temperature = max(0.05, float(cfg.get("temperature", 1.0)))
        self.decision_interval = max(0.0, float(cfg.get("decision_interval", 3.0)))

        default_state_path = "~/.local/share/loki/a2c_state.json"
        self.state_path = Path(os.path.expanduser(str(cfg.get("state_path", default_state_path))))
        self.max_steps_between_saves = max(1, int(cfg.get("save_every_steps", 25)))

        self._actor_weights = [
            [0.0 for _ in range(self.FEATURES)] for _ in range(len(self.ACTIONS))
        ]
        self._critic_weights = [0.0 for _ in range(self.FEATURES)]

        self._started = False
        self._last_decision_ts = 0.0
        self._steps_since_save = 0
        self._total_steps = 0

        self._last_obs = None
        self._last_action = None
        self._last_probs = None
        self._last_value = None
        self._last_metrics = None

        self._prev_action_name = "idle"
        self.state = {
            "enabled": self.enabled,
            "learning": self.learning,
            "model": self.model_name,
            "current_action": "idle",
            "action_probs": {action: 1.0 / len(self.ACTIONS) for action in self.ACTIONS},
            "last_reward": 0.0,
            "last_value": 0.0,
            "steps": 0,
        }

    def on_start(self, loki):
        if not self.enabled:
            logger.info("[AI Brain] disabled in config")
            return

        self._load_state()
        self._started = True
        logger.info(
            "[AI Brain] started (learning=%s, model=%s, decision_interval=%.2fs)",
            self.learning,
            self.model_name,
            self.decision_interval,
        )

    def on_tick(self, shared_state):
        if not self.enabled or not self._started:
            return

        now = time.time()
        if now - self._last_decision_ts < self.decision_interval:
            return
        self._last_decision_ts = now

        obs, metrics = self._build_observation(shared_state)
        probs, value = self._policy_and_value(obs)
        action_idx = self._select_action(probs)
        action_name = self.ACTIONS[action_idx]

        reward = 0.0
        if self._last_obs is not None and self._last_metrics is not None:
            reward = self._compute_reward(self._last_metrics, metrics, action_name)
            if self.learning:
                self._update_a2c(
                    prev_obs=self._last_obs,
                    prev_action=self._last_action,
                    prev_probs=self._last_probs,
                    prev_value=self._last_value,
                    reward=reward,
                    next_value=value,
                )
                self._steps_since_save += 1
                if self._steps_since_save >= self.max_steps_between_saves:
                    self._save_state()

        self._last_obs = obs
        self._last_action = action_idx
        self._last_probs = probs
        self._last_value = value
        self._last_metrics = metrics
        self._prev_action_name = action_name
        self._total_steps += 1

        self.state = {
            "enabled": self.enabled,
            "learning": self.learning,
            "model": self.model_name,
            "current_action": action_name,
            "action_probs": {
                self.ACTIONS[i]: round(probs[i], 4) for i in range(len(self.ACTIONS))
            },
            "last_reward": round(reward, 4),
            "last_value": round(value, 4),
            "steps": self._total_steps,
            "observation": {
                "ap_count": metrics["ap_count"],
                "client_count": metrics["client_count"],
                "error_count": metrics["error_count"],
            },
        }

        if self.debug:
            logger.info(
                "[AI Brain] action=%s reward=%.3f value=%.3f probs=%s",
                action_name,
                reward,
                value,
                self.state["action_probs"],
            )

    def on_stop(self):
        if not self.enabled:
            return
        self._save_state()
        self._started = False
        logger.info("[AI Brain] stopped")

    def _build_observation(self, shared_state):
        bettercap_state = {}
        if isinstance(shared_state, dict):
            maybe_bettercap = shared_state.get("bettercap")
            if isinstance(maybe_bettercap, dict):
                bettercap_state = maybe_bettercap

        ap_count = int(bettercap_state.get("ap_count", 0) or 0)
        client_count = int(bettercap_state.get("client_count", 0) or 0)
        error_count = int(bettercap_state.get("error_count", 0) or 0)
        http_status = int(bettercap_state.get("last_http_status", 0) or 0)

        prev_ap = int(self._last_metrics["ap_count"]) if self._last_metrics else ap_count
        prev_clients = (
            int(self._last_metrics["client_count"]) if self._last_metrics else client_count
        )

        delta_ap = ap_count - prev_ap
        delta_clients = client_count - prev_clients

        is_error_status = 1.0 if http_status >= 400 else 0.0
        repeated_action = 1.0 if self._prev_action_name in ("idle", "cooldown") else 0.0

        obs = [
            1.0,
            min(ap_count / 40.0, 1.0),
            min(client_count / 100.0, 1.0),
            max(-1.0, min(delta_ap / 5.0, 1.0)),
            max(-1.0, min(delta_clients / 8.0, 1.0)),
            min(error_count / 10.0, 1.0),
            is_error_status,
            repeated_action,
        ]

        metrics = {
            "ap_count": ap_count,
            "client_count": client_count,
            "error_count": error_count,
            "delta_ap": delta_ap,
            "delta_clients": delta_clients,
            "http_status": http_status,
        }
        return obs, metrics

    def _compute_reward(self, previous_metrics, current_metrics, action_name):
        reward = 0.0
        reward += 1.2 * max(0, current_metrics["ap_count"] - previous_metrics["ap_count"])
        reward += 0.6 * max(
            0, current_metrics["client_count"] - previous_metrics["client_count"]
        )
        reward -= 0.25 * max(
            0, current_metrics["error_count"] - previous_metrics["error_count"]
        )

        if action_name in ("idle", "cooldown"):
            reward -= 0.05
        if action_name == self._prev_action_name:
            reward -= 0.03
        if current_metrics["http_status"] >= 400:
            reward -= 0.08
        return reward

    def _policy_and_value(self, obs):
        logits = []
        for action_idx in range(len(self.ACTIONS)):
            logit = 0.0
            weights = self._actor_weights[action_idx]
            for i in range(self.FEATURES):
                logit += weights[i] * obs[i]
            logits.append(logit / self.temperature)

        max_logit = max(logits) if logits else 0.0
        exp_logits = [math.exp(logit - max_logit) for logit in logits]
        denom = sum(exp_logits) or 1.0
        probs = [value / denom for value in exp_logits]

        value = 0.0
        for i in range(self.FEATURES):
            value += self._critic_weights[i] * obs[i]

        return probs, value

    def _select_action(self, probs):
        if not self.learning and self.deterministic:
            best_idx = max(range(len(probs)), key=lambda idx: probs[idx])
            return int(best_idx)
        choice = random.random()
        cumulative = 0.0
        for idx, prob in enumerate(probs):
            cumulative += prob
            if choice <= cumulative:
                return idx
        return len(probs) - 1

    def _update_a2c(self, prev_obs, prev_action, prev_probs, prev_value, reward, next_value):
        td_target = reward + (self.gamma * next_value)
        advantage = td_target - prev_value

        for feature_idx in range(self.FEATURES):
            self._critic_weights[feature_idx] += (
                self.critic_lr * advantage * prev_obs[feature_idx]
            )

        for action_idx in range(len(self.ACTIONS)):
            indicator = 1.0 if action_idx == prev_action else 0.0
            grad_log_prob = indicator - prev_probs[action_idx]
            for feature_idx in range(self.FEATURES):
                self._actor_weights[action_idx][feature_idx] += (
                    self.actor_lr * advantage * grad_log_prob * prev_obs[feature_idx]
                )

    def _load_state(self):
        try:
            if not self.state_path.exists():
                return
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("[AI Brain] failed to load state from %s", self.state_path)
            return

        actor = payload.get("actor_weights")
        critic = payload.get("critic_weights")
        total_steps = int(payload.get("total_steps", 0) or 0)

        if (
            isinstance(actor, list)
            and len(actor) == len(self.ACTIONS)
            and all(isinstance(row, list) and len(row) == self.FEATURES for row in actor)
        ):
            self._actor_weights = [[float(value) for value in row] for row in actor]
        if isinstance(critic, list) and len(critic) == self.FEATURES:
            self._critic_weights = [float(value) for value in critic]
        self._total_steps = total_steps

    def _save_state(self):
        payload = {
            "actor_weights": self._actor_weights,
            "critic_weights": self._critic_weights,
            "total_steps": self._total_steps,
            "saved_at": int(time.time()),
        }
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self._steps_since_save = 0
        except Exception:
            logger.exception("[AI Brain] failed to save state to %s", self.state_path)


Plugin = A2CBrainPlugin
