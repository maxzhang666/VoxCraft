#!/usr/bin/env bash
# 下载 MVP 所需模型到 $VOXCRAFT_MODELS_DIR（默认 ./models）
# 依赖: huggingface-cli 或 wget

set -euo pipefail

MODELS_DIR="${VOXCRAFT_MODELS_DIR:-./models}"
mkdir -p "$MODELS_DIR"

echo "==> 模型下载目录: $MODELS_DIR"

# Whisper Medium (int8)
echo "==> faster-whisper medium"
huggingface-cli download Systran/faster-whisper-medium \
    --local-dir "$MODELS_DIR/whisper-medium" --local-dir-use-symlinks False

# Piper 中文
echo "==> Piper zh_CN huayan medium"
mkdir -p "$MODELS_DIR/piper"
wget -nc -O "$MODELS_DIR/piper/zh_CN-huayan-medium.onnx" \
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx"
wget -nc -O "$MODELS_DIR/piper/zh_CN-huayan-medium.onnx.json" \
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx.json"

# VoxCPM
echo "==> VoxCPM"
huggingface-cli download openbmb/VoxCPM \
    --local-dir "$MODELS_DIR/voxcpm" --local-dir-use-symlinks False

# Demucs (htdemucs 默认会在首次使用时 torch.hub 自动下载)
echo "==> Demucs 模型将由 torch.hub 在首次推理时自动下载"

echo "==> 完成"
