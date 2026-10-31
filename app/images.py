import hashlib
import io
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 25_000_000


def normalizeImage(content):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                if image.format not in ("JPEG", "PNG", "WEBP"):
                    raise ValueError("Only JPEG, PNG and WebP are supported")
                if getattr(image, "n_frames", 1) != 1:
                    raise ValueError("Animated images are not supported")
                image.load()
                image = ImageOps.exif_transpose(image)
                hasAlpha = "A" in image.getbands() or "transparency" in image.info
                clean = Image.new("RGBA" if hasAlpha else "RGB", image.size)
                clean.paste(image.convert(clean.mode))
                output = io.BytesIO()
                clean.save(output, format="WEBP", quality=90, method=4)
                return output.getvalue(), clean.width, clean.height, hashlib.sha256(content).hexdigest()
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise ValueError("Invalid image or image exceeds the 25 megapixel limit") from error
