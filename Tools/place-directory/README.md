# Park Ridge Place Directory Backend

This folder contains the production path for keeping Park Ridge restaurants,
businesses, parks, and public places current without scraping Google Maps.

## Source policy

- Do not scrape Google Maps pages or store copied Google Maps place data.
- If Google data is ever used, use an approved Google Maps Platform API and
  follow its attribution, display, and caching terms.
- The default free source here is OpenStreetMap/Overpass, with OpenStreetMap
  attribution preserved on every generated place.

## Generate the catalog

```sh
python3 Tools/place-directory/build_catalog.py \
  --output /tmp/park-ridge-places.json \
  --fallback-input docs/place-directory/park-ridge-places.json \
  --supplemental-input docs/place-directory/park-ridge-supplemental-places.json \
  --minimum-places 20
```

The builder queries small OpenStreetMap/Overpass fragments, preserves the
last-good catalog when a public endpoint is unavailable, and merges curated
Park Ridge supplemental records for known restaurants, library, recreation, and
civic places that OSM may omit.
Successful live refreshes write a fresh `generatedAt` timestamp even when the
place list is unchanged, so the hosted catalog can prove it was checked
recently.

The output shape is:

```json
{
  "generatedAt": "2026-06-16T00:00:00+00:00",
  "source": { "...": "..." },
  "supplementalPlaces": { "...": "..." },
  "places": []
}
```

`places` is an array of `LocalPlace` JSON objects, so the iOS app can decode it
directly through `PlaceDirectoryRefreshService`.

## Production setup

1. The repository includes `.github/workflows/update-place-catalog.yml`, which
   refreshes `docs/place-directory/park-ridge-places.json` daily using OSM plus
   `docs/place-directory/park-ridge-supplemental-places.json`.
2. Publish `docs/place-directory/park-ridge-places.json` to a stable public
   HTTPS URL.
3. Set the app target build setting `TOWN_PLACE_CATALOG_URL` to that HTTPS URL
   before App Store submission. The app target injects this into Info.plist as
   `TOWN_PLACE_CATALOG_URL` during the build.
4. Keep the JSON URL public and reachable during App Review.

If the hosted catalog is unavailable, the app falls back to the cached catalog,
then to the seeded local guide.
