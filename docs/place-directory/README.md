# Park Ridge Place Catalog

`park-ridge-places.json` is the hosted catalog consumed by the iOS app through
the `TOWN_PLACE_CATALOG_URL` build setting.

## Publishing

The scheduled GitHub Actions workflow refreshes this JSON daily from
OpenStreetMap/Overpass, merges `park-ridge-supplemental-places.json` for known
Park Ridge records that public OSM endpoints may omit, and commits a new copy
only when the catalog changes. GitHub Pages publishes the `docs/` folder for
this public catalog repository.

Do not use a private `raw.githubusercontent.com` URL for App Review. Use one of
these public HTTPS options instead:

- GitHub Pages serving this repository's `docs/` folder.
- A public static object URL such as Cloudflare R2, S3, Netlify, Vercel, or a
  borough-owned static host.

For GitHub Pages from the public catalog repository, the app build setting
should be:

```text
TOWN_PLACE_CATALOG_URL=https://chrisjdimarco.github.io/park-ridge-connect-catalog/place-directory/park-ridge-places.json
```

Before submitting to App Review, open the final URL in a private/incognito
browser and confirm it returns this JSON without authentication.
