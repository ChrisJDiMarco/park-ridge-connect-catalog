# Park Ridge Connect Place Catalog

Public static place catalog for Park Ridge Connect.

The checked-in JSON is generated from OpenStreetMap/Overpass and served through
GitHub Pages at:

```text
https://chrisjdimarco.github.io/park-ridge-connect-catalog/place-directory/park-ridge-places.json
```

Public app pages:

- Privacy policy: https://chrisjdimarco.github.io/park-ridge-connect-catalog/privacy/
- Support: https://chrisjdimarco.github.io/park-ridge-connect-catalog/support/

The scheduled workflow refreshes `docs/place-directory/park-ridge-places.json`
daily and keeps the last-good catalog if live Overpass endpoints are
temporarily unavailable.
Successful live refreshes write a fresh `generatedAt` timestamp even when the
place list is unchanged, so the hosted catalog can prove it was checked
recently.
