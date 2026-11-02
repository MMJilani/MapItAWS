# Where is crime moving? London

**Is crime spreading into areas that used to be quiet?** This map shows London's crime hotspots over three years. Press play to watch them appear, stay and fade.
**Live map:** <[Map Link](http://amzn-s3-bucket-mapit.s3-website.eu-north-1.amazonaws.com/)>
**Video:** <Video Link>(https://www.youtube.com/watch?v=db1QYh95TF4)

## What the map reveals
- **Total crime barely changed:** 1,139,469 crimes in Sep 2023–Aug 2024 vs 1,125,245 in Sep 2025–Aug 2026 (about −1%).
- **But hotspots moved:** in the latest year, 63 of London's 312 hotspots were new (about 1 in 5) and 65 faded.
- **Crime isn't rising overall, but it isn't standing still either.**

## What you can do
- Drag the year slider or press ▶ to watch hotspots change
- Show or hide new (red), established (orange) and faded (grey) hotspots
- Tap a hotspot to see its crimes and change from last year
- Turn on **Crimes per km²** to compare boroughs, and tap one for its rank out of 33

## How it works
police.uk CSVs → `src/process.py` (Python) → small GeoJSON files → Amazon S3 → MapLibre page drawn over an **Amazon Location Service** base map

1. **Clean:** 3.44M crimes loaded; 0.4% with no location and 0.4% outside London removed (3.42M left, 33 areas).
2. **Split** into three 12-month periods.
3. **Find hotspots:** DBSCAN clustering (haversine distance) per borough, per year. A hotspot is a spot where at least 1% of the borough's yearly crimes fall within 150 m.
4. **Compare years:** a hotspot within 300 m of last year's is *established*; otherwise it's *new*. Last year's hotspots with nothing nearby now are *faded*.

## Run it yourself
1. Download crime data from [data.police.uk](https://data.police.uk/data/) (pick your police force, crime data only) and unzip it into `data/raw/`.
2. run python (install pip if required)
3. python src/process.py. This writes the map files to `web/data/`.
4. Copy web/config.example.js to web/config.js and add your Amazon Location API key.
5. Upload web/ to an S3 bucket with static website hosting.

**Another city:** change the `LONDON` list in `process.py` to that area's district names. The settings (`EPS_M`, `MIN_SHARE`, `MATCH_M`) are at the top of the file.

## Limitations
- Police locations are anonymised to nearby points, so this shows **areas, not exact streets**.
- Hotspots are **relative to each borough**: a hotspot in a quiet borough can have fewer crimes than ordinary streets in central London.
- Crimes per km² measures concentration, not personal risk. Central boroughs score high partly because of large daytime and visitor populations.
- British Transport Police data (railways and the Tube) is not included.

## Data and credits
Contains public sector information licensed under the [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/). Crime data: data.police.uk. Borough boundaries: London Datastore.
Built by Moizz Ilyas and Eylul for the AWS Builder Center "Map it" challenge