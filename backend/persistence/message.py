import io
import base64
from typing import Optional
from pydantic import BaseModel, model_validator
from PIL import Image
from shared.logger import logger



class Message(BaseModel):
    text: str | None = None
    image_b64: str | None = None

    _converted_image_mime_type: str | None = None
    _converted_image_b64: str | None = None

    @model_validator(mode='after')
    def validate_and_normalize(self):

        if self.text is not None and any(char.isalpha() for char in self.text):
            self.text = self.text.strip()
            if not self.text:
                raise ValueError("message is empty")
            if len(self.text) > 10000:
                raise ValueError("message is too long")

        if self.image_b64:
            try:
                raw_bytes = base64.b64decode(self.image_b64)
                with Image.open(io.BytesIO(raw_bytes)) as img:
                    rgb = img.convert("RGB")
                    buffer = io.BytesIO()
                    rgb.save(buffer, format="JPEG", quality=80, optimize=True)
                    buffer.seek(0)

                    max_size_mb = 5
                    converted_bytes = buffer.read()
                    if len(converted_bytes) > (max_size_mb * 1024 * 1024):
                        raise ValueError(f"image too large: {len(converted_bytes) / (1024 * 1024):.2f} MB")

                    buffer.seek(0)
                    self._converted_image_b64 = base64.b64encode(buffer.read()).decode("utf-8")
                    self._converted_image_mime_type = "image/jpeg"
            except Exception:
                raise ValueError("invalid image_b64")

        if not self.text and not self._converted_image_b64:
            raise ValueError("either 'message' with real characters or valid 'image_b64' is required")

        return self

    @property
    def converted_image_b64(self):
        return self._converted_image_b64

    @property
    def converted_image_mime_type(self):
        return self._converted_image_mime_type
