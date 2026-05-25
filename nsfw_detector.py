# nsfw_detector.py
# Author: Marco D'Amico <marcodamico@protonmail.com>
# Copyright (c) 2026 Marco D'Amico

import numpy as np

NSFW_MODEL_VERSION = "heuristic-v1"


class NsfwDetector:
    """
    Lightweight heuristic NSFW scorer intended for local, CPU-only usage.
    This is assistive, not a moderation-grade model.
    
    Uses skin tone detection and brightness analysis to identify potential NSFW content.
    Higher thresholds are used to reduce false positives from portraits, faces, and
    other legitimate photos with exposed skin.
    """

    def detect(self, pil_image):
        small = pil_image.convert("YCbCr").resize((256, 256))
        arr = np.array(small)
        y = arr[:, :, 0]
        cb = arr[:, :, 1]
        cr = arr[:, :, 2]

        # Skin tone detection in YCbCr space
        skin = (cb >= 77) & (cb <= 127) & (cr >= 133) & (cr <= 173) & (y >= 35)
        skin_ratio = float(skin.mean())
        bright_ratio = float((y > 65).mean())
        
        # Composite score: weighted combination of skin ratio and brightness
        score = (skin_ratio * 0.85) + (bright_ratio * 0.15)
        score = max(0.0, min(1.0, (score - 0.12) / 0.58))
        
        # Much higher thresholds to reduce false positives from portraits and faces
        # A typical portrait or headshot might have 20-40% skin ratio - we want 65%+
        if score >= 0.85:
            label = "nsfw"
        elif score >= 0.65:
            label = "possible_nsfw"
        else:
            label = "safe"
        return float(score), label
