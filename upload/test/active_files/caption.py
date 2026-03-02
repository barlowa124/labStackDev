from __future__ import annotations

from pathlib import Path
from typing import Optional


class Captioner:
    def __init__(
        self,
        enabled: bool = True,
        model_id: str = "Salesforce/blip-image-captioning-base",
        max_new_tokens: int = 40,
        task_prompt: str = "<MORE_DETAILED_CAPTION>",
        device: str = "cpu",
        batch_size: int = 1,
    ):
        self.enabled = enabled
        self.model_id = model_id
        self.max_new_tokens = max_new_tokens
        self.task_prompt = task_prompt
        self.device = device
        self.batch_size = max(1, int(batch_size))
        self._pipe = None
        self._task = None
        self._processor = None
        self._model = None
        self._torch = None
        self._torch_device = "cpu"
        self.error: Optional[str] = None

        if not enabled:
            return

        try:
            if "florence-2" in model_id.lower():
                from transformers import AutoModelForCausalLM, AutoProcessor
                import torch

                self._processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
                self._model = AutoModelForCausalLM.from_pretrained(model_id, trust_remote_code=True)
                if self.device == "cuda" and torch.cuda.is_available():
                    self._model = self._model.to("cuda")
                    self._torch_device = "cuda"
                else:
                    self._torch_device = "cpu"
                self._model.eval()
                self._torch = torch
                self._task = "florence-2"
            else:
                from transformers import pipeline

                device_index = 0 if self.device == "cuda" else -1

                task_candidates = ["image-to-text", "image-text-to-text"]
                last_error = None
                for task in task_candidates:
                    try:
                        self._pipe = pipeline(task, model=model_id, device=device_index, batch_size=self.batch_size)
                        self._task = task
                        last_error = None
                        break
                    except Exception as exc:
                        last_error = exc
                if self._pipe is None and last_error is not None:
                    raise last_error
        except Exception as exc:
            self.error = str(exc)
            self.enabled = False

    def generate(self, image_path: Path, prompt: Optional[str] = None) -> Optional[str]:
        if not self.enabled:
            return None
        try:
            if self._task == "florence-2":
                return self._generate_florence(image_path, prompt=prompt)

            if self._pipe is None:
                return None

            prompt_norm = (prompt or "").strip().lower()

            if self._task == "image-text-to-text" and prompt:
                out = self._pipe(images=str(image_path), text=prompt, max_new_tokens=self.max_new_tokens)
            else:
                out = self._pipe(str(image_path), max_new_tokens=self.max_new_tokens)

            if not (isinstance(out, list) and out):
                return None

            text = (out[0].get("generated_text") or out[0].get("caption") or "").strip()
            if not text:
                return None

            if prompt_norm:
                text_norm = text.lower().strip()
                if text_norm == prompt_norm:
                    return None
                if text_norm.startswith(prompt_norm):
                    text = text[len(prompt or ""):].lstrip(" :.-")

            return text or None
        except Exception as exc:
            self.error = str(exc)
            return None

    def _generate_florence(self, image_path: Path, prompt: Optional[str] = None) -> Optional[str]:
        if self._processor is None or self._model is None or self._torch is None:
            return None

        from PIL import Image

        prompt_text = (prompt or "").strip()
        task_prompt = self.task_prompt if self.task_prompt else "<MORE_DETAILED_CAPTION>"

        image = Image.open(image_path).convert("RGB")
        inputs = self._processor(text=task_prompt, images=image, return_tensors="pt")
        if self._torch_device == "cuda":
            inputs = {k: v.to("cuda") for k, v in inputs.items()}

        with self._torch.no_grad():
            generated_ids = self._model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=self.max_new_tokens,
                num_beams=3,
            )

        raw = self._processor.batch_decode(generated_ids, skip_special_tokens=False)[0].strip()
        parsed = None
        try:
            parsed = self._processor.post_process_generation(
                raw,
                task=task_prompt,
                image_size=(image.width, image.height),
            )
        except Exception:
            parsed = None

        if isinstance(parsed, dict):
            text = (parsed.get(task_prompt) or "").strip()
        else:
            text = raw

        if not text:
            return None

        if prompt_text:
            return f"{text}. Microscopy context: {prompt_text}".strip()
        return text
