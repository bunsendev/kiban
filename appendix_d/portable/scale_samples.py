"""Synthetic load-test ZIPs, never business or accuracy-validation data."""

import io
import zipfile
from datetime import date, timedelta


def sample_zip(count):
    def jan(index):
        body = f"4901234{index:05d}"
        check = (-sum(int(v) * (1 if i % 2 == 0 else 3) for i, v in enumerate(body))) % 10
        return body + str(check)

    target = io.BytesIO()
    inventory = ["商品コード,商品名,明細バラ数,賞味期限"]
    for index in range(count):
        inventory.append(f"{jan(index)},人工検証商品{index},100,2026/04/30")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for offset in range(35):
            day = date(2026, 1, 1) + timedelta(days=offset)
            rows = ["出荷日,納品日,商品名,JAN,数量"]
            for index in range(count):
                rows.append(
                    f"{day:%Y/%m/%d},{day:%Y/%m/%d},人工検証商品{index},"
                    f"{jan(index)},{1 + index % 10 + offset % 7}"
                )
            archive.writestr(f"data/神戸日時出荷_{day:%Y%m%d}.csv", "\n".join(rows).encode("cp932"))
        archive.writestr("data/神戸日時在庫_20260204.csv", "\n".join(inventory).encode("cp932"))
    return target.getvalue()


def write_samples(output):
    output.mkdir(parents=True, exist_ok=True)
    for count in (100, 500, 1000):
        (output / f"SYNTHETIC-{count}-products.zip").write_bytes(sample_zip(count))
