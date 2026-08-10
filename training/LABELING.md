# Labeled captures for production model refresh

Target: ≥200 real phone photos with paper + foot masks (and ruler ground-truth length in mm).

## Layout

```
training/labeled/
  images/0001.jpg
  masks/0001.png   # 0=background, 1=paper, 2=foot
  lengths.csv      # id,cm_gt
```

## Process

1. Capture with the production A4 protocol (`docs/QA_CHECKLIST.md`).
2. Label masks (CVAT / Label Studio / or bootstrap then correct).
3. Retrain:

```bash
pip install -r requirements-train.txt
python -m training.train_seg --data training/labeled --epochs 20 --size 256
python -m training.eval_gate --n 40 --max-mae-mm 5 --max-fail-rate 0.10
```

4. Ship when holdout **MAE ≤ 5 mm** and fail-rate < 10% on real labeled holdout.
5. Commit updated `models/paper_foot_seg.onnx` + `models/model_card.json`.
