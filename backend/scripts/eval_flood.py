"""
Flood depth test set -> numbers for the "Testing + reliability" criterion.

Put 20-30 flood photos in data/flood_eval/ and a labels.csv next to them:
    filename,true_depth_cm
    street1.jpg,15
    ...
(label them yourselves from visible objects, or use photos with reported depths)

Run:  python -m scripts.eval_flood
Prints: mean absolute error (cm), % in the correct danger level, % the model
refused (routed to manual body-level input), and the average time per photo.
"""
import asyncio
import csv
import time
from pathlib import Path

from app.reports.flood import analyze_photo, level_for

EVAL_DIR = Path(__file__).resolve().parent.parent / "data" / "flood_eval"


async def main():
    rows = list(csv.DictReader(open(EVAL_DIR / "labels.csv", encoding="utf-8")))
    errors, level_hits, refused, times = [], 0, 0, []
    for row in rows:
        t = time.time()
        res = await analyze_photo((EVAL_DIR / row["filename"]).read_bytes())
        times.append(time.time() - t)
        truth = float(row["true_depth_cm"])
        if not res["ok"]:
            refused += 1
            print(f"  REFUSED {row['filename']}: {res['reason']}")
            continue
        err = abs(res["depth_cm"] - truth)
        errors.append(err)
        level_hits += level_for(res["depth_cm"])[0] == level_for(truth)[0]
        print(f"  {row['filename']}: predicted {res['depth_cm']:.0f} cm "
              f"({res['anchor']}), truth {truth:.0f} cm, error {err:.0f}")
    n = len(rows)
    answered = len(errors)
    print("\n=== Flood depth evaluation ===")
    print(f"photos: {n}   answered: {answered}   refused -> manual: {refused} ({refused/n:.0%})")
    if answered:
        print(f"mean absolute error: {sum(errors)/answered:.1f} cm")
        print(f"correct danger level: {level_hits/answered:.0%}")
    print(f"avg latency: {sum(times)/n:.1f} s per photo")


if __name__ == "__main__":
    asyncio.run(main())
