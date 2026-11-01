import os
import io
import re

import numpy as np
from PIL import Image, ImageOps, ImageEnhance, ImageFilter

_MODEL_FILE = os.path.join(os.path.dirname(__file__), "best.onnx")
_CANVAS = 384
_ALPHABET = "abcdefghijklmnopqrstuvwxyz"
_MIN_SCORE = 0.3
_PAD = (114, 114, 114)


class _Detector:
    def __init__(self):
        self._engine = None
        self._feed = None
        self._ocr = None

    def _ensure_loaded(self):
        if self._engine is None and self._ocr is None:
            if os.path.exists(_MODEL_FILE):
                try:
                    import onnxruntime
                    self._engine = onnxruntime.InferenceSession(
                        _MODEL_FILE, providers=["CPUExecutionProvider"]
                    )
                    self._feed = self._engine.get_inputs()[0].name
                except Exception as e:
                    print(f"[Captcha Detector] Failed loading onnx model: {e}")
                    self._engine = None

            if self._engine is None:
                try:
                    import ddddocr
                    self._ocr = ddddocr.DdddOcr(show_ad=False)
                except Exception as e:
                    print(f"[Captcha Detector] Failed loading ddddocr: {e}")

    @staticmethod
    def _fit_square(frame):
        pic = Image.fromarray(frame)
        width, height = pic.size
        ratio = min(_CANVAS / width, _CANVAS / height)
        target = (max(1, int(width * ratio)), max(1, int(height * ratio)))
        shrunk = pic.resize(target, Image.BILINEAR)

        canvas = Image.new("RGB", (_CANVAS, _CANVAS), _PAD)
        offset = ((_CANVAS - target[0]) // 2, (_CANVAS - target[1]) // 2)
        canvas.paste(shrunk, offset)
        return np.asarray(canvas)

    def _to_tensor(self, frame):
        tensor = self._fit_square(frame).astype(np.float32) / 255.0
        tensor = np.transpose(tensor, (2, 0, 1))
        return tensor[np.newaxis, ...]

    def predict(self, frame, strategy_index=0, expected=None):
        self._ensure_loaded()

        # 1. Use ONNX engine if available
        if self._engine is not None:
            try:
                tensor = self._to_tensor(frame)
                raw = self._engine.run(None, {self._feed: tensor})[0][0]

                found = []
                for row in raw:
                    ax, ay, bx, by, score, label = row
                    if score < _MIN_SCORE:
                        continue
                    found.append((float((ax + bx) / 2), float(score), _ALPHABET[int(label)]))

                if expected and len(found) > expected:
                    found.sort(key=lambda item: item[1], reverse=True)
                    found = found[:expected]

                found.sort(key=lambda item: item[0])
                res = "".join(item[2] for item in found)
                if res:
                    return res
            except Exception as e:
                print(f"[Captcha ONNX Predict Error]: {e}")

        # 2. Use DdddOcr with preprocessing strategies
        if self._ocr is not None:
            try:
                pil_img = Image.fromarray(frame) if isinstance(frame, np.ndarray) else frame
                processed = self._apply_strategy(pil_img, strategy_index)
                
                buf = io.BytesIO()
                processed.save(buf, format="PNG")
                raw_text = self._ocr.classification(buf.getvalue())
                
                # Sanitize text
                clean_text = "".join(c.lower() for c in raw_text if c.isalnum() or c in _ALPHABET)
                if expected and len(clean_text) > expected:
                    clean_text = clean_text[:expected]
                if clean_text:
                    return clean_text
            except Exception as e:
                print(f"[Captcha DdddOcr Predict Error]: {e}")

        # 3. Fallback: Try NopeCHA API if available (with multi-key pool / fallback)
        try:
            nopecha_keys = []
            env_key = os.getenv("NOPECHA_KEY")
            if env_key:
                nopecha_keys.append(env_key)

            try:
                cfg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "global_settings.json")
                if os.path.exists(cfg_path):
                    with open(cfg_path, "r", encoding="utf-8") as cf:
                        cdata = json.load(cf)
                    np_conf = cdata.get("captcha", {}).get("nopecha", {})
                    pkey = np_conf.get("key")
                    if pkey and pkey not in nopecha_keys:
                        nopecha_keys.append(pkey)
                    for k in np_conf.get("keys", []):
                        if k and k not in nopecha_keys:
                            nopecha_keys.append(k)
            except Exception:
                pass

            if not nopecha_keys:
                nopecha_keys = [k for k in [os.environ.get("NOPECHA_KEY", "")] if k]

            if nopecha_keys:
                import requests
                pil_img = Image.fromarray(frame) if isinstance(frame, np.ndarray) else frame
                buf = io.BytesIO()
                pil_img.save(buf, format="PNG")
                import base64
                b64 = base64.b64encode(buf.getvalue()).decode()

                for nk in nopecha_keys:
                    try:
                        r = requests.post(
                            "https://api.nopecha.com/v1/recognition",
                            json={"key": nk, "type": "textcaptcha", "image": b64},
                            timeout=10
                        )
                        if r.status_code == 200:
                            data = r.json()
                            ans = data.get("data", "")
                            if ans:
                                clean_ans = "".join(c.lower() for c in ans if c.isalnum())
                                return clean_ans
                        elif r.status_code in (400, 402, 404):
                            continue
                    except Exception:
                        continue
        except Exception:
            pass

        return ""

    @staticmethod
    def _apply_strategy(img, strategy_index):
        if strategy_index == 0:
            # Standard
            return img
        elif strategy_index == 1:
            # Adaptive / Grayscale + High Contrast
            gray = ImageOps.grayscale(img)
            enhancer = ImageEnhance.Contrast(gray)
            return enhancer.enhance(2.0)
        elif strategy_index == 2:
            # Heavy Distortion / Median Filter + Sharpness
            gray = ImageOps.grayscale(img)
            filt = gray.filter(ImageFilter.MedianFilter(size=3))
            sharp = ImageEnhance.Sharpness(filt).enhance(2.5)
            return sharp
        elif strategy_index == 3:
            # Binarization / Thresholding
            gray = ImageOps.grayscale(img)
            thresh = gray.point(lambda p: 255 if p > 128 else 0, mode='1')
            return thresh.convert("RGB")
        return img


_detector = _Detector()


def get_strategy_count():
    return 4


def _read_frame(source):
    if isinstance(source, (bytes, bytearray)):
        handle = Image.open(io.BytesIO(source))
    else:
        handle = Image.open(source)
    handle.load()
    return np.asarray(handle.convert("RGB"))


def solve_captcha(img_path, strategy_index=0, letter_count=None):
    return _detector.predict(_read_frame(img_path), strategy_index=strategy_index, expected=letter_count)
