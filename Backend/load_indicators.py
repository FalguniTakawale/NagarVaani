"""Load an external dataset CSV into region_indicators.

    python load_indicators.py example_indicators_FORMAT_ONLY.csv

CSV columns: country,state,city,indicator,value,year,source
(indicator examples: population, infra_index, planned_investment). `source` is
mandatory provenance. Nothing is bundled — bring your own census/index data."""
import asyncio, csv, sys
from app.database import AsyncSessionLocal, create_tables
from app.models.models import RegionIndicator


async def main(path: str):
    await create_tables()
    n = 0
    async with AsyncSessionLocal() as s:
        with open(path, newline="", encoding="utf-8-sig") as f:
            for rec in csv.DictReader(f):
                s.add(RegionIndicator(
                    country=(rec.get("country") or "India").strip(), state=(rec.get("state") or None),
                    city=(rec.get("city") or None), indicator=rec["indicator"].strip(),
                    value=float(rec["value"]), year=int(rec["year"]) if rec.get("year") else None,
                    source=(rec.get("source") or "").strip() or "unspecified",
                ))
                n += 1
        await s.commit()
    print(f"Loaded {n} rows")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1]))
