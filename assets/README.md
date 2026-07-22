# assets/

Static files served by Dash. Any file placed in `assets/` is automatically picked up and served by the Dash app (per [Dash's asset-loading convention](https://dash.plotly.com/external-resources)) — nothing here is wired up manually except where noted.

| File/Folder | Purpose |
| --- | --- |
| `style.css` | Global page styling (layout, cards, typography overrides on top of the `dbc.themes.CYBORG` Bootstrap theme). |
| `navbar.css` | Styling specific to the fixed top navbar defined in `app.py`, including the responsive desktop-links / mobile-hamburger-menu behavior. |
| `style.js` | Reserved for global client-side JS; currently empty (page-specific clientside callbacks live inline in `app.py` and `pages/overview.py` instead). |
| `dmp_for_dash.html` | Standalone, pre-rendered interactive datamap (built with [DataMapPlot](https://github.com/TutteInstitute/datamapplot)) of the project latent space. Embedded via an `html.Iframe` on the Concept page (`pages/overview.py`) and communicates the currently-clicked point back to Dash via `window.postMessage`, which a clientside callback there listens for to open the project detail sidebar. |
| `img/` | Logos and illustrative images used across pages (FBK/CHUB/DH logos, section placeholder images on the Concept page, team photos). |

Note: this is a Dash *assets* folder in the framework sense (auto-served static files), unrelated to the `data/` folder, which holds datasets loaded by the Python backend.
