"""Train a tiny U-Net for paper/foot segmentation and export ONNX."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from training.synthesize import write_dataset  # noqa: E402


def build_model(torch, nn):
    class ConvBNReLU(nn.Module):
        def __init__(self, c_in, c_out):
            super().__init__()
            self.net = nn.Sequential(
                nn.Conv2d(c_in, c_out, 3, padding=1, bias=False),
                nn.BatchNorm2d(c_out),
                nn.ReLU(inplace=True),
            )

        def forward(self, x):
            return self.net(x)

    class TinyUNet(nn.Module):
        def __init__(self, n_classes=3):
            super().__init__()
            self.e1 = ConvBNReLU(3, 16)
            self.e2 = ConvBNReLU(16, 32)
            self.e3 = ConvBNReLU(32, 64)
            self.pool = nn.MaxPool2d(2)
            self.up = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=False)
            self.d2 = ConvBNReLU(64 + 32, 32)
            self.d1 = ConvBNReLU(32 + 16, 16)
            self.out = nn.Conv2d(16, n_classes, 1)

        def forward(self, x):
            x1 = self.e1(x)
            x2 = self.e2(self.pool(x1))
            x3 = self.e3(self.pool(x2))
            y = self.up(x3)
            y = self.d2(torch.cat([y, x2], dim=1))
            y = self.up(y)
            y = self.d1(torch.cat([y, x1], dim=1))
            return self.out(y)

    return TinyUNet()


def load_pair(img_path: Path, mask_path: Path, size: int):
    bgr = cv2.imread(str(img_path))
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
    rgb = cv2.resize(rgb, (size, size), interpolation=cv2.INTER_AREA)
    mask = cv2.resize(mask, (size, size), interpolation=cv2.INTER_NEAREST)
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
    x = rgb.astype(np.float32) / 255.0
    x = (x - mean) / std
    x = np.transpose(x, (2, 0, 1))
    return x, mask.astype(np.int64)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--epochs', type=int, default=8)
    p.add_argument('--n-synthetic', type=int, default=240)
    p.add_argument('--size', type=int, default=256)
    p.add_argument('--out', type=Path, default=ROOT / 'models')
    p.add_argument('--data', type=Path, default=ROOT / 'training' / 'data')
    args = p.parse_args()

    try:
        import torch
        import torch.nn as nn
        import torch.nn.functional as F
    except ImportError:
        print('PyTorch required for training: pip install torch')
        sys.exit(1)

    args.out.mkdir(parents=True, exist_ok=True)
    if not (args.data / 'images').exists() or len(list((args.data / 'images').glob('*.jpg'))) < 20:
        print(f'Synthesizing {args.n_synthetic} samples → {args.data}')
        write_dataset(args.data, n=args.n_synthetic, size=args.size)

    images = sorted((args.data / 'images').glob('*.jpg'))
    pairs = [(im, args.data / 'masks' / f'{im.stem}.png') for im in images]
    pairs = [(a, b) for a, b in pairs if b.is_file()]
    rng = np.random.default_rng(0)
    rng.shuffle(pairs)
    split = max(1, int(0.85 * len(pairs)))
    train_pairs, val_pairs = pairs[:split], pairs[split:]

    device = torch.device('cpu')
    model = build_model(torch, nn).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)

    def batch_iter(plist, bs=8):
        for i in range(0, len(plist), bs):
            xs, ys = [], []
            for ip, mp in plist[i:i + bs]:
                x, y = load_pair(ip, mp, args.size)
                xs.append(x)
                ys.append(y)
            yield (
                torch.from_numpy(np.stack(xs)).to(device),
                torch.from_numpy(np.stack(ys)).to(device),
            )

    print(f'Train {len(train_pairs)} / val {len(val_pairs)}')
    for epoch in range(args.epochs):
        model.train()
        total = 0.0
        n = 0
        for xb, yb in batch_iter(train_pairs):
            opt.zero_grad()
            logits = model(xb)
            loss = F.cross_entropy(logits, yb)
            loss.backward()
            opt.step()
            total += float(loss.item())
            n += 1
        model.eval()
        correct = 0
        count = 0
        with torch.no_grad():
            for xb, yb in batch_iter(val_pairs, bs=8):
                pred = model(xb).argmax(1)
                correct += int((pred == yb).sum().item())
                count += int(yb.numel())
        acc = correct / max(count, 1)
        print(f'epoch {epoch + 1}/{args.epochs} loss={total / max(n, 1):.4f} val_acc={acc:.3f}')

    model.eval()
    onnx_path = args.out / 'paper_foot_seg.onnx'
    dummy = torch.zeros(1, 3, args.size, args.size, device=device)
    torch.onnx.export(
        model,
        dummy,
        str(onnx_path),
        input_names=['input'],
        output_names=['logits'],
        dynamic_axes=None,
        opset_version=17,
        dynamo=False,
    )
    card = {
        'version': 'bootstrap-unet-v1',
        'input_size': args.size,
        'classes': ['background', 'paper', 'foot'],
        'mean': [0.485, 0.456, 0.406],
        'std': [0.229, 0.224, 0.225],
        'release_gate_mae_mm': 5.0,
        'notes': 'Bootstrap weights from synthetic A4+foot composites. Replace after labeled real captures.',
    }
    (args.out / 'model_card.json').write_text(json.dumps(card, indent=2))
    print(f'Wrote {onnx_path}')
    print(f'Wrote {args.out / "model_card.json"}')


if __name__ == '__main__':
    main()
