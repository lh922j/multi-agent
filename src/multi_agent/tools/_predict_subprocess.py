"""서브프로세스에서 단독 실행되는 예측 스크립트. stdin → JSON row, stdout → float."""
import json
import sys
import warnings

import joblib
import numpy as np
import pandas as pd

model_path = sys.argv[1]
row = json.loads(sys.stdin.read())

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    bundle = joblib.load(model_path)

model = bundle["model"]
model.set_params(n_jobs=1)

encoders = {
    col: {cls: i for i, cls in enumerate(le.classes_)}
    for col, le in bundle.get("label_encoders", {}).items()
}
for col, mapping in encoders.items():
    if col in row:
        row[col] = mapping.get(str(row[col]), mapping.get("unknown", 0))

df = pd.DataFrame(
    [[row[f] for f in bundle["feature_names"]]],
    columns=bundle["feature_names"],
).astype("float64")

print(float(model.predict(df)[0]))
