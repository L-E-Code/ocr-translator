"""
Processing device selection (CPU or GPU) for the OCR models.
Supports NVIDIA (CUDA), Intel Arc (XPU) and Apple (MPS), depending on the installed PyTorch.
"""
import subprocess
import sys

from core.logger_config import get_logger

logger = get_logger("Device")

KIND_LABELS = {"cuda": "CUDA", "xpu": "Intel XPU", "mps": "Apple MPS", "cpu": "CPU"}


def available_gpus():
    """Lists [(kind, name)] of the GPUs the installed PyTorch can use."""
    import torch  # imported here: torch is heavy and the interface must not wait for it on startup
    gpus = []
    try:
        if torch.cuda.is_available():
            gpus.append(("cuda", torch.cuda.get_device_name(0)))
    except Exception:
        pass
    try:
        xpu = getattr(torch, "xpu", None)
        if xpu is not None and xpu.is_available():
            gpus.append(("xpu", xpu.get_device_name(0)))
    except Exception:
        pass
    try:
        if torch.backends.mps.is_available():
            gpus.append(("mps", "Apple GPU"))
    except Exception:
        pass
    return gpus


def resolve_device(preference="auto"):
    """
    preference: 'auto' (GPU if available), 'gpu' (GPU, falls back to CPU if none) or 'cpu'.
    Returns (kind, label), for example ('xpu', 'Intel(R) Arc(TM) B580 Graphics').
    """
    if preference != "cpu":
        gpus = available_gpus()
        if gpus:
            return gpus[0]
        if preference == "gpu":
            logger.warning("GPU requested, but no usable GPU was found. Using CPU.")
    return "cpu", "Processor (CPU)"


def installed_gpu_names():
    """Names of the system's graphics cards (Windows), even if PyTorch does not use them."""
    if sys.platform != "win32":
        return []
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
            capture_output=True, text=True, timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout
        return [line.strip() for line in out.splitlines() if line.strip()]
    except Exception:
        return []


def gpu_vendor(name):
    low = name.lower()
    if "nvidia" in low or "geforce" in low or "rtx" in low or "gtx" in low:
        return "nvidia"
    if "intel" in low and ("arc" in low or "iris" in low or "xe" in low or "uhd" in low):
        return "intel"
    return "other"
