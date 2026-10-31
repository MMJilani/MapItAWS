#Settings

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN
from sklearn.neighbors import BallTree

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "web" / "data"
SUMMARY_FILE = ROOT / "data" / "crimes_by_borough_year.csv"

EARTH_RADIUS_M = 6_371_000
EPS_M = 150
MIN_SHARE = 0.01
MATCH_M = 300

YEARS = ["Year1", "Year2", "Year3"]

LONDON = [
    "Barking and Dagenham", "Barnet", "Bexley", "Brent", "Bromley", "Camden",
    "City of London", "Croydon", "Ealing", "Enfield", "Greenwich", "Hackney",
    "Hammersmith and Fulham", "Haringey", "Harrow", "Havering", "Hillingdon",
    "Hounslow", "Islington", "Kensington and Chelsea", "Kingston upon Thames",
    "Lambeth", "Lewisham", "Merton", "Newham", "Redbridge",
    "Richmond upon Thames", "Southwark", "Sutton", "Tower Hamlets",
    "Waltham Forest", "Wandsworth", "Westminster",
]

#Load
def load_crimes():
    files = sorted(RAW_DIR.glob("**/*-street.csv"))      # skips the -outcomes.csv files
    if not files:
        raise SystemExit(f"No *-street.csv files found in {RAW_DIR}")

    columns = ["Month", "Longitude", "Latitude", "LSOA name", "Crime type"]
    crimes = pd.concat((pd.read_csv(f, usecols=columns) for f in files), ignore_index=True)
    crimes["Month"] = pd.to_datetime(crimes["Month"])

    print(f"1. Loaded {len(files)} files, {len(crimes):,} rows")
    return crimes


def clean(crimes):
    total = len(crimes)

    crimes = crimes.dropna(subset=["Latitude", "Longitude", "LSOA name"]).copy()
    no_location = total - len(crimes)

    # "Lambeth 012A" -> "Lambeth"
    crimes["Borough"] = crimes["LSOA name"].str.rsplit(" ", n=1).str[0]
    before = len(crimes)
    crimes = crimes[crimes["Borough"].isin(LONDON)].copy()
    outside = before - len(crimes)

    print(f"2. Dropped {no_location:,} with no location ({no_location / total:.1%}), "
          f"{outside:,} outside London ({outside / total:.1%}); "
          f"{len(crimes):,} crimes in {crimes['Borough'].nunique()} areas left")
    return crimes


def add_year_groups(crimes):
    # Three 12-month blocks counting back from the newest month,
    # e.g. latest = Aug 2026 -> Year3 starts Sep 2025, Year2 Sep 2024, Year1 Sep 2023
    latest = crimes["Month"].max()
    year3_start = latest - pd.DateOffset(months=11)
    year2_start = latest - pd.DateOffset(months=23)
    year1_start = latest - pd.DateOffset(months=35)

    crimes = crimes[crimes["Month"] >= year1_start].copy()
    crimes["YearGroup"] = "Year1"
    crimes.loc[crimes["Month"] >= year2_start, "YearGroup"] = "Year2"
    crimes.loc[crimes["Month"] >= year3_start, "YearGroup"] = "Year3"

    counts = crimes["YearGroup"].value_counts().sort_index()
    print("3. Crimes per year: " + ", ".join(f"{y} {n:,}" for y, n in counts.items()))
    return crimes


def get_points(crimes, borough, year):
    """Squash crimes on the same snapped coordinate into one row with a count."""
    sample = crimes[(crimes["Borough"] == borough) & (crimes["YearGroup"] == year)]
    return sample.groupby(["Latitude", "Longitude"]).size().reset_index(name="crimes")


def find_hotspots(points, min_samples):
    """DBSCAN on one borough + one year, then one row per hotspot: centre + total crimes."""
    if points.empty:
        return pd.DataFrame(columns=["Latitude", "Longitude", "crimes"])

    coords = np.radians(points[["Latitude", "Longitude"]])
    db = DBSCAN(eps=EPS_M / EARTH_RADIUS_M, min_samples=min_samples,
                metric="haversine", algorithm="ball_tree")
    db.fit(coords, sample_weight=points["crimes"])

    points = points.assign(cluster=db.labels_)
    hot = points[points["cluster"] != -1]          # -1 = not part of any hotspot

    # Centre of each hotspot = average position weighted by crimes
    hot = hot.assign(lat_w=hot["Latitude"] * hot["crimes"],
                     lon_w=hot["Longitude"] * hot["crimes"])
    summary = hot.groupby("cluster")[["crimes", "lat_w", "lon_w"]].sum().reset_index()
    summary["Latitude"] = summary["lat_w"] / summary["crimes"]
    summary["Longitude"] = summary["lon_w"] / summary["crimes"]
    return summary[["Latitude", "Longitude", "crimes"]]


def all_hotspots(crimes):
    results = []
    for borough in sorted(crimes["Borough"].unique()):
        # Same setting for all 3 years of a borough, so change comes from the data
        yearly_average = (crimes["Borough"] == borough).sum() / len(YEARS)
        min_samples = max(int(yearly_average * MIN_SHARE), 1)

        for year in YEARS:
            hotspots = find_hotspots(get_points(crimes, borough, year), min_samples)
            hotspots["Borough"] = borough
            hotspots["YearGroup"] = year
            results.append(hotspots)

    hotspots = pd.concat(results, ignore_index=True)
    counts = hotspots["YearGroup"].value_counts().sort_index()
    print("4. Hotspots per year: " + ", ".join(f"{y} {n}" for y, n in counts.items()))
    return hotspots


def nearest(from_df, to_df):
    """For each hotspot in from_df: distance in metres to the closest one in to_df, and which one."""
    if len(from_df) == 0 or len(to_df) == 0:
        return np.full(len(from_df), np.inf), np.full(len(from_df), -1)
    tree = BallTree(np.radians(to_df[["Latitude", "Longitude"]]), metric="haversine")
    dist, idx = tree.query(np.radians(from_df[["Latitude", "Longitude"]]), k=1)
    return dist[:, 0] * EARTH_RADIUS_M, idx[:, 0]

#Labelling
def label_years(hotspots):
    labelled = []

    for borough in hotspots["Borough"].unique():
        b = hotspots[hotspots["Borough"] == borough]

        first = b[b["YearGroup"] == YEARS[0]].copy()
        first["status"] = "baseline"                 # nothing earlier to compare with
        first["prev_crimes"] = np.nan
        labelled.append(first)

        for prev_year, year in zip(YEARS, YEARS[1:]):
            prev = b[b["YearGroup"] == prev_year].reset_index(drop=True)
            cur = b[b["YearGroup"] == year].reset_index(drop=True)

            # This year's hotspots: was there one within MATCH_M last year?
            dist, idx = nearest(cur, prev)
            matched = dist <= MATCH_M
            cur["status"] = np.where(matched, "established", "new")
            cur["prev_crimes"] = np.where(matched, prev["crimes"].reindex(idx).values, np.nan)

            # Last year's hotspots with nothing near them now: faded
            dist_back, _ = nearest(prev, cur)
            faded = prev[dist_back > MATCH_M].copy()
            faded["YearGroup"] = year
            faded["status"] = "faded"
            faded["prev_crimes"] = faded["crimes"]
            faded["crimes"] = np.nan                 # not a hotspot this year

            labelled.extend([cur, faded])

    hotspots = pd.concat(labelled, ignore_index=True)
    hotspots["change_pct"] = ((hotspots["crimes"] - hotspots["prev_crimes"])
                              / hotspots["prev_crimes"] * 100).round(1)

    print("5. Status per year:")
    print(hotspots.groupby(["YearGroup", "status"]).size().to_string())
    return hotspots

#Save
def to_number(value):
    """NaN -> None (null in JSON), otherwise a rounded number."""
    return None if pd.isna(value) else round(float(value), 1)


def save_geojson(hotspots):
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    for year in YEARS:
        rows = hotspots[hotspots["YearGroup"] == year]
        features = [{
            "type": "Feature",
            "geometry": {"type": "Point",
                         # GeoJSON order is [longitude, latitude]
                         "coordinates": [round(r["Longitude"], 5), round(r["Latitude"], 5)]},
            "properties": {
                "borough": r["Borough"],
                "status": r["status"],
                "crimes": to_number(r["crimes"]),
                "prev_crimes": to_number(r["prev_crimes"]),
                "change_pct": to_number(r["change_pct"]),
            },
        } for _, r in rows.iterrows()]

        path = OUT_DIR / f"hotspots_{year}.geojson"
        with open(path, "w") as f:
            json.dump({"type": "FeatureCollection", "features": features}, f)
        print(f"6. Saved {path.relative_to(ROOT)} ({len(features)} hotspots, "
              f"{path.stat().st_size / 1024:.0f} KB)")


def save_summary(crimes):
    summary = crimes.pivot_table(index="Borough", columns="YearGroup",
                                 values="Month", aggfunc="size")
    summary.to_csv(SUMMARY_FILE)
    print(f"6. Saved {SUMMARY_FILE.relative_to(ROOT)}")


#Run
def main():
    crimes = add_year_groups(clean(load_crimes()))
    hotspots = label_years(all_hotspots(crimes))
    save_geojson(hotspots)
    save_summary(crimes)
    print("Done.")


if __name__ == "__main__":
    main()


