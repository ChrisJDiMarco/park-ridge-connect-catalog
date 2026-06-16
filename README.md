# Park Ridge Connect Place Catalog

Public static place catalog for Park Ridge Connect.

The checked-in JSON is generated from OpenStreetMap/Overpass and served through
GitHub Pages at:

```text
https://chrisjdimarco.github.io/park-ridge-connect-catalog/place-directory/park-ridge-places.json
```

The scheduled workflow refreshes `docs/place-directory/park-ridge-places.json`
daily and keeps the last-good catalog if live Overpass endpoints are
temporarily unavailable.
