import cv2
import numpy as np
from pathlib import Path
from typing import Tuple, Union


def deskew(image: np.ndarray) -> Tuple[np.ndarray, float]:
    """
    Detect skew angle and rotate image to correct it.

    Uses Hough Line Transform to find dominant lines,
    then calculates the median angle.
    """
    # Invert for edge detection (text becomes white)
    inverted = cv2.bitwise_not(image)

    # Detect edges
    edges = cv2.Canny(inverted, 50, 150, apertureSize=3)

    # Detect lines using Hough Transform
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 100, minLineLength=100, maxLineGap=10)

    if lines is None:
        return image, 0.0

    # Calculate angles of detected lines
    angles = []
    for line in lines.reshape(-1, 4):
        x1, y1, x2, y2 = line
        angle = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        # Only consider near-horizontal lines
        if abs(angle) < 45:
            angles.append(angle)

    if not angles:
        return image, 0.0

    # Use median angle to reduce outlier impact
    median_angle = np.median(angles)

    # Only correct if skew is meaningful (avoid over-rotating already-straight images)
    if abs(median_angle) < 0.5:
        return image, 0.0

    # Rotate image to correct skew
    (h, w) = image.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
    rotated = cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_CUBIC,
                              borderMode=cv2.BORDER_REPLICATE)

    return rotated, float(median_angle)


def preprocess_receipt(image_path: Union[str, Path], scale_factor: float = 1.5) -> np.ndarray:
    """
    Complete preprocessing pipeline for receipt images.

    Pipeline:
    1. Load & convert to grayscale
    2. CLAHE — boosts faded thermal ink without over-saturating
    3. Gentle Gaussian blur — removes scanner/camera noise
    4. Otsu thresholding — optimal global binarization for high-contrast receipts
    5. Morphological closing — reconnects broken character strokes
    6. Upscale 1.5× (INTER_CUBIC) — gives PaddleOCR more pixel resolution
    7. Deskew — corrects camera tilt

    Args:
        image_path: Path to the receipt image
        scale_factor: Upscale factor (default 2.0×)

    Returns:
        Preprocessed binary image as numpy array (uint8)
    """
    # 1. Load image
    img = cv2.imread(str(image_path))
    if img is None:
        raise ValueError(f"Could not load image: {image_path}")

    # 2. Convert to grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 3. CLAHE — Contrast Limited Adaptive Histogram Equalization
    #    clipLimit=2.0 and tileGridSize=8×8 work well for receipt paper textures
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    # 4. Gentle Gaussian blur to suppress sensor/JPEG noise before thresholding
    blurred = cv2.GaussianBlur(enhanced, (3, 3), 0)

    # 5. Otsu thresholding — automatically finds the optimal global threshold
    #    Works excellently on high-contrast thermal receipt prints
    _, binary = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # 6. Morphological closing — reconnects strokes broken by Otsu binarization
    #    Kernel (2,1): vertical closing only to avoid merging adjacent characters horizontally
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 1))
    closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    # 7. Upscale — 2× gives PaddleOCR significantly more pixels to work with
    width = int(closed.shape[1] * scale_factor)
    height = int(closed.shape[0] * scale_factor)
    upscaled = cv2.resize(closed, (width, height), interpolation=cv2.INTER_CUBIC)

    # 8. Deskew
    deskewed, _ = deskew(upscaled)

    return deskewed


def preprocess_receipt_raw(image_path: Union[str, Path], scale_factor: float = 2.0) -> np.ndarray:
    """
    Lighter preprocessing: grayscale + CLAHE + upscale only (no binarization).

    Use as a fallback when Otsu binarization degrades OCR quality on
    colour photos or low-contrast scans.

    Args:
        image_path: Path to the receipt image
        scale_factor: Upscale factor (default 2.0×)

    Returns:
        Grayscale enhanced image as numpy array (uint8)
    """
    img = cv2.imread(str(image_path))
    if img is None:
        raise ValueError(f"Could not load image: {image_path}")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    width = int(enhanced.shape[1] * scale_factor)
    height = int(enhanced.shape[0] * scale_factor)
    upscaled = cv2.resize(enhanced, (width, height), interpolation=cv2.INTER_CUBIC)

    deskewed, _ = deskew(upscaled)
    return deskewed
